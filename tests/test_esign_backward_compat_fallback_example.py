"""Example tests for the backward-compat auto-placement fallback (task 11.7).

:func:`app.modules.esignatures.service.create_and_send_envelope` keeps the
legacy single-signature auto-placement path for sends that carry **no**
sender-defined Field_Set, and switches to the ``field/create-many`` path for
sends that **do** carry one (R8.3). Concretely:

  * a send with **no** ``fields`` (omitted / ``None`` / empty) runs the existing
    single auto-placement path unchanged — ``place_signature_field`` is called
    (once per signer) and ``create_fields`` is **not**; and
  * a send **with** a valid ``fields`` list uses ``create_fields``
    (``field/create-many``) and **not** the single ``place_signature_field``.

These are **example** tests (not Hypothesis properties). They inject a spy
:class:`DocumensoClient` (via the ``client=`` parameter) that records which
methods are called, monkeypatch the connection gate so a *verified*
:class:`~app.integrations.documenso.DocumensoConnection` is returned (the send
proceeds), and stub the best-effort audit/notification side-effect so the
assertion is isolated from those writes. This follows the spy-client +
connection-injection patterns established in
``tests/test_esign_send_orchestration_example.py``.

_Requirements: 8.3_
"""

from __future__ import annotations

import asyncio
import uuid

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
    DocumensoFieldSpec,
    RecipientSpec,
)
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# A minimal but genuine PDF byte string (starts with the %PDF magic marker so
# the pure ``is_pdf`` validation passes).
_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"


# ---------------------------------------------------------------------------
# Spy DocumensoClient — records WHICH placement method is used.
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    """Records the sequence of Documenso method invocations.

    ``create_document`` echoes one :class:`CreatedRecipient` per input recipient
    (matched by email). Each ``recipient_id`` is a **numeric** string so the
    Field_Set path's ``int(recipient_id)`` reconciliation succeeds. Both
    ``place_signature_field`` (single auto-placement) and ``create_fields``
    (``field/create-many``) record themselves so a test can assert which path
    the send actually took.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.created_field_specs: list[DocumensoFieldSpec] | None = None

    async def create_document(
        self, *, title: str, recipients: list[RecipientSpec], pdf_bytes: bytes
    ) -> DocumensoCreateResult:
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=str(i + 1),  # numeric → int(recipient_id) works
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

    async def create_fields(
        self, document_id: str, fields: list[DocumensoFieldSpec]
    ) -> None:
        self.calls.append("create_fields")
        self.created_field_specs = list(fields)

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


def _patch_gate_and_audit(monkeypatch):
    """Make the connection gate pass and isolate the orchestration from the
    best-effort audit/notification writes (those run in a SAVEPOINT the fake
    session does not implement)."""

    async def _fake_get_connection(_db, _org_id):
        return _verified_connection()

    monkeypatch.setattr(esign_service, "get_documenso_connection", _fake_get_connection)

    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)


def test_send_without_fields_uses_auto_placement_not_create_fields(monkeypatch):
    """A send with NO Field_Set runs the legacy single auto-placement path
    (``place_signature_field`` per signer) and never calls ``create_fields``
    (R8.3 fallback)."""
    _patch_gate_and_audit(monkeypatch)

    payload = EnvelopeCreate(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com", signing_role="signer"),
            RecipientIn(name="Bob", email="bob@example.com", signing_role="signer"),
        ],
        # fields omitted → backward-compat fallback path
    )

    spy = _SpyDocumensoClient()

    envelope = asyncio.run(
        esign_service.create_and_send_envelope(
            _FakeSession(),
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )

    assert envelope.status == "sent"

    # The legacy single-signature auto-placement path ran: one
    # ``place_signature_field`` per signer (2), and NO ``create_fields``.
    assert spy.calls == [
        "create_document",
        "place_signature_field",
        "place_signature_field",
        "send_document",
    ]
    assert "create_fields" not in spy.calls
    assert spy.created_field_specs is None


def test_send_with_fields_uses_create_fields_not_single_placement(monkeypatch):
    """A send WITH a valid Field_Set uses ``create_fields``
    (``field/create-many``) and never the single ``place_signature_field``
    (R8.3)."""
    _patch_gate_and_audit(monkeypatch)

    payload = EnvelopeCreate(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com", signing_role="signer"),
            RecipientIn(name="Bob", email="bob@example.com", signing_role="signer"),
        ],
        # A valid Field_Set: each signer carries one signature field, all
        # in-bounds, assigned to a real recipient index.
        fields=[
            FieldIn(
                type="signature",
                page=1,
                recipient_index=0,
                position_x=10.0,
                position_y=10.0,
                width=25.0,
                height=8.0,
                required=True,
            ),
            FieldIn(
                type="signature",
                page=1,
                recipient_index=1,
                position_x=10.0,
                position_y=30.0,
                width=25.0,
                height=8.0,
                required=True,
            ),
        ],
    )

    spy = _SpyDocumensoClient()

    envelope = asyncio.run(
        esign_service.create_and_send_envelope(
            _FakeSession(),
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )

    assert envelope.status == "sent"

    # The Field_Set path ran: a single ``create_fields`` (full set) between
    # create and distribute, and NO single ``place_signature_field``.
    assert spy.calls == [
        "create_document",
        "create_fields",
        "send_document",
    ]
    assert "place_signature_field" not in spy.calls

    # ``create_fields`` carried exactly the two placed fields.
    assert spy.created_field_specs is not None
    assert len(spy.created_field_specs) == 2
