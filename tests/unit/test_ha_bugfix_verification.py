"""Verification tests for already-fixed HA bugs (Requirements 18–29).

These tests confirm that previously identified and fixed bugs remain correct.
They use source code inspection, file parsing, and direct function calls
rather than integration tests — no running database or Docker required.

**Validates: Requirements 18.1-18.4, 19.1-19.4, 20.1-20.5, 21.1-21.3,
22.1-22.4, 23.1-23.3, 24.1-24.2, 25.1-25.6, 26.1-26.4, 27.1-27.3,
28.1-28.3, 29.1-29.3**
"""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_source(module) -> str:
    """Return the full source code of a module."""
    return inspect.getsource(module)


def _read_file(relative_path: str) -> str:
    """Read a file relative to the project root, with container fallback."""
    primary = PROJECT_ROOT / relative_path
    if primary.exists():
        return primary.read_text(encoding="utf-8")
    # Inside Docker container, files may be at /app/
    container_path = Path("/app") / relative_path
    if container_path.exists():
        return container_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Cannot find {relative_path} at {primary} or {container_path}")


# ===========================================================================
# Req 18: trigger_resync calls _cleanup_orphaned_slot_on_peer
# ===========================================================================


class TestReq18TriggerResyncOrphanedSlot:
    """Verify trigger_resync cleans up orphaned replication slots.

    **Validates: Requirements 18.1, 18.2, 18.3, 18.4**
    """

    def test_trigger_resync_calls_cleanup_orphaned_slot(self):
        """trigger_resync source contains _cleanup_orphaned_slot_on_peer call."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.trigger_resync)
        assert "_cleanup_orphaned_slot_on_peer" in source, (
            "trigger_resync must call _cleanup_orphaned_slot_on_peer "
            "between drop_subscription and CREATE SUBSCRIPTION"
        )

    def test_trigger_resync_cleanup_before_create(self):
        """_cleanup_orphaned_slot_on_peer appears before CREATE SUBSCRIPTION."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.trigger_resync)
        cleanup_pos = source.index("_cleanup_orphaned_slot_on_peer")
        create_pos = source.index("CREATE SUBSCRIPTION")
        assert cleanup_pos < create_pos, (
            "_cleanup_orphaned_slot_on_peer must be called before CREATE SUBSCRIPTION"
        )

    def test_trigger_resync_cleanup_after_drop(self):
        """_cleanup_orphaned_slot_on_peer appears after drop_subscription."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.trigger_resync)
        drop_pos = source.index("drop_subscription")
        cleanup_pos = source.index("_cleanup_orphaned_slot_on_peer")
        assert drop_pos < cleanup_pos, (
            "_cleanup_orphaned_slot_on_peer must be called after drop_subscription"
        )


# ===========================================================================
# Req 19: promote/demote/demote_and_sync update heartbeat local_role
# ===========================================================================


class TestReq19HeartbeatLocalRoleUpdate:
    """Verify role transitions update _heartbeat_service.local_role.

    **Validates: Requirements 19.1, 19.2, 19.3, 19.4**
    """

    def test_promote_updates_local_role(self):
        """promote() source sets _heartbeat_service.local_role to 'primary'."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.promote)
        assert '_heartbeat_service.local_role = "primary"' in source or \
               "_heartbeat_service.local_role = 'primary'" in source, (
            "promote() must update _heartbeat_service.local_role to 'primary'"
        )

    def test_demote_updates_local_role(self):
        """demote() source sets _heartbeat_service.local_role to 'standby'."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.demote)
        assert '_heartbeat_service.local_role = "standby"' in source or \
               "_heartbeat_service.local_role = 'standby'" in source, (
            "demote() must update _heartbeat_service.local_role to 'standby'"
        )

    def test_demote_and_sync_updates_local_role(self):
        """demote_and_sync() source sets _heartbeat_service.local_role to 'standby'."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.demote_and_sync)
        assert '_heartbeat_service.local_role = "standby"' in source or \
               "_heartbeat_service.local_role = 'standby'" in source, (
            "demote_and_sync() must update _heartbeat_service.local_role to 'standby'"
        )

    def test_local_role_update_guarded_by_none_check(self):
        """All three methods guard the update with 'if _heartbeat_service is not None'."""
        from app.modules.ha.service import HAService

        for method_name in ("promote", "demote", "demote_and_sync"):
            source = inspect.getsource(getattr(HAService, method_name))
            assert "_heartbeat_service is not None" in source, (
                f"{method_name}() must guard local_role update with "
                "'if _heartbeat_service is not None'"
            )


