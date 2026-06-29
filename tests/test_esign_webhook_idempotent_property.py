"""Property-based test: webhook processing is idempotent (task 12.4).

# Feature: esignature-integration, Property 14: Webhook processing is idempotent

**Validates: Requirements 8.3, 8.4**

Requirement 8.3: *WHEN an Esign_Webhook is successfully verified, THE Esign_Module
SHALL compute a synthesized dedupe key from stable payload fields (a hash of the
event type, the Documenso document identifier, the recipient/status, and the
``createdAt`` timestamp) AND SHALL record that synthesized dedupe key uniquely.*

Requirement 8.4: *WHEN an Esign_Webhook arrives whose synthesized dedupe key has
already been processed, THE Esign_Module SHALL acknowledge the webhook without
re-applying the associated state change.*

This module asserts Property 14 in two complementary layers:

1. **Dedupe-key synthesis is a faithful idempotency key** —
   :func:`app.modules.esignatures.service._synthesize_dedupe_key` is exercised
   directly as a pure function:

   * *determinism* — the same payload fields always produce the same key;
   * *recipient order-independence* — permuting the ``recipients[...]`` array
     does not change the key (it is order-independent by construction); and
   * *field sensitivity* — changing the event type, the Documenso document id,
     the ``createdAt`` timestamp, or any recipient's signing status produces a
     **different** key (so genuinely-different events are never collapsed).

2. **Apply is idempotent** —
   :func:`app.modules.esignatures.service.apply_webhook` is driven against a
   fake async session that emulates the ``UNIQUE(dedupe_key)`` constraint on
   ``esign_webhook_events``: the **first** apply of a verified webhook records
   the event and applies any envelope-status transition (outcome ``applied`` or
   ``no_transition``); a **second** apply of the *same* body raises the unique
   violation on the duplicate insert and is acknowledged as ``duplicate``
   **without** re-applying — the envelope status and per-recipient statuses are
   byte-for-byte unchanged by the replay.

Everything runs in-memory (no DB) via ``asyncio.run``, mirroring the no-DB
convention of ``test_esign_documenso_failure_property`` /
``test_esign_per_org_token_property``. The audit/notification side-effects and
the post-commit signed-document retrieval are patched to no-ops so the test
isolates the dedupe/idempotency behaviour.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import IntegrityError

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
from app.modules.esignatures.service import _synthesize_dedupe_key  # noqa: E402

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# the apply layer drives an asyncio event loop per example.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# Real Documenso webhook event names (verbatim, uppercase). Includes events that
# transition an envelope and ``DOCUMENT_SENT`` which is a no-op transition — both
# must be idempotent under replay.
_EVENTS = (
    "DOCUMENT_SENT",
    "DOCUMENT_OPENED",
    "DOCUMENT_VIEWED",
    "DOCUMENT_RECIPIENT_COMPLETED",
    "DOCUMENT_COMPLETED",
    "DOCUMENT_RECIPIENT_REJECTED",
    "DOCUMENT_CANCELLED",
)

# The 8 envelope statuses (incl. the 3 terminal ones) so idempotency is asserted
# from terminal and non-terminal starting points alike.
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

# Safe alphabet for ids / timestamps so generated strings stay printable.
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"
_TS_ALPHABET = "0123456789-:T.Z"


# ===========================================================================
# Layer 1 — _synthesize_dedupe_key is a faithful idempotency key (pure, DB-free)
# ===========================================================================

_recipient_dict = st.fixed_dictionaries(
    {
        "id": st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=8),
        "email": st.builds(
            lambda u, d: f"{u}@{d}.com",
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8),
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6),
        ),
        "signingStatus": st.sampled_from(_SIGNING_STATUSES),
        "readStatus": st.sampled_from(_READ_STATUSES),
    }
)


@st.composite
def _payload_fields(draw):
    """Draw the stable payload fields the dedupe key is synthesized from."""
    event_type = draw(st.sampled_from(_EVENTS))
    document_id = "doc-" + draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=10))
    created_at = draw(st.text(alphabet=_TS_ALPHABET, min_size=1, max_size=24))
    recipients = draw(st.lists(_recipient_dict, min_size=1, max_size=5))
    return event_type, document_id, created_at, recipients


class TestDedupeKeySynthesis:
    """Property 14a: the synthesized dedupe key is a faithful idempotency key.

    **Validates: Requirements 8.3, 8.4**
    """

    @given(fields=_payload_fields())
    @PBT_SETTINGS
    def test_deterministic_and_recipient_order_independent(self, fields):
        event_type, document_id, created_at, recipients = fields

        key1 = _synthesize_dedupe_key(
            event_type=event_type,
            documenso_document_id=document_id,
            recipients=recipients,
            created_at=created_at,
        )
        # Determinism: identical fields -> identical key.
        key2 = _synthesize_dedupe_key(
            event_type=event_type,
            documenso_document_id=document_id,
            recipients=recipients,
            created_at=created_at,
        )
        assert key1 == key2

        # Recipient order-independence: the recipient component is a sorted
        # digest, so permuting the array cannot change the key.
        reversed_recipients = list(reversed(recipients))
        key_rev = _synthesize_dedupe_key(
            event_type=event_type,
            documenso_document_id=document_id,
            recipients=reversed_recipients,
            created_at=created_at,
        )
        assert key1 == key_rev

        # A SHA-256 hexdigest is 64 hex chars — sanity on the key shape.
        assert isinstance(key1, str) and len(key1) == 64

    @given(fields=_payload_fields(), which=st.sampled_from(("event", "doc", "created_at", "recipient")))
    @PBT_SETTINGS
    def test_changing_any_stable_field_changes_the_key(self, fields, which):
        event_type, document_id, created_at, recipients = fields

        base_key = _synthesize_dedupe_key(
            event_type=event_type,
            documenso_document_id=document_id,
            recipients=recipients,
            created_at=created_at,
        )

        # Mutate exactly ONE stable field to a guaranteed-different value, then
        # assert the key changes (different events are never collapsed, R8.4).
        new_event, new_doc, new_created, new_recipients = (
            event_type,
            document_id,
            created_at,
            [dict(r) for r in recipients],
        )
        if which == "event":
            new_event = next(e for e in _EVENTS if e != event_type)
        elif which == "doc":
            new_doc = document_id + "-X"
        elif which == "created_at":
            new_created = created_at + "9"
        else:  # recipient signing status
            cur = new_recipients[0]["signingStatus"]
            new_recipients[0]["signingStatus"] = next(
                s for s in _SIGNING_STATUSES if s != cur
            )

        mutated_key = _synthesize_dedupe_key(
            event_type=new_event,
            documenso_document_id=new_doc,
            recipients=new_recipients,
            created_at=new_created,
        )
        assert mutated_key != base_key


# ===========================================================================
# Layer 2 — apply_webhook is idempotent (fake session emulating UNIQUE dedupe)
# ===========================================================================


class _FakeNestedTxn:
    """Stands in for an ``AsyncSessionTransaction`` used via ``async with``.

    Never suppresses an exception, so an :class:`IntegrityError` raised by the
    duplicate event insert propagates to ``apply_webhook``'s ``except
    IntegrityError`` handler exactly as a real SAVEPOINT would.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeWebhookSession:
    """Minimal async-session stand-in emulating ``UNIQUE(dedupe_key)``.

    Tracks the dedupe keys that have been successfully recorded. Adding a second
    :class:`EsignWebhookEvent` carrying an already-seen ``dedupe_key`` makes the
    next ``flush`` raise :class:`IntegrityError` — exactly the unique-violation
    ``apply_webhook`` relies on to detect a duplicate (R8.4). The envelope
    SELECT is served from the single pre-seeded envelope.
    """

    def __init__(self, envelope: EsignEnvelope) -> None:
        self._envelope = envelope
        self.seen_dedupe_keys: set[str] = set()
        self._pending_event: EsignWebhookEvent | None = None
        self._pending_integrity = False
        self.commits = 0
        self.rollbacks = 0

    def begin_nested(self):
        return _FakeNestedTxn()

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, EsignWebhookEvent):
            if obj.dedupe_key in self.seen_dedupe_keys:
                # Duplicate insert — the next flush must fail the UNIQUE check.
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


