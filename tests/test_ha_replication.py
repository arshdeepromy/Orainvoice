"""Unit tests for HA Replication — service, utils, middleware, and HMAC.

Requirements: 1.2, 2.1, 4.1, 4.3, 4.5, 8.4, 9.1, 11.1, 11.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.ha.hmac_utils import compute_hmac, verify_hmac
from app.modules.ha.schemas import (
    HAConfigRequest,
    HAConfigResponse,
    HeartbeatResponse,
    PublicStatusResponse,
)
from app.modules.ha.service import HAService
from app.modules.ha.utils import (
    can_promote,
    is_valid_role_transition,
    should_block_request,
    validate_confirmation_text,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_ha_config_model(**overrides):
    """Build a mock HAConfig ORM object with sensible defaults."""
    cfg = MagicMock()
    cfg.id = overrides.get("id", uuid.uuid4())
    cfg.node_id = overrides.get("node_id", uuid.uuid4())
    cfg.node_name = overrides.get("node_name", "Pi-Main")
    cfg.role = overrides.get("role", "standalone")
    cfg.peer_endpoint = overrides.get("peer_endpoint", "http://192.168.1.100:8999")
    cfg.auto_promote_enabled = overrides.get("auto_promote_enabled", False)
    cfg.heartbeat_interval_seconds = overrides.get("heartbeat_interval_seconds", 10)
    cfg.failover_timeout_seconds = overrides.get("failover_timeout_seconds", 90)
    cfg.maintenance_mode = overrides.get("maintenance_mode", False)
    cfg.sync_status = overrides.get("sync_status", "not_configured")
    cfg.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    cfg.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    return cfg


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_execute_returns(db, model):
    """Configure db.execute to return a single scalar result."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = model
    db.execute = AsyncMock(return_value=mock_result)


# ═════════════════════════════════════════════════════════════════════
# Pure function tests (no mocking needed)
# ═════════════════════════════════════════════════════════════════════


# ── Role state machine (is_valid_role_transition) ────────────────────


class TestRoleTransitions:
    """Requirement 4.1, 4.3 — role state machine validity."""

    def test_standby_to_primary_valid(self):
        assert is_valid_role_transition("standby", "primary") is True

    def test_primary_to_standby_valid(self):
        assert is_valid_role_transition("primary", "standby") is True

    def test_standalone_to_primary_valid(self):
        assert is_valid_role_transition("standalone", "primary") is True

    def test_standalone_to_standby_valid(self):
        assert is_valid_role_transition("standalone", "standby") is True

    def test_primary_to_primary_invalid(self):
        assert is_valid_role_transition("primary", "primary") is False

    def test_standby_to_standby_invalid(self):
        assert is_valid_role_transition("standby", "standby") is False

    def test_standalone_to_standalone_invalid(self):
        assert is_valid_role_transition("standalone", "standalone") is False


# ── Promotion lag threshold (can_promote) ────────────────────────────


class TestCanPromote:
    """Requirement 4.5 — promotion blocked when lag > 5s without force."""

    def test_lag_under_threshold(self):
        assert can_promote(3.0, False) is True

    def test_lag_at_threshold(self):
        assert can_promote(5.0, False) is True

    def test_lag_over_threshold_no_force(self):
        assert can_promote(10.0, False) is False

    def test_lag_over_threshold_with_force(self):
        assert can_promote(10.0, True) is True

    def test_lag_none(self):
        assert can_promote(None, False) is True


# ── Standby write protection (should_block_request) ─────────────────


class TestShouldBlockRequest:
    """Requirement 9.1, 9.3, 9.4 — standby middleware logic."""

    def test_standby_blocks_post(self):
        assert should_block_request("POST", "/api/v1/invoices", "standby") is True

    def test_standby_blocks_put(self):
        assert should_block_request("PUT", "/api/v1/invoices/1", "standby") is True

    def test_standby_blocks_delete(self):
        assert should_block_request("DELETE", "/api/v1/invoices/1", "standby") is True

    def test_standby_allows_get(self):
        assert should_block_request("GET", "/api/v1/invoices", "standby") is False

    def test_standby_allows_head(self):
        assert should_block_request("HEAD", "/api/v1/invoices", "standby") is False

    def test_standby_allows_options(self):
        assert should_block_request("OPTIONS", "/api/v1/invoices", "standby") is False

    def test_standby_allows_ha_post(self):
        assert should_block_request("POST", "/api/v1/ha/promote", "standby") is False

    def test_standby_allows_ha_put(self):
        assert should_block_request("PUT", "/api/v1/ha/configure", "standby") is False

    def test_primary_allows_all(self):
        assert should_block_request("POST", "/api/v1/invoices", "primary") is False

    def test_standalone_allows_all(self):
        assert should_block_request("POST", "/api/v1/invoices", "standalone") is False


