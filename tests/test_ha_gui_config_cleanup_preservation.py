"""Preservation property tests — HA GUI Config Cleanup (Round 3).

These tests capture EXISTING correct behavior on UNFIXED code.
They should PASS on the current code and continue to PASS after fixes
are applied, confirming no regressions were introduced.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8,
             3.9, 3.10, 3.11, 3.12**
"""

from __future__ import annotations

import ast
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
    cfg.local_lan_ip = overrides.get("local_lan_ip", None)
    cfg.local_pg_port = overrides.get("local_pg_port", None)
    cfg.last_peer_health = overrides.get("last_peer_health", "unknown")
    cfg.last_peer_heartbeat = overrides.get("last_peer_heartbeat", None)
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
# Req 3.1: _build_peer_db_url() with fully populated DB peer config
#           builds valid PostgreSQL URL — unchanged by CRIT fix
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_BuildPeerDbUrl:
    """Verify _build_peer_db_url() continues to build a valid PostgreSQL
    connection string from fully populated DB-stored peer config fields.

    **Validates: Requirements 3.1**
    """

    def test_build_peer_db_url_returns_valid_url_with_full_config(self):
        """_build_peer_db_url() with all peer DB fields populated returns
        a valid postgresql:// URL containing host, port, dbname, user."""
        from app.core.encryption import envelope_encrypt

        encrypted_pw = envelope_encrypt("test-password-123")
        cfg = _make_ha_config(
            peer_db_host="192.168.1.100",
            peer_db_port=5432,
            peer_db_name="workshoppro",
            peer_db_user="replicator",
            peer_db_password=encrypted_pw,
            peer_db_sslmode="disable",
        )

        from app.modules.ha.service import _build_peer_db_url

        result = _build_peer_db_url(cfg)

        assert result is not None, "_build_peer_db_url() should return a URL"
        assert result.startswith("postgresql://"), f"URL should start with postgresql://, got: {result}"
        assert "192.168.1.100" in result, "URL should contain the host"
        assert "5432" in result, "URL should contain the port"
        assert "workshoppro" in result, "URL should contain the database name"
        assert "replicator" in result, "URL should contain the user"

    def test_build_peer_db_url_returns_none_when_fields_missing(self):
        """_build_peer_db_url() returns None when required fields are missing."""
        cfg = _make_ha_config(
            peer_db_host=None,
            peer_db_port=None,
            peer_db_name=None,
            peer_db_user=None,
            peer_db_password=None,
        )

        from app.modules.ha.service import _build_peer_db_url

        result = _build_peer_db_url(cfg)

        assert result is None, "_build_peer_db_url() should return None when fields are missing"

    def test_build_peer_db_url_includes_sslmode_when_not_disable(self):
        """_build_peer_db_url() appends ?sslmode= when sslmode is not 'disable'."""
        from app.core.encryption import envelope_encrypt

        encrypted_pw = envelope_encrypt("test-password")
        cfg = _make_ha_config(
            peer_db_host="192.168.1.100",
            peer_db_port=5432,
            peer_db_name="workshoppro",
            peer_db_user="replicator",
            peer_db_password=encrypted_pw,
            peer_db_sslmode="require",
        )

        from app.modules.ha.service import _build_peer_db_url

        result = _build_peer_db_url(cfg)

        assert result is not None
        assert "?sslmode=require" in result, "URL should include sslmode when not 'disable'"

    def test_build_peer_db_url_no_sslmode_param_when_disable(self):
        """_build_peer_db_url() does NOT append ?sslmode= when sslmode is 'disable'."""
        from app.core.encryption import envelope_encrypt

        encrypted_pw = envelope_encrypt("test-password")
        cfg = _make_ha_config(
            peer_db_host="192.168.1.100",
            peer_db_port=5432,
            peer_db_name="workshoppro",
            peer_db_user="replicator",
            peer_db_password=encrypted_pw,
            peer_db_sslmode="disable",
        )

        from app.modules.ha.service import _build_peer_db_url

        result = _build_peer_db_url(cfg)

        assert result is not None
        assert "?sslmode=" not in result, "URL should NOT include sslmode param when 'disable'"


