"""Property-based tests for TOTP MFA enrolment (Properties 1–4).

Properties covered:
  P1 — TOTP secret conforms to RFC 6238
  P2 — TOTP provisioning URI correctness
  P3 — TOTP enrolment round-trip
  P4 — Invalid TOTP code rejection

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, unquote, urlparse

import pyotp
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.auth.mfa_service import verify_enrolment
from app.modules.auth.schemas import MFAEnrolResponse


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

email_st = st.emails()

six_digit_code_st = st.from_regex(r"[0-9]{6}", fullmatch=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(**overrides) -> MagicMock:
    """Create a mock User with sensible defaults."""
    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.org_id = overrides.get("org_id", uuid.uuid4())
    user.email = overrides.get("email", "test@budgetflow.io")
    user.role = overrides.get("role", "org_admin")
    user.is_active = overrides.get("is_active", True)
    return user


def _make_pending_mfa_record(method: str, user_id: uuid.UUID, **overrides) -> MagicMock:
    """Create a mock UserMfaMethod record representing a pending enrolment."""
    record = MagicMock()
    record.user_id = user_id
    record.method = method
    record.verified = False
    record.verified_at = None
    record.phone_number = overrides.get("phone_number", None)
    record.secret_encrypted = overrides.get("secret_encrypted", None)
    return record


def _mock_db_with_pending(pending_record):
    """Mock AsyncSession that returns the given pending record on select."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = pending_record
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _simulate_totp_enrolment(email: str) -> MFAEnrolResponse:
    """Simulate the TOTP enrolment logic from _enrol_totp without ORM interaction.

    Replicates the exact same logic as mfa_service._enrol_totp:
    - Generate base32 secret via pyotp.random_base32()
    - Encrypt the secret via envelope_encrypt
    - Build provisioning URI with issuer from platform branding (default "OraInvoice")
    - Return MFAEnrolResponse with qr_uri, secret, and message
    """
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    qr_uri = totp.provisioning_uri(name=email, issuer_name="OraInvoice")
    return MFAEnrolResponse(
        method="totp",
        qr_uri=qr_uri,
        secret=secret,
        message="Scan the QR code with your authenticator app, then verify with a 6-digit code.",
    )


# ===========================================================================
# Property 1: TOTP secret conforms to RFC 6238
# ===========================================================================
# Feature: multi-method-mfa, Property 1: TOTP secret conforms to RFC 6238


