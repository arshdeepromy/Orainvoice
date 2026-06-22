"""Organisation Employee Portal authentication primitives.

This module owns the low-level password / lockout helpers used by the
portal-facing login + credential flows (``/e/api/auth/*``) and the
admin-facing credential-issuance flows. It mirrors the structure of the
B2B Fleet Portal's ``app/modules/fleet_portal/auth.py`` (bcrypt cost-12
hashing, a per-account lockout state machine) but deliberately models the
lockout state machine and the password-length validator as **pure,
side-effect-free functions** rather than ORM mutators.

Why pure? Tasks 5.3 and 5.5 write Hypothesis property tests directly
against these functions (design Properties 11 and 14). Pure functions
that take the relevant state as arguments — including an injectable
``now`` — are trivial to test without a database, with deterministic
time. The service layer (task 5.x) calls these helpers and is the only
place that reads/writes the ``EmployeePortalUser`` ORM object.

Provided functions:

- :func:`hash_password` / :func:`verify_password` (async, off the event
  loop) and their sync counterparts — bcrypt cost 12, matching the fleet
  portal and ``app.modules.auth.password``.
- Pure lockout state machine: :func:`is_locked`,
  :func:`record_failed_attempt`, :func:`reset_lockout`. The state is the
  pair ``(failed_attempts, locked_until)``; every helper takes ``now``
  so behaviour is deterministic under test. 5th consecutive failure →
  ``locked_until = now + 15min`` (R6.5); the count resets to 0 once the
  15-minute window elapses or on a successful login (R6.6).
- Pure :func:`validate_password_length` — accepts iff
  ``8 <= len(password) <= 128`` (R5.6, R14.7).

Implements: Organisation Employee Portal task 5.1 — Requirements 5.5,
5.6, 6.5, 6.6, 14.4, 14.7.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# bcrypt cost factor — matches the fleet portal (app/modules/fleet_portal/
# auth.py) and the staff auth pattern (app/modules/auth/password.py).
_BCRYPT_COST = 12

# Lockout policy (Requirements 6.5, 6.6). Fixed by the spec: 5 consecutive
# failures lock the account for 15 minutes, after which the count resets.
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15

# Password length bounds (Requirements 5.5, 5.6, 14.4, 14.7) — inclusive.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

# The exact human-readable message surfaced on a length violation. Kept as
# a module constant so the schema layer, service layer, and property tests
# all reference one source of truth.
PASSWORD_LENGTH_MESSAGE = (
    f"Password must be between {MIN_PASSWORD_LENGTH} and "
    f"{MAX_PASSWORD_LENGTH} characters"
)


def _now_utc() -> datetime:
    """Return the current UTC time. Hoisted so tests can monkey-patch it."""
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    """Normalise a possibly-naive datetime to timezone-aware UTC.

    ``locked_until`` is timezone-aware in the database, but a caller (or a
    property-test generator) may hand us a naive value. Comparing a naive
    and an aware datetime raises ``TypeError``; normalising here keeps the
    pure helpers total over their input domain.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# Password hashing (mirrors fleet portal — bcrypt cost 12)
# ---------------------------------------------------------------------------