# ═════════════════════════════════════════════════════════════════════
# Req 3.2: _get_heartbeat_secret_from_config(cfg) with valid encrypted
#           DB secret returns decrypted value — unchanged by MOD-1 fix
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_GetHeartbeatSecretFromConfig:
    """Verify _get_heartbeat_secret_from_config() continues to decrypt
    and return the DB-stored secret when it exists and is valid.

    **Validates: Requirements 3.2**
    """

    def test_returns_decrypted_secret_when_db_has_valid_encrypted_secret(self):
        """_get_heartbeat_secret_from_config(cfg) with a valid encrypted
        heartbeat_secret returns the decrypted plaintext value."""
        from app.core.encryption import envelope_encrypt
        from app.modules.ha.service import _get_heartbeat_secret_from_config

        plaintext_secret = "my-super-secret-hmac-key"
        encrypted_secret = envelope_encrypt(plaintext_secret)

        cfg = _make_ha_config(heartbeat_secret=encrypted_secret)

        result = _get_heartbeat_secret_from_config(cfg)

        assert result == plaintext_secret, (
            f"Expected decrypted secret '{plaintext_secret}', got '{result}'"
        )

    def test_returns_decrypted_secret_with_special_characters(self):
        """_get_heartbeat_secret_from_config(cfg) handles secrets with
        special characters correctly."""
        from app.core.encryption import envelope_encrypt
        from app.modules.ha.service import _get_heartbeat_secret_from_config

        plaintext_secret = "s3cr3t!@#$%^&*()_+-=[]{}|;':\",./<>?"
        encrypted_secret = envelope_encrypt(plaintext_secret)

        cfg = _make_ha_config(heartbeat_secret=encrypted_secret)

        result = _get_heartbeat_secret_from_config(cfg)

        assert result == plaintext_secret


# ═════════════════════════════════════════════════════════════════════
# Req 3.3: Heartbeat endpoint uses decrypted DB secret for HMAC
#           signing when available — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_HeartbeatHmacSigning:
    """Verify the heartbeat endpoint continues to use the decrypted DB
    secret for HMAC signing when a valid encrypted secret is stored.

    **Validates: Requirements 3.3**
    """

    def test_heartbeat_function_decrypts_db_secret_in_cache_miss(self):
        """The heartbeat() function's cache-miss path decrypts
        cfg_row.heartbeat_secret using envelope_decrypt_str."""
        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        source = router_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "heartbeat":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # Verify the DB secret decryption path exists
                assert "heartbeat_secret" in func_source, (
                    "heartbeat() must reference heartbeat_secret for DB decryption"
                )
                assert "envelope_decrypt_str" in func_source or "_decrypt" in func_source, (
                    "heartbeat() must use envelope_decrypt_str to decrypt DB secret"
                )
                return

        pytest.fail("Could not find heartbeat() function in router.py")

    def test_heartbeat_function_uses_hmac_signing(self):
        """The heartbeat() function signs the payload with HMAC-SHA256."""
        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        source = router_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "heartbeat":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                assert "hmac_signature" in func_source, (
                    "heartbeat() must include hmac_signature in response"
                )
                assert "sha256" in func_source.lower(), (
                    "heartbeat() must use SHA256 for HMAC signing"
                )
                return

        pytest.fail("Could not find heartbeat() function in router.py")


