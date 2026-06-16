"""Property-based test: wrong key material never yields plaintext.

# Feature: cloud-backup-restore, Property 4: Wrong key material never yields plaintext

**Validates: Requirements 16.8, 16.9**

For any WRONG key material supplied to the fresh-deployment bootstrap — a wrong
passphrase, a wrong/tampered Recovery Kit, absent/empty/malformed key material,
or a requested key version that is not present — the
:class:`BackupKeyService.bootstrap` path NEVER returns a usable Backup_Data_Key
that decrypts the artifact to its plaintext. Instead it raises the appropriate
:class:`KeyBootstrapError` subclass and writes nothing:

  * ``KeyMaterialMissingError``     — absent/empty/malformed kit or passphrase (Req 16.8)
  * ``KeyMaterialMismatchError``    — wrong passphrase or wrong/tampered kit
  * ``KeyVersionUnavailableError``  — requested key version absent / undecryptable (Req 16.9)

Additionally, decrypting a correctly-encrypted artifact with the *wrong*
Backup_Data_Key fails (raises) rather than yielding the original plaintext.

The DB and storage are mocked (the project PBT rule): the bootstrap is invoked
with ``persist=False`` so no database is touched, and the baseline Recovery Kit
is assembled in-memory from the real :func:`build_recovery_kit` builder. The
Argon2id KDF cost is reduced to cheap parameters (carried inside the kit, which
``bootstrap`` reads) so 100+ iterations run fast.
"""

from __future__ import annotations

import asyncio
import base64

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.keys.key_service import (
    BackupKeyService,
    KeyBootstrapError,
    KeyMaterialMismatchError,
    KeyMaterialMissingError,
    KeyVersionUnavailableError,
    _wrap_key,
    backup_envelope_decrypt,
    backup_envelope_encrypt,
    build_recovery_kit,
    compute_kcv,
    derive_pwk,
)
from app.modules.backup_restore.models import BackupKeyVersion

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

# Reduced Argon2id cost so the per-example KDF derivations are fast. These are
# carried inside the kit and are exactly what bootstrap re-derives with.
CHEAP_KDF_PARAMS = {"algo": "argon2id", "mem_kib": 8, "time": 1, "parallel": 1}

