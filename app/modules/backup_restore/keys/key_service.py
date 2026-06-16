"""Backup key service — BDK-keyed envelope encryption.

This module provides the encryption primitives for backup artifacts. It reuses
the **same AES-256-GCM envelope construction** as :mod:`app.core.encryption`
(format ``[4-byte DEK-len][AES-GCM-wrapped DEK][AES-GCM payload]``) but
substitutes the wrapping key: the **Backup_Data_Key (BDK)** plays the role that
``ENCRYPTION_MASTER_KEY`` plays in :func:`app.core.encryption.envelope_encrypt`.

Backup artifacts must remain decryptable on a fresh deployment that has lost
``ENCRYPTION_MASTER_KEY`` (Req 16.5-16.9). Therefore they are *never* wrapped
under the deployment master key — only under the escrowed BDK hierarchy
(Req 16.1, 16.2). All artifacts are encrypted in the pipeline before reaching
any storage adapter, so destinations only ever store ciphertext (Req 21.4).

Keeping the same construction and storage format as the core envelope primitive
means there is exactly one audited crypto code path and one on-disk format.

The broader key hierarchy (BMK/BDK setup, bootstrap, rotation) is layered on top
of these primitives in later tasks.
"""

from __future__ import annotations

import base64
import binascii
import logging
import math
import os
import re
import secrets
import struct
from datetime import datetime, timezone

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import (
    _aes_decrypt,
    _aes_encrypt,
    envelope_decrypt,
    envelope_encrypt,
)
from app.modules.backup_restore.keys.passphrase_words import WORDS
from app.modules.backup_restore.models import BackupKeyVersion

logger = logging.getLogger(__name__)

# A BMK / BDK is a 256-bit (32-byte) AES key.
_BDK_SIZE = 32
_BMK_SIZE = 32

# ---------------------------------------------------------------------------
# KDF parameters (Argon2id) — from the design "KDF parameters" table.
# Memory cost is tunable down (e.g. 64 MiB on Raspberry Pi) via config; all
# parameters used for a given key version are recorded in
# ``backup_key_versions.kdf_params`` so older recovery kits stay decryptable.
# ---------------------------------------------------------------------------
KDF_ALGO = "argon2id"
ARGON2_MEMORY_KIB = 262144  # 256 MiB
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 4
ARGON2_SALT_BYTES = 16
ARGON2_OUTPUT_BYTES = 32  # AES-256 key

# The Recovery Kit format version this service emits.
RECOVERY_KIT_VERSION = 1
RECOVERY_KIT_SPEC = "cloud-backup-restore"

# Known constant whose AES-GCM encryption under the BMK forms the key-check
# value (KCV). A correct passphrase/kit reproduces a BMK that decrypts this.
_KCV_CONSTANT = b"cloud-backup-restore/bmk-kcv/v1"

# Passphrase strength rules (design "Passphrase strength rules", Req 16.3/16.4).
MIN_PASSPHRASE_LENGTH = 16
MIN_ZXCVBN_SCORE = 3
# Target entropy for generated diceware passphrases (~77 bits ≈ 6-word EFF).
GENERATED_PASSPHRASE_TARGET_BITS = 77


class PassphraseStrengthError(ValueError):
    """Raised when a supplied passphrase fails the strength rules (Req 16.3)."""


class KeySetupError(RuntimeError):
    """Raised when key setup cannot proceed (e.g. an active key already exists)."""


class KeyBootstrapError(RuntimeError):
    """Base error for fresh-deployment bootstrap / key-access failures.

    Bootstrap and the seamless access paths raise subclasses of this so callers
    (the restore flow) can distinguish *why* key material could not be obtained
    and refuse the restore before any write (Req 16.8, 16.9).
    """


class KeyMaterialMissingError(KeyBootstrapError):
    """No usable key material was supplied on a fresh deployment (Req 16.8).

    Raised when the recovery kit or passphrase is absent/empty/malformed, before
    any decryption is attempted and without writing anything to the target.
    """


class KeyMaterialMismatchError(KeyBootstrapError):
    """The supplied passphrase/kit (or stored material) failed verification.

    Raised when the BMK unwrap or its key-check value does not match — i.e. the
    wrong passphrase or wrong recovery kit. Fails fast before any artifact is
    downloaded (design "Fresh-deployment restore bootstrap").
    """


