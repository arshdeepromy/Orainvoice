"""Property-based test: webhooks for unmapped documents are no-ops (task 12.5).

# Feature: esignature-integration, Property 15: Webhooks for unmapped documents are no-ops

**Validates: Requirements 8.5**

Requirement 8.5: *WHEN an Esign_Webhook references a Documenso document
identifier that maps to no Envelope within the resolved organisation, THE
Esign_Module SHALL acknowledge the webhook without modifying any Envelope.*

This module asserts Property 15 against
:func:`app.modules.esignatures.service.apply_webhook`. The webhook is already
verified and RLS-scoped to the resolved org by the 12.1 handler seam; this test
drives the *apply* step for a payload whose ``documenso_document_id`` maps to
**no** ``esign_envelopes`` row within the resolved org.

For every generated (document id, event type, recipients[]) the property holds:

* the dedupe key is recorded once (``begin_nested`` + ``add`` + ``flush``
  succeeds), so retries of the same event stay no-ops;
* the envelope lookup (``execute`` → ``scalar_one_or_none``) returns ``None``;
* the webhook is acknowledged (``outcome == "unmapped"``, session committed); and
* **no envelope is modified** — there is no ``EsignEnvelope`` or
  ``EsignRecipient`` object added/updated on the session, only the single
  ``EsignWebhookEvent`` dedupe row (stamped with the resolved ``org_id``).

Everything runs in-memory (no DB) via ``asyncio.run``, mirroring the no-DB
fake-session convention of ``tests/test_esign_documenso_failure_property.py``
and ``tests/test_esign_webhook_idempotent_property.py``. The audit/notification
side-effects and the post-commit signed-document retrieval are patched to
no-ops (they are never reached on the unmapped path, but the patch keeps the
property isolated to the no-op behaviour).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignWebhookEvent / EsignEnvelope are instantiated inside apply_webhook
# (mirrors the other esign unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.models import (  # noqa: E402
    EsignEnvelope,
    EsignRecipient,
    EsignWebhookEvent,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# the apply layer drives an asyncio event loop per example.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# Real Documenso webhook event names (verbatim, uppercase). The full set is
# exercised so the no-op holds for transition-bearing events as well as the
# no-op ``DOCUMENT_SENT``.
_EVENTS = (
    "DOCUMENT_SENT",
    "DOCUMENT_OPENED",
    "DOCUMENT_VIEWED",
    "DOCUMENT_RECIPIENT_COMPLETED",
    "DOCUMENT_COMPLETED",
    "DOCUMENT_RECIPIENT_REJECTED",
    "DOCUMENT_CANCELLED",
)

_SIGNING_STATUSES = ("NOT_SIGNED", "SIGNED", "REJECTED")
_READ_STATUSES = ("NOT_OPENED", "OPENED")

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"
_TS_ALPHABET = "0123456789-:T.Z"


# ---------------------------------------------------------------------------
# Fake async session whose envelope lookup ALWAYS resolves to None (unmapped)
# ---------------------------------------------------------------------------


class _FakeNestedTxn:
    """Stands in for an ``AsyncSessionTransaction`` used via ``async with``.

    Never suppresses an exception — but on the unmapped path the dedupe insert
    succeeds, so no exception is raised inside the savepoint.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeResultNone:
    """An ``execute`` result whose ``scalar_one_or_none`` is always ``None``.

    This is the heart of the unmapped scenario: the SELECT for an envelope by
    ``documenso_document_id`` within the resolved org finds nothing.
    """

    @staticmethod
    def scalar_one_or_none():
        return None


class _UnmappedSession:
    """Minimal async-session stand-in for the unmapped-document path.

    * ``begin_nested`` + ``add`` + ``flush`` records the dedupe event (the only
      row written on this path);
    * ``execute`` returns a result whose ``scalar_one_or_none`` is ``None`` so
      the envelope lookup maps to nothing;
    * ``commit``/``rollback`` are counted so the acknowledgement is observable.

    Every object handed to ``add`` is captured so the test can assert that NO
    ``EsignEnvelope`` / ``EsignRecipient`` was added or mutated.
    """

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.execute_calls = 0

    def begin_nested(self):
        return _FakeNestedTxn()

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1

    async def execute(self, *_args, **_kwargs):
        self.execute_calls += 1
        return _FakeResultNone()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# Generators — a verified webhook body referencing an UNMAPPED document id
# ---------------------------------------------------------------------------

