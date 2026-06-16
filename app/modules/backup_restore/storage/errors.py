"""Uniform error types for the provider-agnostic Storage_Interface.

Every storage destination (Google Drive, OneDrive, S3-compatible, NAS) and the
provider registry raise :class:`StorageError` so that backup and restore logic
sees a single, provider-independent failure type regardless of which
Cloud_Provider is active. Concrete adapters (``google_drive.py``,
``onedrive.py``, ``s3.py``, ``nas.py`` — tasks 4.3-4.6) normalise their
provider-specific SDK/API failures to :class:`StorageError`, identifying the
failed operation, so the prior backup state can be preserved without partial
modification (Requirement 3.7).

:class:`ProviderUnavailableError` is the specific, uniform "provider
unavailable" error raised when the configured provider is missing or has no
registered adapter (Requirement 3.6). It is raised *before* any upload, list,
download, or delete is attempted.
"""

from __future__ import annotations


class StorageError(Exception):
    """Uniform, provider-independent storage failure.

    Carries the logical ``operation`` that failed (one of ``upload``,
    ``list``, ``download``, ``delete``, ``connection_status``, or ``resolve``)
    and the ``provider`` type involved, where known. No provider-specific
    detail (SDK exception types, raw API payloads, credentials, or tokens) is
    ever placed in the message — callers and adapters are responsible for
    excluding secrets from the normalised message (Requirements 2.8, 3.7).
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.operation = operation
        self.provider = provider

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        parts = [self.message]
        if self.operation:
            parts.append(f"operation={self.operation}")
        if self.provider:
            parts.append(f"provider={self.provider}")
        return " ".join(parts)


class ProviderUnavailableError(StorageError):
    """The configured Cloud_Provider cannot be used.

    Raised when the Global-Admin configuration identifies no provider, or
    identifies a provider that has no registered Storage_Interface
    implementation (Requirement 3.6). Raising this error guarantees that no
    upload, list, download, or delete was attempted.
    """