# ── Confirmation text validation ─────────────────────────────────────


class TestConfirmationText:
    def test_exact_confirm_accepted(self):
        assert validate_confirmation_text("CONFIRM") is True

    def test_lowercase_rejected(self):
        assert validate_confirmation_text("confirm") is False

    def test_empty_rejected(self):
        assert validate_confirmation_text("") is False


# ── HMAC verification ────────────────────────────────────────────────


class TestHMACVerification:
    """Requirement 11.4 — HMAC sign/verify."""

    def test_compute_and_verify_success(self):
        payload = {"node": "pi-1", "role": "primary"}
        secret = "shared-secret"
        sig = compute_hmac(payload, secret)
        assert verify_hmac(payload, sig, secret) is True

    def test_wrong_secret_fails(self):
        payload = {"node": "pi-1"}
        sig = compute_hmac(payload, "correct-secret")
        assert verify_hmac(payload, sig, "wrong-secret") is False

    def test_tampered_payload_fails(self):
        payload = {"role": "primary"}
        sig = compute_hmac(payload, "key")
        assert verify_hmac({"role": "standby"}, sig, "key") is False

    def test_garbage_signature_fails(self):
        assert verify_hmac({"a": 1}, "garbage", "key") is False


# ═════════════════════════════════════════════════════════════════════
# Schema tests
# ═════════════════════════════════════════════════════════════════════


class TestPublicStatusResponse:
    """Requirement 8.4 — public status exposes only safe fields."""

    def test_only_safe_fields(self):
        resp = PublicStatusResponse(
            node_name="Pi-Main",
            role="primary",
            peer_status="healthy",
            sync_status="healthy",
        )
        fields = set(PublicStatusResponse.model_fields.keys())
        assert fields == {"node_name", "role", "peer_status", "sync_status"}

    def test_no_sensitive_data(self):
        """PublicStatusResponse must not contain node_id, peer_endpoint, etc."""
        resp = PublicStatusResponse(
            node_name="Pi-Main",
            role="primary",
            peer_status="healthy",
            sync_status="healthy",
        )
        data = resp.model_dump()
        for forbidden in ("node_id", "peer_endpoint", "database_status", "hmac_signature"):
            assert forbidden not in data


class TestHeartbeatResponse:
    """Requirement 2.1 — heartbeat returns correct structure."""

    def test_heartbeat_structure(self):
        resp = HeartbeatResponse(
            node_id="abc-123",
            node_name="Pi-Main",
            role="primary",
            status="healthy",
            database_status="connected",
            replication_lag_seconds=None,
            sync_status="healthy",
            uptime_seconds=3600.0,
            maintenance=False,
            timestamp="2025-01-01T00:00:00+00:00",
            hmac_signature="deadbeef" * 8,
        )
        assert resp.node_id == "abc-123"
        assert resp.node_name == "Pi-Main"
        assert resp.role == "primary"
        assert resp.status == "healthy"
        assert resp.database_status == "connected"
        assert resp.replication_lag_seconds is None
        assert resp.sync_status == "healthy"
        assert resp.uptime_seconds == 3600.0
        assert resp.maintenance is False
        assert resp.timestamp == "2025-01-01T00:00:00+00:00"
        assert isinstance(resp.hmac_signature, str)

    def test_heartbeat_with_replication_lag(self):
        resp = HeartbeatResponse(
            node_id="abc-123",
            node_name="Pi-Standby",
            role="standby",
            status="healthy",
            database_status="connected",
            replication_lag_seconds=2.5,
            sync_status="healthy",
            uptime_seconds=1800.0,
            maintenance=False,
            timestamp="2025-01-01T00:00:00+00:00",
            hmac_signature="deadbeef" * 8,
        )
        assert resp.replication_lag_seconds == 2.5
        assert resp.role == "standby"


# ═════════════════════════════════════════════════════════════════════
# Service tests (mocked DB)
# ═════════════════════════════════════════════════════════════════════