# ═════════════════════════════════════════════════════════════════════
# Req 3.4: save_config encrypts and stores heartbeat_secret when
#           provided — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_SaveConfigHeartbeatSecret:
    """Verify save_config() continues to encrypt and store the
    heartbeat_secret when provided in the request.

    **Validates: Requirements 3.4**
    """

    def test_save_config_source_encrypts_heartbeat_secret_on_insert(self):
        """save_config() source code encrypts heartbeat_secret via
        envelope_encrypt in the insert branch."""
        service_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "service.py"
        source = service_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "save_config":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # Verify the insert branch encrypts heartbeat_secret
                assert "envelope_encrypt(config.heartbeat_secret)" in func_source, (
                    "save_config() insert branch must encrypt heartbeat_secret"
                )
                return

        pytest.fail("Could not find save_config() in service.py")

    @pytest.mark.asyncio
    async def test_save_config_encrypts_heartbeat_secret_on_update(self):
        """save_config() encrypts heartbeat_secret via envelope_encrypt
        when updating an existing config."""
        existing_cfg = _make_ha_config()
        db = _mock_db_session()
        _mock_execute_returns(db, existing_cfg)

        config = MagicMock()
        config.node_name = "test-node"
        config.role = "primary"
        config.peer_endpoint = "http://192.168.1.100:8999"
        config.auto_promote_enabled = False
        config.heartbeat_interval_seconds = 10
        config.failover_timeout_seconds = 90
        config.peer_db_host = None
        config.peer_db_port = None
        config.peer_db_name = None
        config.peer_db_user = None
        config.peer_db_password = None
        config.peer_db_sslmode = None
        config.heartbeat_secret = "updated-secret"
        config.local_lan_ip = None
        config.local_pg_port = None

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=existing_cfg),
            patch("app.modules.ha.service.envelope_encrypt") as mock_encrypt,
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.ha.service._get_heartbeat_secret_from_config", return_value=""),
            patch("app.modules.ha.service._heartbeat_service", None),
        ):
            mock_encrypt.return_value = b"encrypted-data"

            from app.modules.ha.service import HAService

            await HAService.save_config(db, config, uuid.uuid4())

            mock_encrypt.assert_any_call("updated-secret")


# ═════════════════════════════════════════════════════════════════════
# Req 3.5: save_config encrypts and stores peer_db_password and
#           persists all peer DB fields — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_SaveConfigPeerDbFields:
    """Verify save_config() continues to encrypt peer_db_password and
    persist all peer DB fields (host, port, name, user, sslmode).

    **Validates: Requirements 3.5**
    """

    def test_save_config_source_encrypts_peer_db_password_on_insert(self):
        """save_config() source code encrypts peer_db_password via
        envelope_encrypt in the insert branch."""
        service_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "service.py"
        source = service_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "save_config":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # Verify the insert branch encrypts peer_db_password
                assert "envelope_encrypt(config.peer_db_password)" in func_source, (
                    "save_config() insert branch must encrypt peer_db_password"
                )
                return

        pytest.fail("Could not find save_config() in service.py")

    @pytest.mark.asyncio
    async def test_save_config_stores_peer_db_fields_on_update(self):
        """save_config() updates peer DB fields when provided on update."""
        existing_cfg = _make_ha_config()
        db = _mock_db_session()
        _mock_execute_returns(db, existing_cfg)

        config = MagicMock()
        config.node_name = "test-node"
        config.role = "standby"
        config.peer_endpoint = "http://192.168.1.100:8999"
        config.auto_promote_enabled = False
        config.heartbeat_interval_seconds = 10
        config.failover_timeout_seconds = 90
        config.peer_db_host = "10.0.0.50"
        config.peer_db_port = 5433
        config.peer_db_name = "mydb"
        config.peer_db_user = "admin"
        config.peer_db_password = "new-pw"
        config.peer_db_sslmode = "verify-full"
        config.heartbeat_secret = None
        config.local_lan_ip = None
        config.local_pg_port = None

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=existing_cfg),
            patch("app.modules.ha.service.envelope_encrypt") as mock_encrypt,
            patch("app.modules.ha.service.set_node_role"),
            patch("app.modules.ha.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.ha.service._get_heartbeat_secret_from_config", return_value=""),
            patch("app.modules.ha.service._heartbeat_service", None),
        ):
            mock_encrypt.return_value = b"encrypted-new-pw"

            from app.modules.ha.service import HAService

            await HAService.save_config(db, config, uuid.uuid4())

            # Verify peer DB fields were set on the config object
            assert existing_cfg.peer_db_host == "10.0.0.50"
            assert existing_cfg.peer_db_port == 5433
            assert existing_cfg.peer_db_name == "mydb"
            assert existing_cfg.peer_db_user == "admin"
            assert existing_cfg.peer_db_sslmode == "verify-full"
            mock_encrypt.assert_any_call("new-pw")