BASELINE_VERSION = 1

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty passphrases (bootstrap does not enforce strength; empty is treated
# as "missing key material", which is a separate, deliberately-tested case).
passphrases = st.text(min_size=1, max_size=48)
plaintexts = st.binary(min_size=0, max_size=2048)


# ---------------------------------------------------------------------------
# Helpers — build a correct baseline (kit + the true BDK) entirely in-memory.
# ---------------------------------------------------------------------------


def _make_baseline(passphrase: str) -> tuple[dict, bytes]:
    """Return a correct ``(recovery_kit, true_bdk)`` for *passphrase*.

    Uses the real :func:`build_recovery_kit` so the kit shape matches exactly
    what :meth:`BackupKeyService.bootstrap` expects, but with cheap KDF params.
    """
    import os

    bmk = os.urandom(32)
    bdk = os.urandom(32)
    salt = os.urandom(16)

    pwk = derive_pwk(passphrase, salt, CHEAP_KDF_PARAMS)
    wrapped_bmk_passphrase = _wrap_key(pwk, bmk)
    wrapped_bdk = _wrap_key(bmk, bdk)
    bmk_kcv = compute_kcv(bmk)

    version = BackupKeyVersion(
        version=BASELINE_VERSION,
        is_active=True,
        kdf_algo="argon2id",
        kdf_params=dict(CHEAP_KDF_PARAMS),
        kdf_salt=salt,
        wrapped_bmk_passphrase=wrapped_bmk_passphrase,
        # Not read by build_recovery_kit / bootstrap; placeholder keeps the
        # in-memory ORM object well-formed.
        wrapped_bmk_env=b"unused-on-fresh-box",
        wrapped_bdk=wrapped_bdk,
        bmk_kcv=bmk_kcv,
    )
    kit = build_recovery_kit([version])
    return kit, bdk


def _bootstrap(kit, passphrase, version=None) -> bytes:
    """Run the async bootstrap with the DB mocked away (``persist=False``)."""
    service = BackupKeyService(db=None)
    return asyncio.run(
        service.bootstrap(kit, passphrase, version=version, persist=False)
    )


def _flip_b64(value: str) -> str:
    """Decode a base64 field, flip its first byte, and re-encode (valid b64)."""
    raw = bytearray(base64.b64decode(value))
    raw[0] ^= 0xFF
    return base64.b64encode(bytes(raw)).decode("ascii")


def _assert_no_plaintext(call):
    """Invoke *call*; assert it raises a KeyBootstrapError and yields no BDK.

    A propagated ``KeyBootstrapError`` means bootstrap returned no key at all,
    so no Backup_Data_Key exists to decrypt the artifact and the plaintext can
    never be recovered. If ``call`` instead returns a key, ``pytest.raises``
    fails the test (wrong material must never produce a usable key).

    Returns the raised exception so callers can assert the precise subclass.
    """
    with pytest.raises(KeyBootstrapError) as excinfo:
        bdk = call()
        # Defensive: a returned key from wrong material is itself a failure.
        # Surface it as a clear assertion rather than silently passing.
        raise AssertionError(
            f"bootstrap unexpectedly returned a key from wrong material: {bdk!r}"
        )
    return excinfo.value


# ---------------------------------------------------------------------------
# Positive control — the CORRECT material does bootstrap and decrypt.
# Guards against a vacuous test where every mutation raises regardless.
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(passphrase=passphrases, plaintext=plaintexts)
def test_correct_material_recovers_plaintext(passphrase: str, plaintext: bytes):
    """Sanity: the correct passphrase + kit unwraps a BDK that decrypts.

    **Validates: Requirements 16.8, 16.9**
    """
    kit, true_bdk = _make_baseline(passphrase)
    bdk = _bootstrap(kit, passphrase)
    assert bdk == true_bdk

    blob = backup_envelope_encrypt(plaintext, bdk)
    assert backup_envelope_decrypt(blob, bdk) == plaintext


# ---------------------------------------------------------------------------
# Wrong passphrase → KeyMaterialMismatchError, no plaintext.
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(correct=passphrases, wrong=passphrases)
def test_wrong_passphrase_never_yields_plaintext(correct: str, wrong: str):
    """A wrong (but non-empty) passphrase fails fast with a mismatch error.

    **Validates: Requirements 16.8, 16.9**
    """
    assume(wrong != correct)
    kit, _ = _make_baseline(correct)
    err = _assert_no_plaintext(lambda: _bootstrap(kit, wrong))
    assert isinstance(err, KeyMaterialMismatchError)


# ---------------------------------------------------------------------------
# Absent key material → KeyMaterialMissingError (Req 16.8), no writes.
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(passphrase=passphrases, missing=st.sampled_from(["", None]))
def test_absent_passphrase_refused(passphrase: str, missing):
    """No/empty passphrase is refused as missing key material before any write.

    **Validates: Requirements 16.8**
    """
    kit, _ = _make_baseline(passphrase)
    err = _assert_no_plaintext(lambda: _bootstrap(kit, missing))
    assert isinstance(err, KeyMaterialMissingError)


@PBT_SETTINGS
@given(passphrase=passphrases, empty_kit=st.sampled_from([None, {}]))
def test_absent_kit_refused(passphrase: str, empty_kit):
    """No/empty recovery kit is refused as missing key material.

    **Validates: Requirements 16.8**
    """
    err = _assert_no_plaintext(lambda: _bootstrap(empty_kit, passphrase))
    assert isinstance(err, KeyMaterialMissingError)


# ---------------------------------------------------------------------------
# Malformed kit → KeyMaterialMissingError (structural / undecodable).
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    passphrase=passphrases,
    drop_key=st.sampled_from(
        ["kdf", "wrapped_bmk_passphrase_b64", "verification", "key_versions"]
    ),
)
def test_malformed_kit_missing_field_refused(passphrase: str, drop_key: str):
    """A kit missing a required field is treated as malformed/missing material.

    **Validates: Requirements 16.8**
    """
    kit, _ = _make_baseline(passphrase)
    del kit[drop_key]
    err = _assert_no_plaintext(lambda: _bootstrap(kit, passphrase))
    assert isinstance(err, KeyMaterialMissingError)


@PBT_SETTINGS
@given(passphrase=passphrases, junk=st.text(min_size=1, max_size=12))
def test_malformed_kit_undecodable_salt_refused(passphrase: str, junk: str):
    """A non-base64 salt makes the kit malformed → missing key material.

    **Validates: Requirements 16.8**
    """
    kit, _ = _make_baseline(passphrase)
    # '!' / '@' etc. are not valid base64 alphabet → binascii.Error in bootstrap.
    kit["kdf"]["salt_b64"] = junk + "!@#$%"
    err = _assert_no_plaintext(lambda: _bootstrap(kit, passphrase))
    assert isinstance(err, KeyMaterialMissingError)


