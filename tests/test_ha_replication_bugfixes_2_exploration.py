"""Bug condition exploration tests — HA Replication Bugfixes Round 2.

These tests confirm that all 6 bugs EXIST in the unfixed code.
Each test asserts the BUGGY behavior (e.g., cleanup NOT called, local_role NOT updated).

After fixes are applied, these same assertions will be INVERTED to verify the fix works.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10**
"""

from __future__ import annotations

import inspect
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import yaml

# Resolve project root — works both inside Docker (/app) and on the host
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ──────────────────────────────────────────────────────────


def _make_ha_config(**overrides):
    """Build a mock HAConfig ORM object with sensible defaults."""
    cfg = MagicMock()
    cfg.id = overrides.get("id", uuid.uuid4())
    cfg.node_id = overrides.get("node_id", uuid.uuid4())
    cfg.node_name = overrides.get("node_name", "test-node")
    cfg.role = overrides.get("role", "standby")
    cfg.peer_endpoint = overrides.get("peer_endpoint", "http://192.168.1.100:8999")
    cfg.auto_promote_enabled = overrides.get("auto_promote_enabled", False)
    cfg.heartbeat_interval_seconds = overrides.get("heartbeat_interval_seconds", 10)
    cfg.failover_timeout_seconds = overrides.get("failover_timeout_seconds", 90)
    cfg.maintenance_mode = overrides.get("maintenance_mode", False)
    cfg.sync_status = overrides.get("sync_status", "not_configured")
    cfg.promoted_at = overrides.get("promoted_at", None)
    cfg.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    cfg.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    # Peer DB fields for building connection string
    cfg.peer_db_host = overrides.get("peer_db_host", "192.168.1.100")
    cfg.peer_db_port = overrides.get("peer_db_port", 5432)
    cfg.peer_db_name = overrides.get("peer_db_name", "workshoppro")
    cfg.peer_db_user = overrides.get("peer_db_user", "replicator")
    cfg.peer_db_password = overrides.get("peer_db_password", "encrypted_pw")
    cfg.peer_db_sslmode = overrides.get("peer_db_sslmode", "disable")
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
# CRIT-1: trigger_resync orphaned slot — resync always fails on 2nd call
# ═════════════════════════════════════════════════════════════════════


class TestCRIT1_TriggerResyncOrphanedSlot:
    """Verifies CRIT-1 FIX: _cleanup_orphaned_slot_on_peer IS called
    between drop_subscription and CREATE SUBSCRIPTION in trigger_resync.

    **Validates: Requirements 2.1, 2.2**
    """

    @pytest.mark.asyncio
    async def test_trigger_resync_cleans_up_orphaned_slot(self):
        """Fix verified: trigger_resync now calls _cleanup_orphaned_slot_on_peer
        between drop_subscription and CREATE SUBSCRIPTION, so the orphaned
        replication slot is removed before re-creating the subscription."""
        db = _mock_db_session()

        with (
            patch(
                "app.modules.ha.replication.ReplicationManager.truncate_all_tables",
                new_callable=AsyncMock,
            ) as mock_truncate,
            patch(
                "app.modules.ha.replication.ReplicationManager.drop_subscription",
                new_callable=AsyncMock,
            ) as mock_drop_sub,
            patch(
                "app.modules.ha.replication.ReplicationManager._exec_autocommit",
                new_callable=AsyncMock,
            ) as mock_exec,
            patch(
                "app.modules.ha.replication.ReplicationManager._cleanup_orphaned_slot_on_peer",
                new_callable=AsyncMock,
            ) as mock_cleanup,
        ):
            from app.modules.ha.replication import ReplicationManager

            await ReplicationManager.trigger_resync(db, "postgresql://primary:5432/db")

            # Confirm the basic flow happened
            mock_truncate.assert_called_once()
            mock_drop_sub.assert_called_once_with(db)
            mock_exec.assert_called_once()  # CREATE SUBSCRIPTION

            # FIX: _cleanup_orphaned_slot_on_peer IS called with the primary connection string
            mock_cleanup.assert_called_once_with("postgresql://primary:5432/db")


# ═════════════════════════════════════════════════════════════════════
# CRIT-2: promote/demote/demote_and_sync don't update local_role
# ═════════════════════════════════════════════════════════════════════


