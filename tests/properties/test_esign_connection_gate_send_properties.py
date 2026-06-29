"""Property-based test for the send-time connection gate (task 8.9).

The function under test is
:func:`app.modules.esignatures.service.create_and_send_envelope`. **Step 0** of
that flow is the per-organisation Documenso *connection gate* (R19.3/19.4):

  * it loads the calling organisation's connection via
    :func:`~app.integrations.documenso.get_documenso_connection`;
  * if the organisation has **no** connection row
    (``DocumensoNotConfiguredError``) **or** the connection is present but
    **unverified** (``is_verified == False``), the send is **blocked** with a
    humanized **503** (``integration_not_configured``) and **no** Documenso API
    call is ever made;
  * the send only proceeds into the Documenso multi-step flow when the
    organisation's connection is present **and** verified.

# Feature: esignature-integration, Property 27: Sends are blocked while the org's connection is missing or unverified

**Validates: Requirements 19.3, 19.4**

Property 27: for *any* send attempted while the org's connection is missing OR
unverified, ``create_and_send_envelope`` raises ``HTTPException`` 503
(``integration_not_configured``), the injected spy ``DocumensoClient`` is
**never** called, and **no** envelope/recipient rows are added; a send proceeds
(reaching the Documenso flow, so the spy *is* called) **only** when the
connection is present and verified.

The connection loader is monkeypatched (no real DB), a spy client is injected
via ``client_factory`` so the test can assert it is never even *constructed* for
a blocked send, and the envelope rows are captured by a lightweight fake async
session — isolating the gate decision with no real DB or network.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the other esign property
# tests) so SQLAlchemy can resolve every string-based relationship reference
# when ``EsignEnvelope`` / ``EsignRecipient`` are instantiated and the whole
# mapper registry is configured. Without this, constructing a single ORM model
# can raise InvalidRequestError.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from fastapi import HTTPException  # noqa: E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoConnection,
    DocumensoCreateResult,
    DocumensoNotConfiguredError,
    map_recipient_role,
)
from app.modules.esignatures import service as svc  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_INTEGRATION_NOT_CONFIGURED,
)
from app.modules.esignatures.models import EsignEnvelope, EsignRecipient  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

PBT_SETTINGS = settings(max_examples=150, deadline=None)


# ---------------------------------------------------------------------------
# Spy client + factory — record every Documenso call (and whether built at all)
# ---------------------------------------------------------------------------


class _SpyClient:
    """Stand-in for :class:`DocumensoClient` injected via ``client_factory``.

    For a *blocked* send (missing / unverified connection) NONE of these methods
    must ever be invoked — the connection gate runs before any client work. For
    a *verified* send the real multi-step flow drives every method, so the spy
    echoes plausible results that let the flow complete.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_document(self, *, title, recipients, pdf_bytes=None):
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=f"r{i}",
                email=r.email,
                role=map_recipient_role(r.role),
                token=f"tok{i}",
                signing_url=f"https://sign.example.test/{i}",
            )
            for i, r in enumerate(recipients)
        ]
        return DocumensoCreateResult(
            document_id="doc-1",
            upload_url="https://upload.example.test/doc-1",
            recipients=created,
        )

    async def upload_pdf(self, upload_url, pdf_bytes):
        self.calls.append("upload_pdf")

    async def place_signature_field(self, document_id, **_kwargs):
        self.calls.append("place_signature_field")

    async def send_document(self, document_id, **_kwargs):
        self.calls.append("send_document")


class _SpyFactory:
    """``conn -> DocumensoClient`` factory that records whether it was called."""

    def __init__(self) -> None:
        self.built = 0
        self.client = _SpyClient()

    def __call__(self, _conn) -> _SpyClient:
        self.built += 1
        return self.client


# ---------------------------------------------------------------------------
# Fake async session — captures add()ed rows; absorbs flush/refresh/savepoints.
# ---------------------------------------------------------------------------


class _FakeSavepoint:
    async def commit(self):
        return None

    async def rollback(self):
        return None


class _FakeSession:
    """Minimal AsyncSession stand-in for ``create_and_send_envelope``.

    Records every ``add``ed object so the test can assert that a blocked send
    persists NOTHING. ``flush`` / ``refresh`` are no-ops (the in-memory envelope
    already carries its recipients), and ``begin_nested`` returns a no-op
    savepoint for the best-effort audit/notify path (stubbed out below anyway).
    """

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None

    async def begin_nested(self):
        return _FakeSavepoint()


# ---------------------------------------------------------------------------
# Strategies — valid send inputs so the ONLY blocking factor is the connection
# ---------------------------------------------------------------------------

# A minimal, syntactically valid one-byte-magic PDF (is_pdf checks the %PDF
# prefix; page count falls back to page 1 when undeterminable).
VALID_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ORIGINATING_TYPES = ("invoice", "quote", "staff")

_ALNUM = "abcdefghijklmnopqrstuvwxyz0123456789"
_TLD_CHARS = "abcdefghijklmnopqrstuvwxyz"