_recipient_dict = st.fixed_dictionaries(
    {
        "id": st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=8),
        "email": st.builds(
            lambda u, d: f"{u}@{d}.com",
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
                min_size=1,
                max_size=8,
            ),
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6),
        ),
        "signingStatus": st.sampled_from(_SIGNING_STATUSES),
        "readStatus": st.sampled_from(_READ_STATUSES),
    }
)


@st.composite
def _unmapped_scenario(draw):
    """A verified webhook body whose document id maps to no envelope.

    The document id is always non-empty (the webhook genuinely *references* a
    document), the event type is a real Documenso event, and the recipients
    array is arbitrary — none of it can cause a modification because the
    resolved org has no envelope for this document id.
    """
    event_type = draw(st.sampled_from(_EVENTS))
    document_id = "doc-" + draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=12))
    created_at = draw(st.text(alphabet=_TS_ALPHABET, min_size=1, max_size=24))
    recipients_payload = draw(st.lists(_recipient_dict, min_size=0, max_size=5))

    body = {
        "event": event_type,
        "payload": {
            "id": document_id,
            "status": draw(st.sampled_from(["PENDING", "COMPLETED", "REJECTED"])),
            "recipients": recipients_payload,
        },
        "createdAt": created_at,
    }
    return body, document_id


async def _noop(*_args, **_kwargs):
    return None


def _run_unmapped(body):
    """Apply the (unmapped) verified webhook; return (result, session, org_id)."""
    org_id = uuid.uuid4()
    session = _UnmappedSession()
    raw_body = json.dumps(body).encode("utf-8")

    async def _go():
        return await service.apply_webhook(session, org_id=org_id, raw_body=raw_body)

    with patch.object(service, "_audit_and_notify_transition", _noop), patch.object(
        service, "_trigger_signed_document_retrieval", _noop
    ):
        result = asyncio.run(_go())

    return result, session, org_id


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


class TestWebhookUnmappedDocumentIsNoOp:
    """Property 15: a webhook for an unmapped document is acknowledged, no-op.

    **Validates: Requirements 8.5**
    """

    @given(scenario=_unmapped_scenario())
    @PBT_SETTINGS
    def test_unmapped_document_acknowledged_without_modification(self, scenario):
        body, document_id = scenario
        result, session, org_id = _run_unmapped(body)

        # The webhook is acknowledged as ``unmapped`` (R8.5).
        assert result.outcome == "unmapped", result.outcome
        # No envelope was touched: no id, status, or completion side-effects.
        assert result.envelope_id is None
        assert result.new_status is None
        assert result.reached_completed is False

        # The session was committed (the dedupe key stays recorded so retries
        # are no-ops) — never rolled back.
        assert session.commits >= 1
        assert session.rollbacks == 0

        # NO envelope or recipient row was added/updated on the session — the
        # ONLY object written is the single dedupe EsignWebhookEvent.
        envelopes = [o for o in session.added if isinstance(o, EsignEnvelope)]
        recipients = [o for o in session.added if isinstance(o, EsignRecipient)]
        events = [o for o in session.added if isinstance(o, EsignWebhookEvent)]
        assert envelopes == [], "no envelope may be created/updated on the unmapped path"
        assert recipients == [], "no recipient may be created/updated on the unmapped path"
        assert len(events) == 1, "exactly one dedupe event row is recorded"

        # The dedupe event is stamped with the resolved org id (R13.6) and
        # carries the referenced document id.
        event = events[0]
        assert event.org_id == org_id
        assert event.documenso_document_id == document_id

    @given(scenario=_unmapped_scenario())
    @PBT_SETTINGS
    def test_replay_of_unmapped_webhook_stays_a_noop(self, scenario):
        """Re-applying the same unmapped webhook never starts modifying state.

        The dedupe row recorded on the first apply means a genuine replay is a
        ``duplicate``; either way no envelope is ever modified (R8.5)."""
        body, _document_id = scenario

        # Two independent applies (fresh org/session each) both resolve to
        # ``unmapped`` and modify nothing — the no-op is stable across replays.
        result_a, session_a, _ = _run_unmapped(body)
        result_b, session_b, _ = _run_unmapped(body)

        for result, session in ((result_a, session_a), (result_b, session_b)):
            assert result.outcome == "unmapped"
            assert [o for o in session.added if isinstance(o, EsignEnvelope)] == []
            assert [o for o in session.added if isinstance(o, EsignRecipient)] == []