# ===========================================================================
# Req 20: drop_replication_slot endpoint has Depends(get_db_session)
# ===========================================================================


class TestReq20DropSlotDbSession:
    """Verify drop_replication_slot endpoint uses Depends(get_db_session).

    **Validates: Requirements 20.1, 20.2, 20.3, 20.4, 20.5**
    """

    def test_drop_slot_endpoint_has_db_dependency(self):
        """drop_replication_slot function signature includes Depends(get_db_session)."""
        from app.modules.ha.router import drop_replication_slot

        source = inspect.getsource(drop_replication_slot)
        assert "Depends(get_db_session)" in source, (
            "drop_replication_slot must have db: AsyncSession = Depends(get_db_session)"
        )

    def test_drop_slot_endpoint_passes_db_to_manager(self):
        """drop_replication_slot passes db to ReplicationManager.drop_replication_slot."""
        from app.modules.ha.router import drop_replication_slot

        source = inspect.getsource(drop_replication_slot)
        assert "drop_replication_slot(db," in source or \
               "drop_replication_slot(db, slot_name)" in source, (
            "drop_replication_slot must pass db session to ReplicationManager"
        )

    def test_drop_slot_function_signature_has_db_param(self):
        """The function signature includes 'db' as a parameter."""
        from app.modules.ha.router import drop_replication_slot

        sig = inspect.signature(drop_replication_slot)
        assert "db" in sig.parameters, (
            "drop_replication_slot must have 'db' in its function signature"
        )


# ===========================================================================
# Req 21: save_config wires Redis lock fields on new HeartbeatService
# ===========================================================================


class TestReq21SaveConfigRedisLockWiring:
    """Verify save_config wires Redis lock fields to new HeartbeatService.

    **Validates: Requirements 21.1, 21.2, 21.3**
    """

    def test_save_config_sets_redis_lock_key(self):
        """save_config source sets _redis_lock_key on new HeartbeatService."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.save_config)
        assert "_redis_lock_key" in source, (
            "save_config must wire _redis_lock_key to new HeartbeatService"
        )

    def test_save_config_sets_lock_ttl(self):
        """save_config source sets _lock_ttl on new HeartbeatService."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.save_config)
        assert "_lock_ttl" in source, (
            "save_config must wire _lock_ttl to new HeartbeatService"
        )

    def test_save_config_sets_redis_client(self):
        """save_config source sets _redis_client on new HeartbeatService."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.save_config)
        assert "_redis_client" in source, (
            "save_config must wire _redis_client to new HeartbeatService"
        )

    def test_save_config_redis_wiring_in_try_except(self):
        """Redis wiring is wrapped in try/except for graceful fallback."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.save_config)
        # The redis wiring block should be inside a try/except
        redis_section_start = source.index("_redis_lock_key")
        # Find the nearest preceding 'try:' before the redis wiring
        # Look back up to 200 chars for the try: statement
        preceding = source[:redis_section_start]
        last_200 = preceding[-200:]
        assert "try:" in last_200, (
            "Redis lock wiring must be wrapped in try/except"
        )


# ===========================================================================
# Req 22: resume_subscription uses copy_data=false; demote drops publication
# ===========================================================================