@st.composite
def valid_emails(draw) -> str:
    """Generate addresses accepted by pydantic ``EmailStr`` (deliverability off).

    Kept conservative — alphanumeric local part and a simple alphanumeric
    domain label — so the connection state is the only thing under test, never
    an accidentally-malformed email.
    """
    local = draw(st.text(alphabet=_ALNUM, min_size=1, max_size=10))
    label = draw(st.text(alphabet=_ALNUM, min_size=1, max_size=8))
    tld = draw(st.text(alphabet=_TLD_CHARS, min_size=2, max_size=4))
    return f"{local}@{label}.{tld}"


@st.composite
def valid_recipients(draw) -> list[RecipientIn]:
    """A non-empty recipient list with >= 1 signer and all-valid emails."""
    n = draw(st.integers(min_value=1, max_value=4))
    recipients = []
    for i in range(n):
        # Guarantee at least one signer (the first recipient).
        role = "signer" if i == 0 else draw(st.sampled_from(("signer", "viewer")))
        recipients.append(
            RecipientIn(name=f"Recipient {i}", email=draw(valid_emails()), signing_role=role)
        )
    return recipients


@st.composite
def valid_payloads(draw) -> EnvelopeCreate:
    return EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ORIGINATING_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=draw(valid_recipients()),
    )


def _connection(*, is_verified: bool) -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=is_verified,
    )


# ---------------------------------------------------------------------------
# Property 27 — sends are blocked while the connection is missing or unverified
# ---------------------------------------------------------------------------


class TestConnectionGateBlocksSend:
    """Property 27: blocked while the org's connection is missing or unverified.

    **Validates: Requirements 19.3, 19.4**
    """

    @PBT_SETTINGS
    @given(payload=valid_payloads(), missing=st.booleans())
    def test_blocked_when_missing_or_unverified(self, payload: EnvelopeCreate, missing: bool):
        """A missing OR unverified connection blocks the send with a 503 and
        makes no Documenso call and persists no rows.
        """
        org_id = uuid.uuid4()
        session = _FakeSession()
        factory = _SpyFactory()

        if missing:
            # Scenario (a): no connection row → loader raises.
            async def _loader(db, oid):
                raise DocumensoNotConfiguredError("not configured")
        else:
            # Scenario (b): present but unverified.
            async def _loader(db, oid):
                return _connection(is_verified=False)

        with mock.patch.object(svc, "get_documenso_connection", _loader):
            with pytest.raises(HTTPException) as excinfo:
                asyncio.run(
                    svc.create_and_send_envelope(
                        session,
                        org_id=org_id,
                        user_id=uuid.uuid4(),
                        payload=payload,
                        pdf_bytes=VALID_PDF,
                        client_factory=factory,
                    )
                )

        # Blocked with a humanized 503 (integration_not_configured) ...
        assert excinfo.value.status_code == 503
        assert excinfo.value.detail["code"] == CODE_INTEGRATION_NOT_CONFIGURED
        assert isinstance(excinfo.value.detail["message"], str)
        assert excinfo.value.detail["message"]  # non-empty, human-readable

        # ... the spy client was never even constructed, let alone called ...
        assert factory.built == 0
        assert factory.client.calls == []

        # ... and no envelope/recipient rows were persisted.
        assert session.added == []
        assert not any(isinstance(o, EsignEnvelope) for o in session.added)
        assert not any(isinstance(o, EsignRecipient) for o in session.added)


# ---------------------------------------------------------------------------
# Control — a verified connection lets the send proceed into the Documenso flow
# ---------------------------------------------------------------------------


class TestVerifiedConnectionProceeds:
    """Control: a present + verified connection reaches the Documenso flow.

    Proves the gate blocks ONLY when the connection is missing/unverified — a
    verified connection drives the multi-step Documenso flow (the spy IS used).

    **Validates: Requirements 19.3, 19.4**
    """

    @settings(max_examples=50, deadline=None)
    @given(payload=valid_payloads())
    def test_verified_connection_reaches_documenso_flow(self, payload: EnvelopeCreate):
        org_id = uuid.uuid4()
        session = _FakeSession()
        factory = _SpyFactory()

        async def _loader(db, oid):
            return _connection(is_verified=True)

        async def _noop_audit(*_args, **_kwargs):
            return None

        with mock.patch.object(svc, "get_documenso_connection", _loader), mock.patch.object(
            svc, "_audit_and_notify_send", _noop_audit
        ):
            envelope = asyncio.run(
                svc.create_and_send_envelope(
                    session,
                    org_id=org_id,
                    user_id=uuid.uuid4(),
                    payload=payload,
                    pdf_bytes=VALID_PDF,
                    client_factory=factory,
                )
            )

        # The gate let the send through: the spy client was built and the full
        # Documenso multi-step flow ran (ending in send_document).
        assert factory.built == 1
        assert "create_document" in factory.client.calls
        assert "send_document" in factory.client.calls

        # A faithful, sent envelope was persisted.
        assert isinstance(envelope, EsignEnvelope)
        assert envelope.status == "sent"
        assert envelope in session.added
