"""S3 / S3-compatible backup-storage adapter (multipart + Object Lock).

This module implements :class:`S3Adapter`, the concrete
:class:`~app.modules.backup_restore.storage.interface.StorageInterface`
implementation for the ``s3`` provider, and registers it with the provider
registry under that name (Requirements 3.1-3.5, 3.8).

The adapter writes every large artifact through an **S3 multipart upload**,
persisting each acknowledged part (its part number and ETag) before sending
the next part and resuming an interrupted upload from the last acknowledged
part rather than restarting from the beginning (Req 4.8). Each part uses a
part size within the 5-100 MiB bound (default 16 MiB), clamped up to the S3
5 MiB minimum. Small artifacts (no larger than one part) are written with a
single ``PutObject``. Transient part failures are retried with exponential
backoff (1 s initial, x2, 60 s cap, <=1 s jitter, <=5 attempts); a non-transient
failure (auth rejection, quota, invalid request, or a vanished multipart
upload) stops immediately, aborts the in-flight multipart upload to remove the
partial artifact, and surfaces a uniform error (Req 4.4, 4.7, 4.8, 4.10).

When ``immutable_until`` is supplied, the object is written under S3 **Object
Lock retention** (compliance mode) until that instant, making the bucket the
recommended Immutable_Copy destination (Req 27.2, 27.6). A delete of an object
still within an active Object Lock retention window is refused before any
provider call (Req 27.3).

Authentication uses an access key ID, a secret access key, and an optional
session token, all decrypted by the service layer from the destination's
``config_encrypted`` (envelope-encrypted under ``ENCRYPTION_MASTER_KEY`` —
Req 28.4). The adapter honours an optional endpoint URL (MinIO/Backblaze
B2/Wasabi), a region, and an addressing style (``path_style`` or
``virtual_hosted``, default virtual-hosted) (Req 28.5, 28.6). A save-time
``HeadBucket``-or-put-then-delete reachability test gates the ``connected``
state (Req 28.7). Credentials are never placed in any log or error message
(Req 28.8).

The adapter always receives already-encrypted bytes; encryption happens in the
backup pipeline before any adapter is invoked (Req 28.9).

The AWS SDK (``boto3``) is imported lazily inside the operations so that the
storage package remains importable in environments where the optional SDK is
not installed; an S3 operation attempted without it raises a uniform
:class:`~app.modules.backup_restore.storage.errors.StorageError`.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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

PROVIDER = "s3"

# --- Part-size constants (Req 4.8) ----------------------------------------
_MIN_PART = 5 * 1024 * 1024            # 5 MiB (S3 minimum part size)
_MAX_PART = 100 * 1024 * 1024          # 100 MiB (Req 4.1 upper bound)
_DEFAULT_PART = 16 * 1024 * 1024       # 16 MiB (Req 4.1 default)

# --- Retry/backoff constants (Req 4.3, applied to S3 per Req 4.8) ---------
_RETRY_INITIAL_DELAY = 1.0             # seconds
_RETRY_MULTIPLIER = 2.0
_RETRY_MAX_DELAY = 60.0                # seconds
_RETRY_MAX_JITTER = 1.0                # seconds
_MAX_PART_ATTEMPTS = 5                 # per part (Req 4.3/4.8)

# Request timeout beyond which a call is treated as a transient failure
# (Req 4.3: "a request timeout exceeding 30 seconds").
_REQUEST_TIMEOUT = 30.0

# Download streaming chunk size.
_DOWNLOAD_CHUNK = 8 * 1024 * 1024      # 8 MiB

# HTTP status codes treated as retriable/transient (Req 4.3).
_TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

# S3 / botocore error codes treated as transient (Req 4.3/4.8).
_TRANSIENT_CODES = frozenset(
    {
        "RequestTimeout",
        "RequestTimeoutException",
        "SlowDown",
        "Throttling",
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "TooManyRequestsException",
        "InternalError",
        "ServiceUnavailable",
        "ServiceUnavailableException",
    },
)

# Addressing-style mapping (Req 28.6). Default virtual-hosted.
_ADDRESSING_MAP = {
    "path_style": "path",
    "virtual_hosted": "virtual",
}

# Sleep + jitter hooks are module-level so tests can patch them deterministically.
SleepFn = Callable[[float], Awaitable[None]]
JitterFn = Callable[[], float]


def _default_jitter() -> float:
    return random.uniform(0.0, _RETRY_MAX_JITTER)


def normalise_part_size(requested: int | None) -> int:
    """Clamp ``requested`` to the 5-100 MiB part-size bound (Req 4.8).

    Returns the default 16 MiB when ``requested`` is ``None``. The S3 minimum
    part size (5 MiB) is the floor; the Req 4.1 upper bound (100 MiB) is the
    ceiling.
    """
    size = _DEFAULT_PART if requested is None else int(requested)
    if size < _MIN_PART:
        size = _MIN_PART
    elif size > _MAX_PART:
        size = _MAX_PART
    return size


def _map_addressing_style(style: str | None) -> str:
    """Map the provider-independent addressing style to a botocore value.

    ``virtual_hosted`` (the default when unset) -> ``"virtual"``;
    ``path_style`` -> ``"path"`` (Req 28.6).
    """
    if not style:
        return "virtual"
    mapped = _ADDRESSING_MAP.get(style)
    if mapped is None:
        raise StorageError(
            "Invalid S3 addressing style; expected 'path_style' or "
            "'virtual_hosted'.",
            operation="resolve",
            provider=PROVIDER,
        )
    return mapped


@dataclass
class S3Config:
    """Provider-independent configuration for an S3 / S3-compatible bucket.

    The access key ID, secret access key, and optional session token here are
    the **already-decrypted** values; the service layer decrypts
    ``BackupDestination.config_encrypted`` (stored under
    ``ENCRYPTION_MASTER_KEY``) before building the adapter (Req 28.4).
    """

    access_key_id: str
    secret_access_key: str
    bucket: str
    session_token: str | None = None
    region: str | None = None
    # Endpoint URL for S3-compatible providers (MinIO/B2/Wasabi); when unset,
    # the AWS S3 endpoint for ``region`` is used (Req 28.5).
    endpoint_url: str | None = None
    # ``path_style`` | ``virtual_hosted``; default virtual-hosted (Req 28.6).
    addressing_style: str | None = None
    # Desired part size; normalised to the 5-100 MiB bound (Req 4.8).
    part_size: int | None = None
    # TLS verification toggle for self-hosted endpoints (defaults to verifying).
    verify_tls: bool = True


@dataclass
class _MultipartSession:
    """In-flight multipart-upload bookkeeping for a single key (Req 4.8)."""

    upload_id: str
    # part number -> ETag for every acknowledged part.
    parts: dict[int, str] = field(default_factory=dict)


class MultipartSessionStore:
    """Persists multipart-upload session state so uploads survive restarts.

    The default implementation is in-process only; the service layer may inject
    a durable store so an interrupted multipart upload can be resumed in a later
    process (Req 4.8). Keyed by the provider-independent object ``key``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _MultipartSession] = {}

    async def load(self, key: str) -> _MultipartSession | None:
        return self._sessions.get(key)

    async def save(self, key: str, session: _MultipartSession) -> None:
        self._sessions[key] = session

    async def clear(self, key: str) -> None:
        self._sessions.pop(key, None)


