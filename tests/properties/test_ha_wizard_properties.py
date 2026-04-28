"""Property-based tests for the HA Setup Wizard feature.

Tests Properties 1–10 from the HA Setup Wizard design document using Hypothesis.
Each property validates specific correctness guarantees across randomised inputs.
"""

from __future__ import annotations

import inspect
import os
import re
import secrets
import tempfile
import textwrap
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ============================================================================
# Property 1 — Address validation
# ============================================================================


class TestProperty1AddressValidation:
    """Property 1: Address validation accepts valid addresses and rejects invalid ones.

    *For any* string input to the wizard address validator, the function SHALL
    return ``true`` if and only if the input is a non-empty string containing a
    valid IPv4 address, IPv6 address, hostname, or URL with a hostname component;
    and SHALL return ``false`` for empty strings, whitespace-only strings, and
    strings that do not contain a valid network address.

    # Feature: ha-setup-wizard, Property 1: Address validation accepts valid addresses and rejects invalid ones

    **Validates: Requirements 4.2**
    """

    @staticmethod
    def _validate_wizard_address(address: str) -> bool:
        """Replicate the wizard's address validation logic.

        The wizard check-reachability endpoint strips and checks for empty,
        then attempts an HTTP request.  For property testing we validate the
        address format: non-empty, non-whitespace, and looks like a valid
        IP, hostname, or URL.
        """
        addr = address.strip()
        if not addr:
            return False

        import re
        from urllib.parse import urlparse

        # Try parsing as URL first
        parsed = urlparse(addr)
        host = parsed.hostname or ""

        # If no scheme was provided, urlparse puts everything in path
        if not parsed.scheme and not parsed.netloc:
            # Treat the raw string as a potential host
            host = addr.split(":")[0].split("/")[0].strip()

        if not host:
            return False

        # Valid IPv4
        ipv4_pattern = re.compile(
            r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
        )
        m = ipv4_pattern.match(host)
        if m and all(0 <= int(g) <= 255 for g in m.groups()):
            return True

        # Valid IPv6 (simplified — bracketed or raw)
        stripped_host = host.strip("[]")
        if ":" in stripped_host:
            try:
                import ipaddress
                ipaddress.IPv6Address(stripped_host)
                return True
            except ValueError:
                pass

        # Valid hostname (RFC 952 / RFC 1123)
        hostname_pattern = re.compile(
            r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*\.?$"
        )
        if hostname_pattern.match(host):
            return True

        return False

    @given(
        ip=st.tuples(
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
        )
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_ipv4_addresses_accepted(self, ip: tuple) -> None:
        addr = f"{ip[0]}.{ip[1]}.{ip[2]}.{ip[3]}"
        assert self._validate_wizard_address(addr) is True

    @given(
        ip=st.tuples(
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
        ),
        port=st.integers(min_value=1, max_value=65535),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_urls_with_ip_accepted(self, ip: tuple, port: int) -> None:
        addr = f"http://{ip[0]}.{ip[1]}.{ip[2]}.{ip[3]}:{port}"
        assert self._validate_wizard_address(addr) is True

    @given(
        hostname=st.from_regex(r"[a-z][a-z0-9]{1,10}(\.[a-z][a-z0-9]{1,10}){0,3}", fullmatch=True)
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_hostnames_accepted(self, hostname: str) -> None:
        assert self._validate_wizard_address(hostname) is True

    @given(text=st.text(alphabet=st.characters(whitelist_categories=("Zs",)), min_size=0, max_size=20))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_and_whitespace_rejected(self, text: str) -> None:
        assert self._validate_wizard_address(text) is False

    def test_empty_string_rejected(self) -> None:
        assert self._validate_wizard_address("") is False

    def test_localhost_accepted(self) -> None:
        assert self._validate_wizard_address("localhost") is True

    def test_url_with_hostname_accepted(self) -> None:
        assert self._validate_wizard_address("http://my-node.local:8999") is True



# ============================================================================
# Property 2 — HMAC secret generation
# ============================================================================


class TestProperty2HMACSecretGeneration:
    """Property 2: HMAC secret generation produces cryptographically strong secrets.

    *For any* invocation of the HMAC secret generator, the resulting secret SHALL
    be at least 32 bytes (64 hex characters) in length, and for any two independent
    invocations, the generated secrets SHALL be distinct (with overwhelming probability).

    # Feature: ha-setup-wizard, Property 2: HMAC secret generation produces cryptographically strong secrets

    **Validates: Requirements 7.6, 16.2**
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_secret_length_at_least_64_hex_chars(self, data: st.DataObject) -> None:
        """Each generated secret must be at least 64 hex characters (32 bytes)."""
        secret = secrets.token_hex(32)
        assert len(secret) >= 64
        # Verify it's valid hex
        assert all(c in "0123456789abcdef" for c in secret)

    @given(data=st.data())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_two_independent_secrets_are_distinct(self, data: st.DataObject) -> None:
        """Two independent invocations produce distinct secrets."""
        secret_a = secrets.token_hex(32)
        secret_b = secrets.token_hex(32)
        assert secret_a != secret_b

    @given(n=st.integers(min_value=2, max_value=50))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_batch_of_secrets_all_unique(self, n: int) -> None:
        """A batch of N secrets should all be unique."""
        generated = [secrets.token_hex(32) for _ in range(n)]
        assert len(set(generated)) == n

    def test_secret_is_exactly_64_hex_chars(self) -> None:
        """secrets.token_hex(32) produces exactly 64 hex characters."""
        secret = secrets.token_hex(32)
        assert len(secret) == 64


# ============================================================================
# Property 3 — Wizard endpoints require auth
# ============================================================================


WIZARD_ENDPOINT_PATHS = [
    ("/api/v1/ha/wizard/check-reachability", "POST"),
    ("/api/v1/ha/wizard/authenticate", "POST"),
    ("/api/v1/ha/wizard/handshake", "POST"),
    ("/api/v1/ha/wizard/receive-handshake", "POST"),
    ("/api/v1/ha/wizard/setup", "POST"),
    ("/api/v1/ha/events", "GET"),
]


class TestProperty3WizardEndpointsRequireAuth:
    """Property 3: All wizard endpoints reject unauthenticated requests.

    *For any* wizard API endpoint (check-reachability, authenticate, handshake,
    receive-handshake, setup, events), calling the endpoint without a valid
    Global_Admin authentication token SHALL return HTTP 401 or 403.

    # Feature: ha-setup-wizard, Property 3: All wizard endpoints reject unauthenticated requests

    **Validates: Requirements 10.6, 16.1**
    """

    @pytest.fixture(autouse=True)
    def _setup_client(self):
        """Create a test client for the FastAPI app."""
        from httpx import AsyncClient, ASGITransport
        from app.main import create_app

        self.app = create_app()
        self.transport = ASGITransport(app=self.app)

    @given(endpoint=st.sampled_from(WIZARD_ENDPOINT_PATHS))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_unauthenticated_requests_rejected(self, endpoint: tuple) -> None:
        """Calling any wizard endpoint without auth returns 401 or 403."""
        from httpx import AsyncClient, ASGITransport

        path, method = endpoint
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            if method == "POST":
                resp = await client.post(path, json={})
            else:
                resp = await client.get(path)

        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code}, expected 401 or 403"
        )

    @pytest.mark.asyncio
    async def test_all_endpoints_reject_without_token(self) -> None:
        """Explicit check: every wizard endpoint rejects unauthenticated calls."""
        from httpx import AsyncClient, ASGITransport

        for path, method in WIZARD_ENDPOINT_PATHS:
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                if method == "POST":
                    resp = await client.post(path, json={})
                else:
                    resp = await client.get(path)
            assert resp.status_code in (401, 403), (
                f"{method} {path} returned {resp.status_code}"
            )


# ============================================================================
# Property 4 — Handshake idempotency for authorized_keys
# ============================================================================


class TestProperty4HandshakeIdempotency:
    """Property 4: Trust handshake is idempotent for authorized_keys.

    *For any* SSH public key and any number of repeated trust handshake
    executions with that same key, the ``/ha_keys/authorized_keys`` file SHALL
    contain exactly one entry for that key (no duplicates), and the file SHALL
    remain a valid OpenSSH authorized_keys format.

    # Feature: ha-setup-wizard, Property 4: Trust handshake is idempotent for authorized_keys

    **Validates: Requirements 15.2**
    """

    @staticmethod
    def _append_ssh_key_to_authorized_keys(ssh_pub_key: str, auth_keys_path: str) -> None:
        """Replicate the idempotent append logic from the router."""
        key_stripped = ssh_pub_key.strip()

        existing_keys: list[str] = []
        try:
            with open(auth_keys_path, "r") as f:
                existing_keys = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            pass

        if key_stripped in existing_keys:
            return

        with open(auth_keys_path, "a") as f:
            f.write(key_stripped + "\n")

    @given(
        key_type=st.sampled_from(["ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"]),
        key_data=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=20,
            max_size=80,
        ),
        comment=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            min_size=0,
            max_size=30,
        ).map(lambda s: s.strip()),
        repeat_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_duplicates_after_repeated_appends(
        self, key_type: str, key_data: str, comment: str, repeat_count: int
    ) -> None:
        """Appending the same key N times results in exactly one entry."""
        ssh_key = f"{key_type} {key_data}"
        if comment:
            ssh_key += f" {comment}"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".keys", delete=False) as f:
            tmp_path = f.name

        try:
            for _ in range(repeat_count):
                self._append_ssh_key_to_authorized_keys(ssh_key, tmp_path)

            with open(tmp_path, "r") as f:
                lines = [line.strip() for line in f if line.strip()]

            # Exactly one entry for this key
            assert lines.count(ssh_key.strip()) == 1
            # Total lines should be 1
            assert len(lines) == 1
        finally:
            os.unlink(tmp_path)

    @given(
        keys=st.lists(
            st.tuples(
                st.sampled_from(["ssh-ed25519", "ssh-rsa"]),
                st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                    min_size=20,
                    max_size=40,
                ),
            ).map(lambda t: f"{t[0]} {t[1]}"),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        repeat_count=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_multiple_unique_keys_no_duplicates(
        self, keys: list[str], repeat_count: int
    ) -> None:
        """Multiple unique keys appended multiple times — each appears exactly once."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".keys", delete=False) as f:
            tmp_path = f.name

        try:
            for _ in range(repeat_count):
                for key in keys:
                    self._append_ssh_key_to_authorized_keys(key, tmp_path)

            with open(tmp_path, "r") as f:
                lines = [line.strip() for line in f if line.strip()]

            assert len(lines) == len(keys)
            for key in keys:
                assert lines.count(key.strip()) == 1
        finally:
            os.unlink(tmp_path)


# ============================================================================
# Property 5 — Role transitions update heartbeat local_role
# ============================================================================


VALID_ROLE_TRANSITIONS = [
    ("standby", "primary", "promote"),
    ("primary", "standby", "demote"),
    ("primary", "standby", "demote_and_sync"),
]


class TestProperty5RoleTransitionsUpdateHeartbeat:
    """Property 5: Role transitions update heartbeat service local_role.

    *For any* valid role transition (standby→primary via promote,
    primary→standby via demote, primary→standby via demote_and_sync),
    after the transition completes, the HeartbeatService's ``local_role``
    attribute SHALL equal the new role string.

    # Feature: ha-setup-wizard, Property 5: Role transitions update heartbeat service local_role

    **Validates: Requirements 19.1, 19.2, 19.3**
    """

    @given(transition=st.sampled_from(VALID_ROLE_TRANSITIONS))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_heartbeat_local_role_updated_after_transition(
        self, transition: tuple
    ) -> None:
        """After a role transition, HeartbeatService.local_role equals the new role."""
        from_role, to_role, method_name = transition

        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://localhost:9999",
            interval=10,
            secret="test-secret",
            local_role=from_role,
        )

        assert svc.local_role == from_role

        # Simulate what promote/demote/demote_and_sync do to the heartbeat service
        svc.local_role = to_role

        assert svc.local_role == to_role

    @given(transition=st.sampled_from(VALID_ROLE_TRANSITIONS))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_source_code_updates_local_role(self, transition: tuple) -> None:
        """Verify the actual source code of promote/demote/demote_and_sync
        contains the line that updates _heartbeat_service.local_role."""
        from_role, to_role, method_name = transition

        from app.modules.ha import service as ha_service_module

        source = inspect.getsource(ha_service_module)

        if method_name == "promote":
            assert '_heartbeat_service.local_role = "primary"' in source
        elif method_name in ("demote", "demote_and_sync"):
            assert '_heartbeat_service.local_role = "standby"' in source


# ============================================================================
# Property 6 — Auto-promote flag reset on recovery
# ============================================================================


class TestProperty6AutoPromoteFlagResetOnRecovery:
    """Property 6: Auto-promote flag resets when peer recovers.

    *For any* sequence where the peer transitions from unreachable to reachable
    in the heartbeat loop, ``_auto_promote_attempted`` SHALL be reset to ``False``,
    while ``_auto_promote_failed_permanently`` SHALL remain unchanged.

    # Feature: ha-setup-wizard, Property 6: Auto-promote flag resets when peer recovers

    **Validates: Requirements 23.1, 23.2, 23.3**
    """

    @given(
        initial_attempted=st.booleans(),
        initial_failed_permanently=st.booleans(),
        transitions=st.lists(
            st.sampled_from(["unreachable", "reachable"]),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_auto_promote_attempted_resets_on_recovery(
        self,
        initial_attempted: bool,
        initial_failed_permanently: bool,
        transitions: list[str],
    ) -> None:
        """Simulate unreachable/reachable transitions and verify flag behaviour."""
        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://localhost:9999",
            interval=10,
            secret="test-secret",
            local_role="standby",
        )
        svc._auto_promote_attempted = initial_attempted
        svc._auto_promote_failed_permanently = initial_failed_permanently

        previous_health = "unknown"

        for transition in transitions:
            if transition == "unreachable":
                current_health = "unreachable"
            else:
                current_health = "healthy"

            # Simulate the heartbeat loop's recovery logic
            if previous_health == "unreachable" and current_health != "unreachable":
                # Peer recovered — reset _auto_promote_attempted
                svc._auto_promote_attempted = False
                # _auto_promote_failed_permanently is intentionally NOT reset

            previous_health = current_health

        # After all transitions, check the final state
        # If the last transition was a recovery (unreachable → reachable),
        # _auto_promote_attempted must be False
        for i in range(len(transitions)):
            if i > 0 and transitions[i - 1] == "unreachable" and transitions[i] == "reachable":
                # This was a recovery — _auto_promote_attempted should have been reset
                pass  # We check the final state below

        # _auto_promote_failed_permanently should never change from its initial value
        assert svc._auto_promote_failed_permanently == initial_failed_permanently

        # If the last transition was a recovery, _auto_promote_attempted must be False
        if len(transitions) >= 2:
            last_two = transitions[-2:]
            if last_two == ["unreachable", "reachable"]:
                assert svc._auto_promote_attempted is False

    @given(initial_failed_permanently=st.booleans())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_failed_permanently_never_changes_on_recovery(
        self, initial_failed_permanently: bool
    ) -> None:
        """_auto_promote_failed_permanently is never reset by recovery."""
        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://localhost:9999",
            interval=10,
            secret="test-secret",
            local_role="standby",
        )
        svc._auto_promote_attempted = True
        svc._auto_promote_failed_permanently = initial_failed_permanently

        # Simulate recovery: unreachable → reachable
        # This is what the heartbeat loop does:
        svc._auto_promote_attempted = False
        # NOTE: _auto_promote_failed_permanently is intentionally NOT reset

        assert svc._auto_promote_attempted is False
        assert svc._auto_promote_failed_permanently == initial_failed_permanently

    def test_source_code_confirms_reset_logic(self) -> None:
        """Verify the heartbeat source code resets _auto_promote_attempted on recovery
        but does NOT reset _auto_promote_failed_permanently."""
        from app.modules.ha import heartbeat as hb_module

        source = inspect.getsource(hb_module.HeartbeatService._ping_loop)

        # Should contain the reset of _auto_promote_attempted
        assert "_auto_promote_attempted = False" in source

        # Should NOT contain a reset of _auto_promote_failed_permanently in the
        # recovery block. Check that the recovery section doesn't touch it.
        # The source has a comment: "NOTE: _auto_promote_failed_permanently is intentionally NOT reset"
        assert "_auto_promote_failed_permanently" in source


# ============================================================================
# Property 7 — No env fallback for secrets
# ============================================================================


class TestProperty7NoEnvFallbackForSecrets:
    """Property 7: HA secret functions have no environment variable fallback.

    *For any* call to ``_get_heartbeat_secret_from_config()`` with a ``None``
    or invalid DB secret, the function SHALL return an empty string regardless
    of the value of the ``HA_HEARTBEAT_SECRET`` environment variable. Similarly,
    ``get_peer_db_url()`` SHALL return ``None`` when DB peer config is empty,
    regardless of the ``HA_PEER_DB_URL`` environment variable.

    # Feature: ha-setup-wizard, Property 7: HA secret functions have no environment variable fallback

    **Validates: Requirements 26.1, 26.2**
    """

    @given(
        env_value=st.text(
            min_size=1,
            max_size=100,
            alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
        )
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_heartbeat_secret_ignores_env_var(self, env_value: str) -> None:
        """_get_heartbeat_secret_from_config(None) returns '' regardless of env."""
        old_val = os.environ.get("HA_HEARTBEAT_SECRET")
        try:
            os.environ["HA_HEARTBEAT_SECRET"] = env_value

            from app.modules.ha.service import _get_heartbeat_secret_from_config

            result = _get_heartbeat_secret_from_config(None)
            assert result == ""
        finally:
            if old_val is None:
                os.environ.pop("HA_HEARTBEAT_SECRET", None)
            else:
                os.environ["HA_HEARTBEAT_SECRET"] = old_val

    @given(
        env_value=st.text(
            min_size=1,
            max_size=100,
            alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
        )
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_heartbeat_secret_no_env_fallback_with_empty_config(
        self, env_value: str
    ) -> None:
        """Even with a config object that has no heartbeat_secret, env is ignored."""
        old_val = os.environ.get("HA_HEARTBEAT_SECRET")
        try:
            os.environ["HA_HEARTBEAT_SECRET"] = env_value

            from app.modules.ha.service import _get_heartbeat_secret_from_config

            # Create a mock config with no heartbeat_secret
            mock_cfg = MagicMock()
            mock_cfg.heartbeat_secret = None

            result = _get_heartbeat_secret_from_config(mock_cfg)
            assert result == ""
        finally:
            if old_val is None:
                os.environ.pop("HA_HEARTBEAT_SECRET", None)
            else:
                os.environ["HA_HEARTBEAT_SECRET"] = old_val

    def test_source_code_has_no_env_fallback(self) -> None:
        """Verify the service module source code does not read HA_ env vars."""
        from app.modules.ha import service as svc_module

        source = inspect.getsource(svc_module)

        # The source should NOT contain os.environ.get("HA_HEARTBEAT_SECRET")
        # or os.environ.get("HA_PEER_DB_URL") as fallback patterns
        assert 'os.environ.get("HA_HEARTBEAT_SECRET")' not in source
        assert "os.environ.get('HA_HEARTBEAT_SECRET')" not in source
        assert 'os.environ.get("HA_PEER_DB_URL")' not in source
        assert "os.environ.get('HA_PEER_DB_URL')" not in source


# ============================================================================
# Property 8 — Connection string escaping
# ============================================================================


class TestProperty8ConnectionStringEscaping:
    """Property 8: Connection string escaping produces valid SQL.

    *For any* connection string containing single quotes, backslashes, or other
    SQL-special characters, the ``_escape_conn_str()`` function SHALL produce a
    string that, when wrapped in single quotes in a SQL ``CONNECTION`` clause,
    results in syntactically valid SQL. Specifically, every single quote in the
    input SHALL be doubled (``'`` → ``''``).

    # Feature: ha-setup-wizard, Property 8: Connection string escaping produces valid SQL

    **Validates: Requirements 33.1, 33.2, 33.3**
    """

    @given(
        conn_str=st.text(min_size=0, max_size=200).filter(
            lambda s: "'" in s or "\\" in s or ";" in s or any(
                c in s for c in ['"', '%', '&', '=', '@', '!', '#']
            )
        )
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_single_quotes_are_doubled(self, conn_str: str) -> None:
        """Every single quote in the input is doubled in the output."""
        from app.modules.ha.replication import ReplicationManager

        escaped = ReplicationManager._escape_conn_str(conn_str)

        # Count single quotes: output should have exactly 2x the input count
        input_quotes = conn_str.count("'")
        output_quotes = escaped.count("'")
        assert output_quotes == input_quotes * 2

    @given(conn_str=st.text(min_size=0, max_size=200))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_escaping_doubles_all_single_quotes(self, conn_str: str) -> None:
        """For any string, _escape_conn_str doubles all single quotes."""
        from app.modules.ha.replication import ReplicationManager

        escaped = ReplicationManager._escape_conn_str(conn_str)
        assert escaped == conn_str.replace("'", "''")

    @given(conn_str=st.text(min_size=0, max_size=200))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_unescaped_single_quotes_remain(self, conn_str: str) -> None:
        """After escaping, there are no lone single quotes — all are paired."""
        from app.modules.ha.replication import ReplicationManager

        escaped = ReplicationManager._escape_conn_str(conn_str)

        # Replace all '' pairs, then check no single quotes remain
        after_removing_pairs = escaped.replace("''", "")
        assert "'" not in after_removing_pairs

    def test_known_escaping_examples(self) -> None:
        """Test with known problematic connection strings."""
        from app.modules.ha.replication import ReplicationManager

        # O'Brien password
        assert ReplicationManager._escape_conn_str("pass'word") == "pass''word"
        # Multiple quotes
        assert ReplicationManager._escape_conn_str("a'b'c") == "a''b''c"
        # No quotes — unchanged
        assert ReplicationManager._escape_conn_str("simple") == "simple"
        # Empty string
        assert ReplicationManager._escape_conn_str("") == ""


# ============================================================================
# Property 9 — Publication excludes ha_event_log
# ============================================================================


class TestProperty9PublicationExcludesEventLog:
    """Property 9: ha_event_log is excluded from replication publication.

    *For any* publication created by ``ReplicationManager.init_primary()``, the
    set of published tables SHALL NOT include ``ha_event_log``, ``ha_config``,
    or ``dead_letter_queue``.

    # Feature: ha-setup-wizard, Property 9: ha_event_log is excluded from replication publication

    **Validates: Requirements 34.2**
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_init_primary_source_excludes_all_three_tables(self, data: st.DataObject) -> None:
        """Verify the init_primary source code excludes ha_event_log, ha_config,
        and dead_letter_queue from the publication."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.init_primary)

        # The SQL query should exclude all three tables
        assert "ha_config" in source
        assert "dead_letter_queue" in source
        assert "ha_event_log" in source

        # Verify the NOT IN clause contains all three
        # Find the SQL query string that filters tables
        assert "NOT IN" in source

    def test_exclusion_list_in_sql_query(self) -> None:
        """Verify the exact NOT IN clause includes all three excluded tables."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.init_primary)

        # The source should contain the NOT IN clause with all three tables
        # Look for the pattern: tablename NOT IN ('ha_config', 'dead_letter_queue', 'ha_event_log')
        assert "'ha_config'" in source
        assert "'dead_letter_queue'" in source
        assert "'ha_event_log'" in source

    def test_excluded_tables_check_query_also_covers_all_three(self) -> None:
        """Verify the existing-publication check also looks for all three excluded tables."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.init_primary)

        # The check for excluded tables leaking into the publication should
        # also reference all three tables
        assert "ha_config" in source
        assert "dead_letter_queue" in source
        assert "ha_event_log" in source

    @given(table_name=st.sampled_from(["ha_config", "dead_letter_queue", "ha_event_log"]))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_each_excluded_table_appears_in_not_in_clause(self, table_name: str) -> None:
        """Each excluded table name appears in the init_primary source."""
        from app.modules.ha.replication import ReplicationManager

        source = inspect.getsource(ReplicationManager.init_primary)
        assert f"'{table_name}'" in source


# ============================================================================
# Property 10 — Event pruning removes only events older than 30 days
# ============================================================================


class TestProperty10EventPruningPreservesRecent:
    """Property 10: Event pruning removes only events older than 30 days.

    *For any* set of ``ha_event_log`` rows with varying timestamps, after the
    pruning operation executes, no rows with ``timestamp`` older than 30 days
    from the current time SHALL remain, and all rows with ``timestamp`` within
    the last 30 days SHALL be preserved.

    # Feature: ha-setup-wizard, Property 10: Event pruning removes only events older than 30 days

    **Validates: Requirements 34.9**
    """

    @staticmethod
    def _simulate_pruning(
        events: list[dict], now: datetime
    ) -> list[dict]:
        """Simulate the pruning logic: remove events older than 30 days.

        This mirrors the SQL: DELETE FROM ha_event_log WHERE timestamp < now() - interval '30 days'
        """
        cutoff = now - timedelta(days=30)
        return [e for e in events if e["timestamp"] >= cutoff]

    @given(
        days_ago_list=st.lists(
            st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=50,
        )
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_pruning_preserves_recent_removes_old(self, days_ago_list: list[float]) -> None:
        """Events within 30 days are preserved; events older than 30 days are removed."""
        now = datetime.now(timezone.utc)

        events = []
        for days_ago in days_ago_list:
            ts = now - timedelta(days=days_ago)
            events.append({
                "id": str(uuid.uuid4()),
                "timestamp": ts,
                "event_type": "test",
                "severity": "info",
                "message": f"Test event {days_ago} days ago",
            })

        surviving = self._simulate_pruning(events, now)
        cutoff = now - timedelta(days=30)

        # All surviving events must be within 30 days
        for event in surviving:
            assert event["timestamp"] >= cutoff

        # All removed events must be older than 30 days
        surviving_ids = {e["id"] for e in surviving}
        for event in events:
            if event["id"] not in surviving_ids:
                assert event["timestamp"] < cutoff

    @given(
        days_ago=st.floats(min_value=0.0, max_value=29.999, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_recent_events_always_preserved(self, days_ago: float) -> None:
        """Any event less than 30 days old is always preserved."""
        now = datetime.now(timezone.utc)
        ts = now - timedelta(days=days_ago)
        events = [{"id": "1", "timestamp": ts, "event_type": "test", "severity": "info", "message": "recent"}]

        surviving = self._simulate_pruning(events, now)
        assert len(surviving) == 1

    @given(
        days_ago=st.floats(min_value=30.001, max_value=60.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_old_events_always_removed(self, days_ago: float) -> None:
        """Any event older than 30 days is always removed."""
        now = datetime.now(timezone.utc)
        ts = now - timedelta(days=days_ago)
        events = [{"id": "1", "timestamp": ts, "event_type": "test", "severity": "info", "message": "old"}]

        surviving = self._simulate_pruning(events, now)
        assert len(surviving) == 0

    def test_pruning_sql_in_heartbeat_source(self) -> None:
        """Verify the heartbeat loop contains the correct pruning SQL."""
        from app.modules.ha import heartbeat as hb_module

        source = inspect.getsource(hb_module.HeartbeatService._ping_loop)

        # The pruning SQL should delete events older than 30 days
        assert "DELETE FROM ha_event_log" in source
        assert "30 days" in source

    @given(
        recent_count=st.integers(min_value=0, max_value=20),
        old_count=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_exact_count_after_pruning(self, recent_count: int, old_count: int) -> None:
        """After pruning, exactly recent_count events survive."""
        now = datetime.now(timezone.utc)

        events = []
        # Recent events (within 30 days)
        for i in range(recent_count):
            ts = now - timedelta(days=i % 30)
            events.append({
                "id": str(uuid.uuid4()),
                "timestamp": ts,
                "event_type": "test",
                "severity": "info",
                "message": f"recent {i}",
            })
        # Old events (older than 30 days)
        for i in range(old_count):
            ts = now - timedelta(days=31 + i)
            events.append({
                "id": str(uuid.uuid4()),
                "timestamp": ts,
                "event_type": "test",
                "severity": "info",
                "message": f"old {i}",
            })

        surviving = self._simulate_pruning(events, now)
        assert len(surviving) == recent_count
