"""Envelope encryption for secrets.

Implements a two-layer encryption scheme:

1. A **master key** (from ``settings.encryption_master_key``) is used to
   encrypt/decrypt per-record **data encryption keys** (DEKs).
2. Each secret gets its own random DEK.  The DEK encrypts the plaintext,
   and the encrypted DEK is stored alongside the ciphertext.

This means rotating the master key only requires re-encrypting the DEKs,
not every secret in the database.

Storage format (bytes)::

    [4 bytes: DEK ciphertext length (big-endian)]
    [N bytes: encrypted DEK (nonce ‖ ciphertext ‖ tag)]
    [remaining: encrypted payload (nonce ‖ ciphertext ‖ tag)]

Both layers use AES-256-GCM via the ``cryptography`` library.
"""

from __future__ import annotations

import hashlib
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

_NONCE_SIZE = 12  # 96-bit nonce for AES-GCM


def _derive_master_key() -> bytes:
    """Derive a 256-bit key from the configured master key string."""
    return hashlib.sha256(settings.encryption_master_key.encode()).digest()


# ---------------------------------------------------------------------------
# Low-level AES-GCM helpers
# ---------------------------------------------------------------------------

def _aes_encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt *plaintext* with AES-256-GCM.  Returns ``nonce ‖ ciphertext``."""
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _aes_decrypt(key: bytes, blob: bytes) -> bytes:
    """Decrypt a ``nonce ‖ ciphertext`` blob produced by ``_aes_encrypt``."""
    nonce = blob[:_NONCE_SIZE]
    ciphertext = blob[_NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


# ---------------------------------------------------------------------------
# Public API — envelope encrypt / decrypt
# ---------------------------------------------------------------------------

def envelope_encrypt(plaintext: str | bytes) -> bytes:
    """Encrypt *plaintext* using envelope encryption.

    Returns an opaque ``bytes`` blob suitable for storing in a ``BYTEA``
    column.  Use ``envelope_decrypt`` to recover the original value.
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    master_key = _derive_master_key()

    # Generate a random DEK and encrypt the payload with it.
    dek = os.urandom(32)  # 256-bit DEK
    encrypted_payload = _aes_encrypt(dek, plaintext)

    # Encrypt the DEK with the master key.
    encrypted_dek = _aes_encrypt(master_key, dek)

    # Pack: [4-byte DEK length][encrypted DEK][encrypted payload]
    return struct.pack(">I", len(encrypted_dek)) + encrypted_dek + encrypted_payload


def envelope_decrypt(blob: bytes) -> bytes:
    """Decrypt a blob produced by ``envelope_encrypt``.

    Returns the original plaintext as ``bytes``.
    """
    master_key = _derive_master_key()

    # Unpack the DEK length header.
    (dek_len,) = struct.unpack(">I", blob[:4])
    encrypted_dek = blob[4 : 4 + dek_len]
    encrypted_payload = blob[4 + dek_len :]

    # Decrypt the DEK, then decrypt the payload.
    dek = _aes_decrypt(master_key, encrypted_dek)
    return _aes_decrypt(dek, encrypted_payload)


def envelope_decrypt_str(blob: bytes) -> str:
    """Convenience wrapper that returns the decrypted value as a UTF-8 string."""
    return envelope_decrypt(blob).decode("utf-8")


# ---------------------------------------------------------------------------
# High-level field encryption API (Task 51.2)
# ---------------------------------------------------------------------------


def encrypt_field(value: str) -> bytes:
    """Encrypt a PII field value (tax numbers, bank details, API keys).

    Wrapper around ``envelope_encrypt`` for use with model column hooks.
    """
    if not value:
        return b""
    return envelope_encrypt(value)


def decrypt_field(blob: bytes) -> str:
    """Decrypt a PII field value back to plaintext string.

    Wrapper around ``envelope_decrypt_str`` for use with model column hooks.
    """
    if not blob:
        return ""
    return envelope_decrypt_str(blob)


def rotate_master_key(old_key: str, new_key: str, blob: bytes) -> bytes:
    """Re-encrypt a blob under a new master key.

    Only the DEK wrapper is re-encrypted — the payload stays the same.
    This enables key rotation without touching every encrypted value's
    inner ciphertext.
    """
    import struct

    old_master = hashlib.sha256(old_key.encode()).digest()
    new_master = hashlib.sha256(new_key.encode()).digest()

    # Unpack the existing blob
    (dek_len,) = struct.unpack(">I", blob[:4])
    encrypted_dek = blob[4 : 4 + dek_len]
    encrypted_payload = blob[4 + dek_len :]

    # Decrypt DEK with old key, re-encrypt with new key
    dek = _aes_decrypt(old_master, encrypted_dek)
    new_encrypted_dek = _aes_encrypt(new_master, dek)

    return struct.pack(">I", len(new_encrypted_dek)) + new_encrypted_dek + encrypted_payload
