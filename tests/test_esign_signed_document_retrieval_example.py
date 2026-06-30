"""Example test: reaching ``completed`` triggers signed-document retrieval (task 13.5).

**Validates: Requirements 9.1**

Requirement 9.1: *WHEN an Envelope reaches Envelope_Status ``completed``, THE
Esign_Module SHALL retrieve the Signed_Document from Documenso.*

This is an **example** test (not a Hypothesis property). It pins the wiring that
connects the webhook status reducer to signed-document retrieval, in two
complementary layers:

1. **apply_webhook angle (the wiring under test, R9.1).** Driving
   :func:`app.modules.esignatures.service.apply_webhook` with a verified webhook
   that transitions a non-terminal envelope to ``completed`` (event
   ``DOCUMENT_COMPLETED``) invokes
   :func:`app.modules.esignatures.service._trigger_signed_document_retrieval`
   exactly once, with the envelope's ``id`` and the resolved ``org_id`` — and a
   **non-completing** transition (``DOCUMENT_VIEWED`` → ``viewed``) does **not**
   trigger retrieval at all. The trigger is replaced with an async spy so the
   assertion is isolated from the (separately tested, task 13.4) retrieval body.

2. **retrieval angle (R9.1 concretely — ``download_signed`` with a mocked
   client).** Firing the real
   :func:`~app.modules.esignatures.service._trigger_signed_document_retrieval`
   for a ``completed`` envelope drives the real retrieval entrypoint
   (``signed_document.retrieve_and_store_signed_document``), which calls
   ``download_signed`` on the (mocked) Documenso client for that envelope's
   document id. The encrypted-pipeline store and the fresh-session machinery are
   replaced with light stubs so this example proves only the
   "completed → download_signed" wiring (the encrypted-pipeline storage itself
   is covered by Property 19 / task 13.4).

Everything runs in-memory via ``asyncio.run`` (no DB), mirroring the no-DB
convention of ``test_esign_send_orchestration_example`` /
``test_esign_webhook_idempotent_property``.

_Requirements: 9.1_
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignEnvelope / EsignRecipient / EsignWebhookEvent
# are instantiated (mirrors the other esign unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures import signed_document as sd  # noqa: E402
from app.modules.esignatures.models import (  # noqa: E402
    EsignEnvelope,
    EsignRecipient,
    EsignWebhookEvent,
)

# A minimal genuine signed-PDF byte string (starts with the %PDF magic marker and
# carries a /ByteRange entry, the hallmark of a PDF digital signature, so it
# passes the retrieval signed-ness guard).
_SIGNED_PDF_BYTES = b"%PDF-1.7\n/ByteRange[0 1 2 3]\nsigned-agreement\n%%EOF\n"


# ===========================================================================
# Layer 1 — apply_webhook: completed transition triggers retrieval (R9.1)
# ===========================================================================


class _FakeNestedTxn:
    """Stands in for an ``AsyncSessionTransaction`` used via ``async with``.

    Never suppresses an exception, so a duplicate-insert ``IntegrityError`` would
    propagate exactly as a real SAVEPOINT would (not exercised here — every
    webhook in this test is a first-time delivery).
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
    """Minimal async-session stand-in for :func:`service.apply_webhook`.

    Serves the single pre-seeded envelope for the ``SELECT`` and accepts the
    event/envelope writes; ``begin_nested`` / ``flush`` / ``commit`` are enough
    for one verified, first-time webhook delivery.
    """

    def __init__(self, envelope: EsignEnvelope) -> None:
        self._envelope = envelope
        self.commits = 0
        self.rollbacks = 0

    def begin_nested(self):
        return _FakeNestedTxn()

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    async def flush(self):
        return None

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._envelope)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _build_envelope(org_id, *, status, document_id="doc-abc123"):
    env = EsignEnvelope(
        id=uuid.uuid4(),
        org_id=org_id,
        agreement_type="nda",
        originating_entity_type="staff",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id=document_id,
        status=status,
    )
    env.recipients.append(
        EsignRecipient(
            id=uuid.uuid4(),
            name="Signer One",
            email="signer1@example.com",
            signing_role="SIGNER",
            recipient_status="pending",
            documenso_recipient_id="rcpt-0",
        )
    )
    return env


def _completed_webhook_body(document_id):
    """A ``DOCUMENT_COMPLETED`` body (every recipient signed)."""
    return {
        "event": "DOCUMENT_COMPLETED",
        "payload": {
            "id": document_id,
            "status": "COMPLETED",
            "recipients": [
                {
                    "id": "rcpt-0",
                    "email": "signer1@example.com",
                    "signingStatus": "SIGNED",
                    "readStatus": "OPENED",
                }
            ],
        },
        "createdAt": "2026-06-28T10:00:00.000Z",
    }


