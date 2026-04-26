"""Bug condition exploration tests — HA GUI Config Cleanup (Round 3).

These tests confirm that all 9 bugs EXIST in the unfixed code.
Each test asserts the BUGGY behavior so that test FAILURE confirms the bug exists.

After fixes are applied, these same tests will PASS (confirming the fix works).

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9,
             1.10, 1.11, 1.12, 1.13, 1.14, 1.15**
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Resolve project root — works both inside Docker (/app) and on the host
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ──────────────────────────────────────────────────────────


def _make_ha_config(**overrides):
    """Build a mock HAConfig ORM object with sensible defaults."""
    cfg = MagicMock()
    cfg.id = overrides.get("id", uuid.uuid4())
    cfg.node_id = overrides.get("node_id", uuid.uuid4())
    cfg.node_name = overrides.get("node_name", "test-node")
    cfg.role = overrides.get("role", "primary")
    cfg.peer_endpoint = overrides.get("peer_endpoint", "http://192.168.1.100:8999")
    cfg.auto_promote_enabled = overrides.get("auto_promote_enabled", False)
    cfg.heartbeat_interval_seconds = overrides.get("heartbeat_interval_seconds", 10)
    cfg.failover_timeout_seconds = overrides.get("failover_timeout_seconds", 90)
    cfg.maintenance_mode = overrides.get("maintenance_mode", False)
    cfg.sync_status = overrides.get("sync_status", "not_configured")
    cfg.promoted_at = overrides.get("promoted_at", None)
    cfg.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    cfg.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    cfg.peer_db_host = overrides.get("peer_db_host", None)
    cfg.peer_db_port = overrides.get("peer_db_port", None)
    cfg.peer_db_name = overrides.get("peer_db_name", None)
    cfg.peer_db_user = overrides.get("peer_db_user", None)
    cfg.peer_db_password = overrides.get("peer_db_password", None)
    cfg.peer_db_sslmode = overrides.get("peer_db_sslmode", None)
    cfg.heartbeat_secret = overrides.get("heartbeat_secret", None)
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
# CRIT: Peer DB URL env fallback — get_peer_db_url() falls back to env
# ═════════════════════════════════════════════════════════════════════


class TestCRIT_PeerDbUrlEnvFallback:
    """Verifies CRIT: get_peer_db_url() does NOT fall back to HA_PEER_DB_URL
    env var when DB peer config is empty.

    After fix: returns None without reading env var.

    **Validates: Requirements 1.1, 1.2**
    """

    @pytest.mark.asyncio
    async def test_get_peer_db_url_returns_none_when_db_empty(self):
        """get_peer_db_url() should return None when DB peer config is empty,
        NOT the HA_PEER_DB_URL env var value."""
        db = _mock_db_session()
        # Config with no peer DB fields populated
        cfg = _make_ha_config(
            peer_db_host=None,
            peer_db_port=None,
            peer_db_name=None,
            peer_db_user=None,
            peer_db_password=None,
        )
        _mock_execute_returns(db, cfg)

        test_env_url = "postgresql://replicator:leaked@192.168.1.90:5432/workshoppro"

        with patch.dict(os.environ, {"HA_PEER_DB_URL": test_env_url}):
            from app.modules.ha.service import get_peer_db_url

            result = await get_peer_db_url(db)

        # EXPECTED after fix: returns None (not the env var value)
        assert result is None, (
            f"get_peer_db_url() returned '{result}' instead of None — "
            "env fallback is still active (CRIT bug)"
        )


# ═════════════════════════════════════════════════════════════════════
# MOD-1a: Heartbeat secret env fallback in _get_heartbeat_secret_from_config
# ═════════════════════════════════════════════════════════════════════


class TestMOD1a_HeartbeatSecretEnvFallback:
    """Verifies MOD-1a: _get_heartbeat_secret_from_config(None) does NOT
    fall back to HA_HEARTBEAT_SECRET env var.

    After fix: returns "" without reading env var.

    **Validates: Requirements 1.3, 1.5**
    """

    def test_heartbeat_secret_returns_empty_when_no_config(self):
        """_get_heartbeat_secret_from_config(None) should return ''
        when no DB config exists, NOT the env var value."""
        test_env_secret = "dev-ha-secret-for-testing"

        with patch.dict(os.environ, {"HA_HEARTBEAT_SECRET": test_env_secret}):
            from app.modules.ha.service import _get_heartbeat_secret_from_config

            result = _get_heartbeat_secret_from_config(None)

        # EXPECTED after fix: returns "" (not the env var value)
        assert result == "", (
            f"_get_heartbeat_secret_from_config(None) returned '{result}' instead of '' — "
            "env fallback is still active (MOD-1a bug)"
        )


# ═════════════════════════════════════════════════════════════════════
# MOD-1b: Heartbeat endpoint env fallback in router.py cache-miss
# ═════════════════════════════════════════════════════════════════════


class TestMOD1b_HeartbeatEndpointEnvFallback:
    """Verifies MOD-1b: The heartbeat endpoint cache-miss code path in
    router.py does NOT fall back to os.environ.get("HA_HEARTBEAT_SECRET", "")
    when DB secret is empty.

    After fix: uses "" directly without reading env var.

    **Validates: Requirements 1.4**
    """

    def test_heartbeat_cache_miss_no_env_fallback(self):
        """Inspect the heartbeat function source to verify it does NOT
        contain os.environ.get("HA_HEARTBEAT_SECRET") in the cache-miss path."""
        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        source = router_path.read_text()

        tree = ast.parse(source)

        # Find the heartbeat function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "heartbeat":
                # Search for os.environ.get("HA_HEARTBEAT_SECRET", ...) calls
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    # Fallback: check the raw source
                    func_source = source

                # EXPECTED after fix: no HA_HEARTBEAT_SECRET env fallback in heartbeat()
                assert 'HA_HEARTBEAT_SECRET' not in func_source, (
                    "heartbeat() still contains HA_HEARTBEAT_SECRET env fallback "
                    "(MOD-1b bug)"
                )
                return

        pytest.fail("Could not find heartbeat() function in router.py")


# ═════════════════════════════════════════════════════════════════════
# MOD-2: Stale error messages referencing HA_PEER_DB_URL env var
# ═════════════════════════════════════════════════════════════════════


class TestMOD2_StaleErrorMessages:
    """Verifies MOD-2: Error messages in replication_init and replication_resync
    do NOT reference HA_PEER_DB_URL env var.

    After fix: messages reference GUI configuration only.

    **Validates: Requirements 1.6, 1.7**
    """

    def test_replication_init_error_no_env_reference(self):
        """replication_init error message should NOT mention HA_PEER_DB_URL."""
        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        source = router_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "replication_init":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # EXPECTED after fix: no HA_PEER_DB_URL in error messages
                assert "HA_PEER_DB_URL" not in func_source, (
                    "replication_init() still references HA_PEER_DB_URL in error message "
                    "(MOD-2 bug)"
                )
                return

        pytest.fail("Could not find replication_init() function in router.py")

    def test_replication_resync_error_no_env_reference(self):
        """replication_resync error message should NOT mention HA_PEER_DB_URL."""
        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        source = router_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "replication_resync":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # EXPECTED after fix: no HA_PEER_DB_URL in error messages
                assert "HA_PEER_DB_URL" not in func_source, (
                    "replication_resync() still references HA_PEER_DB_URL in error message "
                    "(MOD-2 bug)"
                )
                return

        pytest.fail("Could not find replication_resync() function in router.py")


# ═════════════════════════════════════════════════════════════════════
# MOD-3: Missing DB columns for local_lan_ip / local_pg_port
# ═════════════════════════════════════════════════════════════════════


class TestMOD3_MissingDbColumns:
    """Verifies MOD-3: HAConfig model HAS local_lan_ip and local_pg_port columns.

    Before fix: columns do NOT exist.
    After fix: columns exist.

    **Validates: Requirements 1.8, 1.9**
    """

    def test_haconfig_has_local_lan_ip_column(self):
        """HAConfig model should have a local_lan_ip column."""
        from sqlalchemy import inspect as sa_inspect
        from app.modules.ha.models import HAConfig

        mapper = sa_inspect(HAConfig)
        column_names = [col.key for col in mapper.mapper.column_attrs]

        # EXPECTED after fix: local_lan_ip IS in the model
        assert "local_lan_ip" in column_names, (
            "HAConfig model does not have local_lan_ip column (MOD-3 bug)"
        )

    def test_haconfig_has_local_pg_port_column(self):
        """HAConfig model should have a local_pg_port column."""
        from sqlalchemy import inspect as sa_inspect
        from app.modules.ha.models import HAConfig

        mapper = sa_inspect(HAConfig)
        column_names = [col.key for col in mapper.mapper.column_attrs]

        # EXPECTED after fix: local_pg_port IS in the model
        assert "local_pg_port" in column_names, (
            "HAConfig model does not have local_pg_port column (MOD-3 bug)"
        )


# ═════════════════════════════════════════════════════════════════════
# MOD-4: peer_role not in FailoverStatusResponse
# ═════════════════════════════════════════════════════════════════════


class TestMOD4_PeerRoleNotInFailoverStatus:
    """Verifies MOD-4: FailoverStatusResponse schema HAS a peer_role field.

    Before fix: field does NOT exist.
    After fix: field exists.

    **Validates: Requirements 1.10, 1.11**
    """

    def test_failover_status_response_has_peer_role(self):
        """FailoverStatusResponse should have a peer_role field."""
        from app.modules.ha.schemas import FailoverStatusResponse

        field_names = list(FailoverStatusResponse.model_fields.keys())

        # EXPECTED after fix: peer_role IS in the schema
        assert "peer_role" in field_names, (
            "FailoverStatusResponse does not have peer_role field (MOD-4 bug)"
        )


# ═════════════════════════════════════════════════════════════════════
# MOD-5: stop-replication not in CONFIRM gate
# ═════════════════════════════════════════════════════════════════════


class TestMOD5_StopReplicationNoConfirm:
    """Verifies MOD-5: 'stop-replication' IS in the needsConfirmText list.

    Before fix: NOT in the list.
    After fix: IS in the list.

    **Validates: Requirements 1.12**
    """

    def test_stop_replication_in_confirm_gate(self):
        """The needsConfirmText logic should include 'stop-replication'."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        # Find the needsConfirmText line
        # Pattern: needsConfirmText = modalAction && (['promote', 'demote', ...].includes(modalAction)
        match = re.search(
            r"needsConfirmText\s*=\s*modalAction\s*&&\s*\(\s*\[([^\]]+)\]\.includes",
            source,
        )
        assert match is not None, "Could not find needsConfirmText definition"

        confirm_list_str = match.group(1)

        # EXPECTED after fix: 'stop-replication' IS in the list
        assert "'stop-replication'" in confirm_list_str, (
            f"'stop-replication' is not in needsConfirmText list: [{confirm_list_str}] "
            "(MOD-5 bug)"
        )