class TestHAServiceGetConfig:
    """Requirement 1.2 — config CRUD (read)."""

    @pytest.mark.asyncio
    async def test_get_config_returns_none_when_empty(self):
        db = _mock_db_session()
        _mock_execute_returns(db, None)
        result = await HAService.get_config(db)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_config_returns_response(self):
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="primary", node_name="Pi-Main")
        _mock_execute_returns(db, cfg)
        result = await HAService.get_config(db)
        assert result is not None
        assert result.node_name == "Pi-Main"
        assert result.role == "primary"


class TestHAServiceSaveConfig:
    """Requirement 1.2 — config CRUD (create, update)."""

    @pytest.mark.asyncio
    @patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.ha.service.set_node_role")
    async def test_save_config_creates_new(self, mock_set_role, mock_audit):
        db = _mock_db_session()
        # No existing config
        _mock_execute_returns(db, None)

        # After flush+refresh, simulate the ORM object being populated
        new_cfg = _make_ha_config_model(role="primary", node_name="Pi-Main")
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        db.flush = AsyncMock()

        # Patch _load_config to return None (insert path)
        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=None):
            # Patch the HAConfig constructor to return our mock
            with patch("app.modules.ha.service.HAConfig", return_value=new_cfg):
                result = await HAService.save_config(
                    db,
                    HAConfigRequest(
                        node_name="Pi-Main",
                        role="primary",
                        peer_endpoint="http://192.168.1.100:8999",
                    ),
                    user_id=uuid.uuid4(),
                )

        assert result.node_name == "Pi-Main"
        assert result.role == "primary"
        mock_set_role.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.ha.service.set_node_role")
    async def test_save_config_updates_existing(self, mock_set_role, mock_audit):
        db = _mock_db_session()
        existing = _make_ha_config_model(role="standalone", node_name="Pi-Old")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=existing):
            result = await HAService.save_config(
                db,
                HAConfigRequest(
                    node_name="Pi-Updated",
                    role="primary",
                    peer_endpoint="http://192.168.1.200:8999",
                ),
                user_id=uuid.uuid4(),
            )

        assert result.node_name == "Pi-Updated"
        assert result.role == "primary"
        assert existing.node_name == "Pi-Updated"


class TestHAServicePromote:
    """Requirement 4.1, 4.5 — promote happy path and blocked cases."""

    @pytest.mark.asyncio
    @patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.ha.service.set_node_role")
    @patch("app.modules.ha.service.ReplicationManager")
    async def test_promote_happy_path(self, mock_repl, mock_set_role, mock_audit):
        """Standby → primary with lag under threshold."""
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="standby")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg):
            mock_repl.get_replication_lag = AsyncMock(return_value=2.0)
            mock_repl.stop_subscription = AsyncMock()

            result = await HAService.promote(db, uuid.uuid4(), "rolling update", force=False)

        assert result["status"] == "ok"
        assert result["role"] == "primary"
        assert cfg.role == "primary"
        mock_set_role.assert_called_with("primary", cfg.peer_endpoint)

    @pytest.mark.asyncio
    async def test_promote_blocked_when_already_primary(self):
        """Cannot promote a node that is already primary."""
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="primary")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg):
            with pytest.raises(ValueError, match="Cannot promote"):
                await HAService.promote(db, uuid.uuid4(), "test", force=False)

    @pytest.mark.asyncio
    @patch("app.modules.ha.service.ReplicationManager")
    async def test_promote_blocked_when_lag_over_threshold(self, mock_repl):
        """Promotion blocked when lag > 5s and force=False."""
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="standby")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg):
            mock_repl.get_replication_lag = AsyncMock(return_value=10.0)

            with pytest.raises(ValueError, match="Replication lag"):
                await HAService.promote(db, uuid.uuid4(), "test", force=False)

    @pytest.mark.asyncio
    @patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.ha.service.set_node_role")
    @patch("app.modules.ha.service.ReplicationManager")
    async def test_promote_with_force_overrides_lag(self, mock_repl, mock_set_role, mock_audit):
        """Promotion succeeds with force=True even when lag > 5s."""
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="standby")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg):
            mock_repl.get_replication_lag = AsyncMock(return_value=10.0)
            mock_repl.stop_subscription = AsyncMock()

            result = await HAService.promote(db, uuid.uuid4(), "emergency", force=True)

        assert result["status"] == "ok"
        assert result["role"] == "primary"