# ═════════════════════════════════════════════════════════════════════
# Req 3.6: _detect_host_lan_ip() auto-detect chain works when no
#           override exists — unchanged by MOD-3 fix
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_DetectHostLanIp:
    """Verify _detect_host_lan_ip() continues its auto-detect chain
    (Docker Desktop → UDP socket → fallback) when no DB or env override.

    **Validates: Requirements 3.6**
    """

    def test_detect_host_lan_ip_uses_env_var_when_set(self):
        """_detect_host_lan_ip() returns HA_LOCAL_LAN_IP env var when set."""
        with patch.dict(os.environ, {"HA_LOCAL_LAN_IP": "10.0.0.99"}):
            from app.modules.ha.router import _detect_host_lan_ip

            result = _detect_host_lan_ip()

        assert result == "10.0.0.99", (
            f"Expected '10.0.0.99' from env var, got '{result}'"
        )

    def test_detect_host_lan_ip_fallback_chain_order(self):
        """_detect_host_lan_ip() has the correct fallback chain:
        env var → Docker Desktop → UDP socket → 127.0.0.1."""
        router_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "router.py"
        source = router_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_detect_host_lan_ip":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # Strip the docstring to only check the code body
                # Find the first non-docstring line after def
                lines = func_source.split("\n")
                code_lines = []
                in_docstring = False
                past_docstring = False
                for line in lines:
                    stripped = line.strip()
                    if not past_docstring:
                        if '"""' in stripped or "'''" in stripped:
                            # Count triple quotes to detect docstring boundaries
                            count = stripped.count('"""') + stripped.count("'''")
                            if count >= 2:
                                # Single-line docstring
                                past_docstring = True
                                continue
                            elif not in_docstring:
                                in_docstring = True
                                continue
                            else:
                                in_docstring = False
                                past_docstring = True
                                continue
                        if in_docstring:
                            continue
                        if stripped.startswith("def ") or stripped.startswith("import "):
                            past_docstring = True
                    if past_docstring:
                        code_lines.append(line)

                code_body = "\n".join(code_lines)

                # Verify the fallback chain order in the code body
                env_pos = code_body.find("HA_LOCAL_LAN_IP")
                docker_pos = code_body.find("host.docker.internal")
                udp_pos = code_body.find("8.8.8.8")
                fallback_pos = code_body.rfind("127.0.0.1")

                assert env_pos != -1, "Code body must reference HA_LOCAL_LAN_IP"
                assert docker_pos != -1, "Code body must reference host.docker.internal"
                assert udp_pos != -1, "Code body must reference 8.8.8.8 (UDP socket trick)"
                assert fallback_pos != -1, "Code body must have 127.0.0.1 fallback"

                assert env_pos < docker_pos < udp_pos < fallback_pos, (
                    "Fallback chain must be: env var → Docker Desktop → UDP socket → 127.0.0.1"
                )
                return

        pytest.fail("Could not find _detect_host_lan_ip() in router.py")

    def test_detect_host_lan_ip_returns_string(self):
        """_detect_host_lan_ip() always returns a non-empty string."""
        # Clear the env var to test auto-detect path
        env = {k: v for k, v in os.environ.items() if k != "HA_LOCAL_LAN_IP"}
        with patch.dict(os.environ, env, clear=True):
            from app.modules.ha.router import _detect_host_lan_ip

            result = _detect_host_lan_ip()

        assert isinstance(result, str), "Result should be a string"
        assert len(result) > 0, "Result should not be empty"


