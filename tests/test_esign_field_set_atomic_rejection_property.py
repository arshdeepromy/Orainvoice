"""Property-based test: an invalid Field_Set is rejected before any Documenso
call (task 11.3).

# Feature: esignature-field-placement, Property 12: An invalid Field_Set is rejected before any Documenso call

**Validates: Requirements 6.6**

Requirement 6.6: *THE Esign_Module SHALL re-validate the submitted Field_Set on
the server before creating any Field on the Documenso_Document AND SHALL reject
a send whose Field_Set fails server-side validation with a human-readable error
without creating any Field.*

This test exercises the **Step 1b server-side re-validation** in
:func:`app.modules.esignatures.service.create_and_send_envelope` — the
``validate_field_set`` call that runs **before** any Documenso call. For every
send whose inputs are otherwise valid (a real PDF, ≥1 signer recipient,
syntactically valid emails, a verified org connection) but whose **Field_Set
fails server validation**, the property holds:

* **(a)** the service raises :class:`fastapi.HTTPException` with HTTP **422**
  and a humanized, leak-free ``message`` carrying one of the field-set
  validation codes (``field_unassigned`` / ``field_out_of_bounds`` /
  ``invalid_field_type`` / ``signature_field_missing``); and
* **(b)** **zero** Documenso methods are invoked (no document / recipient /
  field is created and the document is never distributed); and
* **(c)** **no** envelope is persisted — neither a ``sent`` envelope on the
  request session nor an ``error`` envelope on a fresh session.

The invalid Field_Set is generated across three failure modes that are
expressible through the ``FieldIn`` Pydantic guard yet still fail
``validate_field_set``:

* ``unassigned`` — a field whose ``recipient_index`` is out of range (R6.2);
* ``out_of_bounds`` — a field whose ``x + w`` exceeds the page (R6.3);
* ``signature_missing`` — a signer carries only a non-signature field, so it
  has no signature field (R6.1).

The whole flow is driven in-memory: the per-org connection gate is satisfied
with a stub verified connection, the Documenso client is a recording spy that
fails loudly if *any* method is invoked, and both the request session and
``async_session_factory`` capture every added ORM object so the "nothing
persisted" guarantee is observed without a database. This mirrors the no-DB,
``asyncio.run`` convention of ``test_esign_documenso_failure_property``.
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
# if an EsignEnvelope is ever instantiated (mirrors the other esign tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import DocumensoConnection  # noqa: E402
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.field_validation import (  # noqa: E402
    CODE_FIELD_OUT_OF_BOUNDS,
    CODE_FIELD_UNASSIGNED,
    CODE_INVALID_FIELD_TYPE,
    CODE_SIGNATURE_FIELD_MISSING,
)
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the send flow up to the
# rejection point.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# The four field-set validation codes, all HTTP 422 (R6.6). A rejection from
# Step 1b must carry one of these (never a generic / unrelated code).
_FIELD_SET_CODES = frozenset(
    {
        CODE_FIELD_UNASSIGNED,
        CODE_FIELD_OUT_OF_BOUNDS,
        CODE_INVALID_FIELD_TYPE,
        CODE_SIGNATURE_FIELD_MISSING,
    }
)

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")

# A minimal but valid PDF byte string (starts with the %PDF magic bytes that
# ``is_pdf`` checks), so the source passes the PDF gate and the flow reaches the
# Step 1b Field_Set re-validation.
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


# ---------------------------------------------------------------------------
# Recording spy DocumensoClient — fails loudly if ANY method is invoked
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    """A DocumensoClient stand-in that records every method it is asked for.

    ``__getattr__`` returns a recording async callable for *any* method name
    (``create_document``, ``create_fields``, ``place_signature_field``,
    ``send_document``, …) so the test can assert — for the Field_Set rejection
    path — that **no** Documenso method was ever invoked. Reaching any of them
    would itself be a bug (the re-validation must reject before the Documenso
    flow starts), and the recorded :attr:`calls` make that visible.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        # Only reached for names not set on the instance/class (i.e. methods).
        async def _record(*_args, **_kwargs):
            self.calls.append(name)
            return None

        return _record


# ---------------------------------------------------------------------------
# Capturing sessions — observe that NOTHING is persisted on either session
# ---------------------------------------------------------------------------


class _FakeTxn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _CapturingSession:
    """Captures added ORM objects on the request session.

    The Field_Set rejection raises before any ``add`` happens, so ``captured``
    must stay empty — the test asserts no :class:`EsignEnvelope` was persisted.
    """

    def __init__(self, captured: list) -> None:
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return _FakeTxn()

    def begin_nested(self):
        return _FakeTxn()

    async def execute(self, *_args, **_kwargs):
        return None

    def add(self, obj):
        self._captured.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


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
# Generators — valid send inputs + an INVALID Field_Set
# ---------------------------------------------------------------------------

_LOCAL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=10
)
_LABEL = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)
_TLD = st.sampled_from(["com", "net", "org", "io", "co"])

_NON_SIGNATURE_TYPES = ("initials", "name", "date", "email", "text")


@st.composite
def _recipient(draw, *, force_signer: bool = False):
    name = draw(
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ abc", min_size=1, max_size=12)
    )
    email = f"{draw(_LOCAL)}@{draw(_LABEL)}.{draw(_TLD)}"
    role = "signer" if force_signer else draw(st.sampled_from(["signer", "viewer"]))
    return RecipientIn(name=name.strip() or "Recipient", email=email, signing_role=role)


