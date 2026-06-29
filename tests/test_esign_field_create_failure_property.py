"""Property-based test: a field-create failure blocks distribute and records an
error envelope (task 11.4).

# Feature: esignature-field-placement, Property 13: A field-creation failure blocks distribute and records an error envelope

**Validates: Requirements 8.4**

Requirement 8.4: *IF the Field_Create_Endpoint returns an error while creating
the Field_Set, THEN the Esign_Module SHALL NOT perform the Distribute_Step,
SHALL record the Envelope with Envelope_Status ``error``, AND SHALL return a
human-readable error message to the Org_Sender.*

This test exercises the **Field_Set branch** of
:func:`app.modules.esignatures.service.create_and_send_envelope`. For a *valid*
field-placement send (a real PDF, >= 1 signer recipient, syntactically valid
emails, a verified org connection, and a server-valid Field_Set in which every
signer carries a signature field), a spy :class:`DocumensoClient` whose
``create_fields`` raises a :class:`~app.integrations.documenso.DocumensoApiError`
drives the failure path. For every such failure the property holds:

* **(a)** ``send_document`` (the Distribute_Step) is **never** called — the flow
  stops at ``field/create-many``;
* **(b)** the service raises :class:`fastapi.HTTPException` with HTTP **502** and
  the humanized ``code == "documenso_error"``, carrying a non-empty,
  leak-free message; and
* **(c)** exactly one ``error``-status envelope is recorded on the **fresh,
  independently-committed** session (via ``_record_error_envelope`` →
  ``async_session_factory``), carrying the org id, agreement type, the
  originating-entity reference, and the Documenso document id known at the
  point of failure.

Per the connection-gate / Documenso-failure property convention the per-org
client is injected via ``client_factory`` and the fresh error-envelope session
is observed through a capturing fake session that replaces
``async_session_factory`` — so the fresh-session write is asserted without a
database (the same no-DB, ``asyncio.run`` approach used across the esign
property suite).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignEnvelope is instantiated inside _record_error_envelope (mirrors the
# other esign unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoApiError,
    DocumensoConnection,
    DocumensoCreateResult,
)
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.errors import CODE_DOCUMENSO_ERROR  # noqa: E402
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the full send flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# The verbatim upstream error text the spy raises — asserted to NEVER leak into
# the humanized response (R12.3).
_RAW_FIELD_ERROR = "field/create-many exploded: recipient 7 not found"

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


# ---------------------------------------------------------------------------
# Recording spy DocumensoClient — create_document OK, create_fields raises
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in whose ``create_fields`` always fails.

    Records the ordered list of calls so the test can assert the flow stopped at
    ``field/create-many`` and ``send_document`` was never reached. The
    ``create_document`` step returns a well-formed result with one
    ``CreatedRecipient`` per recipient (matched by email, carrying a
    **numeric** recipient id so the service's recipientId reconciliation can
    ``int()`` it).
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        self.calls: list[str] = []

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
        raise DocumensoApiError(_RAW_FIELD_ERROR, status=500)

    async def place_signature_field(self, document_id, **_kwargs):  # noqa: ANN001
        # The Field_Set path must NOT use the single auto-placement.
        self.calls.append("place_signature_field")

    async def send_document(self, document_id, *, signing_order_mode="parallel"):  # noqa: ANN001
        # MUST NOT be reached when create_fields fails (R8.4).
        self.calls.append("send_document")


# ---------------------------------------------------------------------------
# Capturing fake session/factory — observes the fresh-session error envelope
# ---------------------------------------------------------------------------


class _FakeTxn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _CapturingSession:
    """Minimal AsyncSession stand-in that captures added ORM objects.

    ``_record_error_envelope`` opens this via ``async_session_factory()`` as an
    async context manager, runs ``async with session.begin()``, sets the RLS
    org id (a plain ``execute``), then ``add``/``flush`` the error envelope.
    """

    def __init__(self, captured: list) -> None:
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return _FakeTxn()

    async def execute(self, *_args, **_kwargs):
        return None

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._captured.append(obj)

    async def flush(self):
        for obj in self._captured:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, _obj):
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
# Generators — valid send + a server-valid Field_Set (every signer signs)
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
    """Build a valid send (>= 1 signer, valid unique emails) + a server-valid
    Field_Set in which every signer carries a signature field, plus optional
    extra in-bounds fields of other types.
    """
    n = draw(st.integers(min_value=1, max_value=4))
    recipients: list[RecipientIn] = []
    for i in range(n):
        # Unique local part per index guarantees distinct emails (so recipientId
        # reconciliation by email is unambiguous). First recipient is forced to
        # be a signer so the send always has >= 1 signer.
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
    return payload


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run_field_create_failure(payload: EnvelopeCreate):
    """Drive create_and_send_envelope to a ``field/create-many`` failure.

    Returns ``(exc, captured, spy, org_id)`` where ``exc`` is the raised
    HTTPException (or ``None``), ``captured`` is the list of ORM objects written
    to the fresh error-envelope session, and ``spy`` is the recording client.
    """
    org_id = uuid.uuid4()
    captured: list = []
    spy = _SpyClient(document_id="doc-xyz")
    conn = _verified_connection()

    async def _fake_get_conn(_db, _org_id):
        return conn

    def _factory(*_args, **_kwargs):
        # async_session_factory() takes no args; the conn client_factory takes a
        # connection. Tolerate both call shapes with *args/**kwargs.
        return _CapturingSession(captured)

    def _client_factory(_conn):
        return spy

    async def _noop_audit(*_args, **_kwargs):
        return None

    async def _go():
        return await service.create_and_send_envelope(
            _DummyDb(),
            org_id=org_id,
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_VALID_PDF,
            client_factory=_client_factory,
        )

    exc: HTTPException | None = None
    with patch.object(service, "get_documenso_connection", _fake_get_conn), patch.object(
        service, "async_session_factory", _factory
    ), patch.object(service, "_audit_and_notify_send", _noop_audit):
        try:
            asyncio.run(_go())
        except HTTPException as e:
            exc = e

    return exc, captured, spy, org_id


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


class TestFieldCreateFailureBlocksDistribute:
    """Property 13: a field-creation failure blocks distribute and records an
    error envelope.

    **Validates: Requirements 8.4**
    """

    @given(payload=_scenario())
    @PBT_SETTINGS
    def test_field_create_failure_blocks_distribute_and_records_error(self, payload):
        exc, captured, spy, org_id = _run_field_create_failure(payload)

        # (a) Distribute was never performed — the flow stopped at create_fields,
        #     and the legacy single auto-placement was not used.
        assert spy.calls[-1] == "create_fields"
        assert "send_document" not in spy.calls
        assert "place_signature_field" not in spy.calls
        assert spy.calls == ["create_document", "create_fields"]

        # (b) A humanized 502 documenso_error is raised, leaking no raw text.
        assert exc is not None, "expected HTTPException for field/create-many failure"
        assert exc.status_code == 502
        assert isinstance(exc.detail, dict)
        assert exc.detail.get("code") == CODE_DOCUMENSO_ERROR
        message = exc.detail.get("message")
        assert isinstance(message, str) and message
        assert "DocumensoApiError" not in message
        assert _RAW_FIELD_ERROR not in message

        # (c) Exactly one error-status envelope recorded on the fresh session.
        envelopes = [
            obj for obj in captured if isinstance(obj, service.EsignEnvelope)
        ]
        assert len(envelopes) == 1
        env = envelopes[0]
        assert env.status == "error"
        assert env.org_id == org_id
        assert env.agreement_type == payload.agreement_type
        assert env.originating_entity_type == payload.originating_entity_type
        assert env.originating_entity_id == payload.originating_entity_id
        # The Documenso document id known at the point of failure is recorded
        # (create_document succeeded, so the created id is present).
        assert env.documenso_document_id == "doc-xyz"
        # A humanized error message is stored and leaks no raw exception text.
        assert env.last_error
        assert "DocumensoApiError" not in (env.last_error or "")
        assert _RAW_FIELD_ERROR not in (env.last_error or "")