@PBT_SETTINGS
@given(passphrase=passphrases)
def test_empty_key_versions_refused(passphrase: str):
    """A kit whose key-version list is empty is refused as missing material.

    **Validates: Requirements 16.8**
    """
    kit, _ = _make_baseline(passphrase)
    kit["key_versions"] = []
    err = _assert_no_plaintext(lambda: _bootstrap(kit, passphrase))
    assert isinstance(err, KeyMaterialMissingError)


# ---------------------------------------------------------------------------
# Tampered (wrong) kit material → KeyMaterialMismatchError, no plaintext.
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    passphrase=passphrases,
    field=st.sampled_from(["wrapped_bmk_passphrase_b64", "salt_b64", "kcv_b64"]),
)
def test_tampered_kit_never_yields_plaintext(passphrase: str, field: str):
    """Flipping the wrapped BMK, the salt, or the KCV fails verification.

    Each tamper keeps the field valid base64 but changes its bytes, so the BMK
    unwrap or its key-check value fails — never producing a usable key.

    **Validates: Requirements 16.8, 16.9**
    """
    kit, _ = _make_baseline(passphrase)
    if field == "wrapped_bmk_passphrase_b64":
        kit["wrapped_bmk_passphrase_b64"] = _flip_b64(kit["wrapped_bmk_passphrase_b64"])
    elif field == "salt_b64":
        kit["kdf"]["salt_b64"] = _flip_b64(kit["kdf"]["salt_b64"])
    else:  # kcv_b64
        kit["verification"]["bmk_kcv_b64"] = _flip_b64(
            kit["verification"]["bmk_kcv_b64"]
        )

    err = _assert_no_plaintext(lambda: _bootstrap(kit, passphrase))
    assert isinstance(err, KeyMaterialMismatchError)


# ---------------------------------------------------------------------------
# Wrong / missing key VERSION → KeyVersionUnavailableError (Req 16.9).
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(passphrase=passphrases, requested=st.integers(min_value=2, max_value=10_000))
def test_absent_version_refused(passphrase: str, requested: int):
    """Requesting a key version not present in the kit aborts naming it.

    **Validates: Requirements 16.9**
    """
    kit, _ = _make_baseline(passphrase)  # kit holds version 1 only
    assume(requested != BASELINE_VERSION)
    err = _assert_no_plaintext(lambda: _bootstrap(kit, passphrase, version=requested))
    assert isinstance(err, KeyVersionUnavailableError)


@PBT_SETTINGS
@given(passphrase=passphrases)
def test_tampered_wrapped_bdk_refused(passphrase: str):
    """A correct passphrase but corrupted wrapped BDK cannot be unwrapped.

    The BMK and its KCV verify, but the requested version's BDK fails to unwrap
    → KeyVersionUnavailableError, with no plaintext recovered.

    **Validates: Requirements 16.9**
    """
    kit, _ = _make_baseline(passphrase)
    kit["key_versions"][0]["wrapped_bdk_b64"] = _flip_b64(
        kit["key_versions"][0]["wrapped_bdk_b64"]
    )
    err = _assert_no_plaintext(lambda: _bootstrap(kit, passphrase))
    assert isinstance(err, KeyVersionUnavailableError)


# ---------------------------------------------------------------------------
# A WRONG Backup_Data_Key cannot decrypt a correctly-encrypted artifact.
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(plaintext=plaintexts, wrong_bdk=st.binary(min_size=32, max_size=32))
def test_wrong_bdk_decrypt_never_yields_plaintext(plaintext: bytes, wrong_bdk: bytes):
    """Decrypting an artifact under the wrong BDK raises, never the plaintext.

    **Validates: Requirements 16.9**
    """
    import os

    true_bdk = os.urandom(32)
    assume(wrong_bdk != true_bdk)

    blob = backup_envelope_encrypt(plaintext, true_bdk)
    with pytest.raises(Exception) as excinfo:
        recovered = backup_envelope_decrypt(blob, wrong_bdk)
        # Must never silently return the original plaintext.
        assert recovered != plaintext
    # The failure must not itself be an assertion that plaintext leaked.
    assert not isinstance(excinfo.value, AssertionError)