def _viewed_webhook_body(document_id):
    """A ``DOCUMENT_VIEWED`` body — a non-completing transition (→ ``viewed``)."""
    return {
        "event": "DOCUMENT_VIEWED",
        "payload": {
            "id": document_id,
            "status": "PENDING",
            "recipients": [
                {
                    "id": "rcpt-0",
                    "email": "signer1@example.com",
                    "signingStatus": "NOT_SIGNED",
                    "readStatus": "OPENED",
                }
            ],
        },
        "createdAt": "2026-06-28T10:00:00.000Z",
    }


async def _noop(*_args, **_kwargs):
    return None


def _apply(body, envelope, org_id, trigger_spy):
    """Apply a single verified webhook, spying on the retrieval trigger."""
    session = _FakeWebhookSession(envelope)
    raw_body = json.dumps(body).encode("utf-8")

    async def _go():
        return await service.apply_webhook(session, org_id=org_id, raw_body=raw_body)

    # Isolate from the best-effort audit/notification writes and capture the
    # retrieval trigger instead of running it (its body is task 13.4's concern).
    with patch.object(service, "_audit_and_notify_transition", _noop), patch.object(
        service, "_trigger_signed_document_retrieval", trigger_spy
    ):
        return asyncio.run(_go())


def test_reaching_completed_triggers_signed_document_retrieval():
    """A ``DOCUMENT_COMPLETED`` transition triggers retrieval exactly once,
    with the envelope id + resolved org id (R9.1)."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, status="sent")

    calls: list[dict] = []

    async def _spy(*, org_id, envelope_id):
        calls.append({"org_id": org_id, "envelope_id": envelope_id})

    result = _apply(_completed_webhook_body(envelope.documenso_document_id), envelope, org_id, _spy)

    # The transition was applied and reached completed.
    assert result.outcome == "applied"
    assert result.new_status == "completed"
    assert result.reached_completed is True
    assert envelope.status == "completed"

    # Retrieval was triggered exactly once, for THIS envelope + org.
    assert len(calls) == 1
    assert calls[0]["envelope_id"] == envelope.id
    assert calls[0]["org_id"] == org_id


def test_recipient_completed_all_signed_also_triggers_retrieval():
    """``DOCUMENT_RECIPIENT_COMPLETED`` with every recipient signed reaches
    ``completed`` and triggers retrieval (the all-at-once path, R9.1)."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, status="sent")
    body = {
        "event": "DOCUMENT_RECIPIENT_COMPLETED",
        "payload": {
            "id": envelope.documenso_document_id,
            "status": "PENDING",
            "recipients": [
                {
                    "id": "rcpt-0",
                    "email": "signer1@example.com",
                    "signingStatus": "SIGNED",
                    "readStatus": "OPENED",
                }
            ],
        },
        "createdAt": "2026-06-28T10:05:00.000Z",
    }

    calls: list[dict] = []

    async def _spy(*, org_id, envelope_id):
        calls.append({"org_id": org_id, "envelope_id": envelope_id})

    result = _apply(body, envelope, org_id, _spy)

    assert result.new_status == "completed"
    assert result.reached_completed is True
    assert len(calls) == 1
    assert calls[0]["envelope_id"] == envelope.id


def test_non_completing_transition_does_not_trigger_retrieval():
    """A ``DOCUMENT_VIEWED`` transition (→ ``viewed``) does NOT trigger
    retrieval — only reaching ``completed`` does (R9.1)."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, status="sent")

    calls: list[dict] = []

    async def _spy(*, org_id, envelope_id):
        calls.append({"org_id": org_id, "envelope_id": envelope_id})

    result = _apply(_viewed_webhook_body(envelope.documenso_document_id), envelope, org_id, _spy)

    # The transition was applied (sent → viewed) but did not reach completed.
    assert result.outcome == "applied"
    assert result.new_status == "viewed"
    assert result.reached_completed is False

    # Retrieval was NOT triggered.
    assert calls == []


def test_already_completed_envelope_does_not_re_trigger_retrieval():
    """A subsequent non-void event on an already-``completed`` (terminal)
    envelope makes no transition and never re-triggers retrieval (R6.6 + R9.1)."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, status="completed")

    calls: list[dict] = []

    async def _spy(*, org_id, envelope_id):
        calls.append({"org_id": org_id, "envelope_id": envelope_id})

    # A late DOCUMENT_VIEWED against a terminal envelope: terminal immutability
    # means no transition, so retrieval must not fire again.
    result = _apply(_viewed_webhook_body(envelope.documenso_document_id), envelope, org_id, _spy)

    assert result.outcome == "no_transition"
    assert envelope.status == "completed"
    assert result.reached_completed is False
    assert calls == []


# ===========================================================================
# Layer 2 — the trigger drives ``download_signed`` on a mocked client (R9.1)
# ===========================================================================


class _MockDocumensoClient:
    """A mocked Documenso client recording ``download_signed`` invocations."""

    def __init__(self) -> None:
        self.download_calls: list[str] = []

    async def download_signed(self, document_id: str) -> bytes:
        self.download_calls.append(document_id)
        return _SIGNED_PDF_BYTES


