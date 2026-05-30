"""Fleet Portal authentication primitives.

This module owns the low-level password / token / lockout helpers used
by both the portal-facing router (``/fleet/api/auth/*``) and the
admin-facing router (``/api/v2/fleet-portal/admin/...``). It deliberately
contains NO database access — every helper operates on values or on
``PortalAccount`` ORM objects passed in by the service layer, so
behaviour is easy to test with hypothesis under transaction control.

Provided functions:

- :func:`hash_password` / :func:`verify_password` — bcrypt cost 12
  (matches the staff ``app.modules.auth.password`` pattern).
- :func:`validate_password_rules` — Property 7 predicate (length ≥ 8
  AND not equal to email local-part). The richer
  ``validate_password_against_policy`` lives in task 4A.1 alongside the
  HIBP check; this helper is the cheap gate the schema layer also uses.
- :func:`generate_invite_token` / :func:`generate_reset_token` —
  ``secrets.token_urlsafe(32)``, returning a 43-character URL-safe
  base64 string.
- Lockout helpers: :func:`record_failed_attempt`, :func:`check_locked`,
  :func:`reset_lockout`. They mutate the in-memory ORM object and let
  the caller commit. State machine matches Property 6 (Requirement
  3.2–3.6, 4.10).

Implements: B2B Fleet Portal task 3.1 — Requirements 3.3, 3.4, 3.5,
3.6, 3.7, 3.8.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import bcrypt

if TYPE_CHECKING:  # pragma: no cover — avoid circular import at runtime
    from app.modules.fleet_portal.models import PortalAccount


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# bcrypt cost factor — matches existing staff auth (see
# app/modules/auth/password.py) and the spec requirement 3.7.
_BCRYPT_COST = 12

# Token length — secrets.token_urlsafe(32) returns ~43 URL-safe chars.
_TOKEN_BYTES = 32

# Default lockout window — 5 failed attempts → 30-minute lock
# (Requirement 3.4). The `4A.5` task wires these to the per-org
# `portal_security_policy.lockout_policy` so they are ultimately
# configurable; the constants here are the safe defaults that apply
# when no policy is loaded yet.
DEFAULT_TEMP_LOCK_THRESHOLD = 5
DEFAULT_TEMP_LOCK_MINUTES = 30
DEFAULT_PERMANENT_LOCK_THRESHOLD = 10

# Password rule constants — these are the cheap, schema-level gates.
# The richer policy (uppercase / lowercase / digit / special / expiry /
# history / HIBP) is enforced in task 4A.1's
# ``validate_password_against_policy``.
_MIN_PASSWORD_LENGTH = 8


# ---------------------------------------------------------------------------
# Password hashing (Requirement 3.7)
# ---------------------------------------------------------------------------


def hash_password_sync(plaintext: str) -> str:
    """Sync bcrypt hash (cost 12). Prefer :func:`hash_password` in async code."""
    return bcrypt.hashpw(
        plaintext.encode("utf-8"),
        bcrypt.gensalt(rounds=_BCRYPT_COST),
    ).decode("utf-8")


def verify_password_sync(plaintext: str, hashed: str) -> bool:
    """Sync bcrypt verify. Prefer :func:`verify_password` in async code."""
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # bcrypt raises ValueError on a malformed hash. Treat as "no match".
        return False


async def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash (cost 12) of ``plaintext``, off the event loop.

    Returns a UTF-8 decoded string suitable for direct storage in the
    ``portal_accounts.password_hash`` ``VARCHAR(255)`` column. The
    salt is generated with the configured cost factor on every call,
    so two hashes of the same plaintext are always different.

    Bcrypt is intentionally CPU-expensive (~80–300 ms); running it
    inside the FastAPI event loop caps logins-per-second to single
    digits. PERFORMANCE_AUDIT.md §B-H2.
    """
    import asyncio
    return await asyncio.to_thread(hash_password_sync, plaintext)


async def verify_password(plaintext: str, hashed: str) -> bool:
    """Return ``True`` if ``plaintext`` matches ``hashed``, off the event loop.

    Returns ``False`` for any input shape that bcrypt cannot verify
    (empty plaintext, malformed hash, non-bcrypt format) without
    raising — callers can rely on the boolean return alone.
    """
    import asyncio
    return await asyncio.to_thread(verify_password_sync, plaintext, hashed)


# ---------------------------------------------------------------------------
# Password validation (Property 7 — Requirement 3.8)
# ---------------------------------------------------------------------------


def validate_password_rules(password: str, email: str) -> None:
    """Property 7 predicate: length ≥ 8 AND password ≠ email local-part.

    Raises ``ValueError`` on rejection with the exact message we want
    surfaced through the API. The schema layer (``schemas.py``) also
    runs this check via a model_validator so it fires at request
    parsing time before the request even reaches the service.

    The richer ``validate_password_against_policy`` (task 4A.1) wraps
    this and additionally enforces uppercase / lowercase / digit /
    special / expiry / history / HIBP per the org's
    ``portal_security_policy``.
    """
    if password is None or len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {_MIN_PASSWORD_LENGTH} characters"
        )
    local_part = (email.split("@", 1)[0] if "@" in email else email).strip().lower()
    if local_part and password.strip().lower() == local_part:
        raise ValueError("Password must not match your email username")


# ---------------------------------------------------------------------------
# Token generation (Requirements 3.10, 3.11, 4.2)
# ---------------------------------------------------------------------------


def generate_invite_token() -> str:
    """Return a fresh URL-safe invite token (≥ 32 random bytes of entropy).

    ``secrets.token_urlsafe(32)`` returns a 43-character base64-url
    string with 256 bits of entropy — a comfortable margin over the
    spec's "secrets.token_urlsafe(32)" requirement (Requirement 4.2).
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


def generate_reset_token() -> str:
    """Return a fresh URL-safe password-reset token.

    Same shape as :func:`generate_invite_token` — separate function so
    reads at call sites are explicit about which flow generated the
    token, which makes the audit log easier to reason about.
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