class KeyVersionUnavailableError(KeyBootstrapError):
    """The requested key version is absent or its BDK could not be unwrapped.

    Raised when the key version recorded in the backup artifact is not present
    in the supplied key material (or on this deployment), or the obtained key
    fails to decrypt — the restore aborts naming the required version with no
    partial writes (Req 16.9).
    """


def _require_bdk(bdk: bytes) -> bytes:
    """Validate that *bdk* is a 256-bit key suitable for AES-256-GCM."""
    if not isinstance(bdk, (bytes, bytearray)):
        raise TypeError("bdk must be bytes")
    if len(bdk) != _BDK_SIZE:
        raise ValueError(
            f"bdk must be {_BDK_SIZE} bytes (256-bit), got {len(bdk)}"
        )
    return bytes(bdk)


def backup_envelope_encrypt(plaintext: str | bytes, bdk: bytes) -> bytes:
    """Envelope-encrypt *plaintext* for a backup artifact, keyed by the BDK.

    Byte-compatible with :func:`app.core.encryption.envelope_encrypt`, but the
    per-record DEK is wrapped under the supplied **Backup_Data_Key** rather than
    a key derived from ``ENCRYPTION_MASTER_KEY``.

    Args:
        plaintext: The data to encrypt. ``str`` is encoded as UTF-8.
        bdk: The 256-bit Backup_Data_Key used to wrap the DEK.

    Returns:
        An opaque ``bytes`` blob in the format
        ``[4-byte DEK-len][AES-GCM-wrapped DEK][AES-GCM payload]``.
    """
    key = _require_bdk(bdk)

    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    # Generate a random DEK and encrypt the payload with it.
    dek = os.urandom(32)  # 256-bit DEK
    encrypted_payload = _aes_encrypt(dek, plaintext)

    # Wrap the DEK under the BDK (instead of the master key).
    encrypted_dek = _aes_encrypt(key, dek)

    # Pack: [4-byte DEK length][encrypted DEK][encrypted payload]
    return struct.pack(">I", len(encrypted_dek)) + encrypted_dek + encrypted_payload


def backup_envelope_decrypt(blob: bytes, bdk: bytes) -> bytes:
    """Decrypt a blob produced by :func:`backup_envelope_encrypt`.

    Args:
        blob: The envelope blob to decrypt.
        bdk: The 256-bit Backup_Data_Key the DEK was wrapped under.

    Returns:
        The original plaintext as ``bytes``.
    """
    key = _require_bdk(bdk)

    # Unpack the DEK length header.
    (dek_len,) = struct.unpack(">I", blob[:4])
    encrypted_dek = blob[4 : 4 + dek_len]
    encrypted_payload = blob[4 + dek_len :]

    # Unwrap the DEK with the BDK, then decrypt the payload.
    dek = _aes_decrypt(key, encrypted_dek)
    return _aes_decrypt(dek, encrypted_payload)


# ---------------------------------------------------------------------------
# AES-256-GCM key wrapping helpers (BMK under PWK, BDK under BMK, KCV under BMK)
# ---------------------------------------------------------------------------
# These reuse the audited ``_aes_encrypt``/``_aes_decrypt`` (``nonce ‖ ct``)
# primitives from app.core.encryption — the same construction the envelope
# format uses for its DEK-wrapping layer — but applied directly to 32-byte key
# material (no inner DEK indirection needed when wrapping a single key).


def _wrap_key(wrapping_key: bytes, key_material: bytes) -> bytes:
    """AES-256-GCM wrap *key_material* under *wrapping_key*."""
    return _aes_encrypt(wrapping_key, key_material)


def _unwrap_key(wrapping_key: bytes, wrapped: bytes) -> bytes:
    """AES-256-GCM unwrap a blob produced by :func:`_wrap_key`."""
    return _aes_decrypt(wrapping_key, wrapped)


# ---------------------------------------------------------------------------
# Argon2id KDF (Passphrase → PWK)
# ---------------------------------------------------------------------------


def default_kdf_params() -> dict:
    """Return the KDF parameter set recorded for a freshly-minted key version."""
    return {
        "algo": KDF_ALGO,
        "mem_kib": ARGON2_MEMORY_KIB,
        "time": ARGON2_TIME_COST,
        "parallel": ARGON2_PARALLELISM,
    }