class TestCRIT2_LocalRoleUpdated:
    """Verifies CRIT-2 FIX: _heartbeat_service.local_role IS correctly updated
    after manual promote(), demote(), or demote_and_sync().

    **Validates: Requirements 2.3, 2.4, 2.5**
    """

    @pytest.mark.asyncio
    async def test_promote_updates_heartbeat_local_role(self):
        """Fix verified: After promote(), _heartbeat_service.local_role is updated
        to 'primary' so split-brain detection uses the correct local role."""
        db = _mock_db_session()
        cfg = _make_ha_config(role="standby")
        _mock_execute_returns(db, cfg)

        mock_hb = MagicMock()
        mock_hb.local_role = "standby"
        mock_hb.secret = "test-secret"

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.modules.ha.service._heartbeat_service", mock_hb),
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch(
                "app.modules.ha.replication.ReplicationManager.get_replication_lag",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
            patch(
                "app.modules.ha.replication.ReplicationManager.stop_subscription",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.ha.replication.ReplicationManager.sync_sequences_post_promotion",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.ha.service import HAService

            await HAService.promote(db, uuid.uuid4(), "test", force=True)

            # FIX: local_role is now updated to "primary" after promote
            assert mock_hb.local_role == "primary"

    @pytest.mark.asyncio
    async def test_demote_updates_heartbeat_local_role(self):
        """Fix verified: After demote(), _heartbeat_service.local_role is updated
        to 'standby' so split-brain detection does not fire spuriously."""
        db = _mock_db_session()
        cfg = _make_ha_config(role="primary")
        _mock_execute_returns(db, cfg)

        mock_hb = MagicMock()
        mock_hb.local_role = "primary"
        mock_hb.secret = "test-secret"

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.modules.ha.service._heartbeat_service", mock_hb),
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.ha.service.get_peer_db_url", new_callable=AsyncMock, return_value="postgresql://peer:5432/db"),
            patch(
                "app.modules.ha.replication.ReplicationManager.resume_subscription",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.ha.service import HAService

            await HAService.demote(db, uuid.uuid4(), "test")

            # FIX: local_role is now updated to "standby" after demote
            assert mock_hb.local_role == "standby"

    @pytest.mark.asyncio
    async def test_demote_and_sync_updates_heartbeat_local_role(self):
        """Fix verified: After demote_and_sync(), _heartbeat_service.local_role is updated
        to 'standby' so split-brain detection does not fire spuriously."""
        db = _mock_db_session()
        cfg = _make_ha_config(role="primary")
        _mock_execute_returns(db, cfg)

        mock_hb = MagicMock()
        mock_hb.local_role = "primary"
        mock_hb.secret = "test-secret"

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.modules.ha.service._heartbeat_service", mock_hb),
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.set_split_brain_blocked"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.ha.service.get_peer_db_url", new_callable=AsyncMock, return_value="postgresql://peer:5432/db"),
            patch(
                "app.modules.ha.replication.ReplicationManager.truncate_all_tables",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.ha.replication.ReplicationManager.init_standby",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.ha.service import HAService

            await HAService.demote_and_sync(db, uuid.uuid4(), "test")

            # FIX: local_role is now updated to "standby" after demote_and_sync
            assert mock_hb.local_role == "standby"


# ═════════════════════════════════════════════════════════════════════
# CRIT-3: drop_replication_slot passes None as db → 500 on every call
# ═════════════════════════════════════════════════════════════════════


class TestCRIT3_DropSlotHasDB:
    """Verifies CRIT-3 FIX: drop_replication_slot endpoint now has a db parameter
    and passes it (not None) to ReplicationManager.drop_replication_slot.

    **Validates: Requirements 2.6**
    """

    def test_drop_replication_slot_has_db_parameter(self):
        """Fix verified: The endpoint function signature includes db: AsyncSession = Depends(get_db_session),
        so it correctly injects a database session."""
        from app.modules.ha.router import drop_replication_slot

        sig = inspect.signature(drop_replication_slot)
        param_names = list(sig.parameters.keys())

        # FIX: 'db' IS in the parameter list
        assert "db" in param_names

    def test_drop_replication_slot_passes_db_to_manager(self):
        """Fix verified: The source code passes db (a Name node, not None Constant)
        as the first argument to ReplicationManager.drop_replication_slot."""
        import ast

        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        with open(router_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)

        # Find the drop_replication_slot function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "drop_replication_slot":
                # Find the call to ReplicationManager.drop_replication_slot
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Await)
                        and isinstance(child.value, ast.Call)
                    ):
                        call_node = child.value
                        # Check if it's ReplicationManager.drop_replication_slot(db, ...)
                        if (
                            isinstance(call_node.func, ast.Attribute)
                            and call_node.func.attr == "drop_replication_slot"
                            and len(call_node.args) >= 1
                            and isinstance(call_node.args[0], ast.Name)
                            and call_node.args[0].id == "db"
                        ):
                            # FIX CONFIRMED: passes db as first arg
                            assert True
                            return

        pytest.fail("Could not find ReplicationManager.drop_replication_slot(db, ...) call")


# ═════════════════════════════════════════════════════════════════════
# SIG-1: save_config restarts heartbeat without Redis lock info
# ═════════════════════════════════════════════════════════════════════


class TestSIG1_SaveConfigRedisLockWired:
    """Verifies SIG-1 FIX: When save_config restarts the heartbeat service,
    the new HeartbeatService instance has _redis_lock_key, _lock_ttl, and
    _redis_client correctly wired from app.core.redis.redis_pool.

    **Validates: Requirements 2.7**
    """

    @pytest.mark.asyncio
    async def test_save_config_heartbeat_restart_preserves_redis_lock(self):
        """Fix verified: save_config now wires _redis_lock_key, _lock_ttl,
        and _redis_client on the new HeartbeatService instance, so the Redis
        heartbeat lock TTL continues to be renewed and duplicate heartbeat
        services across workers are prevented."""
        db = _mock_db_session()

        # Existing config with a different peer endpoint to trigger restart
        old_cfg = _make_ha_config(role="primary", peer_endpoint="http://old-peer:8999")
        _mock_execute_returns(db, old_cfg)

        new_config = MagicMock()
        new_config.node_name = "test-node"
        new_config.role = "primary"
        new_config.peer_endpoint = "http://new-peer:8999"
        new_config.auto_promote_enabled = False
        new_config.heartbeat_interval_seconds = 10
        new_config.failover_timeout_seconds = 90
        new_config.peer_db_host = None
        new_config.heartbeat_secret = None

        # Track the HeartbeatService instance that gets created
        created_services = []
        original_init = None

        from app.modules.ha.heartbeat import HeartbeatService as RealHBS

        original_init = RealHBS.__init__

        def tracking_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created_services.append(self)

        # Mock the old heartbeat service
        old_hb = MagicMock()
        old_hb.stop = AsyncMock()
        old_hb.secret = "old-secret"

        # Create a mock redis_pool that will be imported by save_config's try/except block
        mock_redis_pool = MagicMock()
        mock_redis_pool.set = AsyncMock()

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=old_cfg),
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.ha.service._get_heartbeat_secret_from_config", return_value="test-secret"),
            patch("app.modules.ha.service._heartbeat_service", old_hb),
            patch.object(RealHBS, "__init__", tracking_init),
            patch.object(RealHBS, "start", new_callable=AsyncMock),
            patch("app.modules.ha.service._config_to_response", return_value=MagicMock()),
            # Mock redis_pool at the source module so `from app.core.redis import redis_pool` works
            patch("app.core.redis.redis_pool", mock_redis_pool),
        ):
            from app.modules.ha.service import HAService
            await HAService.save_config(db, new_config, uuid.uuid4())

            # A new HeartbeatService should have been created
            assert len(created_services) >= 1, "No new HeartbeatService was created"
            new_hb = created_services[-1]

            # FIX: _redis_lock_key is correctly set on the new service
            assert new_hb._redis_lock_key == "ha:heartbeat_lock"
            # FIX: _lock_ttl is correctly set
            assert new_hb._lock_ttl == 30
            # FIX: _redis_client is set (not None)
            assert new_hb._redis_client is not None