def _bcrypt_input(plaintext: str) -> bytes:
    """Derive a fixed-length, bcrypt-safe input from an arbitrary plaintext.

    bcrypt silently truncates / outright rejects inputs longer than 72
    bytes (``ValueError: password cannot be longer than 72 bytes``). Our
    accepted password range is 8..128 *characters* (R5.6 / R14.7), and a
    128-character password — or any multibyte password — can easily exceed
    72 bytes, so handing the raw plaintext to bcrypt would raise on
    otherwise-valid passwords and break invite-acceptance / reset.

    The standard mitigation: pre-hash the plaintext with SHA-256 and
    base64-encode the digest, yielding a constant 44-byte value (well under
    bcrypt's 72-byte limit) that still depends on the full plaintext. This
    is applied identically in :func:`hash_password_sync` and
    :func:`verify_password_sync` so hashing and verification stay
    consistent (design Property 11).

    NOTE: passwords hashed *before* this transform was introduced would no
    longer verify. That is safe here because the employee portal is a
    brand-new feature with no portal users in production yet.
    """
    digest = hashlib.sha256(plaintext.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password_sync(plaintext: str) -> str:
    """Sync bcrypt hash (cost 12). Prefer :func:`hash_password` in async code.

    The plaintext is SHA-256 pre-hashed (see :func:`_bcrypt_input`) so the
    full accepted 8..128 character range hashes successfully regardless of
    byte length.
    """
    return bcrypt.hashpw(
        _bcrypt_input(plaintext),
        bcrypt.gensalt(rounds=_BCRYPT_COST),
    ).decode("utf-8")


def verify_password_sync(plaintext: str, hashed: str) -> bool:
    """Sync bcrypt verify. Prefer :func:`verify_password` in async code.

    Applies the SAME SHA-256 pre-hash transform as
    :func:`hash_password_sync` so verification stays consistent across the
    full 8..128 character range.

    Returns ``False`` for any input shape bcrypt cannot verify (empty
    plaintext, empty/malformed hash, non-bcrypt format) instead of raising,
    so callers can rely on the boolean return alone.
    """
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(_bcrypt_input(plaintext), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # bcrypt raises ValueError on a malformed hash. Treat as "no match".
        return False


async def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash (cost 12) of ``plaintext``, off the event loop.

    Returns a UTF-8 decoded string suitable for direct storage in the
    ``employee_portal_users.password_hash`` ``VARCHAR(255)`` column. A fresh
    salt is generated on every call, so two hashes of the same plaintext are
    always different.

    bcrypt is intentionally CPU-expensive; running it inside the FastAPI
    event loop would cap logins-per-second to single digits, so we offload
    to a worker thread (mirrors the fleet portal).
    """
    import asyncio

    return await asyncio.to_thread(hash_password_sync, plaintext)


async def verify_password(plaintext: str, hashed: str) -> bool:
    """Return ``True`` iff ``plaintext`` matches ``hashed``, off the event loop."""
    import asyncio

    return await asyncio.to_thread(verify_password_sync, plaintext, hashed)


# ---------------------------------------------------------------------------
# Password length validation (Property 11 — Requirements 5.5, 5.6, 14.4, 14.7)
# ---------------------------------------------------------------------------


def validate_password_length(password: str | None) -> tuple[bool, str]:
    """Pure length gate: accept iff ``8 <= len(password) <= 128`` (inclusive).

    Returns ``(ok, message)``:
      - ``(True, "")`` when the length is in range.
      - ``(False, PASSWORD_LENGTH_MESSAGE)`` when ``password`` is ``None`` or
        out of range — the message names the allowed range (R5.6, R14.7).

    This is the only length check; it is shared by invite-acceptance (R5.5)
    and password-reset (R14.4). It performs no hashing and mutates nothing,
    so the caller decides what to do with the verdict (reject → leave all
    stored credential state unchanged).
    """
    if password is None:
        return False, PASSWORD_LENGTH_MESSAGE
    if MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        return True, ""
    return False, PASSWORD_LENGTH_MESSAGE


# ---------------------------------------------------------------------------
# Lockout state machine (Property 14 — Requirements 6.5, 6.6)
# ---------------------------------------------------------------------------
#
# The lockout state is the pair ``(failed_attempts, locked_until)``. These
# three helpers are pure: they read the current state plus ``now`` and
# return the next state (or a boolean). The service layer maps the result
# back onto the ``EmployeePortalUser`` row and flushes.


def is_locked(
    failed_attempts: int,
    locked_until: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return ``True`` iff a temporary lock is currently active.

    A lock is active when ``locked_until`` is set and lies in the future
    relative to ``now``. Once ``now`` reaches/passes ``locked_until`` the
    lock has elapsed and this returns ``False`` — the 15-minute window is
    over and login attempts are accepted again (R6.6).

    ``failed_attempts`` is accepted for signature symmetry with the rest of
    the state machine (and so callers can pass the whole state tuple), but
    the active-lock decision depends only on ``locked_until`` vs ``now``.
    """
    if locked_until is None:
        return False
    current = now or _now_utc()
    return _as_aware(locked_until) > _as_aware(current)


def record_failed_attempt(
    failed_attempts: int,
    locked_until: datetime | None,
    now: datetime | None = None,
    *,
    threshold: int = LOCKOUT_THRESHOLD,
    lock_minutes: int = LOCKOUT_MINUTES,
) -> tuple[int, datetime | None]:
    """Apply one failed login attempt and return the next lockout state.

    Returns the new ``(failed_attempts, locked_until)`` pair.

    State machine (Property 14, R6.5/R6.6):
      - If a previous lock window has already elapsed (``locked_until`` is
        set but in the past), the consecutive-failure count is first reset
        to 0 — the new failure starts a fresh streak (R6.6).
      - While the account is *currently* locked, this is a no-op: failed
        attempts during an active lock do NOT keep extending or
        incrementing it (the caller rejects with 403 before reaching here,
        but we stay total and idempotent in case it does).
      - Otherwise the count increments by 1. When it reaches ``threshold``
        (5), ``locked_until`` is set to ``now + lock_minutes`` (15 min),
        locking the account (R6.5).
    """
    current = now or _now_utc()

    # A lock that has already elapsed clears the streak before this attempt.
    if locked_until is not None and not is_locked(failed_attempts, locked_until, current):
        failed_attempts = 0
        locked_until = None

    # An active lock absorbs the attempt without changing state.
    if is_locked(failed_attempts, locked_until, current):
        return failed_attempts, locked_until

    new_attempts = (failed_attempts or 0) + 1
    new_locked_until = locked_until
    if new_attempts >= threshold:
        new_locked_until = _as_aware(current) + timedelta(minutes=lock_minutes)
    return new_attempts, new_locked_until


def reset_lockout(
    failed_attempts: int = 0,
    locked_until: datetime | None = None,
    now: datetime | None = None,
) -> tuple[int, datetime | None]:
    """Return the cleared lockout state ``(0, None)`` (R6.6).

    Called on a successful login and whenever the caller wants to clear a
    lock whose 15-minute window has elapsed. The reset is unconditional:
    on success the consecutive-failure count returns to 0 and any
    ``locked_until`` is cleared. The arguments are accepted (and ignored)
    so callers can pass the current state/`now` tuple uniformly across the
    three state-machine helpers; the result is always the cleared state.
    """
    return 0, None


__all__ = [
    "LOCKOUT_THRESHOLD",
    "LOCKOUT_MINUTES",
    "MIN_PASSWORD_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "PASSWORD_LENGTH_MESSAGE",
    "hash_password",
    "verify_password",
    "hash_password_sync",
    "verify_password_sync",
    "validate_password_length",
    "is_locked",
    "record_failed_attempt",
    "reset_lockout",
]
