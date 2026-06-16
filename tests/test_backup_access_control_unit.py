"""Unit tests for Cloud Backup & Restore access control + audit-on-reject (Task 15.4).

Covers Requirement 1 acceptance criteria for the backup/restore API surface:

  * **Req 1.2** — a request carrying a valid token whose role is NOT
    ``global_admin`` is rejected with HTTP 403, the requested action does NOT
    execute, and all backup data/config is left unchanged (no side effects).
  * **Req 1.3** — a request with no token, or an invalid/expired token (no
    authenticated user on ``request.state``), is rejected with HTTP 401 and the
    requested action does NOT execute.
  * **Req 1.5** — a successful ``global_admin`` action writes one ``audit_log``
    entry (actor id, action type, target id, UTC timestamp).
  * **Req 1.6** — a rejected attempt writes one ``audit_log`` entry carrying the
    requesting user id, or an unauthenticated indicator when no valid token is
    present.

The access-control behaviour is exercised two ways:

  1. *Dependency-level, real router* — the actual ``/api/v1/backup`` router
     carries exactly the ``require_role("global_admin")`` router-level
     dependency, and invoking that dependency enforces 401/403/allow. This is a
     structural assertion that every route on the router is gated.
  2. *End-to-end, minimal app* — a tiny FastAPI app with a single route gated by
     ``require_role("global_admin")`` plus a side-effect recorder, driven by a
     ``TestClient`` through an ``inject_auth`` middleware that stamps
     ``request.state`` (mirrors ``tests/test_email_link_origin.py``). This proves
     the 403/401 rejections happen BEFORE the handler body runs (no side effects).

The audit-on-reject / audit-on-success behaviour is exercised directly against
``AuditWriter`` using the in-memory ``FakeSession`` pattern from
``tests/test_backup_audit_writer_unit.py`` (no DB, no mock framework). The full
app is deliberately NOT imported (``create_app()`` pulls an unrelated optional
billing dependency) — the router module imports cleanly on its own.

Requirements: 1.2, 1.3, 1.5, 1.6
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.modules.auth.rbac import require_role
from app.modules.backup_restore.audit import (
    ACTION_BACKUP_CREATED,
    ACTION_RESTORE_TRIGGERED,
    AuditWriter,
    UNAUTHENTICATED_INDICATOR,
)
from app.modules.backup_restore.router import router as backup_router


# ===========================================================================
# Test doubles (mirrors tests/test_backup_audit_writer_unit.py)
# ===========================================================================
class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now


class _Begin:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> "FakeSession":
        return self._session

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    """In-memory async session capturing the INSERTed audit-log params."""

    def __init__(self, fail_on_insert: bool = False) -> None:
        self.fail_on_insert = fail_on_insert
        self.inserts: list[dict] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def begin(self) -> _Begin:
        return _Begin(self)

    async def execute(self, statement, params=None):
        # The RLS reset call passes no params; the audit INSERT passes a dict.
        if params is None:
            return None
        if "action" in params:
            if self.fail_on_insert:
                raise RuntimeError("simulated audit-log write failure")
            self.inserts.append(params)
        return None


class SessionFactory:
    """Yields a fresh FakeSession per call; records each created session."""

    def __init__(self, fail_on_insert: bool = False) -> None:
        self.fail_on_insert = fail_on_insert
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession(fail_on_insert=self.fail_on_insert)
        self.sessions.append(session)
        return session

    @property
    def all_inserts(self) -> list[dict]:
        rows: list[dict] = []
        for s in self.sessions:
            rows.extend(s.inserts)
        return rows


def _fake_request(*, user_id: str | None, role: str | None, org_id: str | None = None) -> Request:
    """A minimal object exposing the ``request.state`` attributes the
    ``require_role`` dependency reads via ``getattr`` (user_id, org_id, role)."""
    state = types.SimpleNamespace(user_id=user_id, org_id=org_id, role=role)
    return types.SimpleNamespace(state=state)  # type: ignore[return-value]


# ===========================================================================
# Structural: the REAL backup router is gated by require_role("global_admin")
# ===========================================================================
def test_backup_router_is_mounted_under_api_v1_backup():
    assert backup_router.prefix == "/api/v1/backup"


def test_backup_router_carries_a_router_level_require_role_dependency():
    """Every route inherits the router-level ``require_role`` gate (Req 1.1/1.2/1.3)."""
    assert len(backup_router.dependencies) >= 1
    dep_callables = [getattr(d, "dependency", None) for d in backup_router.dependencies]
    # The require_role factory yields a closure named ``_check``.
    assert any(getattr(fn, "__name__", "") == "_check" for fn in dep_callables)


@pytest.mark.asyncio
async def test_router_dependency_allows_global_admin():
    """A global_admin token passes the router-level gate (no org_id needed)."""
    dep = backup_router.dependencies[0].dependency  # type: ignore[attr-defined]
    request = _fake_request(user_id=str(uuid.uuid4()), role="global_admin", org_id=None)
    # Passes → returns without raising.
    assert await dep(request) is None


@pytest.mark.asyncio
async def test_router_dependency_rejects_non_global_admin_with_403():
    """Req 1.2 — a valid non-global_admin token is rejected with HTTP 403."""
    dep = backup_router.dependencies[0].dependency  # type: ignore[attr-defined]
    request = _fake_request(user_id=str(uuid.uuid4()), role="org_admin", org_id=str(uuid.uuid4()))
    with pytest.raises(HTTPException) as excinfo:
        await dep(request)
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_router_dependency_rejects_missing_token_with_401():
    """Req 1.3 — no authenticated user (missing/invalid/expired token) → HTTP 401."""
    dep = backup_router.dependencies[0].dependency  # type: ignore[attr-defined]
    request = _fake_request(user_id=None, role=None, org_id=None)
    with pytest.raises(HTTPException) as excinfo:
        await dep(request)
    assert excinfo.value.status_code == 401


# ===========================================================================
# End-to-end (minimal app): rejections happen BEFORE the handler → no side effects
# ===========================================================================
def _build_gated_app(*, user_id: str | None, role: str | None, org_id: str | None):
    """A tiny app whose single route is gated by require_role("global_admin")
    and records a side effect when (and only when) the handler body runs."""
    app = FastAPI()
    side_effects: list[str] = []

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = user_id
        request.state.org_id = org_id
        request.state.role = role
        return await call_next(request)

    @app.post("/api/v1/backup/backups", dependencies=[require_role("global_admin")])
    async def _run_backup():
        # Stand-in for the real "create a backup/destination" side effect.
        side_effects.append("backup_created")
        return {"job_id": "00000000-0000-0000-0000-000000000000", "status": "queued"}

    return app, side_effects


def test_non_global_admin_request_is_403_with_no_side_effects():
    """Req 1.2 — non-global_admin → 403 AND the action does not execute."""
    app, side_effects = _build_gated_app(
        user_id=str(uuid.uuid4()), role="org_admin", org_id=str(uuid.uuid4())
    )
    client = TestClient(app)
    resp = client.post("/api/v1/backup/backups", json={})
    assert resp.status_code == 403
    assert side_effects == []  # no backup/destination created


def test_salesperson_request_is_403_with_no_side_effects():
    """Req 1.2 — another non-global_admin role is likewise denied with no effects."""
    app, side_effects = _build_gated_app(
        user_id=str(uuid.uuid4()), role="salesperson", org_id=str(uuid.uuid4())
    )
    client = TestClient(app)
    resp = client.post("/api/v1/backup/backups", json={})
    assert resp.status_code == 403
    assert side_effects == []


def test_missing_token_request_is_401_with_no_side_effects():
    """Req 1.3 — no token (no auth context) → 401 and the action does not execute."""
    app, side_effects = _build_gated_app(user_id=None, role=None, org_id=None)
    client = TestClient(app)
    resp = client.post("/api/v1/backup/backups", json={})
    assert resp.status_code == 401
    assert side_effects == []


def test_invalid_or_expired_token_request_is_401_with_no_side_effects():
    """Req 1.3 — an invalid/expired token leaves no user on state → 401, no effects.

    (An invalid or expired token is rejected upstream by the auth middleware, so
    by the time the dependency runs there is no ``user_id``/``role`` on the
    request — modelled here by a request with a role but no user id.)
    """
    app, side_effects = _build_gated_app(user_id=None, role="global_admin", org_id=None)
    client = TestClient(app)
    resp = client.post("/api/v1/backup/backups", json={})
    assert resp.status_code == 401
    assert side_effects == []


def test_global_admin_request_is_allowed_and_runs_the_action():
    """A global_admin request passes the gate and the action executes."""
    app, side_effects = _build_gated_app(
        user_id=str(uuid.uuid4()), role="global_admin", org_id=None
    )
    client = TestClient(app)
    resp = client.post("/api/v1/backup/backups", json={})
    assert resp.status_code == 200
    assert side_effects == ["backup_created"]


# ===========================================================================
# Audit-on-reject (Req 1.6) and audit-on-success (Req 1.5)
# ===========================================================================
@pytest.mark.asyncio
async def test_rejected_attempt_writes_audit_log_with_requesting_user_id():
    """Req 1.6 — a rejected attempt (authenticated non-global_admin) writes one
    audit_log entry carrying the requesting user id and the attempted action."""
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())
    actor = uuid.uuid4()

    await writer.audit_rejected_attempt(action=ACTION_BACKUP_CREATED, actor_id=actor)

    assert len(factory.all_inserts) == 1
    row = factory.all_inserts[0]
    assert row["action"] == ACTION_BACKUP_CREATED
    assert row["user_id"] == str(actor)
    assert '"outcome": "rejected"' in row["after_value"]
    # A timestamp is recorded for the attempt.
    assert row["created_at"].tzinfo is not None
    # The authenticated case does NOT mark the attempt unauthenticated.
    assert UNAUTHENTICATED_INDICATOR not in row["after_value"]


@pytest.mark.asyncio
async def test_rejected_attempt_writes_audit_log_with_unauthenticated_indicator():
    """Req 1.6 — a rejected attempt with no valid token records the
    unauthenticated indicator (and a null user id)."""
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())

    await writer.audit_rejected_attempt(action=ACTION_RESTORE_TRIGGERED, actor_id=None)

    assert len(factory.all_inserts) == 1
    row = factory.all_inserts[0]
    assert row["action"] == ACTION_RESTORE_TRIGGERED
    assert row["user_id"] is None
    assert UNAUTHENTICATED_INDICATOR in row["after_value"]


@pytest.mark.asyncio
async def test_successful_action_writes_one_audit_log_entry():
    """Req 1.5 — a successful global_admin action writes one audit_log entry with
    actor id, action type, target id, and a UTC timestamp."""
    factory = SessionFactory()
    writer = AuditWriter(session_factory=factory, clock=FakeClock())
    actor = uuid.uuid4()
    target = uuid.uuid4()

    await writer.write_completion(
        action=ACTION_BACKUP_CREATED,
        actor_id=actor,
        target_id=target,
        outcome="succeeded",
    )

    assert len(factory.all_inserts) == 1
    row = factory.all_inserts[0]
    assert row["action"] == ACTION_BACKUP_CREATED
    assert row["user_id"] == str(actor)
    assert row["entity_id"] == str(target)
    assert row["created_at"].tzinfo is not None
    assert '"outcome": "succeeded"' in row["after_value"]


@pytest.mark.asyncio
async def test_rejected_attempt_never_blocks_the_rejection_on_audit_failure():
    """Req 1.6 — even if the audit write fails, the rejection path does not raise
    (the request must still return its 403/401)."""
    factory = SessionFactory(fail_on_insert=True)
    writer = AuditWriter(session_factory=factory, clock=FakeClock())

    result = await writer.audit_rejected_attempt(
        action=ACTION_BACKUP_CREATED, actor_id=uuid.uuid4()
    )
    assert result is None
    assert factory.all_inserts == []
