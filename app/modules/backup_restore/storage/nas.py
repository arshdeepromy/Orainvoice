"""NAS backup-storage adapter (atomic temp-file-then-rename writes).

This module implements :class:`NasAdapter`, the concrete
:class:`~app.modules.backup_restore.storage.interface.StorageInterface`
implementation for the ``nas`` provider, and registers it with the provider
registry under that name (Requirements 3.1-3.5, 3.8).

A NAS_Destination is reached as an SMB/CIFS share, an NFS export, or a
pre-mounted ``volume_path`` (Req 29.2). In every mode the adapter operates on
the destination through ordinary filesystem operations against a resolved base
directory — the share is expected to be mounted/accessible on the host (kernel
SMB/NFS mounting is an infrastructure concern handled outside the adapter), and
the pre-mounted ``volume_path`` mode addresses a local mount point directly.
All blocking filesystem IO is offloaded to a worker thread via
:func:`asyncio.to_thread` so the adapter never blocks the event loop.

Every backup-artifact write is **atomic**: the encrypted bytes are streamed to
a uniquely named temporary file in the configured directory, flushed and
``fsync``-ed, and only then atomically renamed (:func:`os.replace`) to the
final key — so a reader never observes a partially written artifact, and an
interrupted write leaves only a discardable temp file (Req 4.9, 29.6). A write
that fails with a transient filesystem/network error is retried on the Req 4.3
exponential-backoff schedule (1 s initial, x2, 60 s cap, <=1 s jitter, <=5
attempts); a non-transient failure — including a failed atomic rename — stops
immediately, removes any leftover temporary file, and surfaces a uniform error
(Req 4.10). NAS writes are not chunked: local/LAN writes need not be chunked,
but every write is atomic and retryable (Req 4.9).

The save-time connection test mounts/reaches the share and performs a
write-then-delete of a probe artifact in the configured directory; only a
successful round-trip gates the ``connected`` state (Req 29.5).

A standard NAS share provides no write-once-read-many (WORM) immutability, so a
NasAdapter is **not** an Immutable_Copy substitute: ``immutable_until`` is
accepted but cannot be enforced here, and immutable copies belong on an S3
Object-Lock destination unless the NAS itself offers native WORM/immutable
snapshots (Req 27.6).

Credentials (for example an SMB username/password) are stored envelope-encrypted
under ``ENCRYPTION_MASTER_KEY`` by the service layer (Req 29.4); this adapter
receives the already-decrypted configuration and never logs any credential
(Req 29.7). The adapter always receives already-encrypted bytes — encryption
happens in the backup pipeline before any adapter is invoked, so the share only
ever holds ciphertext (Req 29.8).
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import logging
import os
import random
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .errors import StorageError
from .interface import (
    AsyncByteStream,
    ConnectionState,
    RemoteObject,
    StorageInterface,
    UploadResult,
)
from .registry import register_adapter

logger = logging.getLogger(__name__)

PROVIDER = "nas"

# --- Share access modes (Req 29.2) ----------------------------------------
ACCESS_MODE_SMB = "smb"
ACCESS_MODE_NFS = "nfs"
ACCESS_MODE_VOLUME = "volume_path"
ACCESS_MODES = (ACCESS_MODE_SMB, ACCESS_MODE_NFS, ACCESS_MODE_VOLUME)

# --- Read/write streaming chunk (NAS writes need not be chunked; this is only
# the granularity for draining the source stream and for ranged download). ---
_IO_CHUNK = 16 * 1024 * 1024            # 16 MiB

# --- Retry/backoff constants (Req 4.3) ------------------------------------
_RETRY_INITIAL_DELAY = 1.0              # seconds
_RETRY_MULTIPLIER = 2.0
_RETRY_MAX_DELAY = 60.0                 # seconds
_RETRY_MAX_JITTER = 1.0                 # seconds
_MAX_WRITE_ATTEMPTS = 5                 # per artifact write (Req 4.3/4.9)

# Filesystem/network errno values treated as transient and therefore retriable
# (Req 4.3). A stale NFS handle, a busy/locked resource, a momentary network
# blip, or an interrupted syscall can all succeed on a later attempt.
_TRANSIENT_ERRNOS = frozenset(
    code
    for code in (
        getattr(errno, name, None)
        for name in (
            "EAGAIN",
            "EWOULDBLOCK",
            "EBUSY",
            "EINTR",
            "ETIMEDOUT",
            "ECONNRESET",
            "ECONNABORTED",
            "ENETDOWN",
            "ENETUNREACH",
            "EHOSTDOWN",
            "EHOSTUNREACH",
            "ESTALE",
            "EIO",
        )
    )
    if code is not None
)

# Permission/authentication errno values that mean the share rejected us; these
# map the connection probe to ``disconnected`` rather than ``error`` (Req 29.5).
_AUTH_ERRNOS = frozenset(
    code
    for code in (getattr(errno, name, None) for name in ("EACCES", "EPERM"))
    if code is not None
)

# Sleep + jitter hooks are module-level so tests can patch them deterministically.
SleepFn = Callable[[float], Awaitable[None]]
JitterFn = Callable[[], float]


def _default_jitter() -> float:
    return random.uniform(0.0, _RETRY_MAX_JITTER)


@dataclass
class NasConfig:
    """Provider-independent configuration for a NAS destination (Req 29.2).

    The credentials here are the **already-decrypted** values; the service
    layer decrypts ``BackupDestination.config_encrypted`` (stored under
    ``ENCRYPTION_MASTER_KEY``) before building the adapter (Req 29.4). The
    adapter never persists or logs credentials (Req 29.7).
    """

    # The network share path / mount target for ``smb``/``nfs`` modes, or the
    # pre-mounted local mount point for ``volume_path`` mode.
    share_path: str
    # Exactly one of ``smb`` (SMB/CIFS), ``nfs``, or ``volume_path``.
    access_mode: str = ACCESS_MODE_VOLUME
    # The directory, relative to the share/mount root, that holds artifacts.
    target_dir: str = ""
    # Credentials required by the selected access mode (SMB username/password).
    username: str | None = None
    password: str | None = None


class NasAdapter(StorageInterface):
    """``StorageInterface`` over a NAS share with atomic temp-then-rename writes."""

    provider_type = PROVIDER

    def __init__(
        self,
        config: NasConfig,
        *,
        sleep: SleepFn = asyncio.sleep,
        jitter: JitterFn = _default_jitter,
    ) -> None:
        self._validate_config(config)
        self._config = config
        self._sleep = sleep
        self._jitter = jitter

    # ------------------------------------------------------------------
    # Configuration / path resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_config(config: NasConfig) -> None:
        """Reject a configuration missing the share path or a required field.

        The full save-time validation (Req 29.3) lives in the service layer;
        this is a defensive guard so the adapter is never constructed against an
        unusable configuration.
        """
        if not (config.share_path and config.share_path.strip()):
            raise StorageError(
                "NAS destination is missing the network share path / mount "
                "target.",
                operation="resolve",
                provider=PROVIDER,
            )
        if config.access_mode not in ACCESS_MODES:
            raise StorageError(
                "NAS destination has an invalid access mode; expected one of "
                f"{ACCESS_MODES}.",
                operation="resolve",
                provider=PROVIDER,
            )
        # SMB shares authenticate with a username/password; an empty credential
        # is a missing required field for that mode (Req 29.3).
        if config.access_mode == ACCESS_MODE_SMB and not (
            config.username and config.password
        ):
            raise StorageError(
                "NAS destination configured for SMB is missing the username "
                "or password credential.",
                operation="resolve",
                provider=PROVIDER,
            )

    def _base_dir(self) -> Path:
        """Resolve the configured artifact directory on the (mounted) share.

        In every access mode the share is reached through the filesystem at
        ``share_path``; ``target_dir`` is the sub-directory that holds backup
        artifacts (Req 29.2).
        """
        root = Path(self._config.share_path)
        target = (self._config.target_dir or "").strip().strip("/")
        return (root / target) if target else root

    def _safe_path(self, key: str, *, operation: str) -> Path:
        """Resolve a logical ``key`` to an absolute path within the base dir.

        Keys are provider-independent logical paths (for example
        ``"backups/<id>/dump.enc"``). The resolved path is constrained to the
        configured directory so a malicious or malformed key cannot escape it.
        """
        if not key or not key.strip():
            raise StorageError(
                "Refusing a NAS operation with an empty object key.",
                operation=operation,
                provider=PROVIDER,
            )
        base = self._base_dir()
        # Normalise the key as a POSIX-style relative path and reject traversal.
        rel = PurePosixPath(key.strip().lstrip("/"))
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            raise StorageError(
                "Refusing a NAS object key that escapes the configured "
                "directory.",
                operation=operation,
                provider=PROVIDER,
            )
        return base.joinpath(*rel.parts)

    # ------------------------------------------------------------------
    # upload (Req 4.9, 29.6, 29.8)
    # ------------------------------------------------------------------
    async def upload(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        content_length: int,
        immutable_until: datetime | None = None,
    ) -> UploadResult:
        """Atomically write ``content_length`` bytes from ``source`` to ``key``.

        A standard NAS provides no object-lock/WORM retention, so
        ``immutable_until`` is accepted but cannot be enforced here; immutable
        copies belong on an S3 Object-Lock destination unless the NAS natively
        offers WORM (Req 27.6).
        """
        if content_length < 0:
            raise StorageError(
                "Refusing to upload with a negative content length.",
                operation="upload",
                provider=PROVIDER,
            )

        # Buffer the (already-encrypted) source once. NAS writes are atomic and
        # retryable from the buffered bytes; LAN writes need not be chunked
        # (Req 4.9), and buffering keeps a failed write fully replayable.
        payload = await _read_all(source)
        if len(payload) != content_length:
            raise StorageError(
                "NAS upload aborted: source produced "
                f"{len(payload)} bytes but {content_length} were declared.",
                operation="upload",
                provider=PROVIDER,
            )

        target = self._safe_path(key, operation="upload")
        await self._atomic_write_with_retry(target, payload)
        return UploadResult(
            key=key,
            size_bytes=len(payload),
            checksum=hashlib.sha256(payload).hexdigest(),
        )

    async def _atomic_write_with_retry(self, target: Path, payload: bytes) -> None:
        """Write ``payload`` to ``target`` atomically, retrying transient errors.

        Each attempt writes to a fresh temp file in the destination directory,
        ``fsync``-s it, and atomically renames it into place. A transient error
        retries on the Req 4.3 backoff schedule; a non-transient error — or a
        failed rename — stops immediately after removing any leftover temp file
        (Req 4.10).
        """
        delay = _RETRY_INITIAL_DELAY
        last_error: OSError | None = None

        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            try:
                await asyncio.to_thread(_atomic_write_blocking, target, payload)
                return
            except OSError as exc:
                last_error = exc
                if not _is_transient(exc):
                    # Non-transient (no space, read-only fs, permission, or a
                    # failed atomic rename) — stop now; the temp file was
                    # already cleaned up by the blocking writer (Req 4.10).
                    raise StorageError(
                        f"NAS upload failed: {_describe_oserror(exc)}.",
                        operation="upload",
                        provider=PROVIDER,
                    ) from exc
                logger.warning(
                    "Transient NAS write error for %s (attempt %d/%d).",
                    target.name,
                    attempt,
                    _MAX_WRITE_ATTEMPTS,
                )

            # Back off before the next attempt (skip after the final attempt).
            if attempt < _MAX_WRITE_ATTEMPTS:
                await self._sleep(delay + self._jitter())
                delay = min(delay * _RETRY_MULTIPLIER, _RETRY_MAX_DELAY)

        raise StorageError(
            "NAS upload failed: the artifact did not write atomically after "
            f"{_MAX_WRITE_ATTEMPTS} attempts.",
            operation="upload",
            provider=PROVIDER,
        ) from last_error

    # ------------------------------------------------------------------
    # list (Req 3.2, 29 — os.scandir / share walk of the configured dir)
    # ------------------------------------------------------------------
    async def list(self, prefix: str) -> list[RemoteObject]:
        base = self._base_dir()
        try:
            entries = await asyncio.to_thread(_walk_files, base)
        except FileNotFoundError:
            # An absent base directory simply contains no artifacts yet.
            return []
        except OSError as exc:
            raise StorageError(
                f"NAS list failed: {_describe_oserror(exc)}.",
                operation="list",
                provider=PROVIDER,
            ) from exc

        results: list[RemoteObject] = []
        for rel_key, size, mtime in entries:
            if prefix and not rel_key.startswith(prefix):
                continue
            results.append(
                RemoteObject(
                    key=rel_key,
                    size_bytes=size,
                    modified_at=datetime.fromtimestamp(mtime, tz=timezone.utc),
                ),
            )
        return results

    # ------------------------------------------------------------------
    # download (Req 3.2 — open + stream the file)
    # ------------------------------------------------------------------
    async def download(self, key: str) -> AsyncByteStream:
        target = self._safe_path(key, operation="download")
        # Confirm existence up front so a missing object surfaces as a uniform
        # error rather than failing mid-stream.
        exists = await asyncio.to_thread(target.is_file)
        if not exists:
            raise StorageError(
                "NAS download failed: no object found for the requested key.",
                operation="download",
                provider=PROVIDER,
            )

        sleep = self._sleep

        async def _stream() -> AsyncByteStream:
            handle = await asyncio.to_thread(open, target, "rb")
            try:
                while True:
                    chunk = await asyncio.to_thread(handle.read, _IO_CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(handle.close)

        return _stream()

    # ------------------------------------------------------------------
    # delete (Req 3.2 — unlink; a standard NAS has no WORM to refuse against)
    # ------------------------------------------------------------------
    async def delete(self, key: str) -> None:
        target = self._safe_path(key, operation="delete")
        try:
            await asyncio.to_thread(target.unlink)
        except FileNotFoundError:
            # Already gone — delete is idempotent.
            return
        except OSError as exc:
            raise StorageError(
                f"NAS delete failed: {_describe_oserror(exc)}.",
                operation="delete",
                provider=PROVIDER,
            ) from exc

    # ------------------------------------------------------------------
    # connection_status (Req 3.3, 29.5 — reach the share + write-then-delete)
    # ------------------------------------------------------------------
    async def connection_status(self) -> ConnectionState:
        """Probe the share by writing then deleting a test artifact (Req 29.5).

        A successful round-trip reports ``connected``. A permission/auth
        rejection reports ``disconnected``; any other failure (share
        unreachable, mount failed, directory not writable) reports ``error``.
        """
        try:
            await asyncio.to_thread(_connection_probe_blocking, self._base_dir())
        except OSError as exc:
            if exc.errno in _AUTH_ERRNOS:
                logger.warning(
                    "NAS connection probe was rejected by the share "
                    "(permission denied).",
                )
                return ConnectionState.disconnected
            logger.warning(
                "NAS connection probe failed: %s.", _describe_oserror(exc),
            )
            return ConnectionState.error
        return ConnectionState.connected


# ---------------------------------------------------------------------------
# Blocking filesystem helpers (run via asyncio.to_thread)
# ---------------------------------------------------------------------------
def _atomic_write_blocking(target: Path, payload: bytes) -> None:
    """Write ``payload`` to ``target`` via temp-file-then-atomic-rename.

    The temp file is created in the destination directory so the final
    :func:`os.replace` is an atomic, same-filesystem rename. On any failure the
    temp file is removed so no partial artifact is left behind (Req 4.9, 4.10,
    29.6).
    """
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=parent, prefix=f".{target.name}.", suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic rename into place only after the complete artifact is durable
        # (Req 4.9, 29.6). A failed rename propagates as a non-transient error.
        os.replace(tmp_path, target)
    except BaseException:
        # Remove the leftover temp file on any failure (Req 4.10).
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning(
                "Failed to remove NAS temporary file after a failed write.",
            )
        raise


def _walk_files(base: Path) -> list[tuple[str, int, float]]:
    """Recursively list files under ``base`` as ``(rel_key, size, mtime)``.

    ``rel_key`` is the POSIX-style path relative to ``base`` so it matches the
    provider-independent logical key used on upload.
    """
    results: list[tuple[str, int, float]] = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            full = Path(dirpath) / name
            try:
                stat = full.stat()
            except FileNotFoundError:
                # Raced with a concurrent delete; skip it.
                continue
            rel = full.relative_to(base).as_posix()
            results.append((rel, stat.st_size, stat.st_mtime))
    return results


def _connection_probe_blocking(base: Path) -> None:
    """Reach the share and write-then-delete a probe artifact (Req 29.5)."""
    base.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=base, prefix=".nas-connect-test.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"ok")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _read_all(source: AsyncByteStream) -> bytes:
    """Drain an async byte stream into a single ``bytes`` object."""
    parts: list[bytes] = []
    async for piece in source:
        parts.append(piece)
    return b"".join(parts)


def _is_transient(exc: OSError) -> bool:
    """True when an OS error is retriable per the transient errno set."""
    return exc.errno in _TRANSIENT_ERRNOS


def _describe_oserror(exc: OSError) -> str:
    """Human-readable, credential-free description of a filesystem error.

    Only the errno name/symbolic reason is surfaced — never the configuration
    or any credential (Req 29.7).
    """
    if exc.errno == getattr(errno, "ENOSPC", None):
        return "the share has insufficient free space"
    if exc.errno == getattr(errno, "EROFS", None):
        return "the share is read-only"
    if exc.errno in _AUTH_ERRNOS:
        return "the share rejected the write (permission denied)"
    if exc.errno == getattr(errno, "ENOENT", None):
        return "the configured directory is unreachable"
    if exc.errno is not None:
        name = errno.errorcode.get(exc.errno, str(exc.errno))
        return f"a filesystem error occurred ({name})"
    return "a filesystem error occurred"


# ---------------------------------------------------------------------------
# Registry wiring (Req 3.4, 3.5, 3.8)
# ---------------------------------------------------------------------------
def _build_nas_adapter(config: NasConfig | dict, **kwargs: object) -> NasAdapter:
    """Factory used by the provider registry.

    Accepts either a :class:`NasConfig` or a plain decrypted config mapping (the
    service layer decrypts ``config_encrypted`` then forwards it).
    """
    if isinstance(config, dict):
        config = NasConfig(
            share_path=config.get("share_path", "") or "",
            access_mode=config.get("access_mode", ACCESS_MODE_VOLUME),
            target_dir=config.get("target_dir", "") or "",
            username=config.get("username"),
            password=config.get("password"),
        )
    return NasAdapter(config, **kwargs)  # type: ignore[arg-type]


register_adapter(PROVIDER, _build_nas_adapter)