# ═════════════════════════════════════════════════════════════════════
# Req 3.7: _heartbeat_service.peer_role populated from heartbeat
#           responses — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_PeerRoleFromHeartbeat:
    """Verify _heartbeat_service.peer_role continues to be populated
    from heartbeat responses (BUG-HA-15 fix).

    **Validates: Requirements 3.7**
    """

    def test_ping_peer_stores_peer_role_from_response(self):
        """_ping_peer() source code stores peer role from response data
        into self.peer_role."""
        heartbeat_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "heartbeat.py"
        source = heartbeat_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_ping_peer":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # Verify peer_role assignment from response data
                assert "self.peer_role" in func_source, (
                    "_ping_peer() must store peer role in self.peer_role"
                )
                assert 'data.get("role"' in func_source, (
                    "_ping_peer() must read role from response data"
                )
                return

        pytest.fail("Could not find _ping_peer() in heartbeat.py")

    def test_heartbeat_service_initializes_peer_role_unknown(self):
        """HeartbeatService initializes peer_role to 'unknown'."""
        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://192.168.1.100:8999",
            interval=10,
            secret="test-secret",
            local_role="primary",
        )

        assert svc.peer_role == "unknown", (
            f"Initial peer_role should be 'unknown', got '{svc.peer_role}'"
        )


# ═════════════════════════════════════════════════════════════════════
# Req 3.8: get_cluster_status() uses _heartbeat_service.peer_role
#           for peer entry — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_ClusterStatusPeerRole:
    """Verify get_cluster_status() continues to use
    _heartbeat_service.peer_role for the peer entry.

    **Validates: Requirements 3.8**
    """

    @pytest.mark.asyncio
    async def test_get_cluster_status_uses_heartbeat_peer_role(self):
        """get_cluster_status() reads peer_role from _heartbeat_service."""
        db = _mock_db_session()
        cfg = _make_ha_config(role="primary")
        _mock_execute_returns(db, cfg)

        mock_hb = MagicMock()
        mock_hb.peer_role = "standby"
        mock_hb.get_peer_health.return_value = "healthy"
        mock_hb.get_history.return_value = []

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.modules.ha.service._heartbeat_service", mock_hb),
        ):
            from app.modules.ha.service import HAService

            result = await HAService.get_cluster_status(db)

        assert len(result) == 2, "Should return 2 entries (local + peer)"
        peer_entry = result[1]
        assert peer_entry.role == "standby", (
            f"Peer role should be 'standby' from heartbeat service, got '{peer_entry.role}'"
        )

    @pytest.mark.asyncio
    async def test_get_cluster_status_peer_role_unknown_when_no_heartbeat(self):
        """get_cluster_status() returns 'unknown' peer role when no heartbeat service."""
        db = _mock_db_session()
        cfg = _make_ha_config(role="primary")
        _mock_execute_returns(db, cfg)

        with (
            patch("app.modules.ha.service._load_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.modules.ha.service._heartbeat_service", None),
        ):
            from app.modules.ha.service import HAService

            result = await HAService.get_cluster_status(db)

        assert len(result) == 2
        peer_entry = result[1]
        assert peer_entry.role == "unknown", (
            f"Peer role should be 'unknown' when no heartbeat service, got '{peer_entry.role}'"
        )


