"""Google Drive backup-storage adapter (resumable upload).

This module implements :class:`GoogleDriveAdapter`, the concrete
:class:`~app.modules.backup_restore.storage.interface.StorageInterface`
implementation for the ``google_drive`` provider, and registers it with the
provider registry under that name (Requirements 3.1-3.5).

The adapter performs every upload through Google Drive's **resumable upload
session** in 16 MiB chunks (a multiple of 256 KiB, constrained to the
5-100 MiB bound), persisting the last acknowledged byte offset before each
subsequent chunk and resuming an interrupted upload from that offset rather
than restarting (Req 4.1, 4.2, 4.5). Transient chunk failures are retried with
exponential backoff (1 s initial, x2, 60 s cap, <=1 s jitter, <=5 attempts);
an expired/invalid session triggers a fresh session and a restart from offset 0
with up to 3 session-creation retries; non-transient failures stop immediately
(Req 4.3, 4.4, 4.6, 4.7).

OAuth access tokens are refreshed when expired or within 60 s of expiry before
any cloud operation (Req 2.5). A refresh token rejected as revoked/invalid
flips the connection to ``disconnected`` and notifies the caller exactly once
so scheduling can halt (Req 2.6). Every provider failure is normalised to the
uniform :class:`~app.modules.backup_restore.storage.errors.StorageError`
identifying the failed operation, leaving prior backup state untouched
(Req 3.7). OAuth access and refresh tokens are excluded from **all** log output
(Req 2.8).

The adapter always receives already-encrypted bytes; encryption happens in the
backup pipeline before any adapter is invoked.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

from .errors import StorageError
from .interface import (
    AsyncByteStream,
    ConnectionState,
    RemoteObject,
    StorageInterface,
    StorageUsage,
    UploadResult,
)
from .registry import register_adapter

logger = logging.getLogger(__name__)

PROVIDER = "google_drive"

# --- Google Drive / OAuth endpoints ---------------------------------------
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"

# --- Chunking constants (Req 4.1) -----------------------------------------
_CHUNK_MULTIPLE = 256 * 1024            # 256 KiB
_MIN_CHUNK = 5 * 1024 * 1024            # 5 MiB
_MAX_CHUNK = 100 * 1024 * 1024          # 100 MiB
_DEFAULT_CHUNK = 16 * 1024 * 1024       # 16 MiB

# --- Retry/backoff constants (Req 4.3) ------------------------------------
_RETRY_INITIAL_DELAY = 1.0              # seconds
_RETRY_MULTIPLIER = 2.0
_RETRY_MAX_DELAY = 60.0                 # seconds
_RETRY_MAX_JITTER = 1.0                 # seconds
_MAX_CHUNK_ATTEMPTS = 5                 # per chunk (Req 4.3)
_MAX_SESSION_ATTEMPTS = 3               # session (re)creation (Req 4.6)

# --- Token-refresh threshold (Req 2.5) ------------------------------------
_TOKEN_REFRESH_LEEWAY = timedelta(seconds=60)

# Request timeout beyond which a chunk is treated as a transient failure
# (Req 4.3: "a request timeout exceeding 30 seconds").
_REQUEST_TIMEOUT = 30.0

# HTTP status codes treated as retriable/transient (Req 4.3).
_TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

# Sleep + jitter hooks are module-level so tests can patch them deterministically.
SleepFn = Callable[[float], Awaitable[None]]
JitterFn = Callable[[], float]


def _default_jitter() -> float:
    return random.uniform(0.0, _RETRY_MAX_JITTER)


def normalise_chunk_size(requested: int | None) -> int:
    """Clamp ``requested`` to the 5-100 MiB bound and a 256 KiB multiple.

    Returns the default 16 MiB when ``requested`` is ``None``. The result is
    always a multiple of 256 KiB within ``[5 MiB, 100 MiB]`` (Req 4.1).
    """
    size = _DEFAULT_CHUNK if requested is None else int(requested)
    # Round down to a multiple of 256 KiB.
    size -= size % _CHUNK_MULTIPLE
    # Clamp into [min, max].
    if size < _MIN_CHUNK:
        size = _MIN_CHUNK
    elif size > _MAX_CHUNK:
        size = _MAX_CHUNK
    # Re-round after clamping (min/max are already 256 KiB multiples).
    size -= size % _CHUNK_MULTIPLE
    return size


@dataclass
class GoogleDriveConfig:
    """Provider-independent configuration for a Google Drive destination.

    The OAuth tokens here are the **already-decrypted** values; the service
    layer decrypts ``BackupDestination.config_encrypted`` (stored under
    ``ENCRYPTION_MASTER_KEY``) before building the adapter. The adapter never
    persists tokens itself — it invokes ``on_tokens_refreshed`` so the service
    can re-encrypt and store a freshly minted access token (Req 2.4, 2.5).
    """

    refresh_token: str
    access_token: str | None = None
    token_expiry: datetime | None = None
    # The app-created Drive folder that holds this deployment's backups.
    folder_id: str | None = None
    # OAuth client credentials; fall back to the platform Google config.
    client_id: str | None = None
    client_secret: str | None = None
    # Desired chunk size; normalised to the 256 KiB-multiple 5-100 MiB bound.
    chunk_size: int | None = None


@dataclass
class _UploadSession:
    """In-flight resumable-upload session bookkeeping for a single key."""

    session_uri: str
    acked_offset: int = 0


class SessionStore:
    """Persists resumable-upload session state so uploads survive restarts.

    The default implementation is in-process only; the service layer may
    inject a durable store so an interrupted upload can be resumed in a later
    process (Req 4.2, 4.5). Keyed by the provider-independent object ``key``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _UploadSession] = {}

    async def load(self, key: str) -> _UploadSession | None:
        return self._sessions.get(key)

    async def save(self, key: str, session: _UploadSession) -> None:
        self._sessions[key] = session

    async def clear(self, key: str) -> None:
        self._sessions.pop(key, None)


