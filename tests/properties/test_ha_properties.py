"""Property-based tests for the HA Replication feature.

Tests P3, P4, P7, and P8 from the HA design document using Hypothesis.
"""

from __future__ import annotations

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.ha.utils import (
    classify_peer_health,
    is_valid_role_transition,
    validate_confirmation_text,
)
from app.modules.ha.schemas import HeartbeatHistoryEntry, PublicStatusResponse


# ============================================================================
# P3 — Peer health classification
# ============================================================================


class TestP3PeerHealthClassification:
    """Property: peer health is determined solely by the time delta.

    healthy     if delta < 30 s
    degraded    if 30 s <= delta <= 60 s
    unreachable if delta > 60 s

    **Validates: Requirements 2.3**
    """

    @given(delta=st.floats(min_value=0.0, max_value=29.999, allow_nan=False, allow_infinity=False))
    @h_settings(PBT_SETTINGS)
    def test_healthy_when_under_30s(self, delta: float) -> None:
        assert classify_peer_health(delta) == "healthy"

    @given(delta=st.floats(min_value=30.0, max_value=60.0, allow_nan=False, allow_infinity=False))
    @h_settings(PBT_SETTINGS)
    def test_degraded_when_30_to_60s(self, delta: float) -> None:
        assert classify_peer_health(delta) == "degraded"

    @given(delta=st.floats(min_value=60.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))
    @h_settings(PBT_SETTINGS)
    def test_unreachable_when_over_60s(self, delta: float) -> None:
        assert classify_peer_health(delta) == "unreachable"

    @given(delta=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))
    @h_settings(PBT_SETTINGS)
    def test_result_always_one_of_three(self, delta: float) -> None:
        result = classify_peer_health(delta)
        assert result in {"healthy", "degraded", "unreachable"}


# ============================================================================
# P4 — Confirmation text validation
# ============================================================================


class TestP4ConfirmationTextValidation:
    """Property: only the exact string "CONFIRM" is accepted.

    **Validates: Requirements 7.6**
    """

    @given(text=st.text(min_size=0, max_size=50))
    @h_settings(PBT_SETTINGS)
    def test_random_strings_rejected_unless_exact(self, text: str) -> None:
        if text == "CONFIRM":
            assert validate_confirmation_text(text) is True
        else:
            assert validate_confirmation_text(text) is False

    def test_exact_confirm_accepted(self) -> None:
        assert validate_confirmation_text("CONFIRM") is True

    @given(
        prefix=st.text(min_size=1, max_size=5),
        suffix=st.text(min_size=1, max_size=5),
    )
    @h_settings(PBT_SETTINGS)
    def test_padded_strings_rejected(self, prefix: str, suffix: str) -> None:
        assert validate_confirmation_text(prefix + "CONFIRM" + suffix) is False

    @given(text=st.sampled_from([
        "confirm", "Confirm", "CONFIRMED", "CONFIR", " CONFIRM", "CONFIRM ",
        "C0NFIRM", "cONFIRM", "",
    ]))
    @h_settings(PBT_SETTINGS)
    def test_near_miss_variants_rejected(self, text: str) -> None:
        assert validate_confirmation_text(text) is False


# ============================================================================
# P8 — Role state machine validity
# ============================================================================

ALL_ROLES = ["standalone", "primary", "standby"]

VALID_TRANSITIONS = {
    ("standalone", "primary"),
    ("standalone", "standby"),
    ("primary", "standby"),
    ("standby", "primary"),
}


