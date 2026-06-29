"""Property-based test: Documenso failure records an error envelope (task 8.5).

# Feature: esignature-integration, Property 18: Documenso failure records an error envelope

**Validates: Requirements 3.5**

Requirement 3.5: *IF the Documenso API returns an error during document creation
or send, THEN the Esign_Module SHALL record the Envelope with Envelope_Status
``error`` AND SHALL return a human-readable error message to the Org_Sender.*

This test exercises :func:`app.modules.esignatures.service.create_and_send_envelope`
for **valid** send inputs (a real PDF, ≥1 signer recipient, syntactically valid
emails, a verified org connection) where the injected Documenso client raises a
:class:`~app.integrations.documenso.DocumensoApiError` at one of the
*document-creation-or-send* steps that R3.5 covers — ``create_document`` or
``send_document`` (under the v2 RPC API the PDF is uploaded inline with
``create_document``, so there is no separate ``upload_pdf`` step). For every
such failure the property holds:

* **(a)** the service raises :class:`fastapi.HTTPException` with HTTP **502** and
  the humanized ``code == "documenso_error"``; and
* **(b)** an ``error``-status envelope is recorded on a **fresh,
  independently-committed** session (via ``_record_error_envelope`` →
  ``async_session_factory``) carrying the org id, the originating-entity
  reference, and the Documenso document id known at the point of failure.

Scope note — ``place_signature_field`` is **deliberately excluded** here: a
field-placement failure is the distinct R17 path (it is intercepted by the
service, still records an ``error`` envelope, but returns HTTP **422**
``signature_field_failed`` rather than a 502 ``documenso_error``). That path is
owned by Property 25 / task 8.8 and is not part of Property 18.

The whole flow is driven in-memory: the per-org connection gate is satisfied
with a stub verified connection, the Documenso client is a recording spy, and
``async_session_factory`` is replaced with a capturing fake session so the
fresh-session error-envelope write is observed without a database. This mirrors
the no-DB, ``asyncio.run`` convention of ``test_esign_per_org_token_property``.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
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
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the full send flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# The document-creation-or-send steps R3.5 covers: a DocumensoError raised at
# any of these surfaces as a humanized 502 ``documenso_error`` (see scope note).
FAIL_STEPS = ("create_document", "send_document")

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")

# A minimal but valid PDF byte string (starts with the %PDF magic bytes that
# ``is_pdf`` checks). The trailing single-page marker lets ``pdf_page_count``
# resolve a real last page; the property holds regardless of the page result.
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


# ---------------------------------------------------------------------------
# Recording spy DocumensoClient — raises a DocumensoApiError at one chosen step
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in that fails at exactly one step.

    Records the ordered list of calls so the test can assert *where* the flow
    stopped, and returns a well-formed ``create_document`` result (one
    ``CreatedRecipient`` per recipient, matched by email) for the steps that do
    not fail.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, fail_step: str, document_id: str) -> None:
        self.fail_step = fail_step
        self.document_id = document_id
        self.calls: list[str] = []

    async def create_document(self, *, title, recipients, pdf_bytes):  # noqa: ANN001
        self.calls.append("create_document")
        if self.fail_step == "create_document":
            raise DocumensoApiError("create failed", status=500)
        created = [
            CreatedRecipient(
                recipient_id=f"r{i}",
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

    async def place_signature_field(self, document_id, **_kwargs):  # noqa: ANN001
        self.calls.append("place_signature_field")
        # Never the failing step in this property (see scope note).

    async def send_document(self, document_id, *, signing_order_mode="parallel"):  # noqa: ANN001
        self.calls.append("send_document")
        if self.fail_step == "send_document":
            raise DocumensoApiError("send failed", status=503)


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
# Generators — valid send inputs (≥1 signer, valid emails) + a failing step
# ---------------------------------------------------------------------------

_LOCAL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=10
)
_LABEL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)
_TLD = st.sampled_from(["com", "net", "org", "io", "co"])


@st.composite
def _recipient(draw, *, force_signer: bool = False):
    name = draw(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ abc", min_size=1, max_size=12))
    email = f"{draw(_LOCAL)}@{draw(_LABEL)}.{draw(_TLD)}"
    role = "signer" if force_signer else draw(st.sampled_from(["signer", "viewer"]))
    return RecipientIn(name=name.strip() or "Recipient", email=email, signing_role=role)


@st.composite
def _scenario(draw):
    # First recipient is forced to be a signer so the send always has ≥1 signer
    # (a zero-signer send is a validation error, not a Documenso failure).
    first = draw(_recipient(force_signer=True))
    rest = draw(st.lists(_recipient(), min_size=0, max_size=4))
    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=[first, *rest],
    )
    fail_step = draw(st.sampled_from(FAIL_STEPS))
    return payload, fail_step


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run_failure_scenario(payload: EnvelopeCreate, fail_step: str):
    """Drive create_and_send_envelope to a Documenso failure; return outcome.

    Returns ``(exc, captured, spy)`` where ``exc`` is the raised HTTPException
    (or ``None`` if none), ``captured`` is the list of ORM objects written to
    the fresh error-envelope session, and ``spy`` is the recording client.
    """
    org_id = uuid.uuid4()
    captured: list = []
    spy = _SpyClient(fail_step, document_id="doc-xyz")
    conn = _verified_connection()

    async def _fake_get_conn(_db, _org_id):
        return conn

    def _factory():
        return _CapturingSession(captured)

    async def _noop_audit(*_args, **_kwargs):
        return None

    async def _go():
        return await service.create_and_send_envelope(
            _DummyDb(),
            org_id=org_id,
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_VALID_PDF,
            client=spy,
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


class TestDocumensoFailureRecordsErrorEnvelope:
    """Property 18: a Documenso failure raises a 502 AND records an error envelope.

    **Validates: Requirements 3.5**
    """

    @given(scenario=_scenario())
    @PBT_SETTINGS
    def test_documenso_failure_records_error_envelope(self, scenario):
        payload, fail_step = scenario
        exc, captured, spy, org_id = _run_failure_scenario(payload, fail_step)

        # (a) A humanized 502 documenso_error is raised.
        assert exc is not None, f"expected HTTPException for fail at {fail_step}"
        assert exc.status_code == 502
        assert isinstance(exc.detail, dict)
        assert exc.detail.get("code") == CODE_DOCUMENSO_ERROR
        # Human-readable message present and leaks no raw exception text.
        message = exc.detail.get("message")
        assert isinstance(message, str) and message
        assert "DocumensoApiError" not in message
        for raw in ("create failed", "send failed"):
            assert raw not in message

        # The flow stopped at the failing step — never sent after a create
        # failure, and the failing step is the last call recorded.
        assert spy.calls[-1] == fail_step
        if fail_step == "create_document":
            assert "send_document" not in spy.calls
            assert "place_signature_field" not in spy.calls

        # (b) Exactly one error-status envelope was recorded on the fresh session.
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
        assert env.last_error  # a humanized error message is stored, no leak
        assert "DocumensoApiError" not in (env.last_error or "")

        # The Documenso document id known at the point of failure is recorded:
        # None when create_document failed (no id yet), else the created id.
        if fail_step == "create_document":
            assert env.documenso_document_id is None
        else:
            assert env.documenso_document_id == "doc-xyz"
