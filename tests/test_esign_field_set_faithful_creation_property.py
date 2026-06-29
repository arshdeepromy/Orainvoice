"""Property-based test: a valid Field_Set is created faithfully, in order (task 11.2).

# Feature: esignature-field-placement, Property 11: A valid Field_Set is created faithfully, in order, before distribute

**Validates: Requirements 7.4, 8.1, 8.2, 8.3, 8.5**

This test exercises the **Field_Set branch** of
:func:`app.modules.esignatures.service.create_and_send_envelope` — the path taken
when a send carries a non-empty sender-defined ``fields`` Field_Set. For every
valid Field_Set (each signer carries ≥1 signature field, every field references a
real recipient, every field is in-bounds, every type is supported) the property
holds:

* **Order (R8.1).** The Documenso calls occur ``create_document`` →
  ``create_fields`` (``field/create-many``) → ``send_document`` (distribute), in
  that exact order. The PDF is uploaded inline with ``create_document`` under the
  v2 RPC API, so there is no separate upload step.
* **Faithful payload (R7.4, R8.1, R8.2).** ``create_fields`` receives exactly one
  field per placed field, in order, each carrying the mapped UPPERCASE Documenso
  type, the field's page, its normalized coordinates verbatim, the built
  ``fieldMeta``, and a ``recipientId`` equal to the Documenso recipient id of the
  recipient at that field's ``recipient_index`` (reconciled by email).
* **No legacy single placement (R8.3).** ``place_signature_field`` is never
  called for a send that carries a Field_Set.
* **Envelope recorded (R8.5).** The persisted envelope carries ``org_id``, the
  agreement type, the originating-entity reference, the mapped Documenso document
  id, and status ``sent``.

The whole flow is driven in-memory with ``asyncio.run`` (mirroring the no-DB
convention of ``test_esign_per_org_token_property`` /
``test_esign_documenso_failure_property``): the per-org connection gate is
satisfied with a stub verified connection injected via a recording spy
``DocumensoClient`` (``client=``), and the best-effort audit/notify side-effect
is stubbed so the orchestration assertions are isolated from those writes.
"""

from __future__ import annotations

import asyncio
import uuid

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
    DocumensoFieldSpec,
    RecipientSpec,
)
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.field_mapping import (  # noqa: E402
    build_field_meta,
    map_field_type,
)
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the full send flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# Distinct base for the spy's Documenso recipient ids so ``recipientId`` is the
# created recipient's id at the field's recipient_index (created order preserved).
_RCPT_ID_BASE = 1000

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")
_FIELD_TYPES = ("signature", "initials", "name", "date", "email", "text")

# A minimal but valid PDF byte string (starts with the %PDF magic bytes that
# ``is_pdf`` checks).
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


# ---------------------------------------------------------------------------
# Recording spy DocumensoClient — records call ORDER and the Field_Set payload
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in for the Field_Set happy path.

    ``create_document`` echoes one :class:`CreatedRecipient` per input recipient
    (matched by email, ``recipient_id`` = ``_RCPT_ID_BASE + position`` as a
    numeric string so ``int()`` reconciliation works and the id is positional).
    ``create_fields`` captures the exact :class:`DocumensoFieldSpec` list it is
    handed. Every method appends its label to :attr:`calls` so the order is
    asserted.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, document_id: str = "doc-123") -> None:
        self.document_id = document_id
        self.calls: list[str] = []
        self.created_fields: list[DocumensoFieldSpec] | None = None

    async def create_document(self, *, title, recipients, pdf_bytes):  # noqa: ANN001
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=str(_RCPT_ID_BASE + i),
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
        # Must NEVER be called on the Field_Set path (R8.3) — record if it is so
        # the property fails loudly.
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


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_raw",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Generators — a valid recipient list (>=1 signer, unique emails) + a valid
# Field_Set (each signer has >=1 signature field, all in-bounds, valid types).
# ---------------------------------------------------------------------------


@st.composite
def _in_bounds_field(draw, *, recipient_index: int, force_type: str | None = None):
    """A single in-bounds FieldIn assigned to ``recipient_index``.

    Coordinates are generated so ``x+w <= 100`` and ``y+h <= 100`` with
    ``w,h > 0`` — i.e. they always satisfy both the Pydantic constraints and
    ``validate_field_set``'s in-bounds rule, so the Field_Set is valid.
    """
    ftype = force_type or draw(st.sampled_from(_FIELD_TYPES))
    page = draw(st.integers(min_value=1, max_value=5))
    x = draw(st.floats(min_value=0, max_value=95, allow_nan=False, allow_infinity=False))
    w = draw(st.floats(min_value=1, max_value=100 - x, allow_nan=False, allow_infinity=False))
    y = draw(st.floats(min_value=0, max_value=95, allow_nan=False, allow_infinity=False))
    h = draw(st.floats(min_value=1, max_value=100 - y, allow_nan=False, allow_infinity=False))
    required = draw(st.booleans())
    label = None
    placeholder = None
    if ftype == "text":
        label = draw(st.one_of(st.none(), st.text(min_size=1, max_size=12)))
        placeholder = draw(st.one_of(st.none(), st.text(min_size=1, max_size=12)))
    return FieldIn(
        type=ftype,
        page=page,
        recipient_index=recipient_index,
        position_x=x,
        position_y=y,
        width=w,
        height=h,
        required=required,
        label=label,
        placeholder=placeholder,
    )