class TestP8RoleStateMachineValidity:
    """Property: only the four defined transitions are allowed.

    standalone → primary
    standalone → standby
    primary    → standby  (demote)
    standby    → primary  (promote)

    **Validates: Requirements 4.1, 4.3**
    """

    @given(
        from_role=st.sampled_from(ALL_ROLES),
        to_role=st.sampled_from(ALL_ROLES),
    )
    @h_settings(PBT_SETTINGS)
    def test_all_role_pairs(self, from_role: str, to_role: str) -> None:
        expected = (from_role, to_role) in VALID_TRANSITIONS
        assert is_valid_role_transition(from_role, to_role) is expected

    @given(
        from_role=st.text(min_size=1, max_size=20),
        to_role=st.text(min_size=1, max_size=20),
    )
    @h_settings(PBT_SETTINGS)
    def test_arbitrary_strings_only_valid_if_in_set(self, from_role: str, to_role: str) -> None:
        result = is_valid_role_transition(from_role, to_role)
        if (from_role, to_role) in VALID_TRANSITIONS:
            assert result is True
        else:
            assert result is False

    def test_self_transitions_rejected(self) -> None:
        for role in ALL_ROLES:
            assert is_valid_role_transition(role, role) is False

    def test_invalid_reverse_transitions(self) -> None:
        # primary → standalone and standby → standalone are NOT valid
        assert is_valid_role_transition("primary", "standalone") is False
        assert is_valid_role_transition("standby", "standalone") is False


# ============================================================================
# P7 — Public status response field safety
# ============================================================================

ALLOWED_FIELDS = {"node_name", "role", "peer_status", "sync_status"}

PEER_STATUSES = ["healthy", "degraded", "unreachable", "unknown"]
SYNC_STATUSES = [
    "not_configured", "initializing", "healthy",
    "lagging", "disconnected", "resyncing", "error",
]
ROLES = ["standalone", "primary", "standby"]


class TestP7PublicStatusResponseFieldSafety:
    """Property: PublicStatusResponse exposes only the 4 allowed fields.

    No database credentials, user data, or internal configuration.

    **Validates: Requirements 8.4, 11.3**
    """

    @given(
        node_name=st.text(min_size=1, max_size=50),
        role=st.sampled_from(ROLES),
        peer_status=st.sampled_from(PEER_STATUSES),
        sync_status=st.sampled_from(SYNC_STATUSES),
    )
    @h_settings(PBT_SETTINGS)
    def test_model_dump_only_has_allowed_keys(
        self,
        node_name: str,
        role: str,
        peer_status: str,
        sync_status: str,
    ) -> None:
        response = PublicStatusResponse(
            node_name=node_name,
            role=role,
            peer_status=peer_status,
            sync_status=sync_status,
        )
        dumped = response.model_dump()
        assert set(dumped.keys()) == ALLOWED_FIELDS

    @given(
        node_name=st.text(min_size=1, max_size=50),
        role=st.sampled_from(ROLES),
        peer_status=st.sampled_from(PEER_STATUSES),
        sync_status=st.sampled_from(SYNC_STATUSES),
    )
    @h_settings(PBT_SETTINGS)
    def test_no_extra_fields_in_response(
        self,
        node_name: str,
        role: str,
        peer_status: str,
        sync_status: str,
    ) -> None:
        response = PublicStatusResponse(
            node_name=node_name,
            role=role,
            peer_status=peer_status,
            sync_status=sync_status,
        )
        dumped = response.model_dump()
        assert len(dumped) == 4
        # Verify values round-trip correctly
        assert dumped["node_name"] == node_name
        assert dumped["role"] == role
        assert dumped["peer_status"] == peer_status
        assert dumped["sync_status"] == sync_status


# ============================================================================
# P10 — Heartbeat history bounded size
# ============================================================================


class TestP10HeartbeatHistoryBoundedSize:
    """Property: the heartbeat history deque never exceeds 100 entries.

    After appending N entries (N > 100), the oldest entries are evicted
    and len(history) stays at most 100.

    **Validates: Requirements 2.4**
    """

    @given(n=st.integers(min_value=101, max_value=500))
    @h_settings(PBT_SETTINGS)
    def test_history_never_exceeds_100(self, n: int) -> None:
        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://localhost:9999",
            interval=10,
            secret="test-secret",
        )
        for i in range(n):
            entry = HeartbeatHistoryEntry(
                timestamp=f"2025-01-01T00:00:{i:02d}Z",
                peer_status="healthy",
                replication_lag_seconds=None,
                response_time_ms=float(i),
            )
            svc.history.append(entry)

        assert len(svc.history) <= 100

    @given(n=st.integers(min_value=1, max_value=500))
    @h_settings(PBT_SETTINGS)
    def test_history_size_is_min_of_n_and_100(self, n: int) -> None:
        from app.modules.ha.heartbeat import HeartbeatService

        svc = HeartbeatService(
            peer_endpoint="http://localhost:9999",
            interval=10,
            secret="test-secret",
        )
        for i in range(n):
            entry = HeartbeatHistoryEntry(
                timestamp=f"2025-01-01T00:00:{i:02d}Z",
                peer_status="healthy",
                replication_lag_seconds=None,
                response_time_ms=float(i),
            )
            svc.history.append(entry)

        assert len(svc.history) == min(n, 100)


