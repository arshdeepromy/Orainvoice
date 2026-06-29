"""Property-based test: the connection gate blocks a field-placement send unless
the org's Documenso connection is present and verified (task 11.5).

# Feature: esignature-field-placement, Property 14: Sends are blocked unless the org's connection is present and verified

**Validates: Requirements 9.6**

Requirement 9.6: *IF the organisation's Documenso_Org_Connection is missing or
unverified, THEN the Esign_Module SHALL block the field-placement send with a
human-readable error directing the user to have the Documenso integration set
up.*

This test exercises **Step 0 (the connection gate)** of
:func:`app.modules.esignatures.service.create_and_send_envelope` for a send that
carries a sender-defined **Field_Set** (the field-placement path). Over a valid
field-placement send (a real PDF, >= 1 signer recipient, syntactically valid
unique emails, and a server-valid Field_Set in which every signer carries a
signature field) the property holds for every connection state:

* **Missing connection.** ``get_documenso_connection`` raises
  :class:`~app.integrations.documenso.DocumensoNotConfiguredError` -> the service
  raises HTTP **503** ``integration_not_configured`` with a non-empty,
  leak-free message AND makes **no** Documenso call (the spy records nothing).
* **Present-but-unverified connection.** ``get_documenso_connection`` returns a
  connection whose ``is_verified is False`` -> the service raises HTTP **503**
  ``integration_not_configured`` AND makes **no** Documenso call.
* **Present-and-verified connection.** ``get_documenso_connection`` returns a
  verified connection -> the send **proceeds**: the Field_Set path runs the
  Documenso flow (``create_document`` -> ``create_fields`` -> ``send_document``)
  and the persisted envelope is returned with status ``sent``.

This mirrors the established connection-gate / Documenso-failure convention of
the esign property suite (``test_esign_field_create_failure_property`` /
``test_esign_documenso_failure_property``): the per-org connection gate is driven
by patching ``get_documenso_connection``, the Documenso client is an injected
recording spy, the best-effort audit/notify side-effect is stubbed, and the
whole flow is driven in-memory with ``asyncio.run`` (the same no-DB approach the
existing esign property tests use — a live Documenso build / external DB is not
required to exercise the gate).
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignEnvelope / EsignRecipient are instantiated (mirrors the other esign
# unit/property tests).
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
    DocumensoNotConfiguredError,
)
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_INTEGRATION_NOT_CONFIGURED,
)
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the full send flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")
_NON_SIGNATURE_TYPES = ("initials", "name", "date", "email", "text")

# A minimal but valid PDF byte string (starts with the %PDF magic bytes that
# ``is_pdf`` checks).
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


class ConnState(enum.Enum):
    """The three Documenso connection states the gate must distinguish."""

    MISSING = "missing"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


# ---------------------------------------------------------------------------
# Recording spy DocumensoClient — records EVERY call so the test can assert
# that NO Documenso call is made when the gate blocks (R9.6).
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in that records call order and succeeds.

    On the verified path the field-set flow is ``create_document`` ->
    ``create_fields`` -> ``send_document``; ``create_document`` echoes one
    :class:`CreatedRecipient` per recipient (matched by email, numeric id so the
    service's recipientId reconciliation can ``int()`` it). On a gated path the
    spy must never be touched — :attr:`calls` stays empty.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, document_id: str = "doc-xyz") -> None:
        self.document_id = document_id
        self.calls: list[str] = []
        self.created_fields = None

    async def create_document(self, *, title, recipients, pdf_bytes):  # noqa: ANN001
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=str(i + 1),  # numeric id -> int()-able on reconcile
                email=str(spec.email),
                role=(spec.role or "signer").upper(),
                token=f"tok{i}",
                signing_url=f"https://sign.example.test/{i}",
            )
            for i, spec in enumerate(recipients)
        ]
        return DocumensoCreateResult(
            document_id=self.document_id,
            envelope_id=f"envelope_{self.document_id}",
            recipients=created,
        )

    async def create_fields(self, document_id, fields):  # noqa: ANN001
        self.calls.append("create_fields")
        self.created_fields = list(fields)

    async def place_signature_field(self, document_id, **_kwargs):  # noqa: ANN001
        # The Field_Set path must NOT use the single auto-placement.
        self.calls.append("place_signature_field")

    async def send_document(self, document_id, *, signing_order_mode="parallel"):  # noqa: ANN001
        self.calls.append("send_document")


# ---------------------------------------------------------------------------
# Fake async session — add / flush / refresh are the only hooks the success
# path touches once the audit/notify side-effect is stubbed.
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


class _DummyDb:
    """Placeholder request session — only handed to the (patched) conn loader."""


def _verified_connection(*, is_verified: bool) -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_raw",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=is_verified,
    )


# ---------------------------------------------------------------------------
# Generators — valid field-placement send (>= 1 signer, every signer signs) +
# a connection state.
# ---------------------------------------------------------------------------

_LOCAL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)
_LABEL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=6
)
_TLD = st.sampled_from(["com", "net", "org", "io", "co"])


@st.composite
def _scenario(draw):
    """Build a valid field-placement send + a connection state to apply."""
    n = draw(st.integers(min_value=1, max_value=4))
    recipients: list[RecipientIn] = []
    for i in range(n):
        # Unique local part per index guarantees distinct emails. First
        # recipient is forced to be a signer so the send always has >= 1 signer.
        local = f"{draw(_LOCAL)}{i}"
        email = f"{local}@{draw(_LABEL)}.{draw(_TLD)}"
        role = "signer" if i == 0 else draw(st.sampled_from(["signer", "viewer"]))
        recipients.append(
            RecipientIn(name=f"Recipient {i}", email=email, signing_role=role)
        )

    signer_indices = [
        i for i, r in enumerate(recipients) if r.signing_role == "signer"
    ]

    def _coord():
        # Keep x + w <= 100 and y + h <= 100 so every field is in-bounds.
        x = draw(st.floats(min_value=0.0, max_value=80.0))
        y = draw(st.floats(min_value=0.0, max_value=80.0))
        w = draw(st.floats(min_value=1.0, max_value=15.0))
        h = draw(st.floats(min_value=1.0, max_value=15.0))
        page = draw(st.integers(min_value=1, max_value=3))
        return x, y, w, h, page

    fields: list[FieldIn] = []
    # One signature field per signer (satisfies R6.1 so the set is server-valid).
    for idx in signer_indices:
        x, y, w, h, page = _coord()
        fields.append(
            FieldIn(
                type="signature",
                page=page,
                recipient_index=idx,
                position_x=x,
                position_y=y,
                width=w,
                height=h,
                required=True,
            )
        )
    # Optional extra fields of other types assigned to any recipient.
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        x, y, w, h, page = _coord()
        fields.append(
            FieldIn(
                type=draw(st.sampled_from(_NON_SIGNATURE_TYPES)),
                page=page,
                recipient_index=draw(st.integers(min_value=0, max_value=n - 1)),
                position_x=x,
                position_y=y,
                width=w,
                height=h,
                required=draw(st.booleans()),
            )
        )

    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=recipients,
        fields=fields,
    )
    state = draw(st.sampled_from(list(ConnState)))
    return payload, state


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run(payload: EnvelopeCreate, state: ConnState):
    """Drive create_and_send_envelope through the connection gate.

    Returns ``(exc, envelope, spy, org_id)`` where ``exc`` is the raised
    HTTPException (or ``None`` when the send proceeded) and ``envelope`` is the
    persisted envelope (or ``None`` when the gate blocked).
    """
    org_id = uuid.uuid4()
    spy = _SpyClient()
    session = _FakeSession()

    async def _fake_get_conn(_db, _org_id):
        if state is ConnState.MISSING:
            # A missing connection row raises (the loader never silently
            # falls back) — exactly what the gate intercepts -> 503.
            raise DocumensoNotConfiguredError("no connection row")
        return _verified_connection(is_verified=(state is ConnState.VERIFIED))

    async def _noop_audit(*_args, **_kwargs):
        return None

    async def _go():
        return await service.create_and_send_envelope(
            session,
            org_id=org_id,
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_VALID_PDF,
            client=spy,  # type: ignore[arg-type]
        )

    exc: HTTPException | None = None
    envelope = None
    with patch.object(
        service, "get_documenso_connection", _fake_get_conn
    ), patch.object(service, "_audit_and_notify_send", _noop_audit):
        try:
            envelope = asyncio.run(_go())
        except HTTPException as e:
            exc = e

    return exc, envelope, spy, org_id


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


class TestFieldSetConnectionGate:
    """Property 14: a field-placement send is blocked unless the org's Documenso
    connection is present AND verified.

    **Validates: Requirements 9.6**
    """

    @given(scenario=_scenario())
    @PBT_SETTINGS
    def test_connection_gate_blocks_unless_present_and_verified(self, scenario):
        payload, state = scenario
        exc, envelope, spy, org_id = _run(payload, state)

        if state is ConnState.VERIFIED:
            # --- Present-and-verified: the send PROCEEDS ---------------------
            assert exc is None, "a verified connection must not block the send"
            assert envelope is not None
            # The Field_Set path ran the Documenso flow in order (a Documenso
            # call WAS made), using field/create-many, not single placement.
            assert spy.calls == ["create_document", "create_fields", "send_document"]
            assert "place_signature_field" not in spy.calls
            assert envelope.status == "sent"
            assert envelope.org_id == org_id
        else:
            # --- Missing OR present-but-unverified: the send is BLOCKED ------
            assert envelope is None, "a gated send must not persist an envelope"
            assert exc is not None, f"expected the gate to block for state={state}"
            # Humanized 503 integration_not_configured.
            assert exc.status_code == 503
            assert isinstance(exc.detail, dict)
            assert exc.detail.get("code") == CODE_INTEGRATION_NOT_CONFIGURED
            message = exc.detail.get("message")
            assert isinstance(message, str) and message  # human-readable, non-empty
            # Leak-free: no raw exception / DB text in the message.
            assert "DocumensoNotConfiguredError" not in message
            assert "Traceback" not in message
            # CRITICAL (R9.6): NO Documenso call was made — the gate is Step 0,
            # before any client method is touched.
            assert spy.calls == []
