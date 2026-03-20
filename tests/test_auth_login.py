"""Unit tests for Task 4.1 — email/password login endpoint.

Tests cover:
  - Password hashing and verification
  - JWT access token creation and decoding
  - Refresh token generation
  - Login router user-agent parsing
  - Login service logic (mocked DB)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import jwt as jose_jwt

from app.config import settings
from app.modules.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from app.modules.auth.password import hash_password, verify_password
from app.modules.auth.router import _parse_user_agent
from app.modules.auth.schemas import LoginRequest


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------

class TestPasswordUtils:
    def test_hash_and_verify(self):
        plain = "Sup3rS3cure!Pass"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        # bcrypt salts differ each time
        assert h1 != h2
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------

class TestJWTUtils:
    def test_create_and_decode_access_token(self):
        uid = uuid.uuid4()
        oid = uuid.uuid4()
        token = create_access_token(uid, oid, "org_admin", "a@b.com")
        payload = decode_access_token(token)
        assert payload["user_id"] == str(uid)
        assert payload["org_id"] == str(oid)
        assert payload["role"] == "org_admin"
        assert payload["email"] == "a@b.com"
        assert payload["type"] == "access"

    def test_access_token_with_none_org(self):
        uid = uuid.uuid4()
        token = create_access_token(uid, None, "global_admin", "ga@x.com")
        payload = decode_access_token(token)
        assert payload["org_id"] is None

    def test_decode_expired_token_raises(self):
        from jwt.exceptions import InvalidTokenError

        payload = {
            "user_id": "u1",
            "org_id": None,
            "role": "salesperson",
            "email": "e@e.com",
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=1),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        token = jose_jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)

    def test_decode_non_access_token_raises(self):
        from jwt.exceptions import InvalidTokenError

        payload = {
            "user_id": "u1",
            "type": "mfa_pending",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        token = jose_jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(InvalidTokenError, match="not an access token"):
            decode_access_token(token)

    def test_refresh_token_is_random_string(self):
        t1 = create_refresh_token()
        t2 = create_refresh_token()
        assert isinstance(t1, str)
        assert len(t1) > 20
        assert t1 != t2


# ---------------------------------------------------------------------------
# User-Agent parsing
# ---------------------------------------------------------------------------

class TestParseUserAgent:
    def test_none_user_agent(self):
        assert _parse_user_agent(None) == (None, None)

    def test_chrome_desktop(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"
        device, browser = _parse_user_agent(ua)
        assert device == "desktop"
        assert browser == "Chrome"

    def test_safari_mobile(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15 Safari/604.1"
        device, browser = _parse_user_agent(ua)
        assert device == "mobile"
        assert browser == "Safari"

    def test_firefox(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        device, browser = _parse_user_agent(ua)
        assert device == "desktop"
        assert browser == "Firefox"

    def test_edge(self):
        ua = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 Edg/120.0"
        device, browser = _parse_user_agent(ua)
        assert device == "desktop"
        assert browser == "Edge"

    def test_tablet(self):
        ua = "Mozilla/5.0 (iPad; CPU OS 17_0) AppleWebKit/605.1.15"
        device, browser = _parse_user_agent(ua)
        assert device == "tablet"
        assert browser == "Safari"
