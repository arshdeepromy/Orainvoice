"""Property-based test: backup artifact encryption round-trip under the BDK.

# Feature: cloud-backup-restore, Property 2: Artifact encryption round-trip under the BDK

**Validates: Requirements 16.1, 21.4**

For any plaintext (bytes or str) and any valid 256-bit Backup_Data_Key (BDK):

    backup_envelope_decrypt(backup_envelope_encrypt(plaintext, bdk), bdk) == plaintext

This is pure crypto — no storage adapters and no database are involved. The
property exercises :func:`backup_envelope_encrypt` /
:func:`backup_envelope_decrypt` in
``app/modules/backup_restore/keys/key_service.py``, which reuse the
AES-256-GCM envelope construction but key the DEK wrap under the supplied BDK
(never ``ENCRYPTION_MASTER_KEY``).
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.backup_restore.keys.key_service import (
    backup_envelope_decrypt,
    backup_envelope_encrypt,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A valid BDK is exactly 32 bytes (256-bit AES key).
bdks = st.binary(min_size=32, max_size=32)

# Plaintext can be arbitrary bytes (including empty) or an arbitrary str.
# The function accepts both; str is encoded to UTF-8 internally, so a str
# plaintext round-trips to its UTF-8 byte encoding.
byte_plaintexts = st.binary(min_size=0, max_size=4096)
str_plaintexts = st.text(min_size=0, max_size=2048)


# ---------------------------------------------------------------------------
# Property 2: Artifact encryption round-trip under the BDK
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(plaintext=byte_plaintexts, bdk=bdks)
def test_bytes_roundtrip_under_bdk(plaintext: bytes, bdk: bytes):
    """For any bytes plaintext and any valid BDK, decrypt(encrypt(x)) == x.

    **Validates: Requirements 16.1, 21.4**
    """
    blob = backup_envelope_encrypt(plaintext, bdk)

    # The encrypted artifact is never the plaintext (ciphertext leaves the box).
    assert blob != plaintext or plaintext == b""

    recovered = backup_envelope_decrypt(blob, bdk)
    assert recovered == plaintext, (
        f"round-trip mismatch: got {recovered!r} expected {plaintext!r}"
    )


@PBT_SETTINGS
@given(plaintext=str_plaintexts, bdk=bdks)
def test_str_roundtrip_under_bdk(plaintext: str, bdk: bytes):
    """For any str plaintext and any valid BDK, decrypt(encrypt(x)) == utf8(x).

    ``backup_envelope_encrypt`` encodes ``str`` as UTF-8, so the decrypted
    result equals the UTF-8 encoding of the original string.

    **Validates: Requirements 16.1, 21.4**
    """
    blob = backup_envelope_encrypt(plaintext, bdk)

    recovered = backup_envelope_decrypt(blob, bdk)
    assert recovered == plaintext.encode("utf-8"), (
        f"round-trip mismatch for str: got {recovered!r} "
        f"expected {plaintext.encode('utf-8')!r}"
    )