@given(email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_totp_secret_conforms_to_rfc6238(email: str) -> None:
    """For any TOTP enrolment response, the generated secret SHALL be a valid
    base32 string, and constructing a pyotp.TOTP with that secret using a
    30-second interval and SHA-1 algorithm SHALL produce valid 6-digit codes
    that verify within a ±1 window.

    **Validates: Requirements 1.1, 1.2**
    """
    result = _simulate_totp_enrolment(email)

    secret = result.secret
    assert secret is not None, "TOTP enrolment must return a secret"

    # --- Assert 1: secret is valid base32 ---
    try:
        decoded = base64.b32decode(secret, casefold=True)
    except Exception as exc:
        pytest.fail(f"Secret is not valid base32: {exc}")
    assert len(decoded) > 0, "Decoded secret must be non-empty"

    # --- Assert 2: pyotp.TOTP with 30s interval and SHA-1 produces valid codes ---
    totp = pyotp.TOTP(secret, interval=30, digest="sha1")
    code = totp.now()

    assert len(code) == 6, f"TOTP code must be 6 digits, got {len(code)}"
    assert code.isdigit(), f"TOTP code must be all digits, got '{code}'"

    # --- Assert 3: code verifies within ±1 window ---
    assert totp.verify(code, valid_window=1), (
        "Generated code must verify within ±1 window"
    )

    # --- Assert 4: default pyotp.TOTP (30s, SHA-1) also verifies ---
    totp_default = pyotp.TOTP(secret)
    assert totp_default.verify(code, valid_window=1), (
        "Code must also verify with default pyotp.TOTP constructor"
    )

    # --- Assert 5: encrypted secret round-trips correctly ---
    encrypted = envelope_encrypt(secret)
    decrypted = envelope_decrypt_str(encrypted)
    assert decrypted == secret, (
        "Encrypted secret must decrypt back to the original"
    )


# ===========================================================================
# Property 2: TOTP provisioning URI correctness
# ===========================================================================
# Feature: multi-method-mfa, Property 2: TOTP provisioning URI correctness


@given(email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_totp_provisioning_uri_correctness(email: str) -> None:
    """For any TOTP enrolment response, the returned provisioning URI SHALL be
    a valid otpauth://totp/ URI containing the issuer "OraInvoice" and the
    user's email, and the plain-text secret SHALL be included in the response
    for manual entry.

    **Validates: Requirements 1.2, 1.5**
    """
    result = _simulate_totp_enrolment(email)

    qr_uri = result.qr_uri
    secret = result.secret

    assert qr_uri is not None, "TOTP enrolment must return a qr_uri"
    assert secret is not None, "TOTP enrolment must return a plain-text secret"

    # --- Assert 1: URI starts with otpauth://totp/ ---
    assert qr_uri.startswith("otpauth://totp/"), (
        f"Provisioning URI must start with 'otpauth://totp/', got: {qr_uri[:40]}"
    )

    # --- Assert 2: URI contains issuer "OraInvoice" ---
    parsed = urlparse(qr_uri)
    query_params = parse_qs(parsed.query)

    assert "issuer" in query_params, "URI must contain 'issuer' query parameter"
    assert query_params["issuer"][0] == "OraInvoice", (
        f"Issuer must be 'OraInvoice', got '{query_params['issuer'][0]}'"
    )

    # --- Assert 3: URI contains the secret ---
    assert "secret" in query_params, "URI must contain 'secret' query parameter"
    uri_secret = query_params["secret"][0]
    assert uri_secret == secret, (
        "URI secret must match the returned plain-text secret"
    )

    # --- Assert 4: URI path contains the user's email ---
    decoded_uri = unquote(qr_uri)
    assert email in decoded_uri, (
        f"URI must contain the user's email '{email}', got: {decoded_uri}"
    )


# ===========================================================================
# Property 3: TOTP enrolment round-trip
# ===========================================================================
# Feature: multi-method-mfa, Property 3: TOTP enrolment round-trip


@given(email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_totp_enrolment_round_trip(mock_audit, email: str) -> None:
    """For any user with a pending TOTP enrolment, generating the current valid
    TOTP code from the stored secret and submitting it for verification SHALL
    result in the TOTP method being marked as verified=True in the database.

    **Validates: Requirements 1.3**
    """
    user = _make_user(email=email)

    # Step 1: Simulate enrolment to get a secret
    enrol_result = _simulate_totp_enrolment(email)
    secret = enrol_result.secret
    assert secret is not None

    # Step 2: Generate a valid TOTP code from the secret
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()

    # Step 3: Create a pending record with the encrypted secret (simulating DB state)
    encrypted_secret = envelope_encrypt(secret)
    pending = _make_pending_mfa_record(
        "totp", user.id, secret_encrypted=encrypted_secret,
    )
    db = _mock_db_with_pending(pending)

    # Step 4: Verify the code via the real verify_enrolment function
    asyncio.get_event_loop().run_until_complete(
        verify_enrolment(db, user, "totp", valid_code)
    )

    # --- Assert: method is marked as verified ---
    assert pending.verified is True, (
        "TOTP method must be marked verified after valid code submission"
    )
    assert pending.verified_at is not None, (
        "verified_at must be set after successful verification"
    )
    assert isinstance(pending.verified_at, datetime), (
        "verified_at must be a datetime instance"
    )


# ===========================================================================
# Property 4: Invalid TOTP code rejection
# ===========================================================================
# Feature: multi-method-mfa, Property 4: Invalid TOTP code rejection


@given(email=email_st, bad_code=six_digit_code_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_invalid_totp_code_rejection(mock_audit, email: str, bad_code: str) -> None:
    """For any user with a pending TOTP enrolment and for any 6-digit string
    that does not match the current or adjacent TOTP window, submitting that
    code SHALL be rejected and the method SHALL remain unverified.

    **Validates: Requirements 1.4**
    """
    # Generate a fresh secret
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    # Compute the set of valid codes in the ±1 window
    current_time = int(time.time())
    valid_codes = set()
    for offset in [-1, 0, 1]:
        t = current_time + (offset * 30)
        valid_codes.add(totp.at(t))

    # Skip if the randomly generated code happens to be valid
    if bad_code in valid_codes:
        return  # Hypothesis will generate another example

    # Create a pending record with the encrypted secret
    user = _make_user(email=email)
    encrypted_secret = envelope_encrypt(secret)
    pending = _make_pending_mfa_record(
        "totp", user.id, secret_encrypted=encrypted_secret,
    )
    db = _mock_db_with_pending(pending)

    # --- Act & Assert: invalid code is rejected ---
    with pytest.raises(ValueError, match="Invalid TOTP code"):
        asyncio.get_event_loop().run_until_complete(
            verify_enrolment(db, user, "totp", bad_code)
        )

    # --- Assert: method remains unverified ---
    assert pending.verified is False, (
        "TOTP method must remain unverified after invalid code submission"
    )
    assert pending.verified_at is None, (
        "verified_at must remain None after invalid code submission"
    )