@st.composite
def _scenario(draw):
    n = draw(st.integers(min_value=1, max_value=4))
    roles = draw(
        st.lists(st.sampled_from(["signer", "viewer"]), min_size=n, max_size=n)
    )
    # Guarantee >=1 signer (a zero-signer send is a validation error, not this path).
    if "signer" not in roles:
        roles[0] = "signer"
    # Unique emails so the email->created-recipient reconciliation is unambiguous.
    recipients = [
        RecipientIn(name=f"R{i}", email=f"r{i}@example.com", signing_role=roles[i])
        for i in range(n)
    ]
    signer_indices = [i for i, r in enumerate(recipients) if r.signing_role == "signer"]

    fields: list[FieldIn] = []
    # Every signer carries >=1 signature field (R6.1 — keeps the set valid).
    for idx in signer_indices:
        fields.append(draw(_in_bounds_field(recipient_index=idx, force_type="signature")))
    # Extra arbitrary (valid) fields assigned to any recipient.
    n_extra = draw(st.integers(min_value=0, max_value=6))
    for _ in range(n_extra):
        ri = draw(st.integers(min_value=0, max_value=n - 1))
        fields.append(draw(_in_bounds_field(recipient_index=ri)))

    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=recipients,
        fields=fields,
    )
    return payload


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run(payload: EnvelopeCreate):
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    spy = _SpyClient()
    conn = _verified_connection()
    session = _FakeSession()

    async def _fake_get_conn(_db, _org_id):
        return conn

    async def _noop_audit(*_args, **_kwargs):
        return None

    # Patch the connection gate and best-effort audit/notify (no DB needed).
    import unittest.mock as _mock

    with _mock.patch.object(
        esign_service, "get_documenso_connection", _fake_get_conn
    ), _mock.patch.object(esign_service, "_audit_and_notify_send", _noop_audit):
        envelope = asyncio.run(
            esign_service.create_and_send_envelope(
                session,
                org_id=org_id,
                user_id=user_id,
                payload=payload,
                pdf_bytes=_VALID_PDF,
                client=spy,  # type: ignore[arg-type]
            )
        )
    return envelope, spy, org_id


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


class TestFieldSetFaithfulInOrderCreation:
    """Property 11: a valid Field_Set is created faithfully, in order, before distribute.

    **Validates: Requirements 7.4, 8.1, 8.2, 8.3, 8.5**
    """

    @given(payload=_scenario())
    @PBT_SETTINGS
    def test_field_set_created_faithfully_in_order(self, payload):
        envelope, spy, org_id = _run(payload)

        # --- Order (R8.1): create -> field/create-many -> distribute ---------
        assert spy.calls == ["create_document", "create_fields", "send_document"]
        # Legacy single placement is NOT used for a Field_Set send (R8.3).
        assert "place_signature_field" not in spy.calls

        # --- Faithful payload (R7.4, R8.1, R8.2) -----------------------------
        specs = spy.created_fields
        assert specs is not None
        # Exactly one created field per placed field, in the same order.
        assert len(specs) == len(payload.fields)

        # Expected Documenso recipient id at a given recipient_index: the spy
        # echoes one created recipient per input recipient, in order, with
        # recipient_id = _RCPT_ID_BASE + position. So the field's recipient_index
        # maps to that positional id (emails are unique, order preserved).
        for placed, spec in zip(payload.fields, specs):
            assert spec.type == map_field_type(placed.type)
            assert spec.page_number == placed.page
            # Normalized coordinates carried verbatim (no rounding) (R7.4).
            assert spec.page_x == placed.position_x
            assert spec.page_y == placed.position_y
            assert spec.width == placed.width
            assert spec.height == placed.height
            # fieldMeta built faithfully from the placed field (R5.3/R5.4).
            assert spec.field_meta == build_field_meta(placed)
            # recipientId == the Documenso id of the recipient at recipient_index (R8.2).
            assert spec.recipient_id == _RCPT_ID_BASE + placed.recipient_index

        # --- Envelope recorded (R8.5) ----------------------------------------
        assert envelope.status == "sent"
        assert envelope.org_id == org_id
        assert envelope.agreement_type == payload.agreement_type
        assert envelope.originating_entity_type == payload.originating_entity_type
        assert envelope.originating_entity_id == payload.originating_entity_id
        assert envelope.documenso_document_id == spy.document_id