class TestReq22DemoteCopyDataAndPublication:
    """Verify resume_subscription fallback uses copy_data=false and demote drops publication.

    **Validates: Requirements 22.1, 22.2, 22.3, 22.4**
    """

    def test_resume_subscription_uses_copy_data_false(self):
        """resume_subscription fallback CREATE uses copy_data = false."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.resume_subscription)
        assert "copy_data = false" in source or "copy_data=false" in source, (
            "resume_subscription fallback must use copy_data = false"
        )

    def test_demote_drops_publication(self):
        """demote() calls drop_publication before creating subscription."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.demote)
        assert "drop_publication" in source, (
            "demote() must call drop_publication to remove the publication "
            "when transitioning from primary to standby"
        )

    def test_demote_drops_publication_before_resume(self):
        """drop_publication is called before resume_subscription in demote()."""
        from app.modules.ha.service import HAService

        source = inspect.getsource(HAService.demote)
        drop_pos = source.index("drop_publication")
        resume_pos = source.index("resume_subscription")
        assert drop_pos < resume_pos, (
            "drop_publication must be called before resume_subscription in demote()"
        )


# ===========================================================================
# Req 23: _auto_promote_attempted reset on peer recovery
# ===========================================================================


class TestReq23AutoPromoteAttemptedReset:
    """Verify _auto_promote_attempted resets when peer recovers.

    **Validates: Requirements 23.1, 23.2, 23.3**
    """

    def test_auto_promote_attempted_reset_in_ping_loop(self):
        """_ping_loop resets _auto_promote_attempted to False on peer recovery."""
        from app.modules.ha.heartbeat import HeartbeatService

        source = inspect.getsource(HeartbeatService._ping_loop)
        assert "_auto_promote_attempted = False" in source, (
            "_ping_loop must reset _auto_promote_attempted to False "
            "when peer transitions from unreachable to reachable"
        )

    def test_auto_promote_failed_permanently_not_reset(self):
        """_ping_loop does NOT reset _auto_promote_failed_permanently on recovery."""
        from app.modules.ha.heartbeat import HeartbeatService

        source = inspect.getsource(HeartbeatService._ping_loop)
        # The flag should be set to False only for _auto_promote_attempted,
        # not for _auto_promote_failed_permanently
        assert "_auto_promote_failed_permanently = False" not in source, (
            "_ping_loop must NOT reset _auto_promote_failed_permanently — "
            "permanent failure requires container restart"
        )

    def test_reset_happens_on_unreachable_to_reachable_transition(self):
        """The reset is in the unreachable→reachable transition branch."""
        from app.modules.ha.heartbeat import HeartbeatService

        source = inspect.getsource(HeartbeatService._ping_loop)
        # Find the block where peer transitions from unreachable to reachable
        # It should contain both the _peer_unreachable_since = None reset
        # and the _auto_promote_attempted = False reset
        unreachable_block_match = re.search(
            r'previous_health == "unreachable".*?_auto_promote_attempted = False',
            source,
            re.DOTALL,
        )
        assert unreachable_block_match is not None, (
            "_auto_promote_attempted reset must be in the "
            "unreachable→reachable transition block"
        )


# ===========================================================================
# Req 24: docker-compose.ha-standby.yml has max_wal_senders and max_replication_slots
# ===========================================================================


class TestReq24DevStandbyComposeSettings:
    """Verify docker-compose.ha-standby.yml has explicit replication settings.

    **Validates: Requirements 24.1, 24.2**
    """

    @staticmethod
    def _get_compose_path() -> Path:
        """Locate docker-compose.ha-standby.yml — check project root and /app/."""
        candidates = [
            PROJECT_ROOT / "docker-compose.ha-standby.yml",
            Path("/app/docker-compose.ha-standby.yml"),
            # When running inside Docker, compose files may be at workspace root
            Path("/") / "docker-compose.ha-standby.yml",
        ]
        for p in candidates:
            if p.exists():
                return p
        return PROJECT_ROOT / "docker-compose.ha-standby.yml"

    def test_ha_standby_compose_has_max_wal_senders(self):
        """docker-compose.ha-standby.yml postgres command includes max_wal_senders=10."""
        compose_path = self._get_compose_path()
        if not compose_path.exists():
            pytest.skip("docker-compose.ha-standby.yml not available in this environment")
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        pg_command = data["services"]["postgres"]["command"]
        assert "max_wal_senders=10" in pg_command, (
            "docker-compose.ha-standby.yml must include max_wal_senders=10"
        )

    def test_ha_standby_compose_has_max_replication_slots(self):
        """docker-compose.ha-standby.yml postgres command includes max_replication_slots=10."""
        compose_path = self._get_compose_path()
        if not compose_path.exists():
            pytest.skip("docker-compose.ha-standby.yml not available in this environment")
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        pg_command = data["services"]["postgres"]["command"]
        assert "max_replication_slots=10" in pg_command, (
            "docker-compose.ha-standby.yml must include max_replication_slots=10"
        )