# ============================================================================
# P11 — Auto-promote gating
# ============================================================================


class TestP11AutoPromoteGating:
    """Property: auto-promotion never fires when auto_promote_enabled is False.

    When ``auto_promote_enabled=False``, ``should_auto_promote`` must return
    ``False`` regardless of how long the peer has been unreachable.

    **Validates: Requirements 5.3**
    """

    @given(
        peer_unreachable_seconds=st.floats(
            min_value=0.0, max_value=1_000_000.0,
            allow_nan=False, allow_infinity=False,
        ),
        failover_timeout=st.integers(min_value=1, max_value=86400),
    )
    @h_settings(PBT_SETTINGS)
    def test_disabled_never_promotes(
        self,
        peer_unreachable_seconds: float,
        failover_timeout: int,
    ) -> None:
        from app.modules.ha.utils import should_auto_promote

        result = should_auto_promote(
            auto_promote_enabled=False,
            peer_unreachable_seconds=peer_unreachable_seconds,
            failover_timeout=failover_timeout,
        )
        assert result is False

    @given(
        peer_unreachable_seconds=st.floats(
            min_value=0.0, max_value=1_000_000.0,
            allow_nan=False, allow_infinity=False,
        ),
        failover_timeout=st.integers(min_value=1, max_value=86400),
        auto_promote_enabled=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_promotes_only_when_enabled_and_timeout_exceeded(
        self,
        peer_unreachable_seconds: float,
        failover_timeout: int,
        auto_promote_enabled: bool,
    ) -> None:
        from app.modules.ha.utils import should_auto_promote

        result = should_auto_promote(
            auto_promote_enabled=auto_promote_enabled,
            peer_unreachable_seconds=peer_unreachable_seconds,
            failover_timeout=failover_timeout,
        )
        expected = auto_promote_enabled and peer_unreachable_seconds > failover_timeout
        assert result is expected


# ============================================================================
# P6 — Standby write protection
# ============================================================================

# HTTP methods — read-only methods that should always pass through.
_READ_METHODS = ["GET", "HEAD", "OPTIONS"]
# Write methods that should be blocked on standby for non-HA paths.
_WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]
# All roles the node can be in.
_ALL_ROLES = ["standalone", "primary", "standby"]


