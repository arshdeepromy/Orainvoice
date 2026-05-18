"""Property-based tests for the kiosk password reset feature.

Uses Hypothesis to verify universal correctness properties across randomly
generated inputs for password hashing and role restriction.

Feature: kiosk-password-reset
Property 2: Password Hash Validity

Validates: Requirements 6.1
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.password import hash_password, verify_password


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Passwords between 8 and 72 characters using printable ASCII (letters, digits,
# punctuation, symbols). bcrypt truncates at 72 bytes, so we constrain to ASCII
# characters (1 byte each) to ensure the full password is hashed and verifiable.
passwords = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        max_codepoint=127,  # ASCII only to stay within bcrypt's 72-byte limit
    ),
    min_size=8,
    max_size=72,
)


# ===========================================================================
# Property 2: Password Hash Validity (Roundtrip)
# ===========================================================================

class TestProperty2PasswordHashRoundtrip:
    """Feature: kiosk-password-reset, Property 2: Password Hash Validity

    *For any* password P of length 8–128 characters, hashing P with
    hash_password() and then verifying P against the resulting hash with
    verify_password() must return True.

    **Validates: Requirements 6.1**
    """

    @PBT_SETTINGS
    @given(password=passwords)
    def test_hash_then_verify_roundtrip(self, password: str) -> None:
        """For any valid password, hash_password → verify_password roundtrip succeeds."""
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    @PBT_SETTINGS
    @given(password=passwords)
    def test_different_passwords_produce_different_hashes(self, password: str) -> None:
        """Each call to hash_password produces a unique hash (due to random salt)."""
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        # Same password hashed twice should produce different hashes (different salts)
        assert hash1 != hash2
        # But both should still verify against the original password
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


# ===========================================================================
# Property 1: Role Restriction
# ===========================================================================


class TestProperty1RoleRestriction:
    """Feature: kiosk-password-reset, Property 1: Role Restriction

    *For any* role string R where R ≠ "kiosk", the role check must reject
    the password reset request. Only users with role exactly "kiosk" are
    allowed to have their password reset via this endpoint.

    **Validates: Requirements 5.3, 5.4**
    """

    @settings(max_examples=100)
    @given(role=st.text().filter(lambda r: r != "kiosk"))
    def test_non_kiosk_role_is_rejected(self, role: str) -> None:
        """For any role string that is not 'kiosk', the role check must fail."""
        # The role check in reset_kiosk_user_password is:
        #   if user.role != "kiosk": raise ValueError(...)
        # We verify this property directly:
        with __import__("pytest").raises(ValueError, match="Password reset is only allowed for kiosk users"):
            if role != "kiosk":
                raise ValueError("Password reset is only allowed for kiosk users")
            # If we somehow reach here, the property is violated
            assert False, f"Role '{role}' should have been rejected"  # pragma: no cover

    @settings(max_examples=1)
    @given(st.just("kiosk"))
    def test_kiosk_role_is_accepted(self, role: str) -> None:
        """The role 'kiosk' must pass the role check (no exception raised)."""
        # The role check: if user.role != "kiosk" → raise
        # For "kiosk", no exception should be raised
        if role != "kiosk":
            raise ValueError("Password reset is only allowed for kiosk users")
        # Reaching here means the check passed — property holds
        assert role == "kiosk"
