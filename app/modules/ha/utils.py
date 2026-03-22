"""Pure utility functions for the HA Replication feature.

These functions encapsulate core HA logic as pure, testable functions
with no side effects or database dependencies.
"""

from __future__ import annotations


def classify_peer_health(delta_seconds: float) -> str:
    """Classify peer health based on seconds since last successful heartbeat.

    Returns:
        "healthy"     — delta < 30 s
        "degraded"    — 30 s <= delta <= 60 s
        "unreachable" — delta > 60 s

    Requirements: 2.3
    """
    if delta_seconds < 30:
        return "healthy"
    if delta_seconds <= 60:
        return "degraded"
    return "unreachable"


def validate_confirmation_text(text: str) -> bool:
    """Return ``True`` only when *text* is exactly ``"CONFIRM"``.

    Requirements: 7.6
    """
    return text == "CONFIRM"


# Valid role transitions in the HA state machine.
_VALID_TRANSITIONS: set[tuple[str, str]] = {
    ("standalone", "primary"),
    ("standalone", "standby"),
    ("primary", "standby"),
    ("standby", "primary"),
}


def is_valid_role_transition(from_role: str, to_role: str) -> bool:
    """Return ``True`` if transitioning from *from_role* to *to_role* is allowed.

    Valid transitions:
        standalone → primary
        standalone → standby
        primary    → standby  (demote)
        standby    → primary  (promote)

    Requirements: 4.1, 4.3
    """
    return (from_role, to_role) in _VALID_TRANSITIONS


def should_auto_promote(
    auto_promote_enabled: bool,
    peer_unreachable_seconds: float,
    failover_timeout: int,
) -> bool:
    """Decide whether the standby should auto-promote to primary.

    Returns ``True`` only when *auto_promote_enabled* is ``True`` **and**
    *peer_unreachable_seconds* exceeds *failover_timeout*.

    Requirements: 5.3
    """
    return auto_promote_enabled and peer_unreachable_seconds > failover_timeout

# HTTP methods considered read-only (allowed on standby nodes).
_READ_ONLY_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# Path prefix for HA management endpoints (always allowed).
_HA_PATH_PREFIX: str = "/api/v1/ha/"

# Paths that must work on standby even for non-read methods (e.g. login).
_STANDBY_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/api/v1/ha/",
    "/api/v1/auth/login",
    "/api/v1/auth/token/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/mfa/",
    "/api/v1/auth/passkey/login",
    "/api/v2/auth/login",
    "/api/v2/auth/token/refresh",
    "/api/v2/auth/logout",
)


def should_block_request(method: str, path: str, role: str) -> bool:
    """Decide whether a request should be blocked by standby write protection.

    Returns ``True`` when **all** of the following are true:
    - *role* is ``"standby"``
    - *method* is **not** a read-only method (GET, HEAD, OPTIONS)
    - *path* does **not** match any standby-allowed prefix

    Requirements: 9.1, 9.3, 9.4
    """
    if role != "standby":
        return False
    if method.upper() in _READ_ONLY_METHODS:
        return False
    if any(path.startswith(prefix) for prefix in _STANDBY_ALLOWED_PREFIXES):
        return False
    return True


def is_ha_admin_allowed(role: str) -> bool:
    """Return ``True`` only when *role* is exactly ``"global_admin"``.

    All HA management endpoints require the ``global_admin`` role.
    Any other role must receive a 403 Forbidden response.

    Requirements: 1.2, 11.1
    """
    return role == "global_admin"


def can_promote(lag_seconds: float | None, force: bool) -> bool:
    """Decide whether a standby node can be promoted to primary.

    Returns ``True`` when:
    - *lag_seconds* is ``None`` (lag unknown / not applicable), **or**
    - *lag_seconds* <= 5.0, **or**
    - *force* is ``True`` (admin acknowledges potential data loss).

    Returns ``False`` when *lag_seconds* > 5.0 and *force* is ``False``.

    Requirements: 4.5
    """
    if lag_seconds is None:
        return True
    if lag_seconds <= 5.0:
        return True
    return force


def detect_split_brain(local_role: str, peer_role: str) -> bool:
    """Detect a split-brain condition where both nodes claim to be primary.

    Returns ``True`` when both *local_role* and *peer_role* are ``"primary"``.
    In this case the system should alert the admin rather than attempting
    automatic resolution.

    Requirements: 5.5
    """
    return local_role == "primary" and peer_role == "primary"