class TestP6StandbyWriteProtection:
    """Property: standby nodes block non-read requests to non-HA paths.

    - GET/HEAD/OPTIONS always pass through regardless of role.
    - All requests to ``/api/v1/ha/*`` pass through regardless of role or method.
    - Non-read requests to non-HA paths return 503 only when role is ``"standby"``.

    **Validates: Requirements 9.1, 9.3, 9.4**
    """

    @given(
        method=st.sampled_from(_READ_METHODS),
        path=st.text(min_size=1, max_size=100).map(lambda s: "/" + s.lstrip("/")),
        role=st.sampled_from(_ALL_ROLES),
    )
    @h_settings(PBT_SETTINGS)
    def test_read_methods_never_blocked(self, method: str, path: str, role: str) -> None:
        from app.modules.ha.utils import should_block_request

        assert should_block_request(method, path, role) is False

    @given(
        method=st.sampled_from(_WRITE_METHODS),
        # Generate paths that do NOT start with /api/v1/ha/
        path=st.text(min_size=1, max_size=100).map(
            lambda s: "/api/v1/invoices/" + s
        ),
    )
    @h_settings(PBT_SETTINGS)
    def test_write_blocked_on_standby_for_non_ha_paths(self, method: str, path: str) -> None:
        from app.modules.ha.utils import should_block_request

        assert should_block_request(method, path, "standby") is True

    @given(
        method=st.sampled_from(_WRITE_METHODS),
        # Generate HA sub-paths
        path=st.text(min_size=0, max_size=50).map(
            lambda s: "/api/v1/ha/" + s
        ),
        role=st.sampled_from(_ALL_ROLES),
    )
    @h_settings(PBT_SETTINGS)
    def test_ha_paths_never_blocked(self, method: str, path: str, role: str) -> None:
        from app.modules.ha.utils import should_block_request

        assert should_block_request(method, path, role) is False

    @given(
        method=st.sampled_from(_WRITE_METHODS),
        path=st.text(min_size=1, max_size=100).map(lambda s: "/" + s.lstrip("/")),
        role=st.sampled_from(["standalone", "primary"]),
    )
    @h_settings(PBT_SETTINGS)
    def test_non_standby_roles_never_blocked(self, method: str, path: str, role: str) -> None:
        from app.modules.ha.utils import should_block_request

        assert should_block_request(method, path, role) is False

    @given(
        method=st.sampled_from(_READ_METHODS + _WRITE_METHODS),
        path=st.text(min_size=1, max_size=100).map(lambda s: "/" + s.lstrip("/")),
        role=st.sampled_from(_ALL_ROLES),
    )
    @h_settings(PBT_SETTINGS)
    def test_block_iff_standby_write_non_ha(self, method: str, path: str, role: str) -> None:
        """Comprehensive property: blocked ⟺ standby AND write AND non-HA path."""
        from app.modules.ha.utils import should_block_request

        is_standby = role == "standby"
        is_write = method not in {"GET", "HEAD", "OPTIONS"}
        is_ha_path = path.startswith("/api/v1/ha/")

        expected = is_standby and is_write and not is_ha_path
        assert should_block_request(method, path, role) is expected


# ============================================================================
# P1 — RBAC enforcement on HA management endpoints
# ============================================================================

# Common roles found in the system.
_KNOWN_ROLES = [
    "global_admin", "org_admin", "org_member", "viewer", "billing_admin",
    "support", "readonly", "anonymous", "",
]


class TestP1RBACEnforcement:
    """Property: only the ``global_admin`` role is allowed to access HA management.

    *For any* role string, ``is_ha_admin_allowed`` returns ``True`` only when
    the role is exactly ``"global_admin"``.  All other roles must be denied.

    **Validates: Requirements 1.2, 11.1**
    """

    @given(role=st.text(min_size=0, max_size=50))
    @h_settings(PBT_SETTINGS)
    def test_only_global_admin_allowed(self, role: str) -> None:
        from app.modules.ha.utils import is_ha_admin_allowed

        if role == "global_admin":
            assert is_ha_admin_allowed(role) is True
        else:
            assert is_ha_admin_allowed(role) is False

    @given(role=st.sampled_from(_KNOWN_ROLES))
    @h_settings(PBT_SETTINGS)
    def test_known_roles(self, role: str) -> None:
        from app.modules.ha.utils import is_ha_admin_allowed

        expected = role == "global_admin"
        assert is_ha_admin_allowed(role) is expected

    @given(
        prefix=st.text(min_size=1, max_size=5),
        suffix=st.text(min_size=1, max_size=5),
    )
    @h_settings(PBT_SETTINGS)
    def test_padded_global_admin_rejected(self, prefix: str, suffix: str) -> None:
        from app.modules.ha.utils import is_ha_admin_allowed

        assert is_ha_admin_allowed(prefix + "global_admin" + suffix) is False

    def test_exact_global_admin_accepted(self) -> None:
        from app.modules.ha.utils import is_ha_admin_allowed

        assert is_ha_admin_allowed("global_admin") is True

    @given(role=st.sampled_from([
        "Global_Admin", "GLOBAL_ADMIN", "global_Admin", "globaladmin",
        "global admin", " global_admin", "global_admin ",
    ]))
    @h_settings(PBT_SETTINGS)
    def test_case_variants_rejected(self, role: str) -> None:
        from app.modules.ha.utils import is_ha_admin_allowed

        assert is_ha_admin_allowed(role) is False


