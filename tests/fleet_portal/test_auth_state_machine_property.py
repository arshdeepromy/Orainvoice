"""Property tests for fleet portal auth state machine and password rules.

Implements:
- **Property 6** — Login lockout state machine (Requirements 3.2–3.6, 4.10)
- **Property 7** — Password storage and validation rules (Requirements 3.7, 3.8)

Tests are pure-Python — they exercise ``app.modules.fleet_portal.auth``
directly without touching the database, so they run fast and don't need
a DB fixture. The auth helpers operate on duck-typed objects that
mimic the ``PortalAccount`` ORM shape, which keeps the tests independent
from the ORM and the migration head.

File path mandated by spec ``.kiro/specs/b2b-fleet-portal/tasks.md``
task 3.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.fleet_portal import auth as fp_auth


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeAccount:
    """In-memory stand-in for a PortalAccount ORM object.

    Carries just enough state for ``record_failed_attempt``,
    ``check_locked``, and ``reset_lockout`` to mutate. Defaults match
    the ORM column defaults from ``models.PortalAccount``.
    """

    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    is_locked_permanently: bool = False
    is_active: bool = True


# ---------------------------------------------------------------------------
# Property 7 — password validation
# ---------------------------------------------------------------------------


# Strategy: passwords ≥ 8 chars excluding control characters.
_valid_password_strat = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=64,
)
_short_password_strat = st.text(min_size=0, max_size=7)
_email_local_strat = st.text(
    alphabet=st.characters(
        whitelist_categories=(),  # disable Unicode category whitelisting
        whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789._-",
    ),
    min_size=1,
    max_size=24,
).filter(lambda s: s.strip() != "")


@given(password=_short_password_strat, local=_email_local_strat)
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_short_password_rejected(password: str, local: str) -> None:
    """Property 7 — any password shorter than 8 chars is rejected."""
    email = f"{local}@example.com"
    with pytest.raises(ValueError, match="at least 8 characters"):
        fp_auth.validate_password_rules(password, email)


@given(local=_email_local_strat)
@settings(max_examples=200)
def test_password_equal_to_email_local_part_rejected(local: str) -> None:
    """Property 7 — password equal to lower(email local-part) rejected.

    Tested case-insensitively: both the literal local part and a
    case-flipped variant must be rejected when length permits.
    """
    # Pad the local part to ≥ 8 chars so the length check doesn't fire
    # first; the test then asserts the email-match rule kicks in.
    if len(local) < 8:
        local = (local + "abcdefgh")[:8]
    email = f"{local}@example.com"

    with pytest.raises(ValueError, match="must not match your email"):
        fp_auth.validate_password_rules(local, email)
    with pytest.raises(ValueError, match="must not match your email"):
        fp_auth.validate_password_rules(local.upper(), email)


@given(password=_valid_password_strat, local=_email_local_strat)
@settings(max_examples=200)
def test_valid_password_accepted(password: str, local: str) -> None:
    """A long-enough password unrelated to the email passes validation."""
    if len(local) < 8:
        local = (local + "abcdefgh")[:8]
    email = f"{local}@example.com"
    # Avoid the degenerate case where the random passwords happens to
    # equal the local part — that's covered by the previous test.
    if password.strip().lower() == local.strip().lower():
        return
    fp_auth.validate_password_rules(password, email)  # no exception


# ---------------------------------------------------------------------------
# Property 7 — bcrypt round-trip
# ---------------------------------------------------------------------------


@given(password=_valid_password_strat)
@settings(max_examples=10, deadline=None)  # bcrypt cost 12 is slow
def test_bcrypt_round_trip(password: str) -> None:
    """``verify_password(plain, hash_password(plain))`` is always True."""
    hashed = fp_auth.hash_password(password)
    assert fp_auth.verify_password(password, hashed) is True
    # And mismatch returns False rather than raising.
    assert fp_auth.verify_password(password + "x", hashed) is False


def test_hash_password_is_salted() -> None:
    """Two hashes of the same password must differ (random salt)."""
    h1 = fp_auth.hash_password("Correct-Horse-1")
    h2 = fp_auth.hash_password("Correct-Horse-1")
    assert h1 != h2
    assert fp_auth.verify_password("Correct-Horse-1", h1)
    assert fp_auth.verify_password("Correct-Horse-1", h2)


def test_verify_password_handles_garbage() -> None:
    """``verify_password`` returns False (never raises) on bad inputs."""
    assert fp_auth.verify_password("", "") is False
    assert fp_auth.verify_password("anything", "not-a-bcrypt-hash") is False
    assert fp_auth.verify_password("anything", "") is False


# ---------------------------------------------------------------------------
# Property 6 — Login lockout state machine
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Single time source for the lockout tests."""
    return datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)


@given(n=st.integers(min_value=1, max_value=4))
@settings(max_examples=50)
def test_n_failed_attempts_below_threshold_no_lock(n: int) -> None:
    """Property 6 — N < threshold failed attempts ⇒ counter increments,
    no lock applied."""
    account = _FakeAccount()
    now = _now()
    for _ in range(n):
        fp_auth.record_failed_attempt(account, now=now)

    assert account.failed_login_attempts == n
    assert account.locked_until is None
    assert account.is_locked_permanently is False
    assert fp_auth.check_locked(account, now=now) is False


