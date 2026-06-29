"""Property-based test: every applied transition records audit + notification (task 12.7).

# Feature: esignature-integration, Property 16: Every applied transition records audit and notification

**Validates: Requirements 3.7, 3.8, 6.7, 9.6, 14.1, 14.2, 14.4**

Property 16 (design.md): *For any* applied envelope status transition among
``sent``, ``viewed``, ``partially_signed``, ``completed``, ``declined``, and
``voided`` (and the failed-send case), **exactly one** org-scoped audit entry and
**one** in-app notification are recorded, and neither contains plaintext
credentials nor signed-document contents.

This module asserts Property 16 against the webhook apply seam
(:func:`app.modules.esignatures.service.apply_webhook`) which is where every
webhook-driven status transition is applied (R6.7/R14.1/R14.2). It drives
``apply_webhook`` with:

* a generated, mapped envelope and a verified webhook body that *may or may not*
  produce a transition (the reducer :func:`next_status` decides), and
* spies installed over ``write_audit_log`` **and** ``create_in_app_notification``
  in the service module that record every successful (awaited) call.

The assertion is a strict biconditional, computed against the **real** reducer
as an oracle:

* when the webhook produces an **applied** transition
  (``to_status is not None and to_status != from_status``) → **exactly one**
  audit entry and **exactly one** notification are recorded, both pointing at
  the transitioning envelope; and
* when **no** transition occurs — ``no_transition`` (terminal envelope,
  ``DOCUMENT_SENT``, or an event that lands on the same status), ``duplicate``
  (replayed ``dedupe_key``), or ``unmapped`` (document maps to no envelope) —
  **zero** transition audit entries and **zero** notifications are written.

A canary credential value is planted on the envelope's recipient ``signing_url``
and a fake plaintext PDF marker is tracked so the test can assert R14.4: neither
the audit payload nor the notification payload ever carries a plaintext
credential or signed-document contents (only non-secret status/agreement
metadata).

Everything runs in-memory (no DB) via ``asyncio.run`` against a fake async
session that emulates the ``UNIQUE(dedupe_key)`` SAVEPOINT semantics and serves
the envelope SELECT — mirroring the no-DB convention of
``test_esign_webhook_idempotent_property``. The post-commit signed-document
retrieval is patched to a no-op so the test isolates the audit/notification
side-effects.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignEnvelope / EsignRecipient / EsignWebhookEvent are instantiated
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
from app.modules.esignatures.service import (  # noqa: E402
    _recipient_status_from_payload,
    _synthesize_dedupe_key,
)
from app.modules.esignatures.status import RecipientState, next_status  # noqa: E402

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# the apply layer drives an asyncio event loop per example.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# Real Documenso webhook event names (verbatim, uppercase). Includes events that
# transition an envelope and ``DOCUMENT_SENT`` (a no-op transition).
_EVENTS = (
    "DOCUMENT_SENT",
    "DOCUMENT_OPENED",
    "DOCUMENT_VIEWED",
    "DOCUMENT_RECIPIENT_COMPLETED",
    "DOCUMENT_COMPLETED",
    "DOCUMENT_RECIPIENT_REJECTED",
    "DOCUMENT_CANCELLED",
)

# The 8 envelope statuses (incl. the 3 terminal ones) so the biconditional is
# asserted from terminal and non-terminal starting points alike.
_STATUSES = (
    "draft",
    "sent",
    "viewed",
    "partially_signed",
    "completed",
    "declined",
    "voided",
    "error",
)

_SIGNING_STATUSES = ("NOT_SIGNED", "SIGNED", "REJECTED")
_READ_STATUSES = ("NOT_OPENED", "OPENED")

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"
_TS_ALPHABET = "0123456789-:T.Z"

# Canary strings that MUST NEVER appear in any audit/notification payload (R14.4):
# a plaintext credential-shaped token and a fake signed-document content marker.
_CREDENTIAL_CANARY = "tok_SECRET_DO_NOT_LEAK_0123456789"
_DOC_CONTENT_CANARY = "%PDF-1.7-SIGNED-BYTES-DO-NOT-LEAK"

# The transition audit action emitted by ``_audit_and_notify_transition``.
_TRANSITION_ACTION = service._AUDIT_ACTION_TRANSITION
_ENTITY_TYPE = service._AUDIT_ENTITY_TYPE


# ===========================================================================
# Fake async session emulating UNIQUE(dedupe_key) SAVEPOINT semantics + SELECT.
# ===========================================================================


class _FakeSavepoint:
    """Stands in for an ``AsyncSessionTransaction``.

    Usable BOTH as ``async with db.begin_nested():`` (the dedupe insert) AND as
    ``savepoint = await db.begin_nested(); await savepoint.commit()`` (the
    best-effort side-effect wrapper in ``_run_best_effort``). Never suppresses an
    exception, so an :class:`IntegrityError` from the duplicate insert propagates
    to ``apply_webhook`` exactly as a real SAVEPOINT would.
    """

    def __init__(self, session: "_FakeWebhookSession") -> None:
        self._session = session

    def __await__(self):
        async def _coro():
            return self

        return _coro().__await__()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self._session.savepoint_commits += 1

    async def rollback(self):
        self._session.savepoint_rollbacks += 1


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


from sqlalchemy.exc import IntegrityError  # noqa: E402


class _FakeWebhookSession:
    """Minimal async-session stand-in emulating ``UNIQUE(dedupe_key)``.

    ``execute`` serves the (optional) pre-seeded envelope; ``begin_nested``
    returns a :class:`_FakeSavepoint` covering both call patterns; adding a
    second :class:`EsignWebhookEvent` carrying an already-seen ``dedupe_key``
    makes the next ``flush`` raise :class:`IntegrityError` (the duplicate seam).
    """

    def __init__(self, envelope: EsignEnvelope | None) -> None:
        self._envelope = envelope
        self.seen_dedupe_keys: set[str] = set()
        self._pending_event: EsignWebhookEvent | None = None
        self._pending_integrity = False
        self.commits = 0
        self.rollbacks = 0
        self.savepoint_commits = 0
        self.savepoint_rollbacks = 0

    def begin_nested(self):
        return _FakeSavepoint(self)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, EsignWebhookEvent):
            if obj.dedupe_key in self.seen_dedupe_keys:
                self._pending_integrity = True
            else:
                self._pending_event = obj

    async def flush(self):
        if self._pending_integrity:
            self._pending_integrity = False
            self._pending_event = None
            raise IntegrityError(
                "INSERT INTO esign_webhook_events",
                {},
                Exception("duplicate key value violates unique constraint"),
            )
        if self._pending_event is not None:
            self.seen_dedupe_keys.add(self._pending_event.dedupe_key)
            self._pending_event = None

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._envelope)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


# ===========================================================================
# Scenario generation.
# ===========================================================================


@st.composite
def _scenario(draw):
    """A verified webhook body + the envelope it maps to + a delivery mode.

    ``mode`` selects how the webhook is delivered:
      * ``"mapped"``    — the envelope exists; the reducer decides applied/no-op;
      * ``"duplicate"`` — the dedupe key is pre-seeded so the apply is a no-op;
      * ``"unmapped"``  — the document maps to no envelope.
    """
    event_type = draw(st.sampled_from(_EVENTS))
    document_id = "doc-" + draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=10))
    created_at = draw(st.text(alphabet=_TS_ALPHABET, min_size=1, max_size=24))
    initial_status = draw(st.sampled_from(_STATUSES))
    n = draw(st.integers(min_value=1, max_value=4))
    mode = draw(st.sampled_from(("mapped", "mapped", "mapped", "duplicate", "unmapped")))

    recipients_payload = []
    for i in range(n):
        recipients_payload.append(
            {
                "id": f"rcpt-{i}",
                "email": f"signer{i}@example.com",
                "signingStatus": draw(st.sampled_from(_SIGNING_STATUSES)),
                "readStatus": draw(st.sampled_from(_READ_STATUSES)),
            }
        )

    body = {
        "event": event_type,
        "payload": {
            "id": document_id,
            "status": "PENDING",
            "recipients": recipients_payload,
        },
        "createdAt": created_at,
    }
    return body, document_id, initial_status, recipients_payload, mode


def _build_envelope(org_id, document_id, initial_status, recipients_payload):
    env = EsignEnvelope(
        id=uuid.uuid4(),
        org_id=org_id,
        agreement_type="employment_agreement",
        originating_entity_type="staff",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id=document_id,
        status=initial_status,
    )
    for rec in recipients_payload:
        env.recipients.append(
            EsignRecipient(
                id=uuid.uuid4(),
                name=rec["email"].split("@")[0],
                email=rec["email"],
                signing_role="SIGNER",
                recipient_status="pending",
                documenso_recipient_id=rec["id"],
                # Plant a credential-shaped canary on a recipient field so the
                # leak-free assertion (R14.4) is meaningful — it must never reach
                # the audit or notification payload.
                signing_url=f"https://documenso.example/sign/{_CREDENTIAL_CANARY}",
            )
        )
    return env


def _expected_applied(initial_status, event_type, recipients_payload) -> bool:
    """Oracle: does this webhook produce an *applied* transition?

    Mirrors ``apply_webhook`` exactly — builds the ``RecipientState`` list the
    same way ``_apply_recipient_updates`` does and consults the real reducer.
    """
    states = [
        RecipientState(signed=_recipient_status_from_payload(r) == "signed")
        for r in recipients_payload
    ]
    to_status = next_status(initial_status, event_type, states)
    return to_status is not None and to_status != initial_status


async def _noop(*_args, **_kwargs):
    return None


def _run_apply(body, document_id, initial_status, recipients_payload, mode):
    """Drive ``apply_webhook`` once under the given delivery mode; capture the
    recorded audit/notification calls and the result."""
    org_id = uuid.uuid4()

    envelope = None
    if mode != "unmapped":
        envelope = _build_envelope(
            org_id, document_id, initial_status, recipients_payload
        )

    session = _FakeWebhookSession(envelope)
    raw_body = json.dumps(body).encode("utf-8")

    # For the duplicate mode, pre-seed the synthesized dedupe key so the apply's
    # event insert hits the UNIQUE violation and is acknowledged as a no-op.
    if mode == "duplicate":
        key = _synthesize_dedupe_key(
            event_type=body.get("event") or "",
            documenso_document_id=document_id,
            recipients=recipients_payload,
            created_at=body.get("createdAt") or "",
        )
        session.seen_dedupe_keys.add(key)

    audit_calls: list[dict] = []
    notification_calls: list[dict] = []

    async def _spy_audit(_db, **kwargs):
        # Recorded only when actually awaited (i.e. the SAVEPOINT side-effect ran).
        audit_calls.append(kwargs)
        return None

    async def _spy_notify(_db, **kwargs):
        notification_calls.append(kwargs)
        return uuid.uuid4()

    async def _go():
        return await service.apply_webhook(session, org_id=org_id, raw_body=raw_body)

    with patch.object(service, "write_audit_log", _spy_audit), patch.object(
        service, "create_in_app_notification", _spy_notify
    ), patch.object(service, "_trigger_signed_document_retrieval", _noop):
        result = asyncio.run(_go())

    return result, audit_calls, notification_calls, (envelope.id if envelope else None)


# ===========================================================================
# Leak-free assertion helper (R14.4).
# ===========================================================================


def _assert_leak_free(call_kwargs: dict) -> None:
    """Assert a recorded audit/notification call carries no plaintext credential
    or signed-document content (R14.4)."""
    blob = json.dumps(call_kwargs, default=str)
    assert _CREDENTIAL_CANARY not in blob, (
        "credential canary leaked into audit/notification payload"
    )
    assert _DOC_CONTENT_CANARY not in blob, (
        "signed-document content leaked into audit/notification payload"
    )
    lowered = blob.lower()
    for forbidden in ("service_token", "webhook_secret", "signing_url", "file_key"):
        assert forbidden not in lowered, (
            f"forbidden secret-bearing field '{forbidden}' surfaced in payload"
        )


# ===========================================================================
# Property 16.
# ===========================================================================


class TestTransitionRecordsAuditAndNotification:
    """Property 16: every applied transition records exactly one audit entry and
    one notification; a non-transition records neither.

    **Validates: Requirements 3.7, 3.8, 6.7, 9.6, 14.1, 14.2, 14.4**
    """

    @given(scenario=_scenario())
    @PBT_SETTINGS
    def test_applied_transition_records_audit_and_notification(self, scenario):
        body, document_id, initial_status, recipients_payload, mode = scenario
        result, audit_calls, notification_calls, envelope_id = _run_apply(
            body, document_id, initial_status, recipients_payload, mode
        )

        if mode == "mapped":
            applied = _expected_applied(initial_status, body["event"], recipients_payload)
        else:
            # A duplicate or an unmapped document can never apply a transition.
            applied = False

        if applied:
            # Outcome is 'applied' and EXACTLY one audit + one notification fired.
            assert result.outcome == "applied", result.outcome
            assert len(audit_calls) == 1, (
                f"expected exactly one audit entry, got {len(audit_calls)}"
            )
            assert len(notification_calls) == 1, (
                f"expected exactly one notification, got {len(notification_calls)}"
            )

            # The audit entry records THIS envelope's transition (R14.1).
            audit = audit_calls[0]
            assert audit.get("action") == _TRANSITION_ACTION
            assert audit.get("entity_type") == _ENTITY_TYPE
            assert audit.get("entity_id") == envelope_id
            # before/after carry the status transition; after status == new status.
            assert audit.get("before_value", {}).get("status") == initial_status
            assert audit.get("after_value", {}).get("status") == result.new_status

            # The notification records THIS envelope's transition (R14.2).
            notif = notification_calls[0]
            assert notif.get("entity_type") == _ENTITY_TYPE
            assert notif.get("entity_id") == envelope_id

            # Neither payload leaks credentials or signed-document contents (R14.4).
            _assert_leak_free(audit)
            _assert_leak_free(notif)
        else:
            # No transition: outcome is one of the non-applying outcomes and NO
            # transition audit/notification was written.
            assert result.outcome in ("no_transition", "duplicate", "unmapped"), (
                result.outcome
            )
            assert audit_calls == [], (
                f"no transition occurred but {len(audit_calls)} audit entries written"
            )
            assert notification_calls == [], (
                f"no transition occurred but {len(notification_calls)} notifications written"
            )

    @given(
        initial_status=st.sampled_from(("sent", "viewed", "partially_signed")),
        recipients=st.lists(
            st.fixed_dictionaries(
                {
                    "id": st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=6),
                    "email": st.builds(
                        lambda u: f"{u}@example.com",
                        st.text(alphabet="abcdefghij", min_size=1, max_size=6),
                    ),
                    "signingStatus": st.sampled_from(_SIGNING_STATUSES),
                    "readStatus": st.sampled_from(_READ_STATUSES),
                }
            ),
            min_size=1,
            max_size=4,
        ),
    )
    @PBT_SETTINGS
    def test_cancel_from_non_terminal_always_records_once(
        self, initial_status, recipients
    ):
        """A ``DOCUMENT_CANCELLED`` on a non-terminal envelope always voids it,
        so it must always record exactly one audit entry and one notification
        (R7.4/R14.1/R14.2) — a focused generator that guarantees an applied
        transition on every example."""
        document_id = "doc-cancel-" + uuid.uuid4().hex[:8]
        body = {
            "event": "DOCUMENT_CANCELLED",
            "payload": {"id": document_id, "status": "PENDING", "recipients": recipients},
            "createdAt": "2026-01-01T00:00:00.000Z",
        }
        result, audit_calls, notification_calls, envelope_id = _run_apply(
            body, document_id, initial_status, recipients, "mapped"
        )

        assert result.outcome == "applied"
        assert result.new_status == "voided"
        assert len(audit_calls) == 1
        assert len(notification_calls) == 1
        assert audit_calls[0].get("entity_id") == envelope_id
        assert notification_calls[0].get("entity_id") == envelope_id
        _assert_leak_free(audit_calls[0])
        _assert_leak_free(notification_calls[0])

    @given(
        initial_status=st.sampled_from(("completed", "declined", "voided")),
        event=st.sampled_from(_EVENTS),
    )
    @PBT_SETTINGS
    def test_terminal_envelope_never_records_transition(self, initial_status, event):
        """A terminal envelope never transitions under any event, so no audit or
        notification is ever written for it (R6.7)."""
        document_id = "doc-term-" + uuid.uuid4().hex[:8]
        recipients = [
            {
                "id": "rcpt-0",
                "email": "signer0@example.com",
                "signingStatus": "SIGNED",
                "readStatus": "OPENED",
            }
        ]
        body = {
            "event": event,
            "payload": {"id": document_id, "status": "PENDING", "recipients": recipients},
            "createdAt": "2026-02-02T00:00:00.000Z",
        }
        result, audit_calls, notification_calls, _ = _run_apply(
            body, document_id, initial_status, recipients, "mapped"
        )

        assert result.outcome == "no_transition"
        assert audit_calls == []
        assert notification_calls == []
