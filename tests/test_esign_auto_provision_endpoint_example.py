"""Example tests for the Global-Admin auto-provision endpoint (task 14.10).

Concrete example tests for the ``POST
/api/v2/admin/organisations/{org_id}/esign/auto-provision`` handler
(``connection_router.auto_provision_org_connection``). They exercise the route's
own responsibilities — Global-Admin path scoping, delegation to
``auto_provision_connection``, the **masked** response shape (same as the
connection GET, ``*_last4`` only, never plaintext — R1.4/R15.3), and the
``status -> HTTP`` mapping from the design's Error Handling table:

  - ``provisioned``  -> HTTP 200 with the verified, masked connection.
  - ``unavailable``  -> HTTP 200 with humanized ``error``/``code`` (manual path
    intact, R20.5).
  - ``partial``      -> HTTP 502 with humanized ``error``/``code`` **and** the
    partially-populated, manually-completable connection (R20.1, R20.3).
  - org not found    -> HTTP 404.

The orchestration itself (``auto_provision_connection``) is stubbed here — its
behaviour is covered by the service unit/property tests (tasks 14.9/14.11). These
tests target only the endpoint wiring, so DB/RLS helpers are monkeypatched.

Requirements: 19.6, 20.1, 20.3, 20.5
"""

from __future__ import annotations

import json
import uuid

import pytest

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# (mirrors the other esign unit/example tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures import connection_router as cr  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_AUTO_PROVISION_FAILED,
    CODE_AUTO_PROVISION_UNAVAILABLE,
    esign_error,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeURL:
    scheme = "https"


class _FakeState:
    def __init__(self):
        self.user_id = uuid.uuid4()
        self.client_ip = "203.0.113.7"


class _FakeRequest:
    """Minimal stand-in for a FastAPI Request used by the handler."""

    def __init__(self, org_id: uuid.UUID):
        self.headers = {"host": "api.example.test"}
        self.url = _FakeURL()
        self.path_params = {"org_id": str(org_id)}
        self.state = _FakeState()


def _masked(org_id: uuid.UUID, *, is_verified: bool, routing_id: str = "route-xyz") -> dict:
    """Build a masked connection projection (shape of ``_masked_connection``)."""
    return {
        "id": uuid.uuid4(),
        "org_id": org_id,
        "base_url": "https://documenso.example.test",
        "documenso_team_id": "team-abc",
        "webhook_routing_id": routing_id,
        "is_verified": is_verified,
        "service_token_last4": "alue",
        "webhook_secret_last4": "alue",
        "created_at": None,
        "updated_at": None,
    }


@pytest.fixture(autouse=True)
def _stub_db_helpers(monkeypatch):
    """Stub out the RLS/DB existence helpers — these tests target route wiring."""

    async def _exists(_db, _org_id):
        return True

    async def _scope(_db, _org_id):
        return None

    monkeypatch.setattr(cr, "_org_exists", _exists)
    monkeypatch.setattr(cr, "_scope_to_org", _scope)


def _stub_service(monkeypatch, result: dict):
    async def _auto(_db, _org_id, *, requested_by=None, ip_address=None):
        return result

    monkeypatch.setattr(cr, "auto_provision_connection", _auto)


def _call(org_id: uuid.UUID):
    return cr.auto_provision_org_connection(org_id, _FakeRequest(org_id), db=None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provisioned_returns_200_with_masked_verified_connection(monkeypatch):
    """A 'provisioned' result -> HTTP 200, verified connection, no plaintext secrets."""
    org_id = uuid.uuid4()
    _stub_service(
        monkeypatch,
        {
            "status": "provisioned",
            "connection": _masked(org_id, is_verified=True),
            "webhook_url": "https://api.example.test/api/v2/esign/webhook/route-xyz",
            "is_verified": True,
            "error": None,
            "code": None,
        },
    )

    resp = await _call(org_id)
    body = json.loads(resp.body)

    assert resp.status_code == 200
    assert body["status"] == "provisioned"
    assert body["error"] is None
    assert body["code"] is None
    conn = body["connection"]
    assert conn["configured"] is True
    assert conn["is_verified"] is True
    # Secrets surfaced only as a mask + last-4 — never plaintext.
    assert conn["service_token"] == cr._SECRET_MASK
    assert conn["service_token_last4"] == "alue"
    assert conn["webhook_url"].endswith("/api/v2/esign/webhook/route-xyz")


@pytest.mark.asyncio
async def test_unavailable_returns_200_with_humanized_error(monkeypatch):
    """An 'unavailable' result -> HTTP 200 with humanized error + code (R20.5)."""
    org_id = uuid.uuid4()
    err = esign_error(CODE_AUTO_PROVISION_UNAVAILABLE)
    _stub_service(
        monkeypatch,
        {
            "status": "unavailable",
            "connection": None,
            "webhook_url": None,
            "is_verified": None,
            "error": err.message,
            "code": err.code,
        },
    )

    resp = await _call(org_id)
    body = json.loads(resp.body)

    assert resp.status_code == 200
    assert body["status"] == "unavailable"
    assert body["code"] == CODE_AUTO_PROVISION_UNAVAILABLE
    assert body["error"] and isinstance(body["error"], str)
    # No connection row yet -> stable "not configured" shape (still HTTP 200).
    assert body["connection"]["configured"] is False


@pytest.mark.asyncio
async def test_partial_returns_502_with_manually_completable_connection(monkeypatch):
    """A 'partial' result -> HTTP 502 with humanized error AND the partial connection."""
    org_id = uuid.uuid4()
    err = esign_error(CODE_AUTO_PROVISION_FAILED)
    _stub_service(
        monkeypatch,
        {
            "status": "partial",
            "connection": _masked(org_id, is_verified=False),
            "webhook_url": "https://api.example.test/api/v2/esign/webhook/route-xyz",
            "is_verified": False,
            "error": err.message,
            "code": err.code,
        },
    )

    resp = await _call(org_id)
    body = json.loads(resp.body)

    assert resp.status_code == 502
    assert body["status"] == "partial"
    assert body["code"] == CODE_AUTO_PROVISION_FAILED
    assert body["error"] and isinstance(body["error"], str)
    # The partially-populated connection is returned so the admin can finish
    # setup manually; it is not verified.
    conn = body["connection"]
    assert conn["configured"] is True
    assert conn["is_verified"] is False
    assert conn["documenso_team_id"] == "team-abc"


@pytest.mark.asyncio
async def test_org_not_found_returns_404(monkeypatch):
    """An unknown org id -> HTTP 404 before any provisioning is attempted."""
    org_id = uuid.uuid4()

    async def _missing(_db, _org_id):
        return False

    monkeypatch.setattr(cr, "_org_exists", _missing)

    # If the service were called it would raise (it is not stubbed here),
    # proving the 404 short-circuits before delegation.
    resp = await _call(org_id)
    body = json.loads(resp.body)

    assert resp.status_code == 404
    assert body["detail"] == "Organisation not found"
