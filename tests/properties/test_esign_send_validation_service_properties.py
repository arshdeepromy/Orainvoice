"""Property-based test for the SERVICE-layer portion of Property 8 (task 8.4).

The pure-core portion of Property 8 (``is_pdf`` / ``validate_recipients``) is
covered by ``tests/properties/test_esign_send_validation_properties.py``
(task 4.2). This module covers the **service-layer** portion: that
:func:`app.modules.esignatures.service.create_and_send_envelope` is **atomic and
side-effect-free on any invalid send input** — it raises an
:class:`fastapi.HTTPException` (422, humanized ``{message, code}``) **before**
making any Documenso call and **without** persisting any envelope/recipient row.

Invalid send inputs span four categories:

  * **non-PDF** source bytes (do not start with ``%PDF``)            — R3.4
  * **empty** recipient list                                         — R3.3
  * a recipient list with **≥1 syntactically invalid email**         — R4.2/4.3/4.6
  * a recipient list with **zero signers** (all viewers)             — R17 / R4

Because the API schema (``EnvelopeCreate`` / ``RecipientIn``) enforces
``recipients`` ``min_length=1`` and ``EmailStr`` at the Pydantic boundary, the
empty-list and invalid-email payloads are built with ``model_construct`` so they
bypass schema validation and reach the service's **own** guards (``is_pdf`` /
``validate_recipients`` / the zero-signers check) — which is exactly the layer
under test here.

Test harness:
  * ``service.get_documenso_connection`` is patched to return a **verified**
    :class:`~app.integrations.documenso.DocumensoConnection` so the connection
    gate (R19.3/19.4) passes and execution reaches the validation guards.
  * a **spy** ``DocumensoClient`` is injected; it records every method call so
    the test can assert it was **never** touched.
  * a lightweight fake async session records ``add()`` calls (and fails loudly
    if ``flush``/``refresh``/``execute`` are reached) so the test can assert no
    rows were persisted.

# Feature: esignature-integration, Property 8: Send validation is atomic and side-effect-free

**Validates: Requirements 3.3, 3.4, 4.2, 4.3, 4.6**
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the other esign service
# property tests) so SQLAlchemy can resolve every string-based relationship
# reference when ``EsignEnvelope`` / ``EsignRecipient`` are instantiated.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import DocumensoConnection  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_INVALID_RECIPIENT_EMAIL,
    CODE_NO_RECIPIENTS,
    CODE_NO_SIGNERS,
    CODE_NOT_PDF,
)
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402
from app.modules.esignatures import service as esign_service  # noqa: E402

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

_AGREEMENT_TYPES = [
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
]
_ENTITY_TYPES = ["invoice", "quote", "staff"]

# Every validation guard exercised here maps to HTTP 422 in the design's Error
# Handling table.
_VALIDATION_STATUS = 422
_EXPECTED_CODES = {
    "non_pdf": CODE_NOT_PDF,
    "empty_recipients": CODE_NO_RECIPIENTS,
    "invalid_email": CODE_INVALID_RECIPIENT_EMAIL,
    "zero_signers": CODE_NO_SIGNERS,
}


# ---------------------------------------------------------------------------
# Spy client + fake session
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    """Records every Documenso method call so a zero-call assertion is possible.

    On the validation-failure path under test, NONE of these should ever be
    invoked — the service must reject before any Documenso interaction.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_document(self, *args, **kwargs):  # pragma: no cover - never called
        self.calls.append("create_document")
        raise AssertionError("create_document must not be called on invalid input")

    async def upload_pdf(self, *args, **kwargs):  # pragma: no cover - never called
        self.calls.append("upload_pdf")
        raise AssertionError("upload_pdf must not be called on invalid input")

    async def place_signature_field(self, *args, **kwargs):  # pragma: no cover
        self.calls.append("place_signature_field")
        raise AssertionError("place_signature_field must not be called on invalid input")

    async def send_document(self, *args, **kwargs):  # pragma: no cover - never called
        self.calls.append("send_document")
        raise AssertionError("send_document must not be called on invalid input")

    async def download_signed(self, *args, **kwargs):  # pragma: no cover - never called
        self.calls.append("download_signed")
        raise AssertionError("download_signed must not be called on invalid input")

    async def cancel_document(self, *args, **kwargs):  # pragma: no cover - never called
        self.calls.append("cancel_document")
        raise AssertionError("cancel_document must not be called on invalid input")

    async def test_connection(self, *args, **kwargs):  # pragma: no cover - never called
        self.calls.append("test_connection")
        raise AssertionError("test_connection must not be called on invalid input")


