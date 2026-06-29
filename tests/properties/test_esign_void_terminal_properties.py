"""Property-based test for void-eligibility by terminality (task 9.3).

The function under test is
:func:`app.modules.esignatures.service.void_envelope`. After the router has
authorised the caller's role and module enablement, ``void_envelope``:

  * loads the envelope under the org's RLS context — a missing / cross-org row
    yields a humanized **404** (``not_found``);
  * if the envelope is in a **terminal** status (``completed`` / ``declined`` /
    ``voided``) it rejects with a humanized **409** (``not_voidable``) and makes
    **no** Documenso call (``cancel_document`` is never issued);
  * otherwise (a **non-terminal** status: ``draft`` / ``sent`` / ``viewed`` /
    ``partially_signed`` / ``error``) it calls
    :meth:`DocumensoClient.cancel_document` exactly once when the envelope
    carries a mapped Documenso document id, sets ``status='voided'``, flushes /
    refreshes, and writes a best-effort audit log + notification.

# Feature: esignature-integration, Property 12: Void is allowed exactly when non-terminal

**Validates: Requirements 5.4, 7.1, 7.2, 7.3**

Property 12: for *any* starting envelope status, the void succeeds — transitions
the envelope to ``voided`` and issues exactly one ``cancel_document`` (when a
Documenso document id is present) — **exactly when** the starting status is
non-terminal; for every terminal starting status the void is rejected with a
409 and ``cancel_document`` is **never** called and the status is left
unchanged.

A spy :class:`DocumensoClient` is injected via the ``client=`` parameter (it
records every ``cancel_document`` call) and the envelope is served from a
lightweight fake async session, so the test isolates the *void decision* with no
real DB or network. The best-effort audit/notify side-effect is stubbed to a
no-op so the property focuses purely on the terminal-vs-non-terminal gate.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import get_args
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the other esign property
# tests) so SQLAlchemy can resolve every string-based relationship reference
# when ``EsignEnvelope`` is instantiated and the whole mapper registry is
# configured. Without this, constructing a single ORM model can raise
# InvalidRequestError.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from fastapi import HTTPException  # noqa: E402

from app.modules.esignatures import service as svc  # noqa: E402
from app.modules.esignatures.errors import CODE_NOT_VOIDABLE  # noqa: E402
from app.modules.esignatures.models import EsignEnvelope  # noqa: E402
from app.modules.esignatures.status import (  # noqa: E402
    TERMINAL_STATUSES,
    EnvelopeStatus,
)

# The 8 envelope statuses, derived from the Literal so the test never drifts
# from the migration CHECK constraint / status reducer.
ALL_STATUSES: tuple[str, ...] = tuple(get_args(EnvelopeStatus))

# Sanity: the canonical terminal set is exactly {completed, declined, voided}
# and is a subset of the full status space.
assert TERMINAL_STATUSES == frozenset({"completed", "declined", "voided"})
assert TERMINAL_STATUSES <= set(ALL_STATUSES)


PBT_SETTINGS = settings(max_examples=200, deadline=None)


# ---------------------------------------------------------------------------
# Spy client — records every cancel_document call (and nothing else).
# ---------------------------------------------------------------------------


class _SpyClient:
    """Stand-in for :class:`DocumensoClient` injected via ``client=``.

    ``void_envelope`` only ever invokes ``cancel_document`` on the injected
    client, and only for a non-terminal envelope that carries a mapped Documenso
    document id. Recording the calls lets the property assert the
    "called exactly once iff non-terminal + has doc id, never otherwise" rule.
    """

    def __init__(self) -> None:
        self.cancel_calls: list[str] = []

    async def cancel_document(self, document_id: str) -> None:
        self.cancel_calls.append(document_id)


# ---------------------------------------------------------------------------
# Fake async session — serves the envelope SELECT and absorbs add/flush/refresh.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal AsyncSession stand-in for ``void_envelope``.

    ``_load_envelope_for_org`` issues a single ``execute(select(...))`` and reads
    ``scalar_one_or_none()`` — we return the generated envelope. ``add`` /
    ``flush`` / ``refresh`` are no-ops (the in-memory envelope object already
    carries the mutated status).
    """

    def __init__(self, envelope: EsignEnvelope | None):
        self._envelope = envelope
        self.added: list = []

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._envelope)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


def _make_envelope(status: str, *, has_doc_id: bool, org_id: uuid.UUID) -> EsignEnvelope:
    return EsignEnvelope(
        id=uuid.uuid4(),
        org_id=org_id,
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id="doc-abc-123" if has_doc_id else None,
        status=status,
    )


# ---------------------------------------------------------------------------
# Property 12 — void allowed exactly when non-terminal
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(status=st.sampled_from(ALL_STATUSES), has_doc_id=st.booleans())
def test_void_allowed_exactly_when_non_terminal(status: str, has_doc_id: bool):
    """Void succeeds iff the starting status is non-terminal.

    # Feature: esignature-integration, Property 12: Void is allowed exactly when non-terminal

    **Validates: Requirements 5.4, 7.1, 7.2, 7.3**
    """
    org_id = uuid.uuid4()
    envelope = _make_envelope(status, has_doc_id=has_doc_id, org_id=org_id)
    spy = _SpyClient()
    session = _FakeSession(envelope)
    is_terminal = status in TERMINAL_STATUSES

    async def _noop_audit(db, *, org_id, user_id, envelope):  # noqa: A002 - mirror sig
        return None

    with mock.patch.object(svc, "_audit_and_notify_void", _noop_audit):
        if is_terminal:
            # Terminal envelope → 409 not_voidable, NO Documenso call, no change.
            with pytest.raises(HTTPException) as excinfo:
                asyncio.run(
                    svc.void_envelope(
                        session,
                        org_id=org_id,
                        user_id=uuid.uuid4(),
                        envelope_id=envelope.id,
                        client=spy,
                    )
                )
            assert excinfo.value.status_code == 409
            assert excinfo.value.detail["code"] == CODE_NOT_VOIDABLE
            assert spy.cancel_calls == []  # cancel_document NEVER called
            assert envelope.status == status  # status left unchanged
        else:
            # Non-terminal envelope → voided, exactly one cancel call iff a
            # mapped Documenso document id is present.
            result = asyncio.run(
                svc.void_envelope(
                    session,
                    org_id=org_id,
                    user_id=uuid.uuid4(),
                    envelope_id=envelope.id,
                    client=spy,
                )
            )
            assert result is envelope
            assert envelope.status == "voided"
            if has_doc_id:
                assert spy.cancel_calls == ["doc-abc-123"]
            else:
                # No Documenso document mapped (e.g. a failed-send error
                # envelope) → voided locally with no Documenso call.
                assert spy.cancel_calls == []
