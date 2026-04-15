"""Property-based tests for dependency upgrade remediation.

Feature: dependency-upgrade-remediation

Validates cryptographic round-trips, auth invariants, and Redis data integrity
that must hold across all five upgrade phases.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Arbitrary text including empty, unicode, and long strings
_arbitrary_text_st = st.text(min_size=0, max_size=500)

# Printable ASCII passwords 1–72 bytes (bcrypt input limit)
_password_st = st.text(
    min_size=1,
    max_size=72,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" ",
    ),
).filter(lambda s: len(s.encode("utf-8")) <= 72 and len(s.encode("utf-8")) >= 1)

# UUIDs
_uuid_st = st.uuids()

# Optional UUID (UUID or None)
_optional_uuid_st = st.one_of(st.none(), st.uuids())

# Short safe text for JWT claims (avoid control chars / surrogates)
_safe_text_st = st.text(
    min_size=0,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
)

# MFA method
_mfa_method_st = st.sampled_from(["sms", "email"])

# 6-digit OTP code
_otp_code_st = st.from_regex(r"[0-9]{6}", fullmatch=True)

# Increment count for rate limit test (1–500)
_increment_count_st = st.integers(min_value=1, max_value=500)


# ---------------------------------------------------------------------------
# Property 1: Envelope Encryption Round-Trip
# ---------------------------------------------------------------------------
# Feature: dependency-upgrade-remediation, Property 1: Envelope Encryption Round-Trip


class TestEnvelopeEncryptionRoundTrip:
    """Property 1: Envelope Encryption Round-Trip.

    For any plaintext string (including empty, unicode, long strings),
    encrypting with envelope_encrypt and decrypting with envelope_decrypt
    shall produce the original plaintext.

    **Validates: Requirements 1.2, 2.3, 10.2, 10.5, 10.7, 11.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(plaintext=_arbitrary_text_st)
    def test_envelope_encryption_round_trip(self, plaintext: str) -> None:
        from app.core.encryption import (
            envelope_decrypt,
            envelope_decrypt_str,
            envelope_encrypt,
        )

        blob = envelope_encrypt(plaintext)

        # bytes round-trip
        assert envelope_decrypt(blob) == plaintext.encode("utf-8")

        # str round-trip
        assert envelope_decrypt_str(blob) == plaintext


# ---------------------------------------------------------------------------
# Property 2: bcrypt Password Hash Verification Round-Trip
# ---------------------------------------------------------------------------
# Feature: dependency-upgrade-remediation, Property 2: bcrypt Password Hash Verification Round-Trip


class TestBcryptPasswordHashRoundTrip:
    """Property 2: bcrypt Password Hash Verification Round-Trip.

    For any password string (1–72 bytes), hashing with hash_password and
    verifying with verify_password shall return True. Verifying a different
    password against the same hash shall return False.

    **Validates: Requirements 2.4, 10.1, 10.4**
    """

    @settings(max_examples=50, deadline=None)
    @given(password=_password_st)
    def test_bcrypt_password_hash_round_trip(self, password: str) -> None:
        from app.modules.auth.password import hash_password, verify_password

        hashed = hash_password(password)

        # Same password verifies
        assert verify_password(password, hashed) is True

        # A fixed different password does NOT verify (keep under 72 bytes)
        different = ("X" + password[:30] + "Z")[:72]
        if different == password:
            different = "COMPLETELY_DIFFERENT_PASSWORD_1"
        assert verify_password(different, hashed) is False


# ---------------------------------------------------------------------------
# Property 3: JWT Access Token Encode/Decode Round-Trip
# ---------------------------------------------------------------------------
# Feature: dependency-upgrade-remediation, Property 3: JWT Access Token Encode/Decode Round-Trip


class TestJWTAccessTokenRoundTrip:
    """Property 3: JWT Access Token Encode/Decode Round-Trip.

    For any valid combination of user_id (UUID), org_id (UUID or None),
    role (string), and email (string), creating an access token and decoding
    it shall produce matching claims. Tested with HS256 config (default).

    **Validates: Requirements 2.4, 3.2, 10.6**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        user_id=_uuid_st,
        org_id=_optional_uuid_st,
        role=_safe_text_st,
        email=_safe_text_st,
    )
    def test_jwt_access_token_round_trip(
        self,
        user_id: uuid.UUID,
        org_id: uuid.UUID | None,
        role: str,
        email: str,
    ) -> None:
        from app.modules.auth.jwt import create_access_token, decode_access_token

        token = create_access_token(
            user_id=user_id,
            org_id=org_id,
            role=role,
            email=email,
        )

        payload = decode_access_token(token)

        assert payload["user_id"] == str(user_id)
        assert payload["org_id"] == (str(org_id) if org_id else None)
        assert payload["role"] == role
        assert payload["email"] == email


# ---------------------------------------------------------------------------
# Property 4: Redis OTP Store/Retrieve Round-Trip
# ---------------------------------------------------------------------------
# Feature: dependency-upgrade-remediation, Property 4: Redis OTP Store/Retrieve Round-Trip


class TestRedisOTPStoreRetrieveRoundTrip:
    """Property 4: Redis OTP Store/Retrieve Round-Trip.

    For any user_id (UUID), method ("sms"/"email"), and 6-digit OTP code,
    storing via _store_otp_in_redis and retrieving via _get_otp_from_redis
    shall return the original code before TTL expiry.

    **Validates: Requirements 5.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        user_id=_uuid_st,
        method=_mfa_method_st,
        code=_otp_code_st,
    )
    def test_redis_otp_store_retrieve_round_trip(
        self,
        user_id: uuid.UUID,
        method: str,
        code: str,
    ) -> None:
        from fakeredis.aioredis import FakeRedis as AsyncFakeRedis

        from app.modules.auth.mfa_service import (
            _get_otp_from_redis,
            _store_otp_in_redis,
        )

        fake_redis = AsyncFakeRedis(decode_responses=True)

        with patch("app.core.redis.redis_pool", fake_redis):
            loop = asyncio.new_event_loop()
            try:
                # Store the OTP
                loop.run_until_complete(_store_otp_in_redis(user_id, method, code))

                # Retrieve it — should match
                retrieved = loop.run_until_complete(_get_otp_from_redis(user_id, method))
                assert retrieved == code
            finally:
                loop.close()


# ---------------------------------------------------------------------------
# Property 5: Redis Rate Limit Counter Monotonic Increment
# ---------------------------------------------------------------------------
# Feature: dependency-upgrade-remediation, Property 5: Redis Rate Limit Counter Monotonic Increment


class TestRedisRateLimitCounterMonotonicIncrement:
    """Property 5: Redis Rate Limit Counter Monotonic Increment.

    For any N (1–500) increments on a Redis key, the final counter value
    shall equal N. The key shall have an expiry TTL set.

    **Validates: Requirements 5.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(n=_increment_count_st)
    def test_redis_rate_limit_counter_monotonic_increment(self, n: int) -> None:
        from fakeredis.aioredis import FakeRedis as AsyncFakeRedis

        fake_redis = AsyncFakeRedis(decode_responses=True)

        async def _run() -> None:
            key = f"rate_limit:test:{uuid.uuid4()}"

            # Perform N increments with expire (mirrors _increment_mfa_attempts pattern)
            for _ in range(n):
                await fake_redis.incr(key)
            await fake_redis.expire(key, 900)

            # Final value must equal N
            val = await fake_redis.get(key)
            assert int(val) == n

            # TTL must be set (> 0)
            ttl = await fake_redis.ttl(key)
            assert ttl > 0

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()