# ---------------------------------------------------------------------------
# Lockout state machine (Property 6 — Requirements 3.4–3.6, 4.10)
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return the current UTC time. Hoisted so tests can monkey-patch it."""
    return datetime.now(timezone.utc)


def check_locked(account: PortalAccount, *, now: datetime | None = None) -> bool:
    """Return ``True`` iff ``account`` is currently locked out.

    Combines:
      - Permanent lock (``is_locked_permanently = true``) — never expires.
      - Temporary lock (``locked_until > now``) — auto-clears on next
        successful login or when the timestamp passes.

    A return value of ``True`` means the caller MUST reject the login
    attempt with HTTP 403 and the locked-account message; ``False``
    means the caller may continue evaluating credentials.
    """
    if getattr(account, "is_locked_permanently", False):
        return True
    locked_until = getattr(account, "locked_until", None)
    if locked_until is None:
        return False
    current = now or _now_utc()
    # locked_until is timezone-aware in the DB; if the caller passed a
    # naive timestamp, normalise it to UTC for the comparison.
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > current


def record_failed_attempt(
    account: PortalAccount,
    *,
    now: datetime | None = None,
    temp_lock_threshold: int = DEFAULT_TEMP_LOCK_THRESHOLD,
    temp_lock_minutes: int = DEFAULT_TEMP_LOCK_MINUTES,
    permanent_lock_threshold: int = DEFAULT_PERMANENT_LOCK_THRESHOLD,
) -> None:
    """Increment ``failed_login_attempts`` and apply lockout rules.

    Property 6 state machine:
      - Each failed attempt while unlocked increments the counter.
      - When the counter hits ``temp_lock_threshold``, ``locked_until``
        is set to ``now + temp_lock_minutes`` (HTTP 403 from caller).
      - When the counter hits ``permanent_lock_threshold``,
        ``is_locked_permanently`` becomes true and the account never
        auto-unlocks (admin must manually unlock — task 4A.5 / 4A.9).
      - While the account is already locked, this helper is a no-op
        (failed attempts during a lockout window do NOT keep
        incrementing — Requirement 3.5).

    The caller is expected to ``flush()`` the session after this call.
    """
    if check_locked(account, now=now):
        # Spec: "WHILE locked_until > now() ... SHALL NOT increment
        # failed_login_attempts further" (Requirement 3.5).
        return

    current = now or _now_utc()
    account.failed_login_attempts = (account.failed_login_attempts or 0) + 1

    if account.failed_login_attempts >= permanent_lock_threshold:
        account.is_locked_permanently = True
        # Permanent lock supersedes the temp-lock window; clear locked_until
        # so reads of "is account locked?" only need check the boolean.
        account.locked_until = None
        return

    if account.failed_login_attempts >= temp_lock_threshold:
        account.locked_until = current + timedelta(minutes=temp_lock_minutes)


def reset_lockout(account: PortalAccount) -> None:
    """Reset all lockout state on successful auth (Requirement 3.6).

    This does NOT clear ``is_locked_permanently`` — that flag can only
    be cleared by the explicit admin-unlock action (task 4A.9). On a
    successful login of a permanently-locked account, the auth code
    path rejects before reaching this function.
    """
    account.failed_login_attempts = 0
    account.locked_until = None


# ---------------------------------------------------------------------------
# Token freshness (Requirement 9 — invite ≤ 7 days, reset ≤ 1 hour)
# ---------------------------------------------------------------------------


# Maximum invite/reset token freshness windows. Defined here so they
# are constants rather than scattered magic numbers across the service
# layer (Requirement 4.6, 3.11).
INVITE_TOKEN_MAX_AGE = timedelta(days=7)
RESET_TOKEN_MAX_AGE = timedelta(hours=1)


def is_invite_token_fresh(
    invite_sent_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return ``True`` iff the invite token was sent within 7 days.

    Used by ``account_service.accept_invite`` (task 5.1) to validate
    invite tokens. Returning ``False`` triggers the
    "invitation expired" UI path (Requirement 4.6).
    """
    if invite_sent_at is None:
        return False
    current = now or _now_utc()
    if invite_sent_at.tzinfo is None:
        invite_sent_at = invite_sent_at.replace(tzinfo=timezone.utc)
    return current - invite_sent_at <= INVITE_TOKEN_MAX_AGE


def is_reset_token_fresh(
    reset_token_expires_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return ``True`` iff the reset token has not yet expired.

    Reset tokens carry an explicit ``expires_at`` (set to ``now + 1
    hour`` at issue time) rather than a sent-at timestamp, so this
    helper is just a comparison.
    """
    if reset_token_expires_at is None:
        return False
    current = now or _now_utc()
    if reset_token_expires_at.tzinfo is None:
        reset_token_expires_at = reset_token_expires_at.replace(tzinfo=timezone.utc)
    return current < reset_token_expires_at


__all__ = [
    "DEFAULT_TEMP_LOCK_THRESHOLD",
    "DEFAULT_TEMP_LOCK_MINUTES",
    "DEFAULT_PERMANENT_LOCK_THRESHOLD",
    "INVITE_TOKEN_MAX_AGE",
    "RESET_TOKEN_MAX_AGE",
    "hash_password",
    "verify_password",
    "hash_password_sync",
    "verify_password_sync",
    "validate_password_rules",
    "generate_invite_token",
    "generate_reset_token",
    "check_locked",
    "record_failed_attempt",
    "reset_lockout",
    "is_invite_token_fresh",
    "is_reset_token_fresh",
]