def derive_pwk(passphrase: str, salt: bytes, params: dict) -> bytes:
    """Derive the 256-bit Passphrase-Wrapping Key (PWK) with Argon2id.

    Args:
        passphrase: The operator recovery passphrase (never stored/logged).
        salt: The per-BMK Argon2id salt (recorded in the key version + kit).
        params: KDF parameters (``mem_kib``/``time``/``parallel``) — read from
            the recorded key version so older recovery kits stay decryptable.

    Returns:
        A 32-byte key suitable for AES-256-GCM key wrapping.
    """
    algo = params.get("algo", KDF_ALGO)
    if algo != KDF_ALGO:
        raise ValueError(f"unsupported KDF algorithm: {algo!r}")
    kdf = Argon2id(
        salt=salt,
        length=ARGON2_OUTPUT_BYTES,
        iterations=int(params["time"]),
        lanes=int(params["parallel"]),
        memory_cost=int(params["mem_kib"]),
    )
    return kdf.derive(passphrase.encode("utf-8"))


# ---------------------------------------------------------------------------
# Key-check value (KCV)
# ---------------------------------------------------------------------------


def compute_kcv(bmk: bytes) -> bytes:
    """Compute the key-check value: AES-GCM of a known constant under the BMK.

    A correct passphrase/kit reproduces a BMK that decrypts this back to the
    constant; a wrong one fails the GCM tag, letting bootstrap fail fast before
    any artifact is downloaded (design "Fresh-deployment restore bootstrap").
    """
    return _aes_encrypt(bmk, _KCV_CONSTANT)


def verify_kcv(bmk: bytes, kcv: bytes) -> bool:
    """Return ``True`` iff *bmk* decrypts *kcv* back to the known constant."""
    try:
        return _aes_decrypt(bmk, kcv) == _KCV_CONSTANT
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Passphrase strength + diceware generation (Req 16.3 / 16.4)
# ---------------------------------------------------------------------------

try:  # zxcvbn is optional — not a pinned project dependency.
    from zxcvbn import zxcvbn as _zxcvbn  # type: ignore

    _HAS_ZXCVBN = True
except Exception:  # pragma: no cover - import guard
    _zxcvbn = None  # type: ignore
    _HAS_ZXCVBN = False


def _heuristic_strength_score(passphrase: str) -> int:
    """Fallback 0-4 strength score used when zxcvbn is not installed.

    Approximates zxcvbn's banding via a coarse Shannon-style entropy estimate
    over the character classes present plus a length bonus. This is intentionally
    conservative; it is NOT a substitute for the real zxcvbn dictionary checks,
    but enforces a reasonable minimum (design note: "implement a reasonable
    strength check (min length + basic entropy)").
    """
    if not passphrase:
        return 0
    pool = 0
    if re.search(r"[a-z]", passphrase):
        pool += 26
    if re.search(r"[A-Z]", passphrase):
        pool += 26
    if re.search(r"[0-9]", passphrase):
        pool += 10
    if re.search(r"[^A-Za-z0-9]", passphrase):
        pool += 32
    # Whitespace-separated multi-word phrases (diceware) get credit per word.
    words = [w for w in re.split(r"\s+", passphrase.strip()) if w]
    distinct_chars = len(set(passphrase))
    bits = math.log2(pool) * len(passphrase) if pool else 0.0
    # Penalise very low character diversity (e.g. "aaaaaaaaaaaaaaaa").
    if distinct_chars <= 3:
        bits = min(bits, 20.0)
    # Reward genuine multi-word phrases.
    if len(words) >= 4:
        bits = max(bits, len(words) * 8.0)
    if bits < 28:
        return 0
    if bits < 36:
        return 1
    if bits < 60:
        return 2
    if bits < 80:
        return 3
    return 4


def score_passphrase(passphrase: str) -> int:
    """Return a 0-4 strength score, using zxcvbn when available."""
    if _HAS_ZXCVBN:
        try:
            return int(_zxcvbn(passphrase)["score"])
        except Exception:  # pragma: no cover - defensive
            pass
    return _heuristic_strength_score(passphrase)


def validate_passphrase(passphrase: str) -> None:
    """Enforce the passphrase strength rules; raise on failure (Req 16.3).

    Rules (design): minimum 16 characters and a strength score >= 3.
    """
    if not isinstance(passphrase, str):
        raise PassphraseStrengthError("passphrase must be a string")
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise PassphraseStrengthError(
            f"passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters"
        )
    score = score_passphrase(passphrase)
    if score < MIN_ZXCVBN_SCORE:
        raise PassphraseStrengthError(
            "passphrase is too weak; choose a longer, less predictable phrase "
            f"(strength {score}/4, need >= {MIN_ZXCVBN_SCORE})"
        )