# ═════════════════════════════════════════════════════════════════════
# Req 3.9: All existing CONFIRM gates (promote, demote, resync,
#           demote-and-sync, standby init-replication) require CONFIRM
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_ExistingConfirmGates:
    """Verify all existing CONFIRM gates continue to require CONFIRM
    — unchanged by MOD-5 fix.

    **Validates: Requirements 3.9**
    """

    def test_needsconfirmtext_includes_promote(self):
        """The needsConfirmText list includes 'promote'."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        match = re.search(
            r"needsConfirmText\s*=\s*modalAction\s*&&\s*\(\s*\[([^\]]+)\]\.includes",
            source,
        )
        assert match is not None, "Could not find needsConfirmText definition"
        confirm_list_str = match.group(1)

        assert "'promote'" in confirm_list_str, (
            f"'promote' not in needsConfirmText list: [{confirm_list_str}]"
        )

    def test_needsconfirmtext_includes_demote(self):
        """The needsConfirmText list includes 'demote'."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        match = re.search(
            r"needsConfirmText\s*=\s*modalAction\s*&&\s*\(\s*\[([^\]]+)\]\.includes",
            source,
        )
        assert match is not None
        confirm_list_str = match.group(1)

        assert "'demote'" in confirm_list_str, (
            f"'demote' not in needsConfirmText list: [{confirm_list_str}]"
        )

    def test_needsconfirmtext_includes_resync(self):
        """The needsConfirmText list includes 'resync'."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        match = re.search(
            r"needsConfirmText\s*=\s*modalAction\s*&&\s*\(\s*\[([^\]]+)\]\.includes",
            source,
        )
        assert match is not None
        confirm_list_str = match.group(1)

        assert "'resync'" in confirm_list_str, (
            f"'resync' not in needsConfirmText list: [{confirm_list_str}]"
        )

    def test_needsconfirmtext_includes_demote_and_sync(self):
        """The needsConfirmText list includes 'demote-and-sync'."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        match = re.search(
            r"needsConfirmText\s*=\s*modalAction\s*&&\s*\(\s*\[([^\]]+)\]\.includes",
            source,
        )
        assert match is not None
        confirm_list_str = match.group(1)

        assert "'demote-and-sync'" in confirm_list_str, (
            f"'demote-and-sync' not in needsConfirmText list: [{confirm_list_str}]"
        )

    def test_needsconfirmtext_includes_standby_init_replication(self):
        """The needsConfirmText logic includes standby init-replication
        via the isStandbyInit condition."""
        tsx_path = _PROJECT_ROOT / "frontend" / "src" / "pages" / "admin" / "HAReplication.tsx"
        source = tsx_path.read_text()

        # The isStandbyInit condition: modalAction === 'init-replication' && config?.role === 'standby'
        assert "isStandbyInit" in source, "isStandbyInit variable must exist"

        # Verify isStandbyInit is used in needsConfirmText
        # The actual code: needsConfirmText = modalAction && ([...].includes(modalAction) || isStandbyInit)
        match = re.search(
            r"needsConfirmText\s*=.*isStandbyInit",
            source,
        )
        assert match is not None, (
            "needsConfirmText must reference isStandbyInit for standby init-replication"
        )


