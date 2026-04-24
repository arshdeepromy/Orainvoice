"""Compliance document file storage: upload, download, delete with validation.

Handles filesystem operations for compliance document files including
MIME type validation, magic byte verification, file size checks,
filename sanitisation, and secure path generation.

**Validates: Requirements 3.1, 3.2, 3.3, 3.6, 12.1, 12.2, 12.3, 12.4**
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import HTTPException, UploadFile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCEPTED_MIME_TYPES: set[str] = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ALLOWED_EXTENSIONS: set[str] = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".doc", ".docx",
}

MAX_FILE_SIZE: int = 10_485_760  # 10 MB

MAGIC_BYTES: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG",
    "image/gif": b"GIF8",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "application/msword": b"\xd0\xcf\x11\xe0",
}

MIME_TO_CONTENT_TYPE: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ComplianceFileStorage:
    """Manages compliance document files on the local filesystem."""

    def __init__(self, base_path: str = "/app/compliance_files") -> None:
        self.base_path = Path(base_path)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def save_file(self, org_id: uuid.UUID, file: UploadFile) -> str:
        """Validate and persist an uploaded file, returning the file_key.

        The file_key is a relative path like
        ``compliance/{org_id}/{uuid}_{sanitised_filename}``.
        """
        filename = file.filename or "unnamed"
        self._validate_filename(filename)
        self._validate_mime_type(file)

        content = await file.read()
        self._validate_file_size(content)
        self._validate_magic_bytes(content, file.content_type or "")

        file_key = self._generate_storage_path(org_id, filename)
        dest = self.base_path / file_key
        dest.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(dest.write_bytes, content)
        return file_key

    async def read_file(self, file_key: str) -> tuple[AsyncGenerator[bytes, None], str]:
        """Return an async byte generator and content_type for streaming.

        Raises ``HTTPException(404)`` if the file is missing from storage.
        """
        file_path = self.base_path / file_key
        # Prevent path traversal
        try:
            file_path.resolve().relative_to(self.base_path.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not await asyncio.to_thread(file_path.is_file):
            raise HTTPException(
                status_code=404,
                detail="File not found on server. The document record exists but the file is missing.",
            )

        ext = Path(file_key).suffix.lower()
        content_type = MIME_TO_CONTENT_TYPE.get(ext, "application/octet-stream")

        async def _stream() -> AsyncGenerator[bytes, None]:
            data = await asyncio.to_thread(file_path.read_bytes)
            chunk_size = 64 * 1024  # 64 KB chunks
            for i in range(0, len(data), chunk_size):
                yield data[i : i + chunk_size]

        return _stream(), content_type

    async def delete_file(self, file_key: str) -> None:
        """Remove a file from disk. Silently ignores missing files."""
        file_path = self.base_path / file_key
        # Prevent path traversal
        try:
            file_path.resolve().relative_to(self.base_path.resolve())
        except ValueError:
            return

        if await asyncio.to_thread(file_path.is_file):
            await asyncio.to_thread(file_path.unlink)

    # ------------------------------------------------------------------
    # Validation helpers (static for independent testability)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_mime_type(file: UploadFile) -> None:
        """Reject files whose declared MIME type is not in the accepted set."""
        mime = file.content_type or ""
        if mime not in ACCEPTED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail="File type not accepted. Allowed types: PDF, JPEG, PNG, GIF, Word (.doc, .docx)",
            )

    @staticmethod
    def _validate_file_size(content: bytes, max_size: int = MAX_FILE_SIZE) -> None:
        """Reject files larger than *max_size* bytes."""
        if len(content) > max_size:
            raise HTTPException(
                status_code=400,
                detail="File size exceeds maximum of 10MB",
            )

    @staticmethod
    def _validate_magic_bytes(content: bytes, declared_mime: str) -> None:
        """Verify that the file header bytes match the declared MIME type."""
        expected = MAGIC_BYTES.get(declared_mime)
        if expected is None:
            # Unknown MIME — nothing to verify against
            return
        if not content[:len(expected)] == expected:
            raise HTTPException(
                status_code=400,
                detail="File type could not be verified. The file content does not match the declared type.",
            )

    @staticmethod
    def _validate_filename(filename: str) -> None:
        """Reject filenames with double extensions where the final extension is suspicious."""
        # Strip leading/trailing whitespace
        name = filename.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Filename is required")

        # Split on dots — first part is the base name, rest are extensions
        parts = name.split(".")
        if len(parts) > 2:
            # Multiple extensions detected — check if the final extension is allowed
            final_ext = f".{parts[-1].lower()}"
            if final_ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail="Filename contains invalid extension pattern",
                )

    @staticmethod
    def _generate_storage_path(org_id: uuid.UUID, filename: str) -> str:
        """Build a safe storage path: ``compliance/{org_id}/{uuid}_{sanitised}``.

        - UUID prefix prevents collisions
        - Sanitisation removes path separators and traversal sequences
        - File extension is preserved from the original filename
        """
        # Sanitise: keep only safe characters (alphanumeric, hyphens, underscores, dots)
        safe_name = re.sub(r"[^\w.\-]", "_", filename.strip())
        # Remove any path traversal sequences
        safe_name = safe_name.replace("..", "_")
        # Remove leading dots (hidden files)
        safe_name = safe_name.lstrip(".")
        # Fallback if nothing remains
        if not safe_name:
            safe_name = "unnamed"

        unique_prefix = uuid.uuid4()
        return f"compliance/{org_id}/{unique_prefix}_{safe_name}"