# ═════════════════════════════════════════════════════════════════════
# MIN-1: _auto_promote_attempted not reset on peer recovery
# ═════════════════════════════════════════════════════════════════════


class TestMIN1_AutoPromoteFlagNotReset:
    """Verifies MIN-1: _auto_promote_attempted IS reset to False on peer recovery.

    Before fix: flag stays True after peer recovers.
    After fix: flag is reset to False.

    **Validates: Requirements 1.13**
    """

    def test_auto_promote_attempted_reset_on_recovery(self):
        """The peer recovery branch in _ping_loop should reset
        _auto_promote_attempted to False alongside _peer_unreachable_since."""
        heartbeat_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "heartbeat.py"
        source = heartbeat_path.read_text()

        tree = ast.parse(source)

        # Find the _ping_loop method in HeartbeatService
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_ping_loop":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # The recovery branch resets _peer_unreachable_since = None.
                # After fix, it should ALSO reset _auto_promote_attempted = False.
                assert "_auto_promote_attempted = False" in func_source, (
                    "_ping_loop recovery branch does not reset _auto_promote_attempted — "
                    "flag is never cleared on peer recovery (MIN-1 bug)"
                )
                return

        pytest.fail("Could not find _ping_loop() method in heartbeat.py")


# ═════════════════════════════════════════════════════════════════════
# MIN-2: Dead code _get_heartbeat_secret() still exists
# ═════════════════════════════════════════════════════════════════════