# ═════════════════════════════════════════════════════════════════════
# Req 3.10: _auto_promote_failed_permanently is NOT reset on peer
#            recovery — only _auto_promote_attempted is reset
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_AutoPromoteFailedPermanently:
    """Verify _auto_promote_failed_permanently is NOT reset on peer
    recovery. Only _auto_promote_attempted should be reset.

    **Validates: Requirements 3.10**
    """

    def test_ping_loop_does_not_reset_auto_promote_failed_permanently(self):
        """The _ping_loop recovery branch does NOT reset
        _auto_promote_failed_permanently — it is intentionally permanent."""
        heartbeat_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "heartbeat.py"
        source = heartbeat_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_ping_loop":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                # Find the recovery branch: previous_health == "unreachable" and self.peer_health != "unreachable"
                # Verify it does NOT contain _auto_promote_failed_permanently = False
                recovery_pattern = r'previous_health\s*==\s*"unreachable"\s*and\s*self\.peer_health\s*!=\s*"unreachable"'
                recovery_match = re.search(recovery_pattern, func_source)
                assert recovery_match is not None, (
                    "Could not find recovery branch in _ping_loop"
                )

                # Get the code block after the recovery condition
                # Look for _auto_promote_failed_permanently = False in the recovery block
                # It should NOT be there
                recovery_start = recovery_match.start()
                # Get the next ~500 chars after the recovery condition to check the block
                recovery_block = func_source[recovery_start:recovery_start + 500]

                assert "_auto_promote_failed_permanently = False" not in recovery_block, (
                    "_auto_promote_failed_permanently should NOT be reset in recovery branch"
                )
                return

        pytest.fail("Could not find _ping_loop() in heartbeat.py")

    def test_auto_promote_failed_permanently_set_after_two_failures(self):
        """_execute_auto_promote sets _auto_promote_failed_permanently = True
        after two failed attempts — this behavior must be preserved."""
        heartbeat_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "heartbeat.py"
        source = heartbeat_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_auto_promote":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                assert "_auto_promote_failed_permanently = True" in func_source, (
                    "_execute_auto_promote must set _auto_promote_failed_permanently = True "
                    "after two failed attempts"
                )
                return

        pytest.fail("Could not find _execute_auto_promote() in heartbeat.py")

    def test_heartbeat_service_initializes_failed_permanently_false(self):
        """HeartbeatService initializes _auto_promote_failed_permanently to False."""
        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://192.168.1.100:8999",
            interval=10,
            secret="test-secret",
            local_role="standby",
        )

        assert svc._auto_promote_failed_permanently is False, (
            "_auto_promote_failed_permanently should initialize to False"
        )


# ═════════════════════════════════════════════════════════════════════
# Req 3.11: .env.pi-standby already has blank HA_HEARTBEAT_SECRET=
#            and HA_PEER_DB_URL= — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_EnvPiStandbyBlankValues:
    """Verify .env.pi-standby already has blank HA_HEARTBEAT_SECRET=
    and HA_PEER_DB_URL= values — these must remain unchanged.

    **Validates: Requirements 3.11**
    """

    def _find_env_pi_standby(self) -> Path:
        """Locate .env.pi-standby — may be at project root or workspace root."""
        # Inside Docker, _PROJECT_ROOT is /app but .env.pi-standby may not be copied
        # Try the project root first, then common workspace locations
        candidates = [
            _PROJECT_ROOT / ".env.pi-standby",
            Path("/workspace/.env.pi-standby"),
        ]
        for p in candidates:
            if p.exists():
                return p
        pytest.skip(".env.pi-standby not found in container — file is host-only")

    def test_env_pi_standby_has_blank_heartbeat_secret(self):
        """.env.pi-standby has HA_HEARTBEAT_SECRET= (blank value)."""
        env_path = self._find_env_pi_standby()
        content = env_path.read_text()

        # Find the HA_HEARTBEAT_SECRET line
        match = re.search(r"^HA_HEARTBEAT_SECRET=(.*)$", content, re.MULTILINE)
        assert match is not None, "HA_HEARTBEAT_SECRET line not found in .env.pi-standby"

        value = match.group(1).strip()
        assert value == "", (
            f"HA_HEARTBEAT_SECRET should be blank in .env.pi-standby, got '{value}'"
        )

    def test_env_pi_standby_has_blank_peer_db_url(self):
        """.env.pi-standby has HA_PEER_DB_URL= (blank value)."""
        env_path = self._find_env_pi_standby()
        content = env_path.read_text()

        # Find the HA_PEER_DB_URL line
        match = re.search(r"^HA_PEER_DB_URL=(.*)$", content, re.MULTILINE)
        assert match is not None, "HA_PEER_DB_URL line not found in .env.pi-standby"

        value = match.group(1).strip()
        assert value == "", (
            f"HA_PEER_DB_URL should be blank in .env.pi-standby, got '{value}'"
        )


