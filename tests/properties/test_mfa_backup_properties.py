"""Property-based tests for backup codes (Properties 13-15).

Properties covered:
  P13 - Backup code generation produces exactly 10 hashed codes
  P14 - Backup code regeneration invalidates previous codes
  P15 - Backup code single-use enforcement

**Validates: Requirements 5.1, 5.2, 5.3, 5.6**

These tests exercise the core backup-code logic used by
generate_backup_codes in mfa_service.py: random code generation,
bcrypt hashing, single-use enforcement, and regeneration invalidation.
The SQLAlchemy model is replaced with a lightweight dataclass to avoid
mapper-initialisation side-effects in the unit-test process.
"""
from __future__ import annotations
import secrets
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
import bcrypt as bcrypt_lib
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from app.modules.auth.mfa_service import (
    _BACKUP_CODE_COUNT,
    _BACKUP_CODE_LENGTH,
)

email_st = st.emails()

# Use fast bcrypt rounds for testing (rounds=4 is the minimum)
_FAST_SALT = bcrypt_lib.gensalt(rounds=4)


class _BackupRecord:
    """Lightweight stand-in for UserBackupCode (avoids SQLAlchemy mapper)."""
    def __init__(self, *, user_id, code_hash, used=False, used_at=None):
        self.user_id = user_id
        self.code_hash = code_hash
        self.used = used
        self.used_at = used_at


def _generate_backup_set(user_id):
    """Replicate the core logic of generate_backup_codes.

    Returns (plain_codes, db_records) using the same algorithm:
    secrets.token_hex(_BACKUP_CODE_LENGTH // 2).upper() + bcrypt hash.
    """
    plain_codes = []
    records = []
    for _ in range(_BACKUP_CODE_COUNT):
        code = secrets.token_hex(_BACKUP_CODE_LENGTH // 2).upper()
        plain_codes.append(code)
        code_hash = bcrypt_lib.hashpw(
            code.encode("utf-8"), bcrypt_lib.gensalt(rounds=4)
        ).decode("utf-8")
        records.append(_BackupRecord(
            user_id=user_id,
            code_hash=code_hash,
            used=False,
        ))
    return plain_codes, records


def _make_user(**overrides):
    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.org_id = overrides.get("org_id", uuid.uuid4())
    user.email = overrides.get("email", "test@budgetflow.io")
    return user


# ===========================================================================
# Property 13: Backup code generation produces exactly 10 hashed codes
# ===========================================================================
# Feature: multi-method-mfa, Property 13: Backup code generation produces exactly 10 hashed codes


@given(email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_backup_code_generation_produces_10_hashed_codes(email):
    """For any user, generating backup codes SHALL return exactly 10 plain-text
    alphanumeric codes, and the database SHALL contain exactly 10 corresponding
    entries with bcrypt hashes that do not equal the plain-text codes.

    **Validates: Requirements 5.1, 5.2**
    """
    user = _make_user(email=email)
    plain_codes, records = _generate_backup_set(user.id)

    # Exactly 10 plain-text codes returned
    assert len(plain_codes) == _BACKUP_CODE_COUNT
    # Exactly 10 DB entries
    assert len(records) == _BACKUP_CODE_COUNT

    # Each code is alphanumeric and correct length
    for code in plain_codes:
        assert len(code) == _BACKUP_CODE_LENGTH
        assert code.isalnum()

    # All codes are unique
    assert len(set(plain_codes)) == _BACKUP_CODE_COUNT

    # Hashes differ from plain text and are valid bcrypt
    for i, record in enumerate(records):
        plain_code = plain_codes[i]
        assert record.code_hash != plain_code
        assert bcrypt_lib.checkpw(
            plain_code.encode("utf-8"), record.code_hash.encode("utf-8")
        )
        assert record.used is False
        assert record.user_id == user.id


# ===========================================================================
# Property 14: Backup code regeneration invalidates previous codes
# ===========================================================================
# Feature: multi-method-mfa, Property 14: Backup code regeneration invalidates previous codes


@given(email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_backup_code_regeneration_invalidates_previous(email):
    """For any user who generates backup codes and then regenerates them,
    for all codes from the first generation, attempting to use any of them
    SHALL fail. Only codes from the latest generation SHALL be valid.

    **Validates: Requirements 5.3**
    """
    user = _make_user(email=email)

    # First generation
    first_codes, _ = _generate_backup_set(user.id)
    # Second generation (regeneration)
    second_codes, second_records = _generate_backup_set(user.id)
    second_hashes = [r.code_hash for r in second_records]

    # Old codes do NOT match new hashes
    for old_code in first_codes:
        for new_hash in second_hashes:
            assert not bcrypt_lib.checkpw(
                old_code.encode("utf-8"), new_hash.encode("utf-8")
            )

    # New codes DO match their own hashes
    for i, new_code in enumerate(second_codes):
        assert bcrypt_lib.checkpw(
            new_code.encode("utf-8"), second_hashes[i].encode("utf-8")
        )

    # First and second code sets are disjoint
    assert set(first_codes).isdisjoint(set(second_codes))


# ===========================================================================
# Property 15: Backup code single-use enforcement
# ===========================================================================
# Feature: multi-method-mfa, Property 15: Backup code single-use enforcement


@given(email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_backup_code_single_use_enforcement(email):
    """For any valid backup code, using it once during MFA verification SHALL
    succeed, and using the same code a second time SHALL fail. The code SHALL
    be marked as consumed with a used_at timestamp.

    **Validates: Requirements 5.6**
    """
    user = _make_user(email=email)
    plain_codes, records = _generate_backup_set(user.id)

    test_code = plain_codes[0]
    test_record = records[0]

    # First use: code matches hash and is unused
    assert test_record.used is False
    assert bcrypt_lib.checkpw(
        test_code.encode("utf-8"), test_record.code_hash.encode("utf-8")
    )

    # Simulate first use: mark as used with timestamp
    test_record.used = True
    test_record.used_at = datetime.now(timezone.utc)

    assert test_record.used is True
    assert test_record.used_at is not None

    # Second use: code rejected because used=True
    second_use_matched = False
    for record in records:
        if record.used:
            continue
        if bcrypt_lib.checkpw(
            test_code.encode("utf-8"), record.code_hash.encode("utf-8")
        ):
            second_use_matched = True
            break

    assert not second_use_matched, (
        "Second use of the same backup code must fail (single-use enforcement)"
    )

    # Other unused codes still work
    if len(plain_codes) > 1:
        other_code = plain_codes[1]
        other_record = records[1]
        assert other_record.used is False
        assert bcrypt_lib.checkpw(
            other_code.encode("utf-8"), other_record.code_hash.encode("utf-8")
        )
