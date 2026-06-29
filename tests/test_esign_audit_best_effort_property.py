"""Property-based test: audit/notification side-effects are best-effort (task 12.8).

# Feature: esignature-integration, Property 17: Audit and notification side-effects are best-effort

**Validates: Requirements 14.3**

Requirement 14.3: *IF writing the Audit_Log entry or creating the
In_App_Notification fails, THEN THE Esign_Module SHALL log the failure AND SHALL
NOT roll back the underlying Envelope_Status change (audit and notification
side-effects are best-effort relative to the status change).*

Design — Property 17: *For any applied status transition in which writing the
audit entry or creating the notification raises an error, the failure is logged
and the underlying envelope status change is still persisted (never rolled
back).* ``write_audit_log`` does **not** self-guard (a failing INSERT
propagates), so the best-effort ``try/except`` wrapping around it at the call
site (``_run_best_effort`` → a per-side-effect SAVEPOINT) is mandatory;
``create_in_app_notification`` already never raises but is wrapped too for
defence in depth.

This module drives :func:`app.modules.esignatures.service.apply_webhook` against
a fake async session that faithfully models the SAVEPOINT semantics
``_run_best_effort`` relies on:

* ``begin_nested()`` returns a savepoint object usable **both** as an
  ``async with`` context manager (the event-insert path) **and** as an
  awaitable (``savepoint = await db.begin_nested()`` inside
  ``_run_best_effort``); its ``commit``/``rollback`` are tracked.
* The failing side-effect coroutine raises *inside* the SAVEPOINT;
  ``_run_best_effort`` catches it and rolls back only that savepoint — the
  envelope mutation (applied *before* the side-effects, on the outer
  transaction) is preserved, exactly as a real nested transaction would behave.

Across generated combinations (audit raises / notification raises / both raise)
the test asserts that for any verified webhook that produces a real status
transition:

* ``apply_webhook`` does **not** raise;
* the outcome is ``"applied"``;
* the envelope's status reflects the **new** (transitioned) status — the change
  survived the side-effect failure; and
* the outer transaction was committed (``session.commit`` called), never rolled
  back, while the failing side-effect's SAVEPOINT was rolled back.

Everything runs in-memory (no DB) via ``asyncio.run``, mirroring the no-DB
convention of ``test_esign_webhook_idempotent_property``. The post-commit
signed-document retrieval is patched to a no-op so the test isolates the
best-effort audit/notification behaviour.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

from hypothesis import assume, given, settings
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
)
from app.modules.esignatures.status import next_status  # noqa: E402

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# the apply layer drives an asyncio event loop per example.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# Non-terminal starting statuses (terminal ones never transition, so they could
# never produce an "applied" outcome — see Property 9). ``error`` is non-terminal.
_NON_TERMINAL_STATUSES = (
    "draft",
    "sent",
    "viewed",
    "partially_signed",
    "error",
)

# Documenso events that drive a deterministic transition. DOCUMENT_RECIPIENT_*
# and the lifecycle events all map to a concrete next status from a non-terminal
# envelope; the exact target is recomputed with ``next_status`` so the scenario
# only keeps genuine transitions.
_TRANSITION_EVENTS = (
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

# Which side-effect(s) are made to raise. "audit" exercises the MANDATORY
# wrapping around the non-self-guarding ``write_audit_log``; "notify" and "both"
# exercise the defence-in-depth wrapping around ``create_in_app_notification``.
_FAILURE_MODES = ("audit", "notify", "both")


# ===========================================================================
# Fakes — model the SAVEPOINT semantics _run_best_effort relies on
# ===========================================================================


class _FakeSavepoint:
    """Stands in for an ``AsyncSessionTransaction`` from ``begin_nested()``.

    SQLAlchemy's ``begin_nested()`` result is used two ways in the service:

    * ``async with db.begin_nested(): ...`` — the event-insert path; and
    * ``savepoint = await db.begin_nested()`` then ``savepoint.commit()`` /
      ``savepoint.rollback()`` — inside ``_run_best_effort``.

    This fake supports both. As a context manager it never suppresses an
    exception. Its ``commit``/``rollback`` are tallied on the owning session so
    the test can assert the failing side-effect's SAVEPOINT was rolled back
    while the envelope change (on the outer transaction) survived.
    """

    def __init__(self, session: "_FakeWebhookSession") -> None:
        self._session = session

    def __await__(self):
        async def _coro() -> "_FakeSavepoint":
            return self

        return _coro().__await__()

    async def __aenter__(self) -> "_FakeSavepoint":
        return self

    async def __aexit__(self, *exc) -> bool:
        # Never suppress — a failure inside the with-block must propagate so the
        # caller's own try/except handles it (mirrors a real SAVEPOINT).
        return False

    async def commit(self) -> None:
        self._session.savepoint_commits += 1

    async def rollback(self) -> None:
        self._session.savepoint_rollbacks += 1


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeWebhookSession:
    """Minimal async-session stand-in for the apply path.

    The envelope SELECT is served from the single pre-seeded envelope. ``flush``
    always succeeds (this is a first, non-duplicate apply). The outer
    transaction's ``commit``/``rollback`` and every SAVEPOINT's
    ``commit``/``rollback`` are tracked.
    """

    def __init__(self, envelope: EsignEnvelope) -> None:
        self._envelope = envelope
        self.commits = 0
        self.rollbacks = 0
        self.savepoint_commits = 0
        self.savepoint_rollbacks = 0

    def begin_nested(self) -> _FakeSavepoint:
        return _FakeSavepoint(self)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    async def flush(self) -> None:
        return None

    async def execute(self, *_args, **_kwargs) -> _FakeResult:
        return _FakeResult(self._envelope)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ===========================================================================
# Strategy — a verified webhook that produces a genuine status transition
# ===========================================================================


@st.composite
def _transition_scenario(draw):
    """Draw an envelope + webhook body guaranteed to drive a real transition,
    plus which side-effect(s) should raise."""
    event_type = draw(st.sampled_from(_TRANSITION_EVENTS))
    initial_status = draw(st.sampled_from(_NON_TERMINAL_STATUSES))
    document_id = "doc-" + draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=10))
    created_at = draw(st.text(alphabet=_TS_ALPHABET, min_size=1, max_size=24))
    failure_mode = draw(st.sampled_from(_FAILURE_MODES))

    n = draw(st.integers(min_value=1, max_value=4))
    recipients_payload = []
    for i in range(n):
        # For DOCUMENT_RECIPIENT_COMPLETED the signed/unsigned mix decides
        # partially_signed vs completed; both are valid transitions, so any mix
        # is fine. Other events ignore signing state.
        recipients_payload.append(
            {
                "id": f"rcpt-{i}",
                "email": f"signer{i}@example.com",
                "signingStatus": draw(st.sampled_from(_SIGNING_STATUSES)),
                "readStatus": draw(st.sampled_from(_READ_STATUSES)),
            }
        )

    # Recompute the reducer's view to keep ONLY genuine transitions
    # (to_status not None and != from_status) — that is the precondition for an
    # "applied" outcome.
    from app.modules.esignatures.status import RecipientState

    recipients_state = [
        RecipientState(signed=str(r["signingStatus"]).upper() == "SIGNED")
        for r in recipients_payload
    ]
    expected = next_status(initial_status, event_type, recipients_state)
    assume(expected is not None and expected != initial_status)

    body = {
        "event": event_type,
        "payload": {
            "id": document_id,
            "status": "PENDING",
            "recipients": recipients_payload,
        },
        "createdAt": created_at,
    }
    return body, document_id, initial_status, recipients_payload, expected, failure_mode


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


async def _raising_audit(*_args, **_kwargs):
    """Async stand-in for ``write_audit_log`` that raises when awaited.

    Returns a coroutine (matching the real call shape, where
    ``write_audit_log(...)`` is evaluated as the ``_run_best_effort`` argument
    and only fails when awaited *inside* the SAVEPOINT).
    """
    raise RuntimeError("simulated audit-log INSERT failure")


async def _raising_notify(*_args, **_kwargs):
    """Async stand-in for ``create_in_app_notification`` that raises when
    awaited (the real one self-guards; we force a raise to prove the
    defence-in-depth SAVEPOINT wrapping swallows it too)."""
    raise RuntimeError("simulated notification failure")


async def _noop(*_args, **_kwargs):
    return None


def _run_apply_with_failing_side_effects(
    body, document_id, initial_status, recipients_payload, failure_mode
):
    """Apply a verified webhook once while audit and/or notification raise."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, document_id, initial_status, recipients_payload)
    session = _FakeWebhookSession(envelope)
    raw_body = json.dumps(body).encode("utf-8")

    audit_target = _raising_audit if failure_mode in ("audit", "both") else service.write_audit_log
    notify_target = (
        _raising_notify if failure_mode in ("notify", "both") else service.create_in_app_notification
    )

    async def _go():
        result = await service.apply_webhook(session, org_id=org_id, raw_body=raw_body)
        return result, envelope.status

    with patch.object(service, "write_audit_log", audit_target), patch.object(
        service, "create_in_app_notification", notify_target
    ), patch.object(service, "_trigger_signed_document_retrieval", _noop):
        result, status_after = asyncio.run(_go())

    return result, status_after, session


class TestAuditNotificationBestEffort:
    """Property 17: audit/notification failures never roll back the transition.

    **Validates: Requirements 14.3**
    """

    @given(scenario=_transition_scenario())
    @PBT_SETTINGS
    def test_applied_transition_survives_side_effect_failure(self, scenario):
        (
            body,
            document_id,
            initial_status,
            recipients_payload,
            expected_status,
            failure_mode,
        ) = scenario

        result, status_after, session = _run_apply_with_failing_side_effects(
            body, document_id, initial_status, recipients_payload, failure_mode
        )

        # apply_webhook never raises — the failing side-effect is swallowed.
        # The transition was applied despite audit/notification failure (R14.3).
        assert result.outcome == "applied", result.outcome

        # The envelope status reflects the NEW (transitioned) status — the
        # status change survived the best-effort side-effect failure.
        assert result.new_status == expected_status
        assert status_after == expected_status
        assert status_after != initial_status

        # The outer (envelope) transaction was committed, never rolled back —
        # only the failing side-effect's SAVEPOINT was rolled back.
        assert session.commits >= 1
        assert session.rollbacks == 0
        assert session.savepoint_rollbacks >= 1