# ═════════════════════════════════════════════════════════════════════
# Req 3.12: HAConfigRequest peer DB fields continue to be processed
#            and stored — unchanged
# ═════════════════════════════════════════════════════════════════════


class TestPreservation_HAConfigRequestPeerDbFields:
    """Verify HAConfigRequest schema continues to accept and process
    all peer DB fields (host, port, name, user, password, sslmode).

    **Validates: Requirements 3.12**
    """

    def test_haconfigrequest_has_peer_db_host_field(self):
        """HAConfigRequest has peer_db_host field."""
        from app.modules.ha.schemas import HAConfigRequest

        assert "peer_db_host" in HAConfigRequest.model_fields, (
            "HAConfigRequest must have peer_db_host field"
        )

    def test_haconfigrequest_has_peer_db_port_field(self):
        """HAConfigRequest has peer_db_port field."""
        from app.modules.ha.schemas import HAConfigRequest

        assert "peer_db_port" in HAConfigRequest.model_fields, (
            "HAConfigRequest must have peer_db_port field"
        )

    def test_haconfigrequest_has_peer_db_name_field(self):
        """HAConfigRequest has peer_db_name field."""
        from app.modules.ha.schemas import HAConfigRequest

        assert "peer_db_name" in HAConfigRequest.model_fields, (
            "HAConfigRequest must have peer_db_name field"
        )

    def test_haconfigrequest_has_peer_db_user_field(self):
        """HAConfigRequest has peer_db_user field."""
        from app.modules.ha.schemas import HAConfigRequest

        assert "peer_db_user" in HAConfigRequest.model_fields, (
            "HAConfigRequest must have peer_db_user field"
        )

    def test_haconfigrequest_has_peer_db_password_field(self):
        """HAConfigRequest has peer_db_password field."""
        from app.modules.ha.schemas import HAConfigRequest

        assert "peer_db_password" in HAConfigRequest.model_fields, (
            "HAConfigRequest must have peer_db_password field"
        )

    def test_haconfigrequest_has_peer_db_sslmode_field(self):
        """HAConfigRequest has peer_db_sslmode field."""
        from app.modules.ha.schemas import HAConfigRequest

        assert "peer_db_sslmode" in HAConfigRequest.model_fields, (
            "HAConfigRequest must have peer_db_sslmode field"
        )

    def test_haconfigrequest_peer_db_fields_are_optional(self):
        """All peer DB fields in HAConfigRequest are optional (have defaults)."""
        from app.modules.ha.schemas import HAConfigRequest

        peer_fields = [
            "peer_db_host", "peer_db_port", "peer_db_name",
            "peer_db_user", "peer_db_password", "peer_db_sslmode",
        ]

        for field_name in peer_fields:
            field = HAConfigRequest.model_fields[field_name]
            assert field.default is not None or field.is_required() is False, (
                f"Field {field_name} should be optional"
            )

    def test_save_config_source_handles_peer_db_host(self):
        """save_config() source code handles peer_db_host in both
        insert and update branches."""
        service_path = _PROJECT_ROOT / "app" / "modules" / "ha" / "service.py"
        source = service_path.read_text()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "save_config":
                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    func_source = source

                assert "peer_db_host" in func_source, (
                    "save_config() must handle peer_db_host"
                )
                assert "peer_db_port" in func_source, (
                    "save_config() must handle peer_db_port"
                )
                assert "peer_db_name" in func_source, (
                    "save_config() must handle peer_db_name"
                )
                assert "peer_db_user" in func_source, (
                    "save_config() must handle peer_db_user"
                )
                assert "peer_db_password" in func_source, (
                    "save_config() must handle peer_db_password"
                )
                assert "peer_db_sslmode" in func_source, (
                    "save_config() must handle peer_db_sslmode"
                )
                return

        pytest.fail("Could not find save_config() in service.py")
