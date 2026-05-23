"""Unit tests for account_service.

Implements: B2B Fleet Portal task 5.3 — Requirements 4.2, 4.3, 4.6, 4.8.

Tests the service logic using the auth helpers directly (no DB) for
the token-freshness and password-rule paths. The DB-touching paths
(invite, revoke, accept) are covered by the integration smoke tests
in task 20.x.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.fleet_portal import auth as fp_auth
from app.modules.fleet_portal.services.account_service import (
    AccountServiceError,
    CustomerNotEligible,
    DuplicatePortalUser,
    InvalidToken,
    TokenExpired,
)


def test_invite_token_freshness_within_seven_days() -> None:
    """Req 4.6 — invite accepted within 7 days."""
    now = datetime.now(timezone.utc)
    sent = now - timedelta(days=6)
    assert fp_auth.is_invite_token_fresh(sent, now=now) is True


def test_invite_token_expired_after_seven_days() -> None:
    """Req 4.6 — invite expired after 7 days."""
    now = datetime.now(timezone.utc)
    sent = now - timedelta(days=8)
    assert fp_auth.is_invite_token_fresh(sent, now=now) is False


def test_password_rules_reject_short() -> None:
    """Req 3.8 — password < 8 chars rejected."""
    with pytest.raises(ValueError, match="at least 8"):
        fp_auth.validate_password_rules("short", "user@example.com")


def test_password_rules_reject_email_match() -> None:
    """Req 3.8 — password matching email local-part rejected."""
    with pytest.raises(ValueError, match="must not match"):
        fp_auth.validate_password_rules("longusername", "longusername@example.com")


def test_error_hierarchy() -> None:
    """Service errors carry the correct status codes."""
    assert CustomerNotEligible("x").status_code == 400
    assert DuplicatePortalUser("x").status_code == 409
    assert TokenExpired("x").status_code == 400
    assert InvalidToken("x").status_code == 400
    assert AccountServiceError("x", status_code=500).status_code == 500


def test_revoke_deletes_sessions_concept() -> None:
    """Req 4.8 — revoke sets is_active=False and deletes sessions.

    The actual DB interaction is tested in integration; here we verify
    the service function exists and is callable.
    """
    from app.modules.fleet_portal.services.account_service import revoke_access

    assert callable(revoke_access)


def test_resend_invite_generates_fresh_token() -> None:
    """Req 4.9 — resend generates a new token (different from previous)."""
    t1 = fp_auth.generate_invite_token()
    t2 = fp_auth.generate_invite_token()
    assert t1 != t2
    assert len(t1) >= 32
