"""Example/integration test for the per-org connection lifecycle (task 14.8).

This is a concrete *example* test (not a Hypothesis property) covering the
full per-organisation Documenso connection lifecycle (R19) end-to-end against
the service + loader/client with lightweight fakes (a stateful fake async
session, real envelope encryption, and an ``httpx.MockTransport`` spy — no
FastAPI/DB stack needed):

1. **Record connection → unverified** — a fresh ``save_connection`` leaves the
   row ``is_verified = false`` (R19.5: any save clears verification).
2. **Connection test success → verified** — a 200 from Documenso sets
   ``is_verified = true`` and reports ``valid`` (R19.2).
3. **Update clears verification** — saving the connection again (an update)
   resets ``is_verified`` back to ``false`` until a fresh test (R19.5).
4. **Connection test failure → unverified** — a 401 from Documenso sets
   ``is_verified = false`` (R1.6/R19.2).
5. **Webhook surface** — the masked connection response surfaces the org's
   ``webhook_url`` and a ``webhook_subscription_status`` that tracks the
   lifecycle (``pending_verification`` while unverified → ``verified`` once the
   connection test passes).
6. **Send gate follows ``is_verified``** (R19.3/R19.4) — ``create_and_send_envelope``
   blocks the send (humanized 503 ``integration_not_configured``) and makes
   **no** Documenso call while the org's connection is unverified, and proceeds
   to drive the Documenso flow only once the connection is verified. (Property 8.9
   covers the gate as a property; here we assert the connection-row lifecycle
   drives it.)

Requirements: 1.6, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignOrgConnection / EsignEnvelope / EsignRecipient are instantiated
# (mirrors the other esign unit/example tests).
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
    DocumensoCreateResult,
    RecipientSpec,
    invalidate_documenso_connection_cache,
)
from app.modules.esignatures import connection_router as cr  # noqa: E402
from app.modules.esignatures import connection_service as cs  # noqa: E402
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.connection_service import (  # noqa: E402
    _load_row,
    _masked_connection,
    save_connection,
)
from app.modules.esignatures.connection_service import (  # noqa: E402
    test_connection as svc_test_connection,
)
from app.modules.esignatures.errors import CODE_INTEGRATION_NOT_CONFIGURED  # noqa: E402
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

# Capture the real AsyncClient class BEFORE any monkeypatch so the mock factory
# below never recurses into a patched ``httpx.AsyncClient``.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

# A minimal but genuine PDF byte string (starts with the %PDF magic marker so
# the pure ``is_pdf`` validation passes on the send path).
_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"


# ---------------------------------------------------------------------------
# Fakes — a stateful async session that serves the connection SELECT + audit
# INSERT, captures added rows, and supports flush/refresh.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal stand-in for AsyncSession used by the connection service."""

    def __init__(self, existing_row: EsignOrgConnection | None = None):
        self._row = existing_row
        self.added: list[object] = []

    async def execute(self, _stmt, _params=None):
        # The connection SELECT reads the row; the audit-log INSERT ignores the
        # result, so a single behaviour serves both.
        return _FakeResult(self._row)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        # Only a connection row should become the served SELECT row; an envelope
        # add (send path) must not clobber the connection the gate already read.
        if isinstance(obj, EsignOrgConnection):
            self._row = obj

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, _obj):
        return None


class _FakeURL:
    scheme = "https"


class _FakeRequest:
    """Minimal stand-in for a FastAPI Request used by ``_build_response``."""

    def __init__(self, *, host: str, org_id: uuid.UUID):
        self.headers = {"host": host}
        self.url = _FakeURL()
        self.path_params = {"org_id": str(org_id)}


# ---------------------------------------------------------------------------
# Spy DocumensoClient — records the calls it is asked to perform so the send
# gate can be asserted to make NO Documenso call while unverified.
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
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
            document_id="doc-123",
            envelope_id="envelope_doc-123",
            recipients=created,
        )

    async def place_signature_field(self, document_id: str, **kwargs) -> None:
        self.calls.append("place_signature_field")

    async def send_document(
        self, document_id: str, *, signing_order_mode: str = "parallel"
    ) -> None:
        self.calls.append("send_document")


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_documenso_connection_cache()
    yield
    invalidate_documenso_connection_cache()


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    """Silence the connection-service audit log — its INSERT is irrelevant here."""

    async def _noop(**_kwargs):
        return None

    monkeypatch.setattr(cs, "write_audit_log", _noop)


def _mock_http_factory(handler):
    """Return an ``httpx.AsyncClient`` factory wired to a MockTransport.

    Used to monkeypatch ``connection_service.httpx.AsyncClient`` so the real
    :class:`DocumensoClient` is exercised against a scripted Documenso response.
    """

    def _factory(*_args, **_kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    return _factory


def _payload() -> EnvelopeCreate:
    return EnvelopeCreate(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com", signing_role="signer"),
        ],
    )