# ═════════════════════════════════════════════════════════════════════
# SIG-2a: resume_subscription fallback missing copy_data=false
# ═════════════════════════════════════════════════════════════════════


class TestSIG2a_ResumeIncludesCopyDataFalse:
    """Verifies SIG-2a FIX: resume_subscription fallback CREATE SUBSCRIPTION
    now includes 'copy_data = false'.

    **Validates: Requirements 2.8**
    """

    @pytest.mark.asyncio
    async def test_resume_subscription_fallback_includes_copy_data_false(self):
        """Fix verified: When resume_subscription falls back to re-creating the subscription,
        the SQL now includes copy_data = false to prevent duplicate PK violations."""
        db = _mock_db_session()
        captured_sql = []

        async def capture_sql(db_arg, sql):
            captured_sql.append(sql)
            # First call (ALTER SUBSCRIPTION ENABLE) should fail to trigger fallback
            if "ENABLE" in sql:
                raise Exception("slot invalidated")

        with (
            patch(
                "app.modules.ha.replication.ReplicationManager._exec_autocommit",
                side_effect=capture_sql,
            ),
            patch(
                "app.modules.ha.replication.ReplicationManager.drop_subscription",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.ha.replication import ReplicationManager

            await ReplicationManager.resume_subscription(db, "postgresql://primary:5432/db")

        # Find the CREATE SUBSCRIPTION SQL in the fallback path
        create_sqls = [s for s in captured_sql if "CREATE SUBSCRIPTION" in s]
        assert len(create_sqls) == 1, f"Expected 1 CREATE SUBSCRIPTION, got {len(create_sqls)}"

        # FIX: SQL now contains 'copy_data = false'
        assert "copy_data = false" in create_sqls[0]


# ═════════════════════════════════════════════════════════════════════
# SIG-2b: demote() doesn't call drop_publication
# ═════════════════════════════════════════════════════════════════════


class TestSIG2b_DemoteDropsPublication:
    """Verifies SIG-2b FIX: demote() now calls drop_publication
    to remove the orphaned publication on the former primary.

    **Validates: Requirements 2.9**
    """

    @pytest.mark.asyncio
    async def test_demote_drops_publication(self):
        """Fix verified: demote() now calls drop_publication before
        resume_subscription, so the former primary no longer retains
        an active publication that holds WAL unnecessarily."""
        db = _mock_db_session()
        cfg = _make_ha_config(role="primary")
        _mock_execute_returns(db, cfg)

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.modules.ha.service._heartbeat_service", None),
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.ha.service.get_peer_db_url", new_callable=AsyncMock, return_value="postgresql://peer:5432/db"),
            patch(
                "app.modules.ha.replication.ReplicationManager.resume_subscription",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.ha.replication.ReplicationManager.drop_publication",
                new_callable=AsyncMock,
            ) as mock_drop_pub,
        ):
            from app.modules.ha.service import HAService

            await HAService.demote(db, uuid.uuid4(), "test")

            # FIX: drop_publication IS called during demote
            mock_drop_pub.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
# MIN-1: docker-compose.ha-standby.yml missing WAL settings
# ═════════════════════════════════════════════════════════════════════


class TestMIN1_ComposeHasWALSettings:
    """Verifies MIN-1 FIX: docker-compose.ha-standby.yml now includes
    max_wal_senders and max_replication_slots in the postgres command.

    **Validates: Requirements 2.10**
    """

    def test_ha_standby_compose_has_wal_settings(self):
        """Fix verified: The dev standby compose now explicitly declares
        max_wal_senders and max_replication_slots, matching all other compose files."""
        compose_path = _PROJECT_ROOT / "docker-compose.ha-standby.yml"
        # Also check the workspace root (tests may run from /app inside Docker
        # where compose files aren't mounted, but the tests/ dir is)
        if not compose_path.exists():
            # Try one level up from /app (the Docker workdir)
            alt_path = Path("/mnt/hindi-tv/Invoicing/docker-compose.ha-standby.yml")
            if alt_path.exists():
                compose_path = alt_path
            else:
                pytest.skip("docker-compose.ha-standby.yml not available in this environment")

        with open(compose_path, "r") as f:
            compose = yaml.safe_load(f)

        postgres_command = compose["services"]["postgres"]["command"]

        # Flatten the command list to a single string for searching
        command_str = " ".join(str(item) for item in postgres_command)

        # FIX: max_wal_senders IS in the postgres command
        assert "max_wal_senders" in command_str

        # FIX: max_replication_slots IS in the postgres command
        assert "max_replication_slots" in command_str