def generate_passphrase(word_count: int | None = None, separator: str = "-") -> str:
    """Generate a high-entropy diceware-style passphrase (recommended default).

    Words are sampled from the embedded word list with :func:`secrets.choice`
    (a CSPRNG). When *word_count* is omitted, enough words are chosen to exceed
    :data:`GENERATED_PASSPHRASE_TARGET_BITS` of entropy regardless of the word
    list size.
    """
    bits_per_word = math.log2(len(WORDS))
    if word_count is None:
        word_count = max(6, math.ceil(GENERATED_PASSPHRASE_TARGET_BITS / bits_per_word))
    return separator.join(secrets.choice(WORDS) for _ in range(word_count))


# ---------------------------------------------------------------------------
# Recovery Kit (Req 16.4)
# ---------------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(value: str) -> bytes:
    """Strict base64-decode a Recovery-Kit field; raises on malformed input."""
    if not isinstance(value, str):
        raise binascii.Error("expected a base64 string")
    return base64.b64decode(value, validate=True)


def build_recovery_kit(versions: list[BackupKeyVersion]) -> dict:
    """Build the Recovery Kit JSON from retained wrapped key material.

    The kit holds the **wrapped** BMK (under the passphrase-derived PWK) and the
    wrapped BDK for every retained key version — never the plaintext BMK and
    never the passphrase. KDF params + salt come from the active version (the
    BMK and its salt are stable across rotations). Shape matches the design
    "Recovery Kit" JSON.
    """
    if not versions:
        raise KeySetupError("no key versions available to export a recovery kit")

    ordered = sorted(versions, key=lambda v: v.version)
    active = next((v for v in ordered if v.is_active), ordered[-1])

    params = dict(active.kdf_params or {})
    return {
        "kit_version": RECOVERY_KIT_VERSION,
        "spec": RECOVERY_KIT_SPEC,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kdf": {
            "algo": params.get("algo", active.kdf_algo),
            "mem_kib": params.get("mem_kib", ARGON2_MEMORY_KIB),
            "time": params.get("time", ARGON2_TIME_COST),
            "parallel": params.get("parallel", ARGON2_PARALLELISM),
            "salt_b64": _b64(active.kdf_salt),
        },
        "wrapped_bmk_passphrase_b64": _b64(active.wrapped_bmk_passphrase),
        "key_versions": [
            {
                "version": v.version,
                "wrapped_bdk_b64": _b64(v.wrapped_bdk),
                "created_at": (
                    v.created_at.isoformat() if v.created_at is not None else None
                ),
            }
            for v in ordered
        ],
        "verification": {"bmk_kcv_b64": _b64(active.bmk_kcv)},
    }


# ---------------------------------------------------------------------------
# Backup key service (DB-backed BMK/BDK hierarchy)
# ---------------------------------------------------------------------------