class TestMIN2_DeadCode:
    """Verifies MIN-2: _get_heartbeat_secret() function does NOT exist in service.py.

    Before fix: function exists (dead code).
    After fix: function is deleted.

    **Validates: Requirements 1.14**
    """

    def test_get_heartbeat_secret_not_in_service(self):
        """The dead function _get_heartbeat_secret() should not exist in service.py."""
        service_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "service.py"
        source = service_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_get_heartbeat_secret":
                # EXPECTED after fix: this function should NOT exist
                pytest.fail(
                    "_get_heartbeat_secret() still exists in service.py (MIN-2 dead code bug)"
                )

        # If we get here, the function doesn't exist — test passes


# ═════════════════════════════════════════════════════════════════════
# MIN-3: Setup guide still mentions .env files
# ═════════════════════════════════════════════════════════════════════


class TestMIN3_StaleGuideText:
    """Verifies MIN-3: Setup guide security notes do NOT mention .env files
    for HA configuration.

    Before fix: text says "protect your .env files too".
    After fix: text references GUI-only configuration.

    **Validates: Requirements 1.15**
    """

    def test_setup_guide_no_env_reference(self):
        """The setup guide security notes should not mention .env files."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        # Find the Security Notes section in the SetupGuide component
        # Look for the specific stale text
        stale_pattern = r"protect your.*\.env.*files"

        # EXPECTED after fix: stale text is NOT present
        assert not re.search(stale_pattern, source, re.IGNORECASE), (
            "Setup guide still mentions protecting .env files (MIN-3 bug)"
        )
