"""Provider-agnostic Storage_Interface contract and value types.

This module defines the single abstraction through which the Backup_System
performs every upload, list, download, and delete operation against any
backup destination (Google Drive, OneDrive, S3-compatible, or NAS). No
parameter or return type defined here references a specific Cloud_Provider,
so backup and restore logic stays identical regardless of which destination
type is active (Requirements 3.1, 3.2, 3.3).

Concrete adapters (``google_drive.py``, ``onedrive.py``, ``s3.py``,
``nas.py``) implement :class:`StorageInterface`; they are resolved at runtime
from the Global-Admin configuration via ``storage/registry.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# A provider-independent stream of bytes. Adapters receive already-encrypted
# bytes on upload and yield ciphertext on download; the type intentionally
# carries no provider-specific semantics.
AsyncByteStream = AsyncIterator[bytes]


class ConnectionState(str, Enum):
    """Provider-independent connection state for a storage destination.

    The connection-status operation returns one of exactly these states,
    independent of which Cloud_Provider implementation is active
    (Requirement 3.3).
    """

    connected = "connected"
    disconnected = "disconnected"
    error = "error"


@dataclass
class RemoteObject:
    """A stored object as seen through the provider-agnostic interface.

    ``key`` is the provider-independent logical path/key (for example
    ``"backups/<id>/dump.enc"``); it is never a provider-specific identifier.
    """

    key: str
    size_bytes: int
    modified_at: datetime | None


@dataclass
class UploadResult:
    """The result of a completed upload, in provider-independent terms."""

    key: str
    size_bytes: int
    checksum: str  # checksum of the encrypted bytes as stored


@dataclass
class StorageUsage:
    """Provider-independent storage quota/usage for a destination.

    Any field may be ``None`` when the provider does not report it (e.g. an
    unlimited account exposes no ``total_bytes``; object stores like S3 expose
    no quota at all). All values are in bytes.
    """

    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None


class StorageInterface(ABC):
    """Uniform contract for all backup storage destinations.

    Defines exactly five operations — upload, list, download, delete, and
    connection-status. Every operation accepts and returns provider-independent
    values; no signature references a specific Cloud_Provider (Requirement 3.2).
    Any provider whose adapter conforms to these five operations is supported
    with no changes to backup creation or restore logic (Requirement 3.4).
    """

    @abstractmethod
    async def upload(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        content_length: int,
        immutable_until: datetime | None = None,
    ) -> UploadResult:
        """Upload ``content_length`` bytes from ``source`` to ``key``.

        When ``immutable_until`` is supplied, the destination should apply
        write-once/object-lock retention until that instant where it supports
        such immutability.
        """
        ...

    @abstractmethod
    async def list(self, prefix: str) -> list[RemoteObject]:
        """List all stored objects whose key begins with ``prefix``."""
        ...

    @abstractmethod
    async def download(self, key: str) -> AsyncByteStream:
        """Open a byte stream for the object stored at ``key``."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object stored at ``key``."""
        ...

    @abstractmethod
    async def connection_status(self) -> ConnectionState:
        """Report the current connection state for this destination."""
        ...

    async def storage_usage(self) -> "StorageUsage | None":
        """Report the destination's storage quota/usage, or ``None`` if unknown.

        This is an OPTIONAL capability layered on top of the five core
        operations: providers that expose an account quota (Google Drive,
        OneDrive) override it; providers with no quota concept (S3-compatible
        object stores) use the default and return ``None``. Callers must treat
        ``None`` — and any ``None`` field — as "not reported" and degrade
        gracefully. It never raises: a provider/network failure resolves to
        ``None`` so a usage probe can never break a destination listing.
        """
        return None
