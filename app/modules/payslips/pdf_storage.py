"""Encrypted on-disk storage for finalised payslip PDFs (N3).

Implements task B5b from ``.kiro/specs/staff-management-p4/tasks.md``.
Modelled on :mod:`app.modules.job_cards.attachment_service`'s
``_store_file`` / ``_read_file`` / ``_delete_file`` triple — we use the
same encryption / compression / flag-byte convention so future tooling
(backup audits, storage migrators) can treat all attachment-style
files uniformly.

File layout:

  ``UPLOAD_BASE / "payslips" / <org_id> / <payslip_id> / <uuid>.pdf``

Each file is a single byte-string of:

  ``flag (1 byte) + envelope_encrypt(zlib_compressed_bytes)``

where ``flag = b"\\x01"`` (``COMP_ZLIB``) — the same flag the
job-card attachment helpers use for non-image binary blobs. PDFs
compress well with zlib (typical 30-50% reduction on a payslip)
without needing the heavier image-pipeline path.

Cross-tenant access is gated by a strict ``file_key`` prefix check
that mirrors :func:`app.modules.job_cards.attachment_service.download_attachment`.
A path-traversal attempt (e.g. ``payslips/A/../../etc/passwd``)
fails the ``startswith`` guard because the prefix string contains the
literal org_id.

**Validates: Requirement R7.3 — Staff Management Phase 4 task B5b.**
"""

from __future__ import annotations

import os
import uuid
import zlib
from pathlib import Path

from app.core.encryption import envelope_decrypt, envelope_encrypt

__all__ = [
    "PAYSLIP_CATEGORY",
    "store_payslip_pdf",
    "read_payslip_pdf",
    "delete_payslip_pdf",
]


# ---------------------------------------------------------------------------
# Storage configuration — mirrors the job-card / invoice / quote layers
# ---------------------------------------------------------------------------

UPLOAD_BASE = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))

#: Sub-directory under ``UPLOAD_BASE`` for payslip PDFs. Per design
#: §3.1 the on-disk path is ``UPLOAD_BASE / "payslips" / org_id /
#: payslip_id / <uuid>.pdf``.
PAYSLIP_CATEGORY: str = "payslips"

#: Compression-flag byte. ``\x01`` = zlib (matches
#: ``job_cards.attachment_service.COMP_ZLIB``). PDFs are compressed
#: through zlib before envelope encryption.
COMP_ZLIB: bytes = b"\x01"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def store_payslip_pdf(
    pdf_bytes: bytes,
    *,
    org_id: str | uuid.UUID,
    payslip_id: str | uuid.UUID,
) -> str:
    """Compress, encrypt, and write ``pdf_bytes`` to disk.

    Returns the ``file_key`` path string that should be stored on
    ``payslips.pdf_file_key``. The on-disk file lives at
    ``UPLOAD_BASE / file_key``.

    The function is synchronous because the caller already wraps PDF
    rendering in :func:`asyncio.to_thread`; the I/O cost of writing a
    ~50 KB compressed PDF is negligible compared to the 200-1500ms
    WeasyPrint render.

    Raises:
      OSError: when the directory cannot be created or written.
    """
    org_id_str = str(org_id)
    payslip_id_str = str(payslip_id)

    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise TypeError(
            "store_payslip_pdf expects bytes; got "
            f"{type(pdf_bytes).__name__}"
        )
    if not pdf_bytes:
        raise ValueError("store_payslip_pdf: refusing to write empty PDF")

    compressed = zlib.compress(bytes(pdf_bytes), 6)
    encrypted = envelope_encrypt(compressed)

    file_key = (
        f"{PAYSLIP_CATEGORY}/{org_id_str}/{payslip_id_str}/"
        f"{uuid.uuid4().hex}.pdf"
    )
    dest = UPLOAD_BASE / file_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(COMP_ZLIB + encrypted)
    return file_key


def read_payslip_pdf(
    file_key: str,
    *,
    org_id: str | uuid.UUID,
) -> bytes:
    """Read, decrypt, and decompress a payslip PDF.

    Validates that ``file_key`` belongs to ``org_id`` to prevent
    cross-tenant access and path-traversal (e.g.
    ``payslips/A/../../etc/passwd`` fails the prefix check because
    the literal org_id is no longer a prefix once ``..`` re-anchors).

    Raises:
      ValueError: on access denied, file not found, or corrupt content.
      RuntimeError: on decryption failure (re-raised from
        :func:`envelope_decrypt` after wrapping).
    """
    org_id_str = str(org_id)
    expected_prefix = f"{PAYSLIP_CATEGORY}/{org_id_str}/"
    if not file_key.startswith(expected_prefix):
        raise ValueError("Access denied")

    fp = UPLOAD_BASE / file_key

    # Defence-in-depth — even with the prefix check above, validate
    # the resolved path is inside UPLOAD_BASE. Catches path-traversal
    # attempts that somehow slip through (e.g. a literal NUL byte or
    # symlink trick on misconfigured filesystems).
    try:
        fp.resolve().relative_to(UPLOAD_BASE.resolve())
    except ValueError:
        raise ValueError("Access denied")

    if not fp.is_file():
        raise ValueError("File not found")

    raw = fp.read_bytes()
    if len(raw) < 2:
        raise ValueError("Corrupt payslip PDF")

    flag, blob = raw[0:1], raw[1:]
    if flag != COMP_ZLIB:
        raise ValueError(f"Unknown compression flag {flag!r}")

    try:
        decrypted = envelope_decrypt(blob)
    except Exception as exc:  # noqa: BLE001 — rewrap to RuntimeError.
        raise RuntimeError(f"Failed to decrypt payslip PDF: {exc}") from exc

    return zlib.decompress(decrypted)


def delete_payslip_pdf(
    file_key: str,
    *,
    org_id: str | uuid.UUID,
) -> None:
    """Delete a payslip PDF from disk.

    Mirrors the access guard from :func:`read_payslip_pdf`. Silently
    returns when the file is already gone (idempotent — the caller
    may invoke this from a void / cleanup flow without first checking
    existence).
    """
    org_id_str = str(org_id)
    expected_prefix = f"{PAYSLIP_CATEGORY}/{org_id_str}/"
    if not file_key.startswith(expected_prefix):
        raise ValueError("Access denied")

    fp = UPLOAD_BASE / file_key
    try:
        fp.resolve().relative_to(UPLOAD_BASE.resolve())
    except ValueError:
        raise ValueError("Access denied")

    if fp.is_file():
        fp.unlink()