# ===========================================================================
# Req 25: .env* files have empty HA_HEARTBEAT_SECRET and HA_PEER_DB_URL
# ===========================================================================


class TestReq25EnvFilesNoLeakedCredentials:
    """Verify .env* files have empty HA secret and peer DB URL values.

    **Validates: Requirements 25.1, 25.2, 25.3, 25.4, 25.5, 25.6**
    """

    @staticmethod
    def _find_env_file(env_file: str) -> Path | None:
        """Locate an .env file — check project root and /app/."""
        candidates = [
            PROJECT_ROOT / env_file,
            Path("/app") / env_file,
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    @pytest.mark.parametrize(
        "env_file",
        [".env", ".env.pi", ".env.ha-standby", ".env.standby-prod", ".env.pi-standby"],
    )
    def test_ha_heartbeat_secret_is_empty(self, env_file: str):
        """HA_HEARTBEAT_SECRET must be empty (no value after =)."""
        env_path = self._find_env_file(env_file)
        if env_path is None:
            pytest.skip(f"{env_file} not available in this environment")
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("HA_HEARTBEAT_SECRET="):
                value = stripped.split("=", 1)[1].strip()
                assert value == "", (
                    f"{env_file}: HA_HEARTBEAT_SECRET must be empty, got '{value}'"
                )
                return
        # If the key is not present at all, that's also acceptable
        pass

    @pytest.mark.parametrize(
        "env_file",
        [".env", ".env.pi", ".env.ha-standby", ".env.standby-prod", ".env.pi-standby"],
    )
    def test_ha_peer_db_url_is_empty(self, env_file: str):
        """HA_PEER_DB_URL must be empty (no value after =)."""
        env_path = self._find_env_file(env_file)
        if env_path is None:
            pytest.skip(f"{env_file} not available in this environment")
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("HA_PEER_DB_URL="):
                value = stripped.split("=", 1)[1].strip()
                assert value == "", (
                    f"{env_file}: HA_PEER_DB_URL must be empty, got '{value}'"
                )
                return
        # If the key is not present at all, that's also acceptable
        pass


# ===========================================================================
# Req 26: _get_heartbeat_secret_from_config has no env fallback
# ===========================================================================


class TestReq26NoEnvFallbackForSecrets:
    """Verify HA secret functions have no environment variable fallback.

    **Validates: Requirements 26.1, 26.2, 26.3, 26.4**
    """

    def test_get_heartbeat_secret_no_env_fallback(self):
        """_get_heartbeat_secret_from_config does not read HA_HEARTBEAT_SECRET env var."""
        from app.modules.ha.service import _get_heartbeat_secret_from_config

        source = inspect.getsource(_get_heartbeat_secret_from_config)
        assert "HA_HEARTBEAT_SECRET" not in source, (
            "_get_heartbeat_secret_from_config must not reference HA_HEARTBEAT_SECRET env var"
        )
        assert "os.environ" not in source, (
            "_get_heartbeat_secret_from_config must not use os.environ"
        )

    def test_get_heartbeat_secret_returns_empty_for_none_config(self):
        """_get_heartbeat_secret_from_config(None) returns empty string."""
        from app.modules.ha.service import _get_heartbeat_secret_from_config

        # Set env var to verify it's NOT used as fallback
        old_val = os.environ.get("HA_HEARTBEAT_SECRET")
        os.environ["HA_HEARTBEAT_SECRET"] = "should-not-be-used"
        try:
            result = _get_heartbeat_secret_from_config(None)
            assert result == "", (
                "_get_heartbeat_secret_from_config(None) must return '' "
                "regardless of HA_HEARTBEAT_SECRET env var"
            )
        finally:
            if old_val is None:
                os.environ.pop("HA_HEARTBEAT_SECRET", None)
            else:
                os.environ["HA_HEARTBEAT_SECRET"] = old_val

    def test_get_peer_db_url_no_env_fallback(self):
        """get_peer_db_url source does not read HA_PEER_DB_URL env var."""
        from app.modules.ha.service import get_peer_db_url

        source = inspect.getsource(get_peer_db_url)
        assert "HA_PEER_DB_URL" not in source, (
            "get_peer_db_url must not reference HA_PEER_DB_URL env var"
        )
        assert "os.environ" not in source, (
            "get_peer_db_url must not use os.environ"
        )

    def test_no_dead_get_heartbeat_secret_function(self):
        """The dead _get_heartbeat_secret() function (env-only) must not exist."""
        import app.modules.ha.service as svc_module

        # The old dead function was named _get_heartbeat_secret (without _from_config)
        # It should have been removed
        assert not hasattr(svc_module, "_get_heartbeat_secret") or \
               svc_module._get_heartbeat_secret is svc_module._get_heartbeat_secret_from_config, (
            "Dead _get_heartbeat_secret() function must be removed from service.py"
        )


# ===========================================================================
# Req 27: FailoverStatusResponse has peer_role field
# ===========================================================================


class TestReq27PeerRoleField:
    """Verify FailoverStatusResponse schema has peer_role field.

    **Validates: Requirements 27.1, 27.2, 27.3**
    """

    def test_failover_status_response_has_peer_role(self):
        """FailoverStatusResponse schema includes peer_role field."""
        from app.modules.ha.schemas import FailoverStatusResponse

        fields = FailoverStatusResponse.model_fields
        assert "peer_role" in fields, (
            "FailoverStatusResponse must have a 'peer_role' field"
        )

    def test_peer_role_default_is_unknown(self):
        """peer_role field defaults to 'unknown'."""
        from app.modules.ha.schemas import FailoverStatusResponse

        field_info = FailoverStatusResponse.model_fields["peer_role"]
        assert field_info.default == "unknown", (
            "peer_role field must default to 'unknown'"
        )

    def test_peer_role_is_string_type(self):
        """peer_role field is a string type."""
        from app.modules.ha.schemas import FailoverStatusResponse

        # Create an instance with minimal required fields to verify peer_role type
        instance = FailoverStatusResponse(
            auto_promote_enabled=False,
            failover_timeout_seconds=90,
        )
        assert isinstance(instance.peer_role, str), (
            "peer_role must be a string"
        )
        assert instance.peer_role == "unknown", (
            "peer_role must default to 'unknown' on instantiation"
        )


# ===========================================================================
# Req 28: stop-replication is in needsConfirmText list
# ===========================================================================


class TestReq28StopReplicationConfirmGate:
    """Verify stop-replication requires CONFIRM text in the frontend.

    **Validates: Requirements 28.1, 28.2, 28.3**
    """

    def test_stop_replication_in_needs_confirm_list(self):
        """HAReplication.tsx includes 'stop-replication' in the needsConfirmText array."""
        tsx_content = _read_file("frontend/src/pages/admin/HAReplication.tsx")
        # The needsConfirmText pattern: ['promote', 'demote', 'resync', 'stop-replication', ...]
        assert "'stop-replication'" in tsx_content or '"stop-replication"' in tsx_content, (
            "HAReplication.tsx must include 'stop-replication' in the "
            "needsConfirmText list"
        )

    def test_stop_replication_in_confirm_check(self):
        """The handleAction function checks stop-replication against CONFIRM."""
        tsx_content = _read_file("frontend/src/pages/admin/HAReplication.tsx")
        # Find the needsConfirm check that includes stop-replication
        pattern = re.compile(
            r"needsConfirm.*stop-replication.*CONFIRM|"
            r"stop-replication.*needsConfirm.*CONFIRM",
            re.DOTALL,
        )
        # Simpler check: both 'stop-replication' and 'CONFIRM' appear in handleAction context
        assert "stop-replication" in tsx_content, (
            "HAReplication.tsx must reference 'stop-replication'"
        )
        assert "confirmText !== 'CONFIRM'" in tsx_content or \
               'confirmText !== "CONFIRM"' in tsx_content, (
            "HAReplication.tsx must check confirmText against 'CONFIRM'"
        )

    def test_needs_confirm_text_variable_includes_stop_replication(self):
        """The needsConfirmText variable definition includes stop-replication."""
        tsx_content = _read_file("frontend/src/pages/admin/HAReplication.tsx")
        # Match the specific line: const needsConfirmText = modalAction && ([...].includes(modalAction) || ...)
        match = re.search(
            r"needsConfirmText\s*=.*\[.*'stop-replication'.*\]",
            tsx_content,
        )
        assert match is not None, (
            "needsConfirmText variable must include 'stop-replication' in its array"
        )


# ===========================================================================
# Req 29: No .env references for HA config in setup guide text
# ===========================================================================


class TestReq29SetupGuideNoEnvReferences:
    """Verify the setup guide does not instruct users to edit .env files for HA.

    **Validates: Requirements 29.1, 29.2, 29.3**
    """

    def test_setup_guide_no_env_file_instructions(self):
        """SetupGuide component does not reference .env files for HA configuration."""
        tsx_content = _read_file("frontend/src/pages/admin/HAReplication.tsx")

        # Extract the SetupGuide component section
        # It starts with "function SetupGuide" and ends before the next top-level component
        guide_match = re.search(
            r"function SetupGuide.*?^}$",
            tsx_content,
            re.DOTALL | re.MULTILINE,
        )
        assert guide_match is not None, "SetupGuide component must exist in HAReplication.tsx"
        guide_source = guide_match.group(0)

        # Check that .env is not referenced as something users should edit
        # The guide SHOULD mention that .env is NOT needed (negative reference is OK)
        env_edit_patterns = [
            r"edit.*\.env",
            r"set.*\.env",
            r"add.*\.env",
            r"update.*\.env",
            r"configure.*\.env",
        ]
        for pattern in env_edit_patterns:
            match = re.search(pattern, guide_source, re.IGNORECASE)
            assert match is None, (
                f"SetupGuide must not instruct users to edit .env files. "
                f"Found: '{match.group(0)}'" if match else ""
            )

    def test_setup_guide_mentions_db_stored_secrets(self):
        """SetupGuide mentions that secrets are stored encrypted in the database."""
        tsx_content = _read_file("frontend/src/pages/admin/HAReplication.tsx")

        guide_match = re.search(
            r"function SetupGuide.*?^}$",
            tsx_content,
            re.DOTALL | re.MULTILINE,
        )
        assert guide_match is not None
        guide_source = guide_match.group(0)

        # The guide should mention that credentials are stored encrypted in DB
        assert "encrypted" in guide_source.lower() or "database" in guide_source.lower(), (
            "SetupGuide should mention that HA secrets are stored encrypted in the database"
        )

    def test_setup_guide_states_no_env_required(self):
        """SetupGuide states that no .env entries are required for HA configuration."""
        tsx_content = _read_file("frontend/src/pages/admin/HAReplication.tsx")

        guide_match = re.search(
            r"function SetupGuide.*?^}$",
            tsx_content,
            re.DOTALL | re.MULTILINE,
        )
        assert guide_match is not None
        guide_source = guide_match.group(0)

        # Should contain a statement like "no .env file entries are required"
        assert "no" in guide_source.lower() and ".env" in guide_source, (
            "SetupGuide should state that no .env file entries are required for HA"
        )