# ---------------------------------------------------------------------------
# The full lifecycle, asserted as one ordered story (R19.5 → R19.2 → R19.5 →
# R1.6/R19.2) plus the webhook-surface projection.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_is_verified_lifecycle(monkeypatch):
    """record→unverified, test→verified, update→unverified, test-fail→unverified."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    # 1. Record the connection — any save starts/leaves it unverified (R19.5).
    await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        service_token="tok_secret_value",
        webhook_signing_secret="whsec_secret_value",
    )
    assert (await _load_row(session, org_id)).is_verified is False

    # The masked response while unverified surfaces the webhook URL and a
    # ``pending_verification`` subscription status.
    request = _FakeRequest(host="api.example.test", org_id=org_id)
    pending = cr._build_response(_masked_connection(await _load_row(session, org_id)), request)
    assert pending.configured is True
    assert pending.webhook_routing_id
    assert pending.webhook_url == (
        f"https://api.example.test/api/v2/esign/webhook/{pending.webhook_routing_id}"
    )
    assert pending.webhook_subscription_status == "pending_verification"

    # 2. A successful connection test (200) sets is_verified=true (R19.2).
    monkeypatch.setattr(
        cs.httpx, "AsyncClient", _mock_http_factory(lambda r: httpx.Response(200, json={}))
    )
    result = await svc_test_connection(session, org_id)
    assert result == {"is_verified": True, "valid": True}
    assert (await _load_row(session, org_id)).is_verified is True

    # Now verified, the subscription status advances to ``verified`` (no webhook
    # observed yet, so it tops out below ``active``).
    verified = cr._build_response(_masked_connection(await _load_row(session, org_id)), request)
    assert verified.is_verified is True
    assert verified.webhook_subscription_status == "verified"

    # 3. Updating the connection (a fresh save) clears is_verified again (R19.5).
    await save_connection(
        session,
        org_id,
        base_url="https://documenso2.example.test",
        documenso_team_id="team-updated",
        service_token="********",  # masked echo — retain stored token
        webhook_signing_secret="********",  # masked echo — retain stored secret
    )
    assert (await _load_row(session, org_id)).is_verified is False

    # 4. A failed connection test (401) leaves is_verified=false (R1.6/R19.2).
    monkeypatch.setattr(
        cs.httpx, "AsyncClient", _mock_http_factory(lambda r: httpx.Response(401))
    )
    result = await svc_test_connection(session, org_id)
    assert result == {"is_verified": False, "valid": False}
    assert (await _load_row(session, org_id)).is_verified is False


# ---------------------------------------------------------------------------
# The send gate follows the connection's is_verified flag (R19.3/R19.4).
# ---------------------------------------------------------------------------


def test_send_is_blocked_while_connection_unverified(monkeypatch):
    """An unverified connection blocks the send with 503 and makes NO Documenso call."""
    org_id = uuid.uuid4()
    # A recorded-but-unverified connection row (is_verified defaults to False).
    row = EsignOrgConnection(
        id=uuid.uuid4(),
        org_id=org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        webhook_routing_id="route-abc",
        is_verified=False,
    )
    session = _FakeSession(existing_row=row)

    # Stub the best-effort audit/notification (begin_nested isn't faked).
    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)

    spy = _SpyDocumensoClient()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            esign_service.create_and_send_envelope(
                session,
                org_id=org_id,
                user_id=None,
                payload=_payload(),
                pdf_bytes=_PDF_BYTES,
                client=spy,  # type: ignore[arg-type]
            )
        )

    # Humanized 503 "integration not configured" and not a single Documenso call.
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == CODE_INTEGRATION_NOT_CONFIGURED
    assert spy.calls == []


def test_send_proceeds_once_connection_verified(monkeypatch):
    """A verified connection lets the send proceed through the Documenso flow."""
    org_id = uuid.uuid4()
    row = EsignOrgConnection(
        id=uuid.uuid4(),
        org_id=org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        webhook_routing_id="route-abc",
        is_verified=True,  # verified → gate opens (R19.4)
    )
    session = _FakeSession(existing_row=row)

    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)

    spy = _SpyDocumensoClient()

    envelope = asyncio.run(
        esign_service.create_and_send_envelope(
            session,
            org_id=org_id,
            user_id=None,
            payload=_payload(),
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )

    # The gate opened and the full Documenso flow ran, persisting a 'sent' row.
    assert envelope.status == "sent"
    assert spy.calls == [
        "create_document",
        "place_signature_field",
        "send_document",
    ]