class TestHAServiceDemote:
    """Requirement 4.3 — demote happy path and blocked case."""

    @pytest.mark.asyncio
    @patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.ha.service.set_node_role")
    @patch("app.modules.ha.service.ReplicationManager")
    async def test_demote_happy_path(self, mock_repl, mock_set_role, mock_audit):
        """Primary → standby."""
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="primary")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg):
            mock_repl.resume_subscription = AsyncMock()

            result = await HAService.demote(db, uuid.uuid4(), "rolling update")

        assert result["status"] == "ok"
        assert result["role"] == "standby"
        assert cfg.role == "standby"
        mock_set_role.assert_called_with("standby", cfg.peer_endpoint)

    @pytest.mark.asyncio
    async def test_demote_blocked_when_already_standby(self):
        """Cannot demote a node that is already standby."""
        db = _mock_db_session()
        cfg = _make_ha_config_model(role="standby")

        with patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg):
            with pytest.raises(ValueError, match="Cannot demote"):
                await HAService.demote(db, uuid.uuid4(), "test")


# ═════════════════════════════════════════════════════════════════════
# WebSocket write protection middleware tests (BUG-HA-13)
# ═════════════════════════════════════════════════════════════════════


class TestWebSocketWriteProtection:
    """Requirement 13.1, 13.2, 13.3 — WebSocket standby write protection."""

    @pytest.mark.asyncio
    async def test_ws_blocked_on_standby_non_allowlisted_path(self):
        """Non-allowlisted WS path is closed with 1013 on standby."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "standby"
            mw._split_brain_blocked = False

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/ws/orders/live"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            send.assert_called_once_with({
                "type": "websocket.close",
                "code": 1013,
                "reason": "This node is in standby mode. Writes not accepted.",
            })
            app.assert_not_called()
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split

    @pytest.mark.asyncio
    async def test_ws_allowed_kitchen_display_on_standby(self):
        """Kitchen display WS (/ws/kitchen/) is allowed on standby (read-only)."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "standby"
            mw._split_brain_blocked = False

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/ws/kitchen/test-org/all"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            app.assert_called_once_with(scope, receive, send)
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split

    @pytest.mark.asyncio
    async def test_ws_allowed_ha_path_on_standby(self):
        """HA management WS path (/api/v1/ha/) is allowed on standby."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "standby"
            mw._split_brain_blocked = False

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/api/v1/ha/ws-status"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            app.assert_called_once_with(scope, receive, send)
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split

    @pytest.mark.asyncio
    async def test_ws_allowed_on_primary(self):
        """All WS paths are allowed on primary."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "primary"
            mw._split_brain_blocked = False

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/ws/orders/live"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            app.assert_called_once_with(scope, receive, send)
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split

    @pytest.mark.asyncio
    async def test_ws_allowed_on_standalone(self):
        """All WS paths are allowed on standalone."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "standalone"
            mw._split_brain_blocked = False

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/ws/orders/live"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            app.assert_called_once_with(scope, receive, send)
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split

    @pytest.mark.asyncio
    async def test_ws_blocked_on_split_brain(self):
        """Non-allowlisted WS path is closed with 1013 during split-brain."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "primary"
            mw._split_brain_blocked = True

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/ws/orders/live"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            send.assert_called_once_with({
                "type": "websocket.close",
                "code": 1013,
                "reason": "This node is in standby mode. Writes not accepted.",
            })
            app.assert_not_called()
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split

    @pytest.mark.asyncio
    async def test_ws_kitchen_allowed_during_split_brain(self):
        """Kitchen display WS is allowed even during split-brain (read-only)."""
        from app.modules.ha import middleware as mw

        original_role = mw._node_role
        original_split = mw._split_brain_blocked
        try:
            mw._node_role = "primary"
            mw._split_brain_blocked = True

            app = AsyncMock()
            mid = mw.StandbyWriteProtectionMiddleware(app)

            scope = {"type": "websocket", "path": "/ws/kitchen/org-123/all"}
            receive = AsyncMock()
            send = AsyncMock()

            await mid(scope, receive, send)

            app.assert_called_once_with(scope, receive, send)
        finally:
            mw._node_role = original_role
            mw._split_brain_blocked = original_split