class _FakeSession:
    """Minimal AsyncSession stand-in that records ``add()`` calls.

    Any reach into ``flush``/``refresh``/``execute``/``begin_nested`` on the
    validation-failure path is a bug (it would imply a row was being persisted),
    so those raise loudly.
    """

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self, *args, **kwargs):  # pragma: no cover - must not happen
        raise AssertionError("flush must not be called on invalid send input")

    async def refresh(self, *args, **kwargs):  # pragma: no cover - must not happen
        raise AssertionError("refresh must not be called on invalid send input")

    async def execute(self, *args, **kwargs):  # pragma: no cover - must not happen
        raise AssertionError("execute must not be called on invalid send input")

    async def begin_nested(self, *args, **kwargs):  # pragma: no cover - must not happen
        raise AssertionError("begin_nested must not be called on invalid send input")


def _verified_connection() -> DocumensoConnection:
    """A present, VERIFIED connection so the send gate (R19.3/19.4) passes."""
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_test",
        webhook_secret="whsec_test",
        documenso_team_id="team_test",
        webhook_routing_id="route_test",
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Email strategies (mirror the validator's regex; reuse the pure-core shapes)
# ---------------------------------------------------------------------------

_LOCAL_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-"
_DOMAIN_LABEL_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
_TLD_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@st.composite
def valid_emails(draw) -> str:
    local = draw(st.text(alphabet=_LOCAL_CHARS, min_size=1, max_size=12))
    label = draw(st.text(alphabet=_DOMAIN_LABEL_CHARS, min_size=1, max_size=10))
    tld = draw(st.text(alphabet=_TLD_CHARS, min_size=2, max_size=6))
    return f"{local}@{label}.{tld}"


_invalid_emails = st.one_of(
    st.just(""),
    st.just("   "),
    st.just("not-an-email"),
    st.just("missing@domain"),  # no dotted TLD
    st.just("@example.com"),  # empty local part
    st.just("a@b.c"),  # TLD too short
    st.just("spaces in@example.com"),
    st.just("two@@example.com"),
    st.text(alphabet="abc ", min_size=0, max_size=8),  # no '@'
)


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _valid_signer(email: str, name: str = "Signer") -> RecipientIn:
    """A signer recipient whose email passes the SERVICE validator's regex.

    Built with ``model_construct`` so the email is judged by the service's own
    :func:`validate_recipients` (the layer under test), not by the stricter
    Pydantic ``EmailStr`` boundary — the generator's addresses are valid under
    the service regex, which is what matters here.
    """
    return RecipientIn.model_construct(name=name, email=email, signing_role="signer")


def _valid_viewer(email: str, name: str = "Viewer") -> RecipientIn:
    """A VIEWER recipient (no signer) whose email passes the service validator."""
    return RecipientIn.model_construct(name=name, email=email, signing_role="viewer")


def _bad_email_recipient(email: str, name: str = "Bad") -> RecipientIn:
    """A recipient with a syntactically invalid email (schema bypassed)."""
    return RecipientIn.model_construct(name=name, email=email, signing_role="signer")


def _make_payload(recipients: list) -> EnvelopeCreate:
    """Build an EnvelopeCreate, bypassing schema validation via model_construct.

    ``model_construct`` is required for the empty-list and invalid-email cases
    (the schema enforces ``min_length=1`` + ``EmailStr``), so the SERVICE's own
    guards — not Pydantic — are what reject the send.
    """
    return EnvelopeCreate.model_construct(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=recipients,
    )


@st.composite
def invalid_send_inputs(draw):
    """Generate an invalid (payload, pdf_bytes, category) across all 4 categories."""
    category = draw(
        st.sampled_from(
            ["non_pdf", "empty_recipients", "invalid_email", "zero_signers"]
        )
    )
    valid_pdf = b"%PDF-1.7\n" + draw(st.binary(max_size=32))

    if category == "non_pdf":
        # Otherwise-valid payload (>=1 valid signer) so ONLY the non-PDF check
        # can fire — pdf bytes that do not start with the magic marker.
        pdf_bytes = draw(st.binary(max_size=64).filter(lambda b: not b.startswith(b"%PDF")))
        recipients = [_valid_signer(draw(valid_emails()))]
        payload = _make_payload(recipients)
        return payload, pdf_bytes, category

    if category == "empty_recipients":
        payload = _make_payload([])
        return payload, valid_pdf, category

    if category == "invalid_email":
        # >=1 invalid email somewhere in an otherwise non-empty list. Mix in
        # valid signers so the rejection is specifically the invalid-email guard
        # (not the empty-list or zero-signers guard).
        n_before = draw(st.integers(min_value=0, max_value=3))
        n_after = draw(st.integers(min_value=0, max_value=3))
        recipients = [_valid_signer(draw(valid_emails())) for _ in range(n_before)]
        recipients.append(_bad_email_recipient(draw(_invalid_emails)))
        recipients += [_valid_signer(draw(valid_emails())) for _ in range(n_after)]
        payload = _make_payload(recipients)
        return payload, valid_pdf, category

    # zero_signers: non-empty list, every email valid, but ALL viewers.
    n = draw(st.integers(min_value=1, max_value=4))
    recipients = [_valid_viewer(draw(valid_emails()), name=f"V{i}") for i in range(n)]
    payload = _make_payload(recipients)
    return payload, valid_pdf, category


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_send(payload, pdf_bytes):
    """Invoke the service with a patched connection gate + spy client.

    Returns ``(raised_exception_or_None, spy, session)``.
    """
    spy = _SpyDocumensoClient()
    session = _FakeSession()
    org_id = uuid.uuid4()
    conn = _verified_connection()

    async def _fake_get_connection(db, oid):
        return conn

    async def _go():
        with patch.object(
            esign_service, "get_documenso_connection", _fake_get_connection
        ):
            return await esign_service.create_and_send_envelope(
                session,
                org_id=org_id,
                user_id=uuid.uuid4(),
                payload=payload,
                pdf_bytes=pdf_bytes,
                client=spy,
            )

    raised: HTTPException | None = None
    try:
        asyncio.run(_go())
    except HTTPException as exc:
        raised = exc
    return raised, spy, session


# ---------------------------------------------------------------------------
# Property 8 (service layer)
# ---------------------------------------------------------------------------


class TestSendValidationAtomicAndSideEffectFree:
    """Property 8 (service portion): invalid send input is rejected atomically.

    **Validates: Requirements 3.3, 3.4, 4.2, 4.3, 4.6**
    """

    @given(scenario=invalid_send_inputs())
    @PBT_SETTINGS
    def test_invalid_send_rejects_without_documenso_call_or_persisted_rows(
        self, scenario
    ):
        payload, pdf_bytes, category = scenario
        raised, spy, session = _run_send(payload, pdf_bytes)

        # 1) The send was rejected with a humanized 422 {message, code}.
        assert raised is not None, f"expected HTTPException for category={category}"
        assert raised.status_code == _VALIDATION_STATUS
        detail = raised.detail
        assert isinstance(detail, dict)
        assert isinstance(detail.get("message"), str) and detail["message"].strip() != ""
        assert detail.get("code") == _EXPECTED_CODES[category]

        # 2) The injected Documenso client was NEVER called (no Documenso call).
        assert spy.calls == [], (
            f"Documenso client was called {spy.calls!r} for category={category}"
        )

        # 3) NO envelope/recipient rows were added to the session (side-effect-free).
        assert session.added == [], (
            f"rows were persisted {session.added!r} for category={category}"
        )

    @given(email=valid_emails())
    @PBT_SETTINGS
    def test_control_valid_input_passes_validation_and_reaches_documenso(self, email):
        """Control: a fully-valid send DOES reach the Documenso client.

        Proves the four rejections above are caused by the invalid input and not
        by the harness silently short-circuiting every send. A valid payload
        passes all guards and reaches ``create_document``. A sentinel-raising
        control spy lets us assert the client was engaged without performing any
        real Documenso/DB work.
        """

        class _ReachedDocumenso(Exception):
            pass

        class _ControlSpy:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def create_document(self, *args, **kwargs):
                self.calls.append("create_document")
                raise _ReachedDocumenso()

        spy = _ControlSpy()
        conn = _verified_connection()
        payload = _make_payload([_valid_signer(email)])

        async def _fake_get_connection(db, oid):
            return conn

        async def _go():
            with patch.object(
                esign_service, "get_documenso_connection", _fake_get_connection
            ):
                await esign_service.create_and_send_envelope(
                    _FakeSession(),
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    payload=payload,
                    pdf_bytes=b"%PDF-1.7\n%mock pdf body",
                    client=spy,
                )

        # Validation passed (no HTTPException 422); execution reached the client.
        with pytest.raises(_ReachedDocumenso):
            asyncio.run(_go())
        assert "create_document" in spy.calls