# ============================================================================
# P5 — Promotion lag threshold gating
# ============================================================================


class TestP5PromotionLagThreshold:
    """Property: promotion is blocked when lag > 5 s and force is False.

    - lag is None → always allowed
    - lag <= 5.0 → always allowed
    - lag > 5.0 and force=False → blocked
    - lag > 5.0 and force=True → allowed

    **Validates: Requirements 4.5**
    """

    @given(force=st.booleans())
    @h_settings(PBT_SETTINGS)
    def test_none_lag_always_allowed(self, force: bool) -> None:
        from app.modules.ha.utils import can_promote

        assert can_promote(lag_seconds=None, force=force) is True

    @given(
        lag=st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        force=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_low_lag_always_allowed(self, lag: float, force: bool) -> None:
        from app.modules.ha.utils import can_promote

        assert can_promote(lag_seconds=lag, force=force) is True

    @given(
        lag=st.floats(min_value=5.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @h_settings(PBT_SETTINGS)
    def test_high_lag_blocked_without_force(self, lag: float) -> None:
        from app.modules.ha.utils import can_promote

        assert can_promote(lag_seconds=lag, force=False) is False

    @given(
        lag=st.floats(min_value=5.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @h_settings(PBT_SETTINGS)
    def test_high_lag_allowed_with_force(self, lag: float) -> None:
        from app.modules.ha.utils import can_promote

        assert can_promote(lag_seconds=lag, force=True) is True

    @given(
        lag=st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        ),
        force=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_comprehensive_property(self, lag: float | None, force: bool) -> None:
        """Blocked ⟺ lag > 5.0 AND force is False."""
        from app.modules.ha.utils import can_promote

        result = can_promote(lag_seconds=lag, force=force)
        if lag is None or lag <= 5.0 or force:
            assert result is True
        else:
            assert result is False


# ============================================================================
# P9 — HA config persistence round-trip (schema serialization)
# ============================================================================


class TestP9HAConfigPersistenceRoundTrip:
    """Property: HAConfigRequest round-trips through dict serialization.

    *For any* valid HAConfigRequest, converting to dict and back produces
    an identical instance.  This validates schema correctness without a DB.

    **Validates: Requirements 10.1**
    """

    @given(
        node_name=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
        role=st.sampled_from(["primary", "standby"]),
        peer_endpoint=st.from_regex(
            r"http://192\.168\.\d{1,3}\.\d{1,3}:\d{4}", fullmatch=True,
        ),
        auto_promote_enabled=st.booleans(),
        heartbeat_interval_seconds=st.integers(min_value=1, max_value=300),
        failover_timeout_seconds=st.integers(min_value=1, max_value=3600),
    )
    @h_settings(PBT_SETTINGS)
    def test_dict_round_trip(
        self,
        node_name: str,
        role: str,
        peer_endpoint: str,
        auto_promote_enabled: bool,
        heartbeat_interval_seconds: int,
        failover_timeout_seconds: int,
    ) -> None:
        from app.modules.ha.schemas import HAConfigRequest

        original = HAConfigRequest(
            node_name=node_name,
            role=role,
            peer_endpoint=peer_endpoint,
            auto_promote_enabled=auto_promote_enabled,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            failover_timeout_seconds=failover_timeout_seconds,
        )
        dumped = original.model_dump()
        restored = HAConfigRequest(**dumped)

        assert restored.node_name == original.node_name
        assert restored.role == original.role
        assert restored.peer_endpoint == original.peer_endpoint
        assert restored.auto_promote_enabled == original.auto_promote_enabled
        assert restored.heartbeat_interval_seconds == original.heartbeat_interval_seconds
        assert restored.failover_timeout_seconds == original.failover_timeout_seconds

    @given(
        node_name=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
        role=st.sampled_from(["primary", "standby"]),
        peer_endpoint=st.from_regex(
            r"http://192\.168\.\d{1,3}\.\d{1,3}:\d{4}", fullmatch=True,
        ),
        auto_promote_enabled=st.booleans(),
        heartbeat_interval_seconds=st.integers(min_value=1, max_value=300),
        failover_timeout_seconds=st.integers(min_value=1, max_value=3600),
    )
    @h_settings(PBT_SETTINGS)
    def test_json_round_trip(
        self,
        node_name: str,
        role: str,
        peer_endpoint: str,
        auto_promote_enabled: bool,
        heartbeat_interval_seconds: int,
        failover_timeout_seconds: int,
    ) -> None:
        from app.modules.ha.schemas import HAConfigRequest
        import json

        original = HAConfigRequest(
            node_name=node_name,
            role=role,
            peer_endpoint=peer_endpoint,
            auto_promote_enabled=auto_promote_enabled,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            failover_timeout_seconds=failover_timeout_seconds,
        )
        json_str = original.model_dump_json()
        restored = HAConfigRequest(**json.loads(json_str))

        assert restored == original

    @given(
        node_name=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
        role=st.sampled_from(["primary", "standby"]),
        peer_endpoint=st.from_regex(
            r"http://192\.168\.\d{1,3}\.\d{1,3}:\d{4}", fullmatch=True,
        ),
    )
    @h_settings(PBT_SETTINGS)
    def test_defaults_preserved_in_round_trip(
        self,
        node_name: str,
        role: str,
        peer_endpoint: str,
    ) -> None:
        """Verify default values survive the round-trip."""
        from app.modules.ha.schemas import HAConfigRequest

        original = HAConfigRequest(
            node_name=node_name,
            role=role,
            peer_endpoint=peer_endpoint,
        )
        dumped = original.model_dump()
        restored = HAConfigRequest(**dumped)

        # Defaults should be preserved
        assert restored.auto_promote_enabled is False
        assert restored.heartbeat_interval_seconds == 10
        assert restored.failover_timeout_seconds == 90
        assert restored == original


# ============================================================================
# P12 — Split-brain detection
# ============================================================================

_HA_ROLES = ["standalone", "primary", "standby"]


class TestP12SplitBrainDetection:
    """Property: split-brain is detected when both nodes report primary.

    ``detect_split_brain`` returns ``True`` if and only if both
    *local_role* and *peer_role* are ``"primary"``.

    **Validates: Requirements 5.5**
    """

    @given(
        local_role=st.sampled_from(_HA_ROLES),
        peer_role=st.sampled_from(_HA_ROLES),
    )
    @h_settings(PBT_SETTINGS)
    def test_split_brain_iff_both_primary(self, local_role: str, peer_role: str) -> None:
        from app.modules.ha.utils import detect_split_brain

        result = detect_split_brain(local_role, peer_role)
        expected = local_role == "primary" and peer_role == "primary"
        assert result is expected

    def test_both_primary_detected(self) -> None:
        from app.modules.ha.utils import detect_split_brain

        assert detect_split_brain("primary", "primary") is True

    def test_primary_standby_not_split_brain(self) -> None:
        from app.modules.ha.utils import detect_split_brain

        assert detect_split_brain("primary", "standby") is False

    def test_standby_primary_not_split_brain(self) -> None:
        from app.modules.ha.utils import detect_split_brain

        assert detect_split_brain("standby", "primary") is False

    def test_standby_standby_not_split_brain(self) -> None:
        from app.modules.ha.utils import detect_split_brain

        assert detect_split_brain("standby", "standby") is False

    @given(
        local_role=st.text(min_size=0, max_size=30),
        peer_role=st.text(min_size=0, max_size=30),
    )
    @h_settings(PBT_SETTINGS)
    def test_arbitrary_strings(self, local_role: str, peer_role: str) -> None:
        from app.modules.ha.utils import detect_split_brain

        result = detect_split_brain(local_role, peer_role)
        expected = local_role == "primary" and peer_role == "primary"
        assert result is expected