class S3Adapter(StorageInterface):
    """``StorageInterface`` over S3 with multipart upload and Object Lock."""

    provider_type = PROVIDER

    def __init__(
        self,
        config: S3Config,
        *,
        client: Any | None = None,
        session_store: MultipartSessionStore | None = None,
        sleep: SleepFn = asyncio.sleep,
        jitter: JitterFn = _default_jitter,
    ) -> None:
        self._config = config
        self._client = client
        self._sessions = session_store or MultipartSessionStore()
        self._sleep = sleep
        self._jitter = jitter
        self._part_size = normalise_part_size(config.part_size)

    # ------------------------------------------------------------------
    # boto3 client lifecycle (lazy import keeps the package importable)
    # ------------------------------------------------------------------
    def _build_client(self) -> Any:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise StorageError(
                "The S3 storage backend requires the AWS SDK (boto3), which is "
                "not installed.",
                operation="resolve",
                provider=PROVIDER,
            ) from exc

        botocore_config = Config(
            s3={"addressing_style": _map_addressing_style(self._config.addressing_style)},
            # We implement our own resume/backoff (Req 4.8); disable the SDK's
            # internal retries so attempts are not multiplied.
            retries={"max_attempts": 0, "mode": "standard"},
            connect_timeout=_REQUEST_TIMEOUT,
            read_timeout=_REQUEST_TIMEOUT,
        )
        return boto3.client(
            "s3",
            aws_access_key_id=self._config.access_key_id,
            aws_secret_access_key=self._config.secret_access_key,
            aws_session_token=self._config.session_token,
            region_name=self._config.region,
            endpoint_url=self._config.endpoint_url,
            config=botocore_config,
            verify=self._config.verify_tls,
        )

    def _s3(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # ------------------------------------------------------------------
    # Failure classification / normalisation (Req 3.7, 4.3, 4.4, 28.8)
    # ------------------------------------------------------------------
    @staticmethod
    def _client_error_code_status(exc: Exception) -> tuple[str | None, int | None]:
        """Extract ``(error_code, http_status)`` from a botocore ClientError."""
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return None, None
        code = response.get("Error", {}).get("Code")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code, status

    def _is_transient(self, exc: Exception) -> bool:
        """True when ``exc`` is a retriable/transient S3 failure (Req 4.3)."""
        try:
            from botocore.exceptions import (
                ClientError,
                ConnectionClosedError,
                ConnectionError as BotoConnectionError,
                ConnectTimeoutError,
                EndpointConnectionError,
                ReadTimeoutError,
            )
        except ImportError:  # pragma: no cover - depends on environment
            return False

        if isinstance(
            exc,
            (
                EndpointConnectionError,
                ConnectTimeoutError,
                ReadTimeoutError,
                ConnectionClosedError,
                BotoConnectionError,
            ),
        ):
            return True
        if isinstance(exc, ClientError):
            code, status = self._client_error_code_status(exc)
            if status in _TRANSIENT_STATUSES:
                return True
            if code in _TRANSIENT_CODES:
                return True
        return False

    def _raise_non_transient(self, exc: Exception, *, operation: str) -> None:
        """Map a non-transient provider failure to a uniform StorageError.

        No credentials, SDK exception types, or raw API payloads are placed in
        the message, keeping secrets out of all output (Req 28.8).
        """
        code, status = self._client_error_code_status(exc)
        if code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch",
                    "InvalidToken", "ExpiredToken", "AuthorizationHeaderMalformed"):
            reason = "authentication or authorisation was rejected"
        elif code in ("NoSuchBucket",):
            reason = "the bucket does not exist"
        elif code in ("NoSuchUpload",):
            reason = "the multipart upload no longer exists"
        elif code in ("NoSuchKey",):
            reason = "the requested object does not exist"
        elif code in ("QuotaExceeded", "EntityTooLarge"):
            reason = "the storage quota was exceeded"
        elif status is not None and 400 <= status < 500:
            reason = "the request was invalid"
        elif status is not None:
            reason = f"the provider returned status {status}"
        else:
            reason = "the provider rejected the request"
        raise StorageError(
            f"S3 {operation} failed: {reason}.",
            operation=operation,
            provider=PROVIDER,
        ) from exc

    async def _call_with_retry(
        self,
        fn: Callable[[], Any],
        *,
        operation: str,
        what: str,
    ) -> Any:
        """Run a blocking boto3 call with transient retry/backoff (Req 4.3/4.8).

        ``fn`` is a zero-argument callable performing the blocking SDK call; it
        is executed off the event loop via :func:`asyncio.to_thread`. A
        non-transient failure raises a uniform :class:`StorageError`
        immediately (Req 4.4); transient failures are retried up to
        :data:`_MAX_PART_ATTEMPTS` times with exponential backoff + jitter,
        after which a uniform :class:`StorageError` is raised (Req 4.7).
        """
        delay = _RETRY_INITIAL_DELAY
        last_error: Exception | None = None
        for attempt in range(1, _MAX_PART_ATTEMPTS + 1):
            try:
                return await asyncio.to_thread(fn)
            except StorageError:
                raise
            except Exception as exc:  # noqa: BLE001 - classify then normalise
                if self._is_transient(exc):
                    last_error = exc
                    logger.warning(
                        "Transient S3 error during %s (attempt %d/%d).",
                        what,
                        attempt,
                        _MAX_PART_ATTEMPTS,
                    )
                else:
                    # Non-transient (auth/quota/invalid/vanished upload) — stop.
                    self._raise_non_transient(exc, operation=operation)
            if attempt < _MAX_PART_ATTEMPTS:
                await self._sleep(delay + self._jitter())
                delay = min(delay * _RETRY_MULTIPLIER, _RETRY_MAX_DELAY)

        raise StorageError(
            f"S3 {operation} failed: {what} did not succeed after "
            f"{_MAX_PART_ATTEMPTS} attempts.",
            operation=operation,
            provider=PROVIDER,
        ) from last_error

    # ------------------------------------------------------------------
    # upload (Req 4.8, 27.2)
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

        Small artifacts (no larger than one part) use a single ``PutObject``;
        larger artifacts use a resumable multipart upload. When
        ``immutable_until`` is supplied, the object is written under S3 Object
        Lock retention (compliance mode) until that instant (Req 27.2).
        """
        if content_length < 0:
            raise StorageError(
                "Refusing to upload with a negative content length.",
                operation="upload",
                provider=PROVIDER,
            )

        payload = await _read_all(source)
        if len(payload) != content_length:
            raise StorageError(
                "S3 upload aborted: source produced "
                f"{len(payload)} bytes but {content_length} were declared.",
                operation="upload",
                provider=PROVIDER,
            )

        if len(payload) <= self._part_size:
            return await self._put_object(key, payload, immutable_until)
        return await self._multipart_upload(key, payload, immutable_until)

    def _object_lock_kwargs(
        self, immutable_until: datetime | None,
    ) -> dict[str, Any]:
        """Build the Object Lock retention kwargs when ``immutable_until`` set."""
        if immutable_until is None:
            return {}
        retain_until = immutable_until
        if retain_until.tzinfo is None:
            retain_until = retain_until.replace(tzinfo=timezone.utc)
        return {
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": retain_until,
        }

    async def _put_object(
        self, key: str, payload: bytes, immutable_until: datetime | None,
    ) -> UploadResult:
        """Write a small artifact with a single ``PutObject`` (Req 4.8/27.2)."""
        kwargs: dict[str, Any] = {
            "Bucket": self._config.bucket,
            "Key": key,
            "Body": payload,
        }
        kwargs.update(self._object_lock_kwargs(immutable_until))

        def _put() -> Any:
            return self._s3().put_object(**kwargs)

        await self._call_with_retry(_put, operation="upload", what="object write")
        return UploadResult(
            key=key,
            size_bytes=len(payload),
            checksum=_sha256_hex(payload),
        )

    async def _multipart_upload(
        self, key: str, payload: bytes, immutable_until: datetime | None,
    ) -> UploadResult:
        """Drive a resumable multipart upload, persisting each acked part.

        Resumes from the last acknowledged part rather than restarting; on a
        definitive failure the in-flight multipart upload is aborted so no
        partial artifact remains at the destination (Req 4.8, 4.10).
        """
        session = await self._resume_or_create_session(key, immutable_until)
        total = len(payload)
        try:
            completed: list[dict[str, Any]] = []
            offset = 0
            part_number = 1
            while offset < total:
                end = min(offset + self._part_size, total)
                chunk = payload[offset:end]
                etag = session.parts.get(part_number)
                if etag is None:
                    # Part not yet acknowledged — upload it (Req 4.8 resume:
                    # already-acked parts are skipped).
                    etag = await self._upload_part(
                        key, session.upload_id, part_number, chunk,
                    )
                    session.parts[part_number] = etag
                    # Persist the acknowledged part before the next one (Req 4.2).
                    await self._sessions.save(key, session)
                completed.append({"PartNumber": part_number, "ETag": etag})
                offset = end
                part_number += 1

            await self._complete_multipart(key, session.upload_id, completed)
        except StorageError:
            # Definitive failure: remove the partial multipart upload (Req 4.10).
            await self._abort_multipart(key, session.upload_id)
            await self._sessions.clear(key)
            raise

        await self._sessions.clear(key)
        return UploadResult(
            key=key,
            size_bytes=total,
            checksum=_sha256_hex(payload),
        )

    async def _resume_or_create_session(
        self, key: str, immutable_until: datetime | None,
    ) -> _MultipartSession:
        """Return a live multipart session, resuming a persisted one if valid.

        On resume the destination is queried (``ListParts``) for the parts it
        has already acknowledged and the persisted bookkeeping is reconciled
        with it (Req 4.8). A persisted upload the destination no longer
        recognises is discarded and a new one created.
        """
        existing = await self._sessions.load(key)
        if existing is not None:
            confirmed = await self._list_parts(key, existing.upload_id)
            if confirmed is not None:
                existing.parts = confirmed
                await self._sessions.save(key, existing)
                return existing
            await self._sessions.clear(key)

        upload_id = await self._create_multipart(key, immutable_until)
        session = _MultipartSession(upload_id=upload_id, parts={})
        await self._sessions.save(key, session)
        return session

    async def _create_multipart(
        self, key: str, immutable_until: datetime | None,
    ) -> str:
        """Initiate a multipart upload and return its upload id."""
        kwargs: dict[str, Any] = {"Bucket": self._config.bucket, "Key": key}
        kwargs.update(self._object_lock_kwargs(immutable_until))

        def _create() -> Any:
            return self._s3().create_multipart_upload(**kwargs)

        resp = await self._call_with_retry(
            _create, operation="upload", what="multipart initiation",
        )
        upload_id = resp.get("UploadId")
        if not upload_id:
            raise StorageError(
                "S3 upload failed: the provider returned no multipart upload id.",
                operation="upload",
                provider=PROVIDER,
            )
        return upload_id

    async def _list_parts(self, key: str, upload_id: str) -> dict[int, str] | None:
        """Return ``{part_number: etag}`` for an existing upload, or ``None``.

        ``None`` means the destination no longer recognises the upload, so a
        fresh multipart upload must be created.
        """
        def _list() -> Any:
            parts: dict[int, str] = {}
            paginator = self._s3().get_paginator("list_parts")
            for page in paginator.paginate(
                Bucket=self._config.bucket, Key=key, UploadId=upload_id,
            ):
                for part in page.get("Parts", []):
                    parts[int(part["PartNumber"])] = part["ETag"]
            return parts

        try:
            return await asyncio.to_thread(_list)
        except Exception as exc:  # noqa: BLE001 - classify gone-vs-error
            code, _status = self._client_error_code_status(exc)
            if code in ("NoSuchUpload", "NoSuchKey"):
                return None
            if self._is_transient(exc):
                # Treat a transient listing failure as "unknown" and start
                # fresh rather than blocking the upload.
                return None
            self._raise_non_transient(exc, operation="upload")
            return None  # unreachable; _raise_non_transient always raises

    async def _upload_part(
        self, key: str, upload_id: str, part_number: int, chunk: bytes,
    ) -> str:
        """Upload one part with retry/backoff and return its ETag (Req 4.8)."""
        def _put_part() -> Any:
            return self._s3().upload_part(
                Bucket=self._config.bucket,
                Key=key,
                PartNumber=part_number,
                UploadId=upload_id,
                Body=chunk,
            )

        resp = await self._call_with_retry(
            _put_part, operation="upload", what=f"part {part_number} upload",
        )
        etag = resp.get("ETag")
        if not etag:
            raise StorageError(
                f"S3 upload failed: part {part_number} returned no ETag.",
                operation="upload",
                provider=PROVIDER,
            )
        return etag

    async def _complete_multipart(
        self, key: str, upload_id: str, parts: list[dict[str, Any]],
    ) -> None:
        """Finalise the multipart upload from the acknowledged parts."""
        ordered = sorted(parts, key=lambda p: p["PartNumber"])

        def _complete() -> Any:
            return self._s3().complete_multipart_upload(
                Bucket=self._config.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": ordered},
            )

        await self._call_with_retry(
            _complete, operation="upload", what="multipart completion",
        )

    async def _abort_multipart(self, key: str, upload_id: str) -> None:
        """Best-effort abort to remove a partial multipart upload (Req 4.10)."""
        def _abort() -> Any:
            return self._s3().abort_multipart_upload(
                Bucket=self._config.bucket, Key=key, UploadId=upload_id,
            )

        try:
            await asyncio.to_thread(_abort)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            logger.warning(
                "Failed to abort S3 multipart upload for %s during cleanup.",
                key,
            )

    # ------------------------------------------------------------------
    # list (Req 3.2 — ListObjectsV2 by prefix)
    # ------------------------------------------------------------------
    async def list(self, prefix: str) -> list[RemoteObject]:
        def _list() -> list[RemoteObject]:
            results: list[RemoteObject] = []
            paginator = self._s3().get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self._config.bucket, Prefix=prefix or "",
            ):
                for entry in page.get("Contents", []):
                    results.append(
                        RemoteObject(
                            key=entry["Key"],
                            size_bytes=int(entry.get("Size", 0) or 0),
                            modified_at=_as_utc(entry.get("LastModified")),
                        ),
                    )
            return results

        try:
            return await asyncio.to_thread(_list)
        except Exception as exc:  # noqa: BLE001 - normalise to uniform error
            if self._is_transient(exc):
                raise StorageError(
                    "S3 list failed: the provider was temporarily unavailable.",
                    operation="list",
                    provider=PROVIDER,
                ) from exc
            self._raise_non_transient(exc, operation="list")
            raise  # unreachable

    # ------------------------------------------------------------------
    # download (Req 3.2 — GetObject)
    # ------------------------------------------------------------------
    async def download(self, key: str) -> AsyncByteStream:
        def _get() -> bytes:
            resp = self._s3().get_object(Bucket=self._config.bucket, Key=key)
            body = resp["Body"]
            try:
                return body.read()
            finally:
                body.close()

        try:
            data = await asyncio.to_thread(_get)
        except Exception as exc:  # noqa: BLE001 - normalise to uniform error
            if self._is_transient(exc):
                raise StorageError(
                    "S3 download failed: the provider was temporarily "
                    "unavailable.",
                    operation="download",
                    provider=PROVIDER,
                ) from exc
            self._raise_non_transient(exc, operation="download")
            raise  # unreachable

        async def _stream() -> AsyncByteStream:
            for start in range(0, len(data), _DOWNLOAD_CHUNK):
                yield data[start : start + _DOWNLOAD_CHUNK]

        return _stream()

    # ------------------------------------------------------------------
    # delete (Req 3.2, 27.3 — refused while under Object Lock)
    # ------------------------------------------------------------------
    async def delete(self, key: str) -> None:
        # Refuse to delete an object still within an active Object Lock
        # retention window before issuing any delete (Req 27.3).
        if await self._is_under_active_lock(key):
            raise StorageError(
                "S3 delete refused: the object is under an active Object Lock "
                "retention window.",
                operation="delete",
                provider=PROVIDER,
            )

        def _delete() -> Any:
            return self._s3().delete_object(Bucket=self._config.bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:  # noqa: BLE001 - normalise to uniform error
            code, _status = self._client_error_code_status(exc)
            if code in ("NoSuchKey",):
                # Already gone — delete is idempotent.
                return
            if code == "AccessDenied":
                # The destination itself refused the delete, consistent with an
                # Object Lock protected object (Req 27.3).
                raise StorageError(
                    "S3 delete refused: the destination rejected the delete "
                    "(the object may be under Object Lock).",
                    operation="delete",
                    provider=PROVIDER,
                ) from exc
            if self._is_transient(exc):
                raise StorageError(
                    "S3 delete failed: the provider was temporarily "
                    "unavailable.",
                    operation="delete",
                    provider=PROVIDER,
                ) from exc
            self._raise_non_transient(exc, operation="delete")

    async def _is_under_active_lock(self, key: str) -> bool:
        """True when ``key`` has Object Lock retention extending into the future."""
        def _get_retention() -> Any:
            return self._s3().get_object_retention(
                Bucket=self._config.bucket, Key=key,
            )

        try:
            resp = await asyncio.to_thread(_get_retention)
        except Exception as exc:  # noqa: BLE001 - no lock config => not locked
            code, _status = self._client_error_code_status(exc)
            # Bucket without Object Lock, or object with no retention set.
            if code in (
                "ObjectLockConfigurationNotFoundError",
                "NoSuchObjectLockConfiguration",
                "InvalidRequest",
                "NoSuchKey",
            ):
                return False
            # Any other failure here is not a basis to claim a lock; let the
            # actual delete surface the real error.
            return False

        retention = resp.get("Retention") or {}
        retain_until = _as_utc(retention.get("RetainUntilDate"))
        if not retention.get("Mode") or retain_until is None:
            return False
        return retain_until > datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # connection_status (Req 28.7 — head-bucket-or-put-then-delete)
    # ------------------------------------------------------------------
    async def connection_status(self) -> ConnectionState:
        """Report connection state via a HeadBucket-or-put-then-delete probe.

        ``HeadBucket`` reachability is tried first; if it is rejected or
        unsupported, a put-then-delete of a tiny test object is attempted. A
        definitive auth/not-found rejection reports ``disconnected``; an
        unreachable endpoint or other failure reports ``error`` (Req 28.7).
        """
        head_state = await self._head_bucket_state()
        if head_state is ConnectionState.connected:
            return ConnectionState.connected

        # HeadBucket did not confirm reachability — fall back to put-then-delete.
        put_state = await self._put_then_delete_state()
        if put_state is ConnectionState.connected:
            return ConnectionState.connected
        # Prefer a definitive "disconnected" signal from either probe.
        if ConnectionState.disconnected in (head_state, put_state):
            return ConnectionState.disconnected
        return ConnectionState.error

    async def _head_bucket_state(self) -> ConnectionState:
        def _head() -> Any:
            return self._s3().head_bucket(Bucket=self._config.bucket)

        try:
            await asyncio.to_thread(_head)
        except StorageError:
            return ConnectionState.error
        except Exception as exc:  # noqa: BLE001 - classify reachability
            code, status = self._client_error_code_status(exc)
            if code in ("403", "AccessDenied", "401",
                        "InvalidAccessKeyId", "SignatureDoesNotMatch") \
                    or status in (401, 403):
                return ConnectionState.disconnected
            if code in ("404", "NoSuchBucket") or status == 404:
                return ConnectionState.disconnected
            return ConnectionState.error
        return ConnectionState.connected

    async def _put_then_delete_state(self) -> ConnectionState:
        probe_key = ".orainvoice-connection-test"

        def _probe() -> None:
            client = self._s3()
            client.put_object(
                Bucket=self._config.bucket, Key=probe_key, Body=b"",
            )
            client.delete_object(Bucket=self._config.bucket, Key=probe_key)

        try:
            await asyncio.to_thread(_probe)
        except StorageError:
            return ConnectionState.error
        except Exception as exc:  # noqa: BLE001 - classify reachability
            code, status = self._client_error_code_status(exc)
            if code in ("AccessDenied", "InvalidAccessKeyId",
                        "SignatureDoesNotMatch", "NoSuchBucket") \
                    or status in (401, 403, 404):
                return ConnectionState.disconnected
            return ConnectionState.error
        return ConnectionState.connected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _read_all(source: AsyncByteStream) -> bytes:
    """Drain an async byte stream into a single ``bytes`` object."""
    parts: list[bytes] = []
    async for piece in source:
        parts.append(piece)
    return b"".join(parts)


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _as_utc(value: Any) -> datetime | None:
    """Coerce a boto3 timestamp to a timezone-aware UTC ``datetime``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


# ---------------------------------------------------------------------------
# Registry wiring (Req 3.4, 3.5)
# ---------------------------------------------------------------------------
def _build_s3_adapter(config: S3Config | dict, **kwargs: object) -> S3Adapter:
    """Factory used by the provider registry.

    Accepts either an :class:`S3Config` or a plain decrypted config mapping
    (the service layer decrypts ``config_encrypted`` then forwards it).
    """
    if isinstance(config, dict):
        config = S3Config(
            access_key_id=config["access_key_id"],
            secret_access_key=config["secret_access_key"],
            bucket=config["bucket"],
            session_token=config.get("session_token"),
            region=config.get("region"),
            endpoint_url=config.get("endpoint_url"),
            addressing_style=config.get("addressing_style"),
            part_size=config.get("part_size"),
            verify_tls=config.get("verify_tls", True),
        )
    return S3Adapter(config, **kwargs)  # type: ignore[arg-type]


register_adapter(PROVIDER, _build_s3_adapter)