@st.composite
def _apply_scenario(draw):
    """A verified webhook body + a pre-seeded envelope that it maps to."""
    event_type = draw(st.sampled_from(_EVENTS))
    document_id = "doc-" + draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=10))
    created_at = draw(st.text(alphabet=_TS_ALPHABET, min_size=1, max_size=24))
    initial_status = draw(st.sampled_from(_STATUSES))
    n = draw(st.integers(min_value=1, max_value=4))

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
    return body, document_id, initial_status, recipients_payload


def _build_envelope(org_id, document_id, initial_status, recipients_payload):
    env = EsignEnvelope(
        id=uuid.uuid4(),
        org_id=org_id,
        agreement_type="nda",
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
            )
        )
    return env


async def _noop(*_args, **_kwargs):
    return None


def _run_double_apply(body, document_id, initial_status, recipients_payload):
    """Apply the same verified webhook twice on one session; capture state."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, document_id, initial_status, recipients_payload)
    session = _FakeWebhookSession(envelope)
    raw_body = json.dumps(body).encode("utf-8")

    async def _go():
        first = await service.apply_webhook(
            session, org_id=org_id, raw_body=raw_body
        )
        status_after_first = envelope.status
        recipients_after_first = [r.recipient_status for r in envelope.recipients]

        second = await service.apply_webhook(
            session, org_id=org_id, raw_body=raw_body
        )
        status_after_second = envelope.status
        recipients_after_second = [r.recipient_status for r in envelope.recipients]

        return (
            first,
            second,
            status_after_first,
            status_after_second,
            recipients_after_first,
            recipients_after_second,
        )

    with patch.object(service, "_audit_and_notify_transition", _noop), patch.object(
        service, "_trigger_signed_document_retrieval", _noop
    ):
        return asyncio.run(_go())


class TestApplyWebhookIdempotent:
    """Property 14b: applying a verified webhook twice never re-applies state.

    **Validates: Requirements 8.3, 8.4**
    """

    @given(scenario=_apply_scenario())
    @PBT_SETTINGS
    def test_second_apply_is_a_duplicate_noop(self, scenario):
        body, document_id, initial_status, recipients_payload = scenario
        (
            first,
            second,
            status_after_first,
            status_after_second,
            recipients_after_first,
            recipients_after_second,
        ) = _run_double_apply(body, document_id, initial_status, recipients_payload)

        # First apply records the event and either transitions the envelope or
        # is a (terminal-safe / non-transitioning) no-op — never a duplicate.
        assert first.outcome in ("applied", "no_transition"), first.outcome

        # Second apply of the SAME body hits the UNIQUE(dedupe_key) violation and
        # is acknowledged as a duplicate (R8.4).
        assert second.outcome == "duplicate"

        # The replay re-applied NOTHING: envelope status and every per-recipient
        # status are byte-for-byte identical to the post-first-apply snapshot.
        assert status_after_second == status_after_first
        assert recipients_after_second == recipients_after_first

    @given(scenario=_apply_scenario())
    @PBT_SETTINGS
    def test_applying_many_times_converges_to_one_apply(self, scenario):
        """Applying once, then any number of additional times, yields the same
        resulting state as applying exactly once (idempotency, R8.4)."""
        body, document_id, initial_status, recipients_payload = scenario
        org_id = uuid.uuid4()
        envelope = _build_envelope(
            org_id, document_id, initial_status, recipients_payload
        )
        session = _FakeWebhookSession(envelope)
        raw_body = json.dumps(body).encode("utf-8")

        async def _go():
            outcomes = []
            results = []
            for _ in range(4):
                res = await service.apply_webhook(
                    session, org_id=org_id, raw_body=raw_body
                )
                outcomes.append(res.outcome)
                results.append((envelope.status, [r.recipient_status for r in envelope.recipients]))
            return outcomes, results

        with patch.object(service, "_audit_and_notify_transition", _noop), patch.object(
            service, "_trigger_signed_document_retrieval", _noop
        ):
            outcomes, results = asyncio.run(_go())

        # Only the first apply does work; every subsequent one is a duplicate.
        assert outcomes[0] in ("applied", "no_transition")
        assert all(o == "duplicate" for o in outcomes[1:])

        # State after the first apply equals state after the Nth apply.
        assert all(r == results[0] for r in results[1:])
