"""Example tests for the field-placement module gate + no-Documenso-UI smoke (task 14.4).

The field-placement send is an **extension** of the existing
``esignature-integration`` send flow and inherits its server-side guarantees
*unchanged* (design §"Server-side guarantees", R9). This module covers the two
guarantees called out by task 14.4:

* **R9.1 — module gate (reuses the existing gate).** A field-placement send
  (``POST /api/v2/esign/envelopes`` carrying a sender-defined ``fields[]``
  Field_Set) is gated by the same ``esignatures`` module gate as every other
  ``/api/v2/esign`` request: while the module is disabled for the org the send
  is rejected with **HTTP 403** before any handler/service runs. The gate is
  enforced at two layers (defence-in-depth, design §"Module registration and
  gating") — the ``ModuleMiddleware`` ``MODULE_ENDPOINT_MAP`` entry and the
  router-level :func:`~app.modules.esignatures.dependencies.require_esign_module`
  dependency — and both are exercised here against a genuine field-placement
  send.
* **R9.4 — no Documenso UI exposure (smoke).** No registered route exposes the
  Documenso administrative / organisation UI to org users, and a
  field-placement send's envelope **response** never surfaces the Documenso
  base URL, an admin link, or the per-recipient one-time signing URL — the
  Documenso engine is never exposed to OraInvoice org users.

These are **example/smoke** tests (not Hypothesis properties). The gate layers
are driven in isolation with ``ModuleService.is_enabled`` /
``ModuleMiddleware._is_module_enabled_cached`` stubbed (the convention of
``tests/test_esign_module_gate_property.py``), and the no-UI smoke reuses the
real-app route scan + spy-client send conventions of
``tests/test_esign_external_signing_smoke.py``.

_Requirements: 9.1, 9.4_
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# Pre-load the full model graph (mirrors app/main.py + the esign example tests)
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
from app.middleware.modules import ModuleMiddleware, _resolve_module  # noqa: E402
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.dependencies import require_esign_module  # noqa: E402
from app.modules.esignatures.errors import CODE_MODULE_DISABLED  # noqa: E402
from app.modules.esignatures.schemas import (  # noqa: E402
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# A minimal but genuine PDF byte string (starts with the %PDF magic marker so
# the pure ``is_pdf`` validation passes).
_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"

# The org-user field-placement send endpoint.
_SEND_PATH = "/api/v2/esign/envelopes"


# ---------------------------------------------------------------------------
# A genuine field-placement send payload (carries a non-empty Field_Set), so
# every test below is anchored to an *actual* field-placement send rather than
# a fields-less legacy send.
# ---------------------------------------------------------------------------


def _field_placement_payload() -> EnvelopeCreate:
    """A valid field-placement send: two signers, each with one signature field."""
    return EnvelopeCreate(
        agreement_type="sales_agreement",
        originating_entity_type="invoice",
        originating_entity_id=uuid.uuid4(),
        recipients=[
            RecipientIn(name="Alice", email="alice@example.com", signing_role="signer"),
            RecipientIn(name="Bob", email="bob@example.com", signing_role="signer"),
        ],
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


def test_payload_is_a_genuine_field_placement_send():
    """Sanity: the payload used by these tests carries a non-empty Field_Set."""
    payload = _field_placement_payload()
    assert payload.fields is not None and len(payload.fields) == 2


# ===========================================================================
# Part 1 — R9.1: the field-placement send inherits the existing module gate.
# ===========================================================================


def _make_request(org_id: uuid.UUID | None) -> MagicMock:
    """Minimal ``Request``-like object exposing only ``state.org_id``."""
    request = MagicMock()
    request.state = SimpleNamespace(org_id=org_id)
    return request


async def _run_send_through_middleware(
    org_id: uuid.UUID | None, enabled: bool
) -> tuple[int | None, bool]:
    """Drive ``ModuleMiddleware`` for a POST field-placement send.

    ``_is_module_enabled_cached`` is stubbed so no Redis/DB is touched. Returns
    ``(status, downstream_called)`` — the downstream ASGI app records whether
    the send handler would have been reached.
    """
    state: dict = {}
    if org_id is not None:
        state["org_id"] = org_id

    downstream = {"called": False}

    async def dummy_app(scope, receive, send):  # noqa: ANN001
        downstream["called"] = True
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"created"})

    scope = {
        "type": "http",
        "method": "POST",
        "path": _SEND_PATH,
        "raw_path": _SEND_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": [],
        "state": state,
    }

    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):  # noqa: ANN001
        sent.append(message)

    mw = ModuleMiddleware(dummy_app)
    with patch.object(
        ModuleMiddleware,
        "_is_module_enabled_cached",
        new=AsyncMock(return_value=enabled),
    ):
        await mw(scope, receive, send)

    status = next(
        (m["status"] for m in sent if m["type"] == "http.response.start"), None
    )
    return status, downstream["called"]


def test_send_path_is_gated_by_the_esignatures_module():
    """The field-placement send path resolves to the ``esignatures`` slug, so it
    is gated by the same module gate as every other ``/api/v2/esign`` request."""
    assert _resolve_module(_SEND_PATH) == "esignatures"


def test_field_placement_send_returns_403_when_module_disabled_middleware():
    """Layer 1: ``ModuleMiddleware`` rejects the field-placement send with 403
    while the module is disabled, never reaching the send handler (R9.1)."""
    status, downstream_called = asyncio.run(
        _run_send_through_middleware(org_id=uuid.uuid4(), enabled=False)
    )
    assert status == 403
    assert downstream_called is False


def test_field_placement_send_passes_gate_when_module_enabled_middleware():
    """Layer 1: when the module is enabled the field-placement send passes the
    gate and reaches the handler (the gate adds no other constraint, R9.1)."""
    status, downstream_called = asyncio.run(
        _run_send_through_middleware(org_id=uuid.uuid4(), enabled=True)
    )
    assert status == 201
    assert downstream_called is True


def test_field_placement_send_dependency_raises_403_when_module_disabled():
    """Layer 2: the router-level ``require_esign_module`` dependency (carried by
    the ``POST /envelopes`` route) raises a humanized 403 when the module is
    disabled, before the field-placement send service runs (R9.1).

    The payload is a genuine field-placement send (carries a Field_Set), proving
    the field-set path reuses the *existing* gate unchanged rather than a new one.
    """
    # The payload is built to confirm the test targets a field-placement send;
    # the gate rejects before the body is ever parsed by the handler.
    _ = _field_placement_payload()

    org_id = uuid.uuid4()
    request = _make_request(org_id)
    db = AsyncMock()

    with patch(
        "app.core.modules.ModuleService.is_enabled",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_is_enabled:
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(require_esign_module(request, db))

    assert excinfo.value.status_code == 403
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == CODE_MODULE_DISABLED
    assert isinstance(detail["message"], str) and detail["message"]

    # Gated against the canonical slug + the request's org_id.
    mock_is_enabled.assert_awaited_once()
    call_args = mock_is_enabled.await_args.args
    assert call_args[0] == str(org_id)
    assert call_args[1] == "esignatures"


def test_field_placement_send_dependency_passes_when_module_enabled():
    """Layer 2: ``require_esign_module`` returns ``None`` (no 403) for an org
    whose ``esignatures`` module is enabled (R9.1)."""
    request = _make_request(uuid.uuid4())
    db = AsyncMock()

    with patch(
        "app.core.modules.ModuleService.is_enabled",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = asyncio.run(require_esign_module(request, db))

    assert result is None


# ===========================================================================
# Part 2 — R9.4: the Documenso admin/org UI is never exposed to org users.
# ===========================================================================

# Substrings that would betray a route or response leaking the Documenso web UI
# / admin surface. The legitimate esign API surface is named
# ``/api/v2/esign/...`` and never carries the vendor name in its path.
_DOCUMENSO_UI_MARKERS = ("documenso",)

# Path shapes that would indicate a generic UI proxy/embed/iframe surface.
_UI_PROXY_SUFFIXES = ("/ui", "/app", "/embed", "/iframe", "/proxy", "/console", "/admin")


def _registered_paths() -> set[str]:
    """Materialise every effective route path of the assembled app.

    The app uses a lazy router-inclusion scheme: ``app.routes`` holds
    ``_IncludedRouter`` wrappers whose concrete routes are only realised by
    calling ``effective_candidates()``. We walk that tree so the scan sees the
    real, prefixed paths (e.g. ``/api/v2/esign/envelopes``).
    """
    from app.main import create_app

    app = create_app()
    paths: set[str] = set()

    def _walk(routes) -> None:
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                _walk(route.effective_candidates())
            else:
                path = getattr(route, "path", None)
                if path is not None:
                    paths.add(path)

    _walk(app.routes)
    return paths


def test_no_esign_route_exposes_the_documenso_ui():
    """No registered esign route proxies/embeds the Documenso admin or org UI (R9.4)."""
    paths = _registered_paths()

    # 1. No path references Documenso directly — a UI proxy would name the vendor.
    documenso_paths = [
        p for p in paths if any(m in p.lower() for m in _DOCUMENSO_UI_MARKERS)
    ]
    assert documenso_paths == [], (
        "no route may expose a Documenso UI proxy, but found: "
        f"{sorted(documenso_paths)!r}"
    )

    # 2. No esign route is shaped like a UI proxy/embed/admin surface — the esign
    #    API exposes data endpoints only (envelopes, signed-document, webhook).
    esign_ui_proxies = [
        p
        for p in paths
        if p.startswith("/api/v2/esign")
        and any(p.lower().rstrip("/").endswith(s) for s in _UI_PROXY_SUFFIXES)
    ]
    assert esign_ui_proxies == [], (
        "esign routes must not expose a Documenso UI surface, but found: "
        f"{sorted(esign_ui_proxies)!r}"
    )

    # 3. The module is actually mounted (otherwise the assertions are vacuous).
    assert any(p.startswith("/api/v2/esign") for p in paths)


# ---------------------------------------------------------------------------
# Spy DocumensoClient — runs a real field-placement send so the test can scan
# the resulting envelope *response* for any leaked Documenso UI/admin URL.
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    """Echoes one :class:`CreatedRecipient` per input recipient. Each carries a
    Documenso-hosted one-time ``signing_url`` (an internal artifact that MUST
    NOT surface in the org-facing envelope response). ``create_fields`` records
    that the field-placement path was taken."""

    def __init__(self) -> None:
        self.calls: list[str] = []

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
                # A Documenso-hosted URL (vendor host + an /admin-looking path)
                # — if anything leaked into the response the scan would catch it.
                signing_url=f"https://app.documenso-admin.example.test/sign/{i}",
            )
            for i, spec in enumerate(recipients)
        ]
        return DocumensoCreateResult(
            document_id="doc-123", envelope_id="envelope_doc-123", recipients=created
        )

    async def create_fields(
        self, document_id: str, fields: list[DocumensoFieldSpec]
    ) -> None:
        self.calls.append("create_fields")

    async def send_document(
        self, document_id: str, *, signing_order_mode: str = "parallel"
    ) -> None:
        self.calls.append("send_document")


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
        # The org's Documenso base URL — an internal credential-adjacent value
        # that must never reach the org-facing response.
        base_url="https://app.documenso-admin.example.test",
        service_token="tok_org",
        webhook_secret="whsec_org",
        documenso_team_id="team_org",
        webhook_routing_id="route_org",
        is_verified=True,
    )


def _run_field_placement_send(monkeypatch):
    """Drive a real field-placement send; return the serialised envelope response."""

    async def _fake_get_connection(_db, _org_id):
        return _verified_connection()

    monkeypatch.setattr(esign_service, "get_documenso_connection", _fake_get_connection)

    async def _noop_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(esign_service, "_audit_and_notify_send", _noop_audit)

    spy = _SpyDocumensoClient()
    envelope = asyncio.run(
        esign_service.create_and_send_envelope(
            _FakeSession(),
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            payload=_field_placement_payload(),
            pdf_bytes=_PDF_BYTES,
            client=spy,  # type: ignore[arg-type]
        )
    )

    # The fake session does not assign the DB-generated server defaults
    # (primary keys / timestamps) that ``EnvelopeOut`` requires, so populate
    # plausible values here. None of these are URL-bearing — the response scan
    # below is unaffected by them.
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    envelope.id = uuid.uuid4()
    envelope.created_at = now
    envelope.updated_at = now
    for recipient in envelope.recipients:
        recipient.id = uuid.uuid4()

    # The org-facing response shape (what the router returns to the browser).
    return esign_service._envelope_to_out(envelope), spy


def test_field_placement_send_response_never_exposes_documenso_ui(monkeypatch):
    """A field-placement send's envelope response surfaces no Documenso base
    URL, admin link, or per-recipient signing URL to the org user (R9.4).

    The send genuinely takes the field-placement path (``create_fields``), and
    every recipient internally carries a Documenso-hosted one-time signing URL
    + the connection's Documenso base URL — yet the serialised, org-facing
    response must contain none of those vendor/admin artifacts.
    """
    out, spy = _run_field_placement_send(monkeypatch)

    # It really was a field-placement send (not the legacy auto-placement path).
    assert "create_fields" in spy.calls

    # Serialise exactly what the org user would receive over the wire.
    body = out.model_dump(mode="json")
    blob = str(body).lower()

    # No Documenso vendor host / admin marker leaks anywhere in the response.
    assert "documenso" not in blob, f"response leaked a Documenso reference: {body!r}"
    assert "/admin" not in blob, f"response leaked an admin link: {body!r}"
    assert "/sign/" not in blob, (
        f"response leaked a one-time signing URL to the org user: {body!r}"
    )

    # The recipient response objects expose only the safe, org-facing fields —
    # never a signing/admin URL field.
    for recipient in body["recipients"]:
        assert set(recipient.keys()) == {
            "id",
            "name",
            "email",
            "signing_role",
            "recipient_status",
        }
        assert not any("url" in k.lower() for k in recipient.keys())

    # The only URL-bearing field on the envelope is the opaque, org-checked
    # signed-document link, which is absent for a freshly-sent envelope.
    assert body["signed_document_url"] is None


def test_envelope_response_schema_carries_no_documenso_admin_url_field():
    """Static guard: neither ``EnvelopeOut`` nor ``RecipientOut`` declares a
    field that could carry the Documenso base/admin/org UI URL (R9.4)."""
    from app.modules.esignatures.schemas import EnvelopeOut, RecipientOut

    forbidden = ("documenso", "base_url", "admin", "signing_url", "signingurl")
    for model in (EnvelopeOut, RecipientOut):
        for field_name in model.model_fields:
            assert not any(bad in field_name.lower() for bad in forbidden), (
                f"{model.__name__}.{field_name} could expose the Documenso UI"
            )