class BackupKeyService:
    """BMK/BDK escrow hierarchy, recovery kit, and KDF wrap/unwrap.

    Operates on an :class:`AsyncSession`. Per the project ``get_db_session``
    ``session.begin()`` auto-commit pattern, methods use ``flush()`` +
    ``await db.refresh()`` and never ``commit()``.

    This service implements first-run :meth:`setup` and :meth:`export_recovery_kit`,
    the fresh-deployment :meth:`bootstrap` (DR path), the seamless
    :meth:`get_active_bdk`/:meth:`get_bdk` runtime accessors, :meth:`rotate`,
    and :meth:`get_key_status`.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load_versions(self) -> list[BackupKeyVersion]:
        result = await self.db.execute(
            select(BackupKeyVersion).order_by(BackupKeyVersion.version)
        )
        return list(result.scalars().all())

    async def _get_version_row(self, version: int) -> BackupKeyVersion | None:
        result = await self.db.execute(
            select(BackupKeyVersion).where(BackupKeyVersion.version == version)
        )
        return result.scalar_one_or_none()

    async def setup(self, passphrase: str) -> dict:
        """First-run setup: mint the BMK + BDK v1 and persist the key version.

        Steps (design "Setup workflow"):
          1. Enforce passphrase strength rules (Req 16.3/16.4).
          2. ``BMK = random(32)``; ``salt = random(16)``; ``PWK = Argon2id(P, salt)``.
          3. ``wrapped_bmk_passphrase = AES-GCM-wrap(BMK, PWK)`` (recovery path).
          4. ``wrapped_bmk_env = envelope_encrypt(BMK)`` under ENCRYPTION_MASTER_KEY
             (seamless runtime path).
          5. ``BDK_v1 = random(32)``; ``wrapped_bdk = AES-GCM-wrap(BDK_v1, BMK)``.
          6. ``bmk_kcv = AES-GCM(known constant under BMK)``.
          7. INSERT key_version=1 (``is_active=true``).

        Returns the one-time Recovery Kit JSON (download once).

        Raises:
            PassphraseStrengthError: if the passphrase fails the strength rules.
            KeySetupError: if a key version already exists (setup is one-time).
        """
        validate_passphrase(passphrase)

        existing = await self._load_versions()
        if existing:
            raise KeySetupError(
                "backup key setup already completed; use rotate or re-export "
                "the recovery kit instead"
            )

        # Generate root key material.
        bmk = os.urandom(_BMK_SIZE)
        bdk_v1 = os.urandom(_BDK_SIZE)
        salt = os.urandom(ARGON2_SALT_BYTES)
        params = default_kdf_params()

        # Derive PWK and wrap the BMK under it (recovery path).
        pwk = derive_pwk(passphrase, salt, params)
        wrapped_bmk_passphrase = _wrap_key(pwk, bmk)

        # Seamless runtime copy: BMK wrapped under ENCRYPTION_MASTER_KEY.
        wrapped_bmk_env = envelope_encrypt(bmk)

        # Wrap BDK v1 under the BMK, and compute the KCV.
        wrapped_bdk = _wrap_key(bmk, bdk_v1)
        bmk_kcv = compute_kcv(bmk)

        version = BackupKeyVersion(
            version=1,
            is_active=True,
            kdf_algo=KDF_ALGO,
            kdf_params=params,
            kdf_salt=salt,
            wrapped_bmk_passphrase=wrapped_bmk_passphrase,
            wrapped_bmk_env=wrapped_bmk_env,
            wrapped_bdk=wrapped_bdk,
            bmk_kcv=bmk_kcv,
        )
        self.db.add(version)
        await self.db.flush()
        await self.db.refresh(version)

        logger.info("Backup key setup completed: minted BMK and BDK key version 1")

        # The plaintext passphrase, BMK, PWK and BDK are intentionally not
        # returned or logged; only wrapped material leaves this method.
        return build_recovery_kit([version])

    async def export_recovery_kit(self) -> dict:
        """Re-emit the Recovery Kit from the retained wrapped key material.

        Reads every retained key version and rebuilds the kit JSON (the same
        shape returned by :meth:`setup`). Requires no passphrase: it re-emits
        only already-wrapped material.

        Raises:
            KeySetupError: if no key version has been established yet.
        """
        versions = await self._load_versions()
        if not versions:
            raise KeySetupError(
                "no backup key has been set up; run setup before exporting a "
                "recovery kit"
            )
        return build_recovery_kit(versions)

    # ------------------------------------------------------------------
    # Fresh-deployment bootstrap (the DR path) — Req 16.7, 16.8, 16.9
    # ------------------------------------------------------------------

    async def bootstrap(
        self,
        kit: dict,
        passphrase: str,
        version: int | None = None,
        *,
        persist: bool = True,
    ) -> bytes:
        """Unwrap a Backup_Data_Key from a Recovery Kit + passphrase on a fresh box.

        This is the disaster-recovery path: ``ENCRYPTION_MASTER_KEY`` is lost on a
        fresh deployment, so the ``wrapped_bmk_env`` copy is useless. The BMK is
        instead recovered from operator-supplied material only — the Recovery Kit
        (wrapped BMK + wrapped BDKs) and the recovery passphrase. The deployment's
        ``ENCRYPTION_MASTER_KEY`` is **never** used to obtain the BMK here
        (Req 16.7).

        Steps (design "Fresh-deployment restore bootstrap"):
          1. ``PWK = Argon2id(passphrase, kit.salt)`` with the kit's KDF params.
          2. ``BMK = AES-GCM-unwrap(kit.wrapped_bmk_passphrase, PWK)``.
          3. ``verify_kcv(BMK, kit.verification.bmk_kcv)`` — abort fast on a wrong
             passphrase/kit before any artifact is downloaded.
          4. ``BDK_v = AES-GCM-unwrap(kit.key_versions[v].wrapped_bdk, BMK)`` for
             the requested version (defaults to the kit's highest version).
          5. Optionally re-store the wrapped material under THIS deployment's
             ``ENCRYPTION_MASTER_KEY`` so the rest of the restore can use the
             seamless path.

        Args:
            kit: The Recovery Kit JSON (shape produced by :func:`build_recovery_kit`).
            passphrase: The operator recovery passphrase (never stored/logged).
            version: The key version to unwrap (the version recorded in the backup
                artifact). Defaults to the kit's highest version when omitted.
            persist: When ``True`` (default) and this deployment holds no key
                material yet, re-store the kit's wrapped versions locally with
                ``wrapped_bmk_env`` re-wrapped under this deployment's master key.

        Returns:
            The 32-byte Backup_Data_Key for the requested version.

        Raises:
            KeyMaterialMissingError: no/empty/malformed kit or passphrase
                (Req 16.8) — raised before any write.
            KeyMaterialMismatchError: wrong passphrase or recovery kit
                (BMK unwrap or KCV mismatch).
            KeyVersionUnavailableError: the requested version is absent from the
                kit or its BDK cannot be unwrapped (Req 16.9).
        """
        # Req 16.8 — refuse with no writes when no key material is supplied.
        if not passphrase or not isinstance(passphrase, str):
            raise KeyMaterialMissingError(
                "a recovery passphrase must be supplied before a fresh-deployment "
                "restore can proceed"
            )
        if not kit or not isinstance(kit, dict):
            raise KeyMaterialMissingError(
                "a recovery kit must be supplied before a fresh-deployment "
                "restore can proceed"
            )

        # Parse the kit; any structural/decoding problem is "missing key material".
        try:
            kdf = kit["kdf"]
            salt = _b64d(kdf["salt_b64"])
            params = {
                "algo": kdf.get("algo", KDF_ALGO),
                "mem_kib": int(kdf["mem_kib"]),
                "time": int(kdf["time"]),
                "parallel": int(kdf["parallel"]),
            }
            wrapped_bmk_pw = _b64d(kit["wrapped_bmk_passphrase_b64"])
            kcv = _b64d(kit["verification"]["bmk_kcv_b64"])
            kit_versions = {
                int(v["version"]): _b64d(v["wrapped_bdk_b64"])
                for v in kit["key_versions"]
            }
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise KeyMaterialMissingError(
                "the supplied recovery kit is malformed or incomplete"
            ) from exc

        if not kit_versions:
            raise KeyMaterialMissingError(
                "the supplied recovery kit contains no key versions"
            )

        # Derive the PWK and unwrap the BMK from the kit (recovery path only).
        pwk = derive_pwk(passphrase, salt, params)
        try:
            bmk = _unwrap_key(pwk, wrapped_bmk_pw)
        except Exception as exc:
            # GCM tag failure ⇒ wrong passphrase or wrong kit.
            raise KeyMaterialMismatchError(
                "wrong passphrase or recovery kit: the Backup_Master_Key could "
                "not be unwrapped"
            ) from exc

        # Fail fast on a wrong passphrase/kit before any artifact is downloaded.
        if not verify_kcv(bmk, kcv):
            raise KeyMaterialMismatchError(
                "wrong passphrase or recovery kit: key-check value mismatch"
            )

        # Resolve the requested key version (default to the kit's latest).
        requested = version if version is not None else max(kit_versions)
        if requested not in kit_versions:
            raise KeyVersionUnavailableError(
                f"key version {requested} is required but is not present in the "
                f"supplied recovery kit"
            )

        try:
            bdk = _require_bdk(_unwrap_key(bmk, kit_versions[requested]))
        except KeyVersionUnavailableError:
            raise
        except Exception as exc:
            raise KeyVersionUnavailableError(
                f"key version {requested} could not be unwrapped from the supplied "
                f"key material"
            ) from exc

        # Optionally re-store the wrapped material under THIS deployment's
        # ENCRYPTION_MASTER_KEY so subsequent restore steps use the seamless path.
        if persist:
            await self._restore_local_key_material(
                bmk=bmk,
                kcv=kcv,
                salt=salt,
                params=params,
                wrapped_bmk_pw=wrapped_bmk_pw,
                kit_versions=kit_versions,
            )

        logger.info(
            "Backup key bootstrap succeeded for key version %s (fresh-deployment "
            "recovery path)",
            requested,
        )
        return bdk

    async def _restore_local_key_material(
        self,
        *,
        bmk: bytes,
        kcv: bytes,
        salt: bytes,
        params: dict,
        wrapped_bmk_pw: bytes,
        kit_versions: dict[int, bytes],
    ) -> None:
        """Re-store kit key versions locally, re-wrapping the BMK under this box.

        Only runs when this deployment holds no key material yet (a true fresh
        box). The ``wrapped_bmk_env`` copy is recomputed under THIS deployment's
        ``ENCRYPTION_MASTER_KEY`` so :meth:`get_active_bdk`/:meth:`get_bdk` work
        seamlessly for the remainder of the restore; the recovery-path material
        (``wrapped_bmk_passphrase``, KCV, salt, KDF params) is preserved verbatim
        from the kit. No-op if any version already exists locally.
        """
        existing = await self._load_versions()
        if existing:
            # The DB already holds key material; nothing to re-store.
            return

        # Seamless runtime copy of the (long-lived) BMK under this box's master key.
        wrapped_bmk_env = envelope_encrypt(bmk)
        active_version = max(kit_versions)
        for v, wrapped_bdk in sorted(kit_versions.items()):
            self.db.add(
                BackupKeyVersion(
                    version=v,
                    is_active=(v == active_version),
                    kdf_algo=params.get("algo", KDF_ALGO),
                    kdf_params=dict(params),
                    kdf_salt=salt,
                    wrapped_bmk_passphrase=wrapped_bmk_pw,
                    wrapped_bmk_env=wrapped_bmk_env,
                    wrapped_bdk=wrapped_bdk,
                    bmk_kcv=kcv,
                )
            )
        await self.db.flush()
        logger.info(
            "Re-stored %d backup key version(s) locally after bootstrap "
            "(wrapped_bmk_env re-keyed under this deployment)",
            len(kit_versions),
        )

    # ------------------------------------------------------------------
    # Seamless runtime key access (normal operation) — Req 16.1, 16.9
    # ------------------------------------------------------------------

    def _unwrap_bdk_from_row(self, row: BackupKeyVersion) -> bytes:
        """Unwrap a row's BDK via the seamless path (``ENCRYPTION_MASTER_KEY``).

        Unwraps the BMK from ``wrapped_bmk_env`` using this deployment's master
        key, verifies it against the KCV, then unwraps the row's BDK with the BMK.
        """
        try:
            bmk = envelope_decrypt(row.wrapped_bmk_env)
        except Exception as exc:
            # The seamless path needs ENCRYPTION_MASTER_KEY; if it is absent or
            # different (a fresh box), callers must bootstrap instead.
            raise KeyMaterialMismatchError(
                f"key version {row.version} is present but its Backup_Master_Key "
                f"cannot be unwrapped on this deployment; supply recovery key "
                f"material (bootstrap) instead"
            ) from exc
        if not verify_kcv(bmk, row.bmk_kcv):
            raise KeyMaterialMismatchError(
                f"key version {row.version} failed key-check verification on this "
                f"deployment"
            )
        return _require_bdk(_unwrap_key(bmk, row.wrapped_bdk))

    async def get_active_bdk(self) -> tuple[int, bytes]:
        """Return the active key version and its BDK via the seamless path.

        Loads the active key version, unwraps the BMK from ``wrapped_bmk_env``
        using ``ENCRYPTION_MASTER_KEY`` (no passphrase needed during normal
        operation), then unwraps the active BDK with the BMK.

        Returns:
            ``(active_version, bdk)`` — the active key version number and its
            32-byte Backup_Data_Key.

        Raises:
            KeyVersionUnavailableError: no active key version on this deployment.
            KeyMaterialMismatchError: the active BMK cannot be unwrapped/verified
                on this deployment (e.g. a fresh box — bootstrap instead).
        """
        result = await self.db.execute(
            select(BackupKeyVersion).where(BackupKeyVersion.is_active.is_(True))
        )
        active = result.scalar_one_or_none()
        if active is None:
            raise KeyVersionUnavailableError(
                "no active backup key version on this deployment; run setup or "
                "bootstrap first"
            )
        return active.version, self._unwrap_bdk_from_row(active)

    async def get_bdk(self, version: int) -> bytes:
        """Return the BDK for a specific key version via the seamless path.

        Used at restore time when the key version recorded in the backup artifact
        is known and this deployment still has its ``ENCRYPTION_MASTER_KEY``.

        Args:
            version: The key version recorded in the backup artifact.

        Returns:
            The 32-byte Backup_Data_Key for *version*.

        Raises:
            KeyVersionUnavailableError: the version is not present on this
                deployment (Req 16.9).
            KeyMaterialMismatchError: the BMK cannot be unwrapped/verified on this
                deployment (e.g. a fresh box — bootstrap instead).
        """
        row = await self._get_version_row(version)
        if row is None:
            raise KeyVersionUnavailableError(
                f"key version {version} is required but is not present on this "
                f"deployment"
            )
        return self._unwrap_bdk_from_row(row)

    # ------------------------------------------------------------------
    # Rotation and retention (Req 16.10)
    # ------------------------------------------------------------------

    async def rotate(self) -> int:
        """Mint a new BDK + key version; retain all prior versions (Req 16.10).

        Rotation creates a new ``backup_key_versions`` row with a fresh BDK
        (``is_active=true``) and marks the previously-active version
        ``is_active=false`` but retains it so historical backups under prior key
        versions remain restorable. The Backup_Master_Key is long-lived and is
        **reused**: its wrapped copies (``wrapped_bmk_passphrase``,
        ``wrapped_bmk_env``), KDF params/salt and KCV are carried over unchanged.

        Returns:
            The new (now-active) key version number.

        Raises:
            KeySetupError: no key has been set up yet, or no active version found.
            KeyMaterialMismatchError: the active BMK cannot be unwrapped on this
                deployment (rotation needs the seamless path).
        """
        versions = await self._load_versions()
        if not versions:
            raise KeySetupError(
                "no backup key to rotate; run setup before rotating"
            )
        active = next((v for v in versions if v.is_active), None)
        if active is None:
            raise KeySetupError("no active backup key version to rotate from")

        # Recover the long-lived BMK via the seamless path and re-use it.
        bmk = self._unwrap_bdk_via_bmk_only(active)

        new_version = max(v.version for v in versions) + 1
        new_bdk = os.urandom(_BDK_SIZE)
        wrapped_bdk = _wrap_key(bmk, new_bdk)

        # Retain the prior version (still decryptable) and activate the new one.
        active.is_active = False
        row = BackupKeyVersion(
            version=new_version,
            is_active=True,
            kdf_algo=active.kdf_algo,
            kdf_params=dict(active.kdf_params or {}),
            kdf_salt=active.kdf_salt,
            wrapped_bmk_passphrase=active.wrapped_bmk_passphrase,
            wrapped_bmk_env=active.wrapped_bmk_env,
            wrapped_bdk=wrapped_bdk,
            bmk_kcv=active.bmk_kcv,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)

        logger.info(
            "Backup key rotated: minted BDK key version %s (prior version %s "
            "retained)",
            new_version,
            active.version,
        )
        return new_version

    def _unwrap_bdk_via_bmk_only(self, row: BackupKeyVersion) -> bytes:
        """Recover and verify the long-lived BMK from a row via the seamless path."""
        try:
            bmk = envelope_decrypt(row.wrapped_bmk_env)
        except Exception as exc:
            raise KeyMaterialMismatchError(
                f"key version {row.version} is present but its Backup_Master_Key "
                f"cannot be unwrapped on this deployment"
            ) from exc
        if not verify_kcv(bmk, row.bmk_kcv):
            raise KeyMaterialMismatchError(
                f"key version {row.version} failed key-check verification on this "
                f"deployment"
            )
        return bmk

    # ------------------------------------------------------------------
    # Key status (Req 16.12)
    # ------------------------------------------------------------------

    async def get_key_status(self) -> dict:
        """Report this deployment's backup-key state (Req 16.12).

        Returns a dict with:
          - ``has_active_key``: whether an active BMK/BDK is present **and usable**
            on this deployment (i.e. the active ``wrapped_bmk_env`` can be unwrapped
            with the current ``ENCRYPTION_MASTER_KEY`` and passes its KCV). On a
            fresh box whose master key was lost this is ``false`` even if the DB
            rows survived, so the restore flow knows to prompt for recovery key
            material (Req 16.7).
          - ``active_version``: the active key version when an active key is
            present and usable, else ``None``.
          - ``setup_complete``: whether any key version has ever been established.
        """
        versions = await self._load_versions()
        setup_complete = len(versions) > 0
        active = next((v for v in versions if v.is_active), None)

        has_active_key = False
        active_version: int | None = None
        if active is not None:
            try:
                bmk = envelope_decrypt(active.wrapped_bmk_env)
                if verify_kcv(bmk, active.bmk_kcv):
                    has_active_key = True
                    active_version = active.version
            except Exception:
                # Master key absent/different on this deployment (fresh box):
                # the active key is present in the catalog but not usable here.
                has_active_key = False

        return {
            "has_active_key": has_active_key,
            "active_version": active_version,
            "setup_complete": setup_complete,
        }
