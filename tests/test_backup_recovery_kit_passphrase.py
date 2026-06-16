"""Unit tests for Recovery-Kit shape and passphrase strength (Task 2.7).

Covers (cloud-backup-restore design "The Recovery Kit" + "Passphrase strength
rules"):

1. The Recovery-Kit JSON matches the documented shape: every documented key is
   present with the correct type, and every base64 field decodes.
2. Passphrase-strength enforcement: too-short (<16 chars) and low-entropy
   passphrases are rejected with ``PassphraseStrengthError``; a strong /
   generated passphrase is accepted.
3. ``generate_passphrase`` produces a high-entropy multi-word phrase that
   passes ``validate_passphrase``.
4. KDF params (algo/mem_kib/time/parallel) are recorded per key version
   (``default_kdf_params``) and round-trip into the recovery kit.

These tests construct ``BackupKeyVersion`` instances directly (no DB) and rely
only on the heuristic strength fallback, so they pass whether or not the
optional ``zxcvbn`` package is installed.

**Validates: Requirements 16.3, 16.4**
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

import pytest

from app.modules.backup_restore.keys.key_service import (
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    KDF_ALGO,
    MIN_PASSPHRASE_LENGTH,
    MIN_ZXCVBN_SCORE,
    RECOVERY_KIT_SPEC,
    RECOVERY_KIT_VERSION,
    PassphraseStrengthError,
    build_recovery_kit,
    default_kdf_params,
    derive_pwk,
    generate_passphrase,
    score_passphrase,
    validate_passphrase,
)
from app.modules.backup_restore.models import BackupKeyVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_version(
    version: int,
    *,
    is_active: bool,
    kdf_params: dict | None = None,
    salt: bytes | None = None,
    created_at: datetime | None = None,
) -> BackupKeyVersion:
    """Build an in-memory BackupKeyVersion with deterministic wrapped material.

    No database is involved; the wrapped fields are arbitrary bytes since these
    tests exercise the kit *shape* and base64 encoding, not cryptographic
    unwrapping.
    """
    params = kdf_params if kdf_params is not None else default_kdf_params()
    return BackupKeyVersion(
        version=version,
        is_active=is_active,
        kdf_algo=params.get("algo", KDF_ALGO),
        kdf_params=params,
        kdf_salt=salt if salt is not None else os.urandom(16),
        wrapped_bmk_passphrase=b"wrapped-bmk-pw-" + bytes([version]),
        wrapped_bmk_env=b"wrapped-bmk-env-" + bytes([version]),
        wrapped_bdk=b"wrapped-bdk-" + bytes([version]),
        bmk_kcv=b"kcv-" + bytes([version]),
        created_at=created_at,
    )


def _assert_b64_decodes(value: str) -> bytes:
    assert isinstance(value, str)
    return base64.b64decode(value, validate=True)


# ---------------------------------------------------------------------------
# 1. Recovery-Kit JSON shape
# ---------------------------------------------------------------------------


class TestRecoveryKitShape:
    """The kit JSON matches the documented shape and base64 fields decode."""

    def test_kit_has_all_documented_keys_with_correct_types(self):
        salt = os.urandom(16)
        created = datetime(2026, 5, 26, 3, 0, 0, tzinfo=timezone.utc)
        version = _make_version(1, is_active=True, salt=salt, created_at=created)

        kit = build_recovery_kit([version])

        # Top-level documented keys.
        assert set(kit.keys()) == {
            "kit_version",
            "spec",
            "created_at",
            "kdf",
            "wrapped_bmk_passphrase_b64",
            "key_versions",
            "verification",
        }

        assert kit["kit_version"] == RECOVERY_KIT_VERSION
        assert isinstance(kit["kit_version"], int)
        assert kit["spec"] == RECOVERY_KIT_SPEC
        assert isinstance(kit["created_at"], str)
        # created_at is a valid ISO-8601 timestamp.
        datetime.fromisoformat(kit["created_at"])

        # kdf block shape + types.
        kdf = kit["kdf"]
        assert set(kdf.keys()) == {"algo", "mem_kib", "time", "parallel", "salt_b64"}
        assert kdf["algo"] == KDF_ALGO
        assert isinstance(kdf["mem_kib"], int)
        assert isinstance(kdf["time"], int)
        assert isinstance(kdf["parallel"], int)
        assert isinstance(kdf["salt_b64"], str)

        # wrapped BMK + verification.
        assert isinstance(kit["wrapped_bmk_passphrase_b64"], str)
        assert isinstance(kit["verification"], dict)
        assert set(kit["verification"].keys()) == {"bmk_kcv_b64"}
        assert isinstance(kit["verification"]["bmk_kcv_b64"], str)

        # key_versions list shape.
        assert isinstance(kit["key_versions"], list)
        assert len(kit["key_versions"]) == 1
        kv = kit["key_versions"][0]
        assert set(kv.keys()) == {"version", "wrapped_bdk_b64", "created_at"}
        assert kv["version"] == 1
        assert isinstance(kv["version"], int)
        assert isinstance(kv["wrapped_bdk_b64"], str)
        assert kv["created_at"] == created.isoformat()

    def test_kit_base64_fields_decode_to_original_bytes(self):
        salt = os.urandom(16)
        version = _make_version(1, is_active=True, salt=salt)

        kit = build_recovery_kit([version])

        # salt round-trips exactly.
        assert _assert_b64_decodes(kit["kdf"]["salt_b64"]) == salt
        # wrapped material decodes to the bytes we stored.
        assert (
            _assert_b64_decodes(kit["wrapped_bmk_passphrase_b64"])
            == version.wrapped_bmk_passphrase
        )
        assert (
            _assert_b64_decodes(kit["verification"]["bmk_kcv_b64"]) == version.bmk_kcv
        )
        assert (
            _assert_b64_decodes(kit["key_versions"][0]["wrapped_bdk_b64"])
            == version.wrapped_bdk
        )

    def test_kit_orders_versions_and_uses_active_for_kdf(self):
        active_salt = os.urandom(16)
        v1 = _make_version(1, is_active=False, salt=os.urandom(16))
        v2 = _make_version(2, is_active=True, salt=active_salt)

        # Pass out of order to confirm sorting by version.
        kit = build_recovery_kit([v2, v1])

        versions = [kv["version"] for kv in kit["key_versions"]]
        assert versions == [1, 2]
        # kdf salt comes from the active (v2) version.
        assert _assert_b64_decodes(kit["kdf"]["salt_b64"]) == active_salt
        assert (
            _assert_b64_decodes(kit["wrapped_bmk_passphrase_b64"])
            == v2.wrapped_bmk_passphrase
        )

    def test_kit_handles_missing_created_at(self):
        version = _make_version(1, is_active=True, created_at=None)
        kit = build_recovery_kit([version])
        assert kit["key_versions"][0]["created_at"] is None


# ---------------------------------------------------------------------------
# 2. Passphrase strength enforcement
# ---------------------------------------------------------------------------


class TestPassphraseStrength:
    """validate_passphrase enforces min length + minimum strength score."""

    def test_too_short_passphrase_rejected(self):
        # 15 chars, one below the documented 16-char minimum.
        too_short = "Tr0ub4dor&3xkc"
        assert len(too_short) < MIN_PASSPHRASE_LENGTH
        with pytest.raises(PassphraseStrengthError):
            validate_passphrase(too_short)

    def test_low_entropy_passphrase_rejected(self):
        # Long enough (>= 16 chars) but trivially low entropy.
        low_entropy = "a" * 20
        assert len(low_entropy) >= MIN_PASSPHRASE_LENGTH
        assert score_passphrase(low_entropy) < MIN_ZXCVBN_SCORE
        with pytest.raises(PassphraseStrengthError):
            validate_passphrase(low_entropy)

    def test_non_string_rejected(self):
        with pytest.raises(PassphraseStrengthError):
            validate_passphrase(None)  # type: ignore[arg-type]

    def test_strong_passphrase_accepted(self):
        strong = "correct-horse-battery-staple-quantum-vortex-29"
        assert len(strong) >= MIN_PASSPHRASE_LENGTH
        assert score_passphrase(strong) >= MIN_ZXCVBN_SCORE
        # Should not raise.
        assert validate_passphrase(strong) is None

    def test_score_passphrase_within_zero_to_four(self):
        for candidate in ["", "a", "a" * 20, "correct-horse-battery-staple-2"]:
            score = score_passphrase(candidate)
            assert isinstance(score, int)
            assert 0 <= score <= 4


# ---------------------------------------------------------------------------
# 3. Diceware generation
# ---------------------------------------------------------------------------


class TestGeneratePassphrase:
    """generate_passphrase yields a high-entropy multi-word phrase."""

    def test_generated_passphrase_passes_validation(self):
        phrase = generate_passphrase()
        # Multi-word, separated by the default separator.
        words = phrase.split("-")
        assert len(words) >= 6
        assert all(words)  # no empty segments
        assert len(phrase) >= MIN_PASSPHRASE_LENGTH
        assert score_passphrase(phrase) >= MIN_ZXCVBN_SCORE
        # The recommended default must satisfy the strength rules.
        assert validate_passphrase(phrase) is None

    def test_generated_passphrases_are_unique(self):
        phrases = {generate_passphrase() for _ in range(5)}
        # Astronomically unlikely to collide with ~8.7 bits/word over 9 words.
        assert len(phrases) == 5

    def test_word_count_and_separator_respected(self):
        phrase = generate_passphrase(word_count=7, separator="_")
        words = phrase.split("_")
        assert len(words) == 7
        assert "_" in phrase
        assert "-" not in phrase


# ---------------------------------------------------------------------------
# 4. KDF params recorded per version + round-trip into the kit
# ---------------------------------------------------------------------------


class TestKdfParams:
    """default_kdf_params is recorded per version and round-trips into the kit."""

    def test_default_kdf_params_shape_and_values(self):
        params = default_kdf_params()
        assert params == {
            "algo": KDF_ALGO,
            "mem_kib": ARGON2_MEMORY_KIB,
            "time": ARGON2_TIME_COST,
            "parallel": ARGON2_PARALLELISM,
        }

    def test_kdf_params_round_trip_into_kit(self):
        # A custom (e.g. Raspberry-Pi-tuned) param set recorded on the version.
        tuned = {"algo": KDF_ALGO, "mem_kib": 65536, "time": 2, "parallel": 2}
        version = _make_version(1, is_active=True, kdf_params=tuned)

        kdf = build_recovery_kit([version])["kdf"]
        assert kdf["algo"] == tuned["algo"]
        assert kdf["mem_kib"] == tuned["mem_kib"]
        assert kdf["time"] == tuned["time"]
        assert kdf["parallel"] == tuned["parallel"]

    def test_kit_kdf_comes_from_active_version_params(self):
        v1 = _make_version(
            1,
            is_active=False,
            kdf_params={"algo": KDF_ALGO, "mem_kib": 65536, "time": 2, "parallel": 1},
        )
        v2_params = {"algo": KDF_ALGO, "mem_kib": 131072, "time": 4, "parallel": 4}
        v2 = _make_version(2, is_active=True, kdf_params=v2_params)

        kdf = build_recovery_kit([v1, v2])["kdf"]
        assert kdf["mem_kib"] == v2_params["mem_kib"]
        assert kdf["time"] == v2_params["time"]
        assert kdf["parallel"] == v2_params["parallel"]

    def test_derive_pwk_uses_recorded_params_and_is_deterministic(self):
        # Cheap Argon2id params keep this fast while exercising the recorded-param path.
        cheap = {"algo": KDF_ALGO, "mem_kib": 8, "time": 1, "parallel": 1}
        salt = os.urandom(16)
        passphrase = "correct-horse-battery-staple-quantum-vortex-29"

        key_a = derive_pwk(passphrase, salt, cheap)
        key_b = derive_pwk(passphrase, salt, cheap)
        assert key_a == key_b  # deterministic for same inputs
        assert len(key_a) == 32  # AES-256 key

        # Different salt -> different key.
        key_c = derive_pwk(passphrase, os.urandom(16), cheap)
        assert key_c != key_a

    def test_derive_pwk_rejects_unsupported_algo(self):
        with pytest.raises(ValueError):
            derive_pwk(
                "correct-horse-battery-staple-29",
                os.urandom(16),
                {"algo": "bcrypt", "mem_kib": 8, "time": 1, "parallel": 1},
            )