def test_threshold_th_failed_attempt_locks() -> None:
    """Property 6 — the 5th failure sets locked_until = now + 30 min."""
    account = _FakeAccount()
    now = _now()
    for _ in range(5):
        fp_auth.record_failed_attempt(account, now=now)

    assert account.failed_login_attempts == 5
    assert account.locked_until == now + timedelta(minutes=30)
    assert account.is_locked_permanently is False
    assert fp_auth.check_locked(account, now=now) is True


def test_failed_attempt_during_lock_does_not_increment() -> None:
    """Property 6 — failed attempts while locked are no-ops (Req 3.5)."""
    account = _FakeAccount()
    now = _now()
    for _ in range(5):
        fp_auth.record_failed_attempt(account, now=now)
    snapshot = (account.failed_login_attempts, account.locked_until)

    # Same time — still locked. Five more attempts must be no-ops.
    for _ in range(5):
        fp_auth.record_failed_attempt(account, now=now)

    assert (account.failed_login_attempts, account.locked_until) == snapshot
    assert account.is_locked_permanently is False


def test_failed_attempt_after_lock_expires_increments_again() -> None:
    """Property 6 — after locked_until passes, counter resumes increment."""
    account = _FakeAccount()
    now = _now()
    for _ in range(5):
        fp_auth.record_failed_attempt(account, now=now)
    assert account.failed_login_attempts == 5

    # Jump past the lockout window.
    later = now + timedelta(minutes=31)
    assert fp_auth.check_locked(account, now=later) is False

    fp_auth.record_failed_attempt(account, now=later)
    assert account.failed_login_attempts == 6


def test_permanent_lock_at_threshold() -> None:
    """Property 6 + Req 21.7 — hitting permanent_lock_threshold sets the
    flag and clears locked_until (so admin-unlock is the only path out)."""
    account = _FakeAccount()
    now = _now()
    # Walk through enough failed attempts to cross the permanent threshold.
    # We must advance time past each temporary lock window so the counter
    # keeps incrementing.
    current = now
    while account.is_locked_permanently is False:
        fp_auth.record_failed_attempt(account, now=current)
        if account.locked_until and account.locked_until > current:
            current = account.locked_until + timedelta(seconds=1)

    assert account.failed_login_attempts == fp_auth.DEFAULT_PERMANENT_LOCK_THRESHOLD
    assert account.is_locked_permanently is True
    # Even after a long time, permanent lock stays true.
    much_later = current + timedelta(days=365)
    assert fp_auth.check_locked(account, now=much_later) is True


def test_reset_lockout_clears_temp_state_only() -> None:
    """Property 6 — reset_lockout clears counter + temp lock, NOT permanent."""
    account = _FakeAccount(
        failed_login_attempts=4,
        locked_until=_now() + timedelta(minutes=30),
        is_locked_permanently=True,
    )
    fp_auth.reset_lockout(account)

    assert account.failed_login_attempts == 0
    assert account.locked_until is None
    # Permanent lock survives the temporary reset (Req 21.7 — only admin
    # unlock can clear it).
    assert account.is_locked_permanently is True


def test_check_locked_handles_naive_timestamps() -> None:
    """Defensive — code passes a naive locked_until still works."""
    naive_until = datetime(2026, 5, 22, 11, 0, 0)
    account = _FakeAccount(locked_until=naive_until)
    aware_now = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)
    # Naive value is read as UTC.
    assert fp_auth.check_locked(account, now=aware_now) is True

    after = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert fp_auth.check_locked(account, now=after) is False


# ---------------------------------------------------------------------------
# Token freshness
# ---------------------------------------------------------------------------


def test_invite_token_fresh_within_seven_days() -> None:
    now = _now()
    just_sent = now - timedelta(days=6, hours=23)
    assert fp_auth.is_invite_token_fresh(just_sent, now=now) is True

    eight_days = now - timedelta(days=8)
    assert fp_auth.is_invite_token_fresh(eight_days, now=now) is False

    assert fp_auth.is_invite_token_fresh(None, now=now) is False


def test_reset_token_fresh_within_one_hour() -> None:
    now = _now()
    expires_in_30m = now + timedelta(minutes=30)
    assert fp_auth.is_reset_token_fresh(expires_in_30m, now=now) is True

    expired_5m_ago = now - timedelta(minutes=5)
    assert fp_auth.is_reset_token_fresh(expired_5m_ago, now=now) is False

    assert fp_auth.is_reset_token_fresh(None, now=now) is False


# ---------------------------------------------------------------------------
# Token entropy
# ---------------------------------------------------------------------------


def test_generated_tokens_are_url_safe_and_long() -> None:
    """secrets.token_urlsafe(32) yields a 43-char URL-safe base64 string."""
    invite = fp_auth.generate_invite_token()
    reset = fp_auth.generate_reset_token()
    assert len(invite) >= 32
    assert len(reset) >= 32
    # Two consecutive calls return distinct tokens with overwhelming
    # probability — the test uses a different pair for each generator.
    assert fp_auth.generate_invite_token() != invite
    assert fp_auth.generate_reset_token() != reset
    # Only URL-safe base64 alphabet.
    import re
    assert re.fullmatch(r"[A-Za-z0-9_-]+", invite)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", reset)