class _FakeBeginCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeRetrievalSession:
    """Minimal session for :func:`retrieve_and_store_signed_document`.

    Serves the pre-seeded ``completed`` envelope for ``_load_envelope`` and
    accepts the ``flush`` after the file key is stamped. ``begin`` is the only
    transaction hook reached (audit + RLS are stubbed below).
    """

    def __init__(self, envelope: EsignEnvelope) -> None:
        self._envelope = envelope
        self.flushes = 0

    def begin(self):
        return _FakeBeginCtx()

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._envelope)

    async def flush(self):
        self.flushes += 1


class _FakeSessionFactoryCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def test_trigger_drives_download_signed_with_mocked_client():
    """Firing the real retrieval trigger for a ``completed`` envelope calls
    ``download_signed`` on the mocked client for that envelope's document id,
    and the envelope ends ``signed_doc_status='stored'`` (R9.1)."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, status="completed", document_id="doc-signed-xyz")
    envelope.signed_doc_status = "none"

    session = _FakeRetrievalSession(envelope)
    mock_client = _MockDocumensoClient()

    async def _fake_factory():
        return _FakeSessionFactoryCtx(session)

    async def _fake_resolve_client(_session, *, org_id, client, client_factory, http):
        # Inject the mocked client (bypass the per-org connection load).
        return mock_client, None

    async def _fake_store(_session, *, org_id, envelope_id, pdf_bytes):
        # Bypass the real encrypted uploads pipeline (covered by task 13.4),
        # but only after download_signed produced the bytes.
        assert pdf_bytes == _SIGNED_PDF_BYTES
        return f"esign_signed/{org_id}/{uuid.uuid4()}.pdf"

    async def _run_coro(_db, _what, coro):
        # Await the supplied side-effect coroutine so no coroutine is left
        # un-awaited (the audit body itself is stubbed to a no-op below).
        await coro

    async def _go():
        # The real trigger (service._trigger_signed_document_retrieval) lazily
        # imports signed_document and awaits retrieve_and_store_signed_document.
        await service._trigger_signed_document_retrieval(
            org_id=org_id, envelope_id=envelope.id
        )

    with patch.object(sd, "async_session_factory", lambda: _FakeSessionFactoryCtx(session)), patch.object(
        sd, "_set_rls_org_id", _noop
    ), patch.object(sd, "_resolve_client", _fake_resolve_client), patch.object(
        sd, "_store_via_encrypted_pipeline", _fake_store
    ), patch.object(sd, "write_audit_log", _noop), patch.object(sd, "_run_best_effort", _run_coro):
        asyncio.run(_go())

    # download_signed was called exactly once, for this envelope's document id.
    assert mock_client.download_calls == ["doc-signed-xyz"]
    # The retrieval completed: the envelope is now marked stored.
    assert envelope.signed_doc_status == "stored"
    assert envelope.signed_doc_file_key is not None


class _MockUnsignedDocumensoClient:
    """A mocked client whose download returns a still-UNSIGNED PDF (no /ByteRange)."""

    def __init__(self) -> None:
        self.download_calls: list[str] = []

    async def download_signed(self, document_id: str) -> bytes:
        self.download_calls.append(document_id)
        # The unsigned original — what Documenso serves before it finishes
        # sealing the completed document (the seal/completion race).
        return b"%PDF-1.7\noriginal-unsigned\n%%EOF\n"


def test_unsigned_download_is_deferred_not_stored():
    """If the downloaded bytes are not yet digitally signed (no signature
    dictionary), retrieval defers (marks ``pending_retrieval``) and stores
    nothing — guarding against persisting a pre-seal snapshot of the original."""
    org_id = uuid.uuid4()
    envelope = _build_envelope(org_id, status="completed", document_id="doc-not-sealed")
    envelope.signed_doc_status = "none"

    session = _FakeRetrievalSession(envelope)
    mock_client = _MockUnsignedDocumensoClient()

    async def _fake_resolve_client(_session, *, org_id, client, client_factory, http):
        return mock_client, None

    async def _fail_store(_session, *, org_id, envelope_id, pdf_bytes):  # pragma: no cover
        raise AssertionError("must not store an unsigned pre-seal snapshot")

    async def _run_coro(_db, _what, coro):
        await coro

    async def _go():
        return await sd.retrieve_and_store_signed_document(
            envelope_id=envelope.id, org_id=org_id
        )

    with patch.object(sd, "async_session_factory", lambda: _FakeSessionFactoryCtx(session)), patch.object(
        sd, "_set_rls_org_id", _noop
    ), patch.object(sd, "_resolve_client", _fake_resolve_client), patch.object(
        sd, "_store_via_encrypted_pipeline", _fail_store
    ), patch.object(sd, "write_audit_log", _noop), patch.object(sd, "_run_best_effort", _run_coro):
        outcome = asyncio.run(_go())

    # The download was attempted, but nothing was stored: the envelope is left
    # for the sweep to retry once Documenso has sealed the signed PDF.
    assert mock_client.download_calls == ["doc-not-sealed"]
    assert outcome.status == "pending_retrieval"
    assert envelope.signed_doc_status == "pending_retrieval"
    assert envelope.signed_doc_file_key is None
