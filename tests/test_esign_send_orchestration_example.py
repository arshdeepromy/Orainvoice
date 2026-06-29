"""Example test for the create-and-send orchestration order (task 8.6).

The create-and-send flow in
:func:`app.modules.esignatures.service.create_and_send_envelope` must drive the
Documenso v2 RPC multi-step flow in a fixed order on valid input (R3.1):

    create_document → place_signature_field (once per signer) → send_document

(Under the v2 RPC API the PDF is uploaded **inline** with ``create_document``
as ``multipart/form-data``, so there is no separate ``upload_pdf`` step.)

This is an **example** test (not a Hypothesis property). It injects a spy
``DocumensoClient`` (via the ``client=`` parameter) that records the ORDER of
the async methods it is asked to perform, monkeypatches the connection gate so a
*verified* :class:`~app.integrations.documenso.DocumensoConnection` is returned
(the send proceeds), and stubs the best-effort audit/notification side-effect so
the orchestration assertion is isolated from those writes. It then asserts the
recorded call order is exactly:

  * ``create_document`` first,
  * ``place_signature_field`` once per **signer** recipient, all after
    ``create_document`` and before ``send_document``,
  * ``send_document`` last.

_Requirements: 3.1_
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

# Pre-load the full model graph (mirrors app/main.py + the esign property tests)
# so SQLAlchemy can resolve every string-based relationship reference when
# ``EsignEnvelope`` / ``EsignRecipient`` are instantiated and the mapper
# registry is configured.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoConnection,
    DocumensoCreateResult,
    RecipientSpec,
)
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

# A minimal but genuine PDF byte string (starts with the %PDF magic marker so
# the pure ``is_pdf`` validation passes).
_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"


# ---------------------------------------------------------------------------
# Spy DocumensoClient — records the ORDER of the calls it is asked to perform.
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    """Records the sequence of Documenso method invocations.

    ``create_document`` echoes one :class:`CreatedRecipient` per input recipient
    (matched by email, each with a distinct ``recipient_id`` + ``signingUrl``)
    so the service can place a signature field per signer; every other method
    simply appends its label to :attr:`calls`.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_document(
        self, *, title: str, recipients: list[RecipientSpec], pdf_bytes: bytes
    ) -> DocumensoCreateResult:
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=f"rcpt-{i}",
                email=spec.email,
                role=spec.role.upper(),
                token=f"tok-{i}",
                signing_url=f"https://documenso.example.test/sign/{i}",
            )
            for i, spec in enumerate(recipients)
        ]
        return DocumensoCreateResult(
            document_id="doc-123", envelope_id="envelope_doc-123", recipients=created
        )

    async def place_signature_field(self, document_id: str, **kwargs) -> None:
        self.calls.append("place_signature_field")

    async def send_document(
        self, document_id: str, *, signing_order_mode: str = "parallel"
    ) -> None:
        self.calls.append("send_document")


# ---------------------------------------------------------------------------
# Fake async session — add / flush / refresh are the only ORM hooks the
# success path touches once the audit/notification side-effect is stubbed.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_org",
        webhook_secret="whsec_org",
        documenso_team_id="team_org",
        webhook_routing_id="route_org",
        is_verified=True,
    )


def test_send_invokes_documenso_methods_in_order(monkeypatch):
    """Valid input drives create → upload → place(×signers) → send, in order."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Connection gate passes with a verified per-org connection (no DB needed).
    async def _fake_get_connection(_db, _org_id):
        return _verified_connection()

    monkeypatch.setattr(esign_service, "get_documenso_connection", _fake_get_connection)

    # Isolate the orchestration from the best-effort audit/notification writes
    # (those run in a SAVEPOINT the fake session does not implement).
    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)

    # Two SIGNER recipients so "once per signer" is genuinely exercised.
    payload = EnvelopeCreate(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com", signing_role="signer"),
            RecipientIn(name="Bob", email="bob@example.com", signing_role="signer"),
        ],
    )

    spy = _SpyDocumensoClient()
    session = _FakeSession()

    envelope = asyncio.run(
        esign_service.create_and_send_envelope(
            session,
            org_id=org_id,
            user_id=user_id,
            payload=payload,
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )

    # The flow completed and persisted a 'sent' envelope.
    assert envelope.status == "sent"

    # Exact orchestration order: create → place(×2 signers) → send.
    assert spy.calls == [
        "create_document",
        "place_signature_field",
        "place_signature_field",
        "send_document",
    ]

    # Structural guarantees independent of the exact count:
    assert spy.calls[0] == "create_document"
    assert spy.calls[-1] == "send_document"
    # place_signature_field happens once per signer (2), after create, before send.
    assert spy.calls.count("place_signature_field") == 2
    create_idx = spy.calls.index("create_document")
    send_idx = spy.calls.index("send_document")
    place_indices = [i for i, c in enumerate(spy.calls) if c == "place_signature_field"]
    assert all(create_idx < i < send_idx for i in place_indices)


def test_send_places_one_field_per_signer_skipping_viewers(monkeypatch):
    """A viewer recipient gets no signature field; only signers do (R17)."""
    org_id = uuid.uuid4()

    async def _fake_get_connection(_db, _org_id):
        return _verified_connection()

    monkeypatch.setattr(esign_service, "get_documenso_connection", _fake_get_connection)

    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)

    payload = EnvelopeCreate(
        agreement_type="nda",
        originating_entity_type="staff",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Signer", email="signer@example.com", signing_role="signer"),
            RecipientIn(name="Viewer", email="viewer@example.com", signing_role="viewer"),
        ],
    )

    spy = _SpyDocumensoClient()
    session = _FakeSession()

    asyncio.run(
        esign_service.create_and_send_envelope(
            session,
            org_id=org_id,
            user_id=None,
            payload=payload,
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )

    # Only the single signer gets a field; the viewer is skipped.
    assert spy.calls == [
        "create_document",
        "place_signature_field",
        "send_document",
    ]