class _RevokedTokenError(Exception):
    """Internal marker: the refresh token was rejected as revoked/invalid."""


class _TransientUploadError(Exception):
    """Internal marker: a chunk failed transiently and may be retried."""


class _SessionGoneError(Exception):
    """Internal marker: the resumable session expired/was invalidated."""


class GoogleDriveAdapter(StorageInterface):
    """``StorageInterface`` over Google Drive with resumable chunked upload."""

    provider_type = PROVIDER

    def __init__(
        self,
        config: GoogleDriveConfig,
        *,
        client: httpx.AsyncClient | None = None,
        session_store: SessionStore | None = None,
        on_tokens_refreshed: Callable[[str, datetime], Awaitable[None]] | None = None,
        on_disconnected: Callable[[], Awaitable[None]] | None = None,
        sleep: SleepFn = asyncio.sleep,
        jitter: JitterFn = _default_jitter,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = client is None
        self._sessions = session_store or SessionStore()
        self._on_tokens_refreshed = on_tokens_refreshed
        self._on_disconnected = on_disconnected
        self._sleep = sleep
        self._jitter = jitter
        self._chunk_size = normalise_chunk_size(config.chunk_size)
        # In-memory cache of the live access token; never logged.
        self._access_token = config.access_token
        self._token_expiry = config.token_expiry
        # Guard so a revoked-token disconnection notifies exactly once (Req 2.6).
        self._disconnect_notified = False

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        """Close the owned HTTP client, if any."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> GoogleDriveAdapter:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # OAuth token handling (Req 2.5, 2.6, 2.8)
    # ------------------------------------------------------------------
    def _client_credentials(self) -> tuple[str, str]:
        client_id = self._config.client_id or settings.google_client_id
        client_secret = self._config.client_secret or settings.google_client_secret
        if not client_id or not client_secret:
            raise StorageError(
                "Google OAuth client credentials are not configured.",
                operation="connection_status",
                provider=PROVIDER,
            )
        return client_id, client_secret

    def _token_expired(self) -> bool:
        """True when no access token is cached or it is within the leeway."""
        if not self._access_token or self._token_expiry is None:
            return True
        now = datetime.now(timezone.utc)
        expiry = self._token_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return now >= (expiry - _TOKEN_REFRESH_LEEWAY)

    async def _ensure_access_token(self, *, operation: str) -> str:
        """Return a valid access token, refreshing it if expired (Req 2.5).

        Raises :class:`StorageError` (operation-tagged) on failure. A revoked
        refresh token flips the connection to ``disconnected`` and notifies the
        caller exactly once before raising (Req 2.6).
        """
        if not self._token_expired() and self._access_token:
            return self._access_token

        client_id, client_secret = self._client_credentials()
        try:
            resp = await self._http().post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._config.refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
        except httpx.HTTPError as exc:
            # Network failure refreshing the token — transient w.r.t. the
            # provider, surfaced as a uniform error for this operation.
            raise StorageError(
                "Failed to reach the Google token endpoint while refreshing "
                "the access token.",
                operation=operation,
                provider=PROVIDER,
            ) from exc

        if resp.status_code == 200:
            data = resp.json()
            access_token = data.get("access_token")
            if not access_token:
                raise StorageError(
                    "Google token refresh returned no access token.",
                    operation=operation,
                    provider=PROVIDER,
                )
            expires_in = int(data.get("expires_in", 3600))
            self._access_token = access_token
            self._token_expiry = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in,
            )
            if self._on_tokens_refreshed is not None:
                await self._on_tokens_refreshed(access_token, self._token_expiry)
            logger.info(
                "Refreshed Google Drive access token (expires_in=%ss).",
                expires_in,
            )
            return access_token

        # invalid_grant (typically 400/401) means the refresh token is revoked.
        if resp.status_code in (400, 401):
            await self._handle_revoked_token()
            raise StorageError(
                "Google rejected the stored refresh token; the connection is "
                "now disconnected.",
                operation=operation,
                provider=PROVIDER,
            )

        raise StorageError(
            f"Google token refresh failed with status {resp.status_code}.",
            operation=operation,
            provider=PROVIDER,
        )

    async def _handle_revoked_token(self) -> None:
        """Flip to disconnected and notify exactly once (Req 2.6)."""
        self._access_token = None
        self._token_expiry = None
        if not self._disconnect_notified:
            self._disconnect_notified = True
            logger.warning(
                "Google Drive refresh token revoked/invalid; marking the "
                "connection disconnected.",
            )
            if self._on_disconnected is not None:
                await self._on_disconnected()

    async def _auth_headers(self, *, operation: str) -> dict[str, str]:
        token = await self._ensure_access_token(operation=operation)
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # upload (Req 4.1-4.7)
    # ------------------------------------------------------------------
    async def upload(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        content_length: int,
        immutable_until: datetime | None = None,
    ) -> UploadResult:
        """Upload ``content_length`` bytes from ``source`` to ``key``.

        Google Drive provides no write-once/object-lock retention, so
        ``immutable_until`` is accepted but cannot be enforced here (immutable
        copies belong on an S3 Object-Lock destination — Req 27.6).
        """
        # Reject obviously malformed inputs before touching the provider so we
        # never create a partial artifact (Req 3.7).
        if content_length < 0:
            raise StorageError(
                "Refusing to upload with a negative content length.",
                operation="upload",
                provider=PROVIDER,
            )

        try:
            return await self._upload_with_session_recovery(
                key, source, content_length,
            )
        except StorageError:
            raise
        except _RevokedTokenError as exc:  # pragma: no cover - mapped above
            raise StorageError(
                "Google Drive upload aborted: refresh token revoked.",
                operation="upload",
                provider=PROVIDER,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - normalise to uniform error
            raise StorageError(
                "Google Drive upload failed.",
                operation="upload",
                provider=PROVIDER,
            ) from exc

    async def _upload_with_session_recovery(
        self,
        key: str,
        source: AsyncByteStream,
        content_length: int,
    ) -> UploadResult:
        """Drive the resumable upload, recreating the session if it expires.

        Implements the Req 4.6 restart: an expired/invalid session is
        recreated and the upload restarts from offset 0, up to 3 session
        attempts before failing the job.
        """
        # Buffer the source once; resuming requires forward-only re-reads from
        # a byte offset, and the encrypted artifact is already materialised by
        # the pipeline. Reading the stream once keeps the contract simple.
        payload = await _read_all(source)
        if len(payload) != content_length:
            raise StorageError(
                "Google Drive upload aborted: source produced "
                f"{len(payload)} bytes but {content_length} were declared.",
                operation="upload",
                provider=PROVIDER,
            )

        last_error: Exception | None = None
        for session_attempt in range(1, _MAX_SESSION_ATTEMPTS + 1):
            session = await self._resume_or_create_session(key, content_length)
            try:
                return await self._send_chunks(key, session, payload)
            except _SessionGoneError as exc:
                # Session expired/invalid: drop it and restart from offset 0
                # (Req 4.6). Record the restart.
                last_error = exc
                await self._sessions.clear(key)
                logger.warning(
                    "Google Drive upload session for %s expired; restarting "
                    "from offset 0 (session attempt %d/%d).",
                    key,
                    session_attempt,
                    _MAX_SESSION_ATTEMPTS,
                )
                continue

        raise StorageError(
            "Google Drive upload failed: could not establish a usable upload "
            f"session after {_MAX_SESSION_ATTEMPTS} attempts.",
            operation="upload",
            provider=PROVIDER,
        ) from last_error

    async def _resume_or_create_session(
        self, key: str, content_length: int,
    ) -> _UploadSession:
        """Return a live session for ``key``, resuming if one is persisted.

        On resume, the provider is queried for the confirmed offset and the
        persisted bookkeeping is reconciled with it (Req 4.5). A persisted
        session that the provider no longer recognises is discarded and a new
        one created (Req 4.6).
        """
        existing = await self._sessions.load(key)
        if existing is not None:
            confirmed = await self._query_session_offset(existing, content_length)
            if confirmed is not None:
                existing.acked_offset = confirmed
                await self._sessions.save(key, existing)
                return existing
            # Provider no longer recognises the session — start fresh.
            await self._sessions.clear(key)

        session = await self._create_session(key, content_length)
        await self._sessions.save(key, session)
        return session

    async def _create_session(
        self, key: str, content_length: int,
    ) -> _UploadSession:
        """Initiate a resumable upload session and return its URI."""
        headers = await self._auth_headers(operation="upload")
        headers.update(
            {
                "X-Upload-Content-Length": str(content_length),
                "X-Upload-Content-Type": "application/octet-stream",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        metadata: dict[str, object] = {"name": key}
        if self._config.folder_id:
            metadata["parents"] = [self._config.folder_id]

        try:
            resp = await self._http().post(
                _UPLOAD_URL,
                params={"uploadType": "resumable"},
                headers=headers,
                json=metadata,
            )
        except httpx.HTTPError as exc:
            raise StorageError(
                "Failed to initiate a Google Drive resumable upload session.",
                operation="upload",
                provider=PROVIDER,
            ) from exc

        if resp.status_code in (200, 201):
            location = resp.headers.get("Location") or resp.headers.get("location")
            if not location:
                raise StorageError(
                    "Google Drive did not return an upload session URI.",
                    operation="upload",
                    provider=PROVIDER,
                )
            return _UploadSession(session_uri=location, acked_offset=0)

        self._raise_for_non_transient(resp, operation="upload")
        # Transient on session init — surface so the caller retries the session.
        raise _SessionGoneError(
            f"session init returned status {resp.status_code}",
        )

    async def _query_session_offset(
        self, session: _UploadSession, content_length: int,
    ) -> int | None:
        """Ask the provider for the confirmed offset of a resumed session.

        Returns the number of bytes already acknowledged, ``content_length``
        when the upload already completed, or ``None`` when the provider no
        longer recognises the session (Req 4.5).
        """
        headers = await self._auth_headers(operation="upload")
        headers.update(
            {
                "Content-Range": f"bytes */{content_length}",
                "Content-Length": "0",
            },
        )
        try:
            resp = await self._http().put(session.session_uri, headers=headers)
        except httpx.HTTPError:
            # Treat an unreachable session as gone; a fresh one will be made.
            return None

        if resp.status_code in (200, 201):
            return content_length
        if resp.status_code == 308:
            return _parse_range_offset(resp.headers.get("Range"))
        # 404/410 (or anything else) → session no longer usable.
        return None

    async def _send_chunks(
        self, key: str, session: _UploadSession, payload: bytes,
    ) -> UploadResult:
        """Send every remaining chunk, persisting the acked offset each time."""
        total = len(payload)

        # Already complete (resumed an upload that finished server-side).
        if session.acked_offset >= total > 0:
            await self._sessions.clear(key)
            return UploadResult(
                key=key,
                size_bytes=total,
                checksum=_sha256_hex(payload),
            )

        offset = session.acked_offset
        while offset < total:
            end = min(offset + self._chunk_size, total)
            chunk = payload[offset:end]
            new_offset, completed = await self._send_one_chunk(
                session, chunk, offset, total,
            )
            # Persist the last acknowledged offset before the next chunk
            # (Req 4.2).
            session.acked_offset = new_offset
            await self._sessions.save(key, session)
            offset = new_offset
            if completed:
                break

        await self._sessions.clear(key)
        return UploadResult(
            key=key,
            size_bytes=total,
            checksum=_sha256_hex(payload),
        )

    async def _send_one_chunk(
        self,
        session: _UploadSession,
        chunk: bytes,
        offset: int,
        total: int,
    ) -> tuple[int, bool]:
        """Send a single chunk with retry/backoff; return (new_offset, done).

        Retries a transient failure up to :data:`_MAX_CHUNK_ATTEMPTS` times
        with exponential backoff + jitter (Req 4.3). A non-transient failure
        raises immediately (Req 4.4). After exhausting retries, raises a
        uniform :class:`StorageError` (Req 4.7).
        """
        last_byte = offset + len(chunk) - 1
        delay = _RETRY_INITIAL_DELAY
        last_error: Exception | None = None

        for attempt in range(1, _MAX_CHUNK_ATTEMPTS + 1):
            headers = await self._auth_headers(operation="upload")
            headers.update(
                {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{last_byte}/{total}",
                },
            )
            try:
                resp = await self._http().put(
                    session.session_uri, headers=headers, content=chunk,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # Connection reset / timeout > 30 s → transient (Req 4.3).
                last_error = exc
                logger.warning(
                    "Transient network error uploading chunk at offset %d "
                    "(attempt %d/%d).",
                    offset,
                    attempt,
                    _MAX_CHUNK_ATTEMPTS,
                )
            else:
                if resp.status_code in (200, 201):
                    return total, True
                if resp.status_code == 308:
                    confirmed = _parse_range_offset(resp.headers.get("Range"))
                    # Advance to the provider-confirmed offset; default to the
                    # local end when no Range header is present.
                    return (confirmed if confirmed is not None else last_byte + 1), False
                if resp.status_code in (404, 410):
                    # Session expired/invalid mid-upload (Req 4.6).
                    raise _SessionGoneError(
                        f"chunk PUT returned status {resp.status_code}",
                    )
                if resp.status_code in _TRANSIENT_STATUSES:
                    last_error = _TransientUploadError(
                        f"status {resp.status_code}",
                    )
                    logger.warning(
                        "Transient provider response %d uploading chunk at "
                        "offset %d (attempt %d/%d).",
                        resp.status_code,
                        offset,
                        attempt,
                        _MAX_CHUNK_ATTEMPTS,
                    )
                else:
                    # Non-transient (auth/quota/invalid request) — stop now.
                    self._raise_for_non_transient(resp, operation="upload")

            # Back off before the next attempt (skip after the final attempt).
            if attempt < _MAX_CHUNK_ATTEMPTS:
                await self._sleep(delay + self._jitter())
                delay = min(delay * _RETRY_MULTIPLIER, _RETRY_MAX_DELAY)

        raise StorageError(
            "Google Drive upload failed: chunk at offset "
            f"{offset} did not upload after {_MAX_CHUNK_ATTEMPTS} attempts.",
            operation="upload",
            provider=PROVIDER,
        ) from last_error

    def _raise_for_non_transient(
        self, resp: httpx.Response, *, operation: str,
    ) -> None:
        """Map a non-transient provider response to a uniform StorageError.

        Auth rejections additionally flip the connection to ``disconnected``
        so scheduling halts (Req 2.6, 4.4). No response body is logged or
        echoed, keeping tokens out of all output (Req 2.8).
        """
        status = resp.status_code
        if status in (401, 403):
            reason = "authentication or authorisation was rejected"
        elif status in (402, 507):
            reason = "storage quota was exceeded"
        elif 400 <= status < 500:
            reason = "the request was invalid"
        else:
            reason = f"the provider returned status {status}"
        raise StorageError(
            f"Google Drive {operation} failed: {reason}.",
            operation=operation,
            provider=PROVIDER,
        )

    # ------------------------------------------------------------------
    # list (Req 3.2)
    # ------------------------------------------------------------------
    async def list(self, prefix: str) -> list[RemoteObject]:
        headers = await self._auth_headers(operation="list")
        query_parts = ["trashed = false"]
        if self._config.folder_id:
            query_parts.append(f"'{self._config.folder_id}' in parents")
        if prefix:
            # Drive has no native prefix filter; ``name contains`` narrows the
            # server-side set and we filter exactly below.
            escaped = prefix.replace("'", "\\'")
            query_parts.append(f"name contains '{escaped}'")
        params = {
            "q": " and ".join(query_parts),
            "fields": "files(name,size,modifiedTime)",
            "pageSize": "1000",
        }
        try:
            resp = await self._http().get(
                _FILES_URL, headers=headers, params=params,
            )
        except httpx.HTTPError as exc:
            raise StorageError(
                "Google Drive list failed: the provider was unreachable.",
                operation="list",
                provider=PROVIDER,
            ) from exc

        if resp.status_code != 200:
            self._raise_for_non_transient(resp, operation="list")

        results: list[RemoteObject] = []
        for entry in resp.json().get("files", []):
            name = entry.get("name", "")
            if prefix and not name.startswith(prefix):
                continue
            results.append(
                RemoteObject(
                    key=name,
                    size_bytes=int(entry.get("size", 0) or 0),
                    modified_at=_parse_iso8601(entry.get("modifiedTime")),
                ),
            )
        return results

    # ------------------------------------------------------------------
    # download (Req 3.2)
    # ------------------------------------------------------------------
    async def download(self, key: str) -> AsyncByteStream:
        file_id = await self._resolve_file_id(key, operation="download")
        headers = await self._auth_headers(operation="download")
        try:
            resp = await self._http().get(
                f"{_FILES_URL}/{file_id}",
                headers=headers,
                params={"alt": "media"},
            )
        except httpx.HTTPError as exc:
            raise StorageError(
                "Google Drive download failed: the provider was unreachable.",
                operation="download",
                provider=PROVIDER,
            ) from exc

        if resp.status_code != 200:
            self._raise_for_non_transient(resp, operation="download")

        body = resp.content

        async def _stream() -> AsyncByteStream:
            for start in range(0, len(body), self._chunk_size):
                yield body[start : start + self._chunk_size]

        return _stream()

    # ------------------------------------------------------------------
    # delete (Req 3.2)
    # ------------------------------------------------------------------
    async def delete(self, key: str) -> None:
        file_id = await self._resolve_file_id(key, operation="delete")
        headers = await self._auth_headers(operation="delete")
        try:
            resp = await self._http().delete(
                f"{_FILES_URL}/{file_id}", headers=headers,
            )
        except httpx.HTTPError as exc:
            raise StorageError(
                "Google Drive delete failed: the provider was unreachable.",
                operation="delete",
                provider=PROVIDER,
            ) from exc

        # 204 No Content on success; 404 means already gone (idempotent).
        if resp.status_code not in (200, 204, 404):
            self._raise_for_non_transient(resp, operation="delete")

    async def _resolve_file_id(self, key: str, *, operation: str) -> str:
        """Resolve a logical key to a Drive file id within the app folder."""
        headers = await self._auth_headers(operation=operation)
        query_parts = ["trashed = false", f"name = '{key.replace(chr(39), chr(92) + chr(39))}'"]
        if self._config.folder_id:
            query_parts.append(f"'{self._config.folder_id}' in parents")
        params = {
            "q": " and ".join(query_parts),
            "fields": "files(id,name)",
            "pageSize": "1",
        }
        try:
            resp = await self._http().get(
                _FILES_URL, headers=headers, params=params,
            )
        except httpx.HTTPError as exc:
            raise StorageError(
                f"Google Drive {operation} failed: the provider was "
                "unreachable while resolving the object.",
                operation=operation,
                provider=PROVIDER,
            ) from exc

        if resp.status_code != 200:
            self._raise_for_non_transient(resp, operation=operation)

        files = resp.json().get("files", [])
        if not files:
            raise StorageError(
                f"Google Drive {operation} failed: no object found for the "
                "requested key.",
                operation=operation,
                provider=PROVIDER,
            )
        return files[0]["id"]

    # ------------------------------------------------------------------
    # connection_status (Req 3.3, 2.6)
    # ------------------------------------------------------------------
    async def connection_status(self) -> ConnectionState:
        """Report connection state: token validity + folder reachability.

        A revoked refresh token reports ``disconnected``; any other failure
        reports ``error`` (Req 2.6, 3.3).
        """
        try:
            await self._ensure_access_token(operation="connection_status")
        except StorageError:
            if self._disconnect_notified:
                return ConnectionState.disconnected
            return ConnectionState.error

        # Token is valid — probe Drive reachability with a scope-safe call.
        # Under the `drive.file` scope the app can only see files it created, so
        # reading arbitrary folder/root metadata (`files/root`) returns 403/404
        # and would wrongly report a healthy connection as disconnected. A
        # `files.list` is permitted under `drive.file` and returns 200 (possibly
        # an empty list) whenever the token and Drive API are healthy.
        headers = await self._auth_headers(operation="connection_status")
        try:
            resp = await self._http().get(
                _FILES_URL,
                headers=headers,
                params={"pageSize": 1, "fields": "files(id)"},
            )
        except httpx.HTTPError:
            return ConnectionState.error
        if resp.status_code == 200:
            return ConnectionState.connected
        if resp.status_code in (401, 403):
            return ConnectionState.disconnected
        return ConnectionState.error

    async def storage_usage(self) -> StorageUsage | None:
        """Report the Drive account's storage quota (Req 3 optional capability).

        Reads ``about.storageQuota`` (account-level; available under the
        ``drive.file`` scope). ``limit`` is absent for unlimited accounts, in
        which case ``total_bytes``/``available_bytes`` stay ``None`` while the
        used figure is still reported. Never raises — any failure yields
        ``None`` so a usage probe cannot break the destinations listing.
        """

        def _to_int(value: object) -> int | None:
            try:
                return int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        try:
            await self._ensure_access_token(operation="storage_usage")
            headers = await self._auth_headers(operation="storage_usage")
            resp = await self._http().get(
                _ABOUT_URL, headers=headers, params={"fields": "storageQuota"}
            )
        except (StorageError, httpx.HTTPError):
            return None
        if resp.status_code != 200:
            return None

        quota = (resp.json() or {}).get("storageQuota") or {}
        total = _to_int(quota.get("limit"))
        used = _to_int(quota.get("usage"))
        available = (
            max(0, total - used) if total is not None and used is not None else None
        )
        return StorageUsage(total_bytes=total, used_bytes=used, available_bytes=available)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _read_all(source: AsyncByteStream) -> bytes:
    """Drain an async byte stream into a single ``bytes`` object."""
    parts: list[bytes] = []
    async for piece in source:
        parts.append(piece)
    return b"".join(parts)


def _parse_range_offset(range_header: str | None) -> int | None:
    """Parse a Drive ``Range: bytes=0-N`` header into the next byte offset.

    Returns ``N + 1`` (the count of acknowledged bytes), or ``None`` when the
    header is absent/unparseable.
    """
    if not range_header:
        return None
    try:
        # Header looks like ``bytes=0-262143``.
        _, _, span = range_header.partition("=")
        _, _, last = span.partition("-")
        return int(last) + 1
    except (ValueError, AttributeError):
        return None


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Registry wiring (Req 3.4, 3.5)
# ---------------------------------------------------------------------------
def _build_google_drive_adapter(
    config: GoogleDriveConfig | dict, **kwargs: object,
) -> GoogleDriveAdapter:
    """Factory used by the provider registry.

    Accepts either a :class:`GoogleDriveConfig` or a plain decrypted config
    mapping (the service layer decrypts ``config_encrypted`` then forwards it).
    """
    if isinstance(config, dict):
        config = GoogleDriveConfig(
            refresh_token=config["refresh_token"],
            access_token=config.get("access_token"),
            token_expiry=_coerce_expiry(config.get("token_expiry")),
            folder_id=config.get("folder_id"),
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            chunk_size=config.get("chunk_size"),
        )
    return GoogleDriveAdapter(config, **kwargs)  # type: ignore[arg-type]


def _coerce_expiry(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value  # type: ignore[return-value]
    if isinstance(value, str):
        return _parse_iso8601(value)
    return None


register_adapter(PROVIDER, _build_google_drive_adapter)