@st.composite
def _invalid_scenario(draw):
    """Generate a send with valid inputs but a server-invalid Field_Set."""
    # First recipient forced signer so the send always has >=1 signer (a
    # zero-signer send is a *different* validation error, not a Field_Set one).
    first = draw(_recipient(force_signer=True))
    rest = draw(st.lists(_recipient(), min_size=0, max_size=4))
    recipients = [first, *rest]
    recipient_count = len(recipients)
    signer_indices = [
        i for i, r in enumerate(recipients) if r.signing_role == "signer"
    ]

    mode = draw(
        st.sampled_from(["unassigned", "out_of_bounds", "signature_missing"])
    )

    if mode == "unassigned":
        # R6.2 — recipient_index out of range (>= recipient_count). Valid under
        # the Pydantic FieldIn guard (ge=0) but rejected by validate_field_set.
        bad_index = recipient_count + draw(st.integers(min_value=0, max_value=3))
        fields = [
            FieldIn(
                type="signature",
                page=draw(st.integers(min_value=1, max_value=5)),
                recipient_index=bad_index,
                position_x=10.0,
                position_y=10.0,
                width=10.0,
                height=10.0,
            )
        ]
    elif mode == "out_of_bounds":
        # R6.3 — x + w exceeds the page. position_x in [60,100] and width in
        # [50,100] guarantees x + w >= 110 > 100 while each stays within the
        # Pydantic FieldIn guard (le=100).
        ridx = draw(st.sampled_from(signer_indices))
        px = draw(st.floats(min_value=60.0, max_value=100.0))
        w = draw(st.floats(min_value=50.0, max_value=100.0))
        fields = [
            FieldIn(
                type="signature",
                page=draw(st.integers(min_value=1, max_value=5)),
                recipient_index=ridx,
                position_x=px,
                position_y=10.0,
                width=w,
                height=10.0,
            )
        ]
    else:  # signature_missing
        # R6.1 — a signer carries only a non-signature field, so it has no
        # signature field. The Field_Set is non-empty (so the field-set branch
        # is taken) yet a signer lacks the required signature field.
        ridx = draw(st.sampled_from(signer_indices))
        ftype = draw(st.sampled_from(_NON_SIGNATURE_TYPES))
        fields = [
            FieldIn(
                type=ftype,
                page=draw(st.integers(min_value=1, max_value=5)),
                recipient_index=ridx,
                position_x=10.0,
                position_y=10.0,
                width=10.0,
                height=10.0,
            )
        ]

    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=recipients,
        fields=fields,
    )
    return payload, mode


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run_rejection_scenario(payload: EnvelopeCreate):
    """Drive create_and_send_envelope with an invalid Field_Set.

    Returns ``(exc, spy, request_added, fresh_added)`` where ``exc`` is the
    raised HTTPException (or ``None``), ``spy`` is the recording client,
    ``request_added`` is the list of ORM objects added on the request session,
    and ``fresh_added`` is the list added on any fresh ``async_session_factory``
    session.
    """
    org_id = uuid.uuid4()
    spy = _SpyDocumensoClient()
    conn = _verified_connection()
    request_added: list = []
    fresh_added: list = []

    async def _fake_get_conn(_db, _org_id):
        return conn

    def _fresh_factory():
        return _CapturingSession(fresh_added)

    request_db = _CapturingSession(request_added)

    async def _go():
        return await service.create_and_send_envelope(
            request_db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            payload=payload,
            pdf_bytes=_VALID_PDF,
            client=spy,  # type: ignore[arg-type]
        )

    exc: HTTPException | None = None
    with patch.object(service, "get_documenso_connection", _fake_get_conn), patch.object(
        service, "async_session_factory", _fresh_factory
    ):
        try:
            asyncio.run(_go())
        except HTTPException as e:
            exc = e

    return exc, spy, request_added, fresh_added


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


class TestInvalidFieldSetRejectedBeforeDocumenso:
    """Property 12: an invalid Field_Set is rejected before any Documenso call.

    **Validates: Requirements 6.6**
    """

    @given(scenario=_invalid_scenario())
    @PBT_SETTINGS
    def test_invalid_field_set_rejected_before_documenso(self, scenario):
        payload, mode = scenario
        exc, spy, request_added, fresh_added = _run_rejection_scenario(payload)

        # (a) A humanized 422 carrying a field-set validation code is raised.
        assert exc is not None, f"expected HTTPException (mode={mode})"
        assert exc.status_code == 422
        assert isinstance(exc.detail, dict)
        code = exc.detail.get("code")
        assert code in _FIELD_SET_CODES, f"unexpected code {code!r} (mode={mode})"
        message = exc.detail.get("message")
        assert isinstance(message, str) and message
        # Leak-free: no raw exception/DB/stack-trace text.
        for leak in ("Traceback", "Exception", "ValidationError", "SQL", 'File "'):
            assert leak not in message

        # (b) Zero Documenso methods were invoked — the re-validation rejected
        # before the Documenso flow began (no create / field create / distribute).
        assert spy.calls == [], f"no Documenso call expected, saw {spy.calls}"

        # (c) Nothing was persisted: no 'sent' envelope on the request session
        # and no 'error' envelope on a fresh session.
        request_envelopes = [
            obj for obj in request_added if isinstance(obj, service.EsignEnvelope)
        ]
        fresh_envelopes = [
            obj for obj in fresh_added if isinstance(obj, service.EsignEnvelope)
        ]
        assert request_envelopes == []
        assert fresh_envelopes == []
