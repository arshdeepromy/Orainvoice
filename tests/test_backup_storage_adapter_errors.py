"""Unit tests for storage-adapter error normalisation & credential masking (Task 4.7).

Covers the four provider adapters under
``app/modules/backup_restore/storage/`` (Google Drive, OneDrive, S3, NAS) and
asserts the cross-provider guarantees the design pins on every adapter:

  1. **Uniform error normalisation (Req 2.8, 3.7, 28.4, 29.4).** Every
     provider-specific failure is normalised to a single
     :class:`StorageError` that identifies the *failed operation*
     (``upload`` / ``list`` / ``download`` / ``delete``), regardless of which
     Cloud_Provider raised it. A rejection that happens *before* any provider
     mutation (an S3 delete refused under Object Lock, a validation rejection)
     leaves prior state untouched — no destructive provider call is attempted.

  2. **Secrets excluded from messages and logs (Req 2.8, 28.4/28.8, 29.4/29.7).**
     OAuth tokens (Google/OneDrive), S3 access keys/secrets, and NAS
     credentials never appear in a normalised :class:`StorageError` message or
     in any emitted log record.

Fakes are injected through each adapter's constructor seam so no real network
or SDK is exercised:
  * ``GoogleDriveAdapter`` / ``OneDriveAdapter`` accept an ``httpx.AsyncClient``
    (``client=``) plus ``sleep`` / ``jitter`` hooks.
  * ``S3Adapter`` accepts a boto3-like ``client=`` object, so ``boto3`` need
    not be installed (the lazy import is only reached when ``client`` is None).
  * ``NasAdapter`` operates on a real temporary directory.

Note on "masked-credential save detection skips re-encrypt": that behaviour is
a **service-layer** concern (``config_service`` — task 13.6), where a saved
destination config whose credential fields still hold the masked placeholder is
detected and the existing ciphertext is reused instead of re-encrypting the
mask. The storage adapters intentionally expose no masking helper (they receive
already-decrypted config), so the adapter-level masking guarantee verified here
is strictly the exclusion of secrets from error messages and log output.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.modules.backup_restore.storage.errors import StorageError
from app.modules.backup_restore.storage.google_drive import (
    GoogleDriveAdapter,
    GoogleDriveConfig,
)
from app.modules.backup_restore.storage.nas import NasConfig, NasAdapter
from app.modules.backup_restore.storage.onedrive import (
    OneDriveAdapter,
    OneDriveConfig,
)
from app.modules.backup_restore.storage.s3 import S3Adapter, S3Config


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response``."""

    def __init__(
        self,
        status_code: int = 200,
        *,
        json_data: dict | None = None,
        headers: dict | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}
        self.content = content

    def json(self) -> dict:
        return self._json


class _FakeHTTPClient:
    """Configurable async stand-in for ``httpx.AsyncClient``.

    Each HTTP verb maps to a handler that is either a ready
    :class:`_FakeResponse`, a callable returning one, or an ``Exception`` to
    raise (to simulate a transport failure / provider rejection).
    """

    def __init__(self, **handlers: object) -> None:
        self._handlers = handlers
        self.calls: list[tuple[str, tuple, dict]] = []

    async def _dispatch(self, verb: str, *args, **kwargs):
        self.calls.append((verb, args, kwargs))
        handler = self._handlers.get(verb)
        if handler is None:
            raise AssertionError(f"unexpected {verb} call")
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(*args, **kwargs)
        return handler

    async def post(self, *a, **k):
        return await self._dispatch("post", *a, **k)

    async def get(self, *a, **k):
        return await self._dispatch("get", *a, **k)

    async def put(self, *a, **k):
        return await self._dispatch("put", *a, **k)

    async def delete(self, *a, **k):
        return await self._dispatch("delete", *a, **k)

    async def aclose(self) -> None:  # pragma: no cover - never owned in tests
        pass


class _FakeClientError(Exception):
    """A botocore-ClientError-shaped failure with a ``response`` mapping.

    The S3 adapter classifies failures from ``exc.response['Error']['Code']``
    and ``exc.response['ResponseMetadata']['HTTPStatusCode']`` without requiring
    the exception to be a real ``botocore`` type, so this is sufficient to drive
    the non-transient normalisation path with ``boto3`` absent.
    """

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class _FakeS3Client:
    """Configurable boto3-like client.

    Methods are supplied as keyword handlers; each is either a value to return,
    a callable, or an ``Exception`` to raise. Any un-supplied method raises
    ``AssertionError`` when called, which lets a test assert that a destructive
    call (for example ``delete_object``) was never attempted.
    """

    def __init__(self, **methods: object) -> None:
        self._methods = methods
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name: str):
        def _method(**kwargs):
            # ``object.__getattribute__`` avoids recursing through __getattr__.
            object.__getattribute__(self, "calls").append((name, kwargs))
            handler = object.__getattribute__(self, "_methods").get(name)
            if handler is None:
                raise AssertionError(f"unexpected S3 call: {name}")
            if isinstance(handler, Exception):
                raise handler
            if callable(handler):
                return handler(**kwargs)
            return handler

        return _method


async def _bytes_source(data: bytes):
    """A one-shot async byte stream yielding ``data``."""
    yield data


async def _noop_sleep(_seconds: float) -> None:
    """Sleep hook that never actually waits."""
    return None


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


# Recognisable secret values asserted to never leak into messages or logs.
_GD_REFRESH = "SECRET-GD-REFRESH-TOKEN-abc123"
_GD_ACCESS = "SECRET-GD-ACCESS-TOKEN-zzz999"
_OD_REFRESH = "SECRET-OD-REFRESH-TOKEN-def456"
_S3_KEY_ID = "AKIA-SECRET-KEY-ID-0001"
_S3_SECRET = "SECRET-S3-SECRET-ACCESS-KEY-9999"
_NAS_USER = "smb-secret-user"
_NAS_PASS = "SECRET-NAS-PASSWORD-7777"


# ---------------------------------------------------------------------------
# Google Drive — error normalisation
# ---------------------------------------------------------------------------
def _gd_adapter(client: _FakeHTTPClient, **overrides) -> GoogleDriveAdapter:
    config = GoogleDriveConfig(
        refresh_token=_GD_REFRESH,
        access_token=_GD_ACCESS,
        token_expiry=_future(),  # valid token => operation proceeds
        client_id="cid",
        client_secret="csecret",
    )
    return GoogleDriveAdapter(
        config,
        client=client,
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
        **overrides,
    )


@pytest.mark.asyncio
async def test_google_drive_list_failure_normalised_to_storage_error():
    client = _FakeHTTPClient(get=httpx.ConnectError("network down"))
    adapter = _gd_adapter(client)

    with pytest.raises(StorageError) as exc:
        await adapter.list("backups/")

    assert exc.value.operation == "list"
    assert exc.value.provider == "google_drive"


@pytest.mark.asyncio
async def test_google_drive_upload_failure_normalised_to_storage_error():
    client = _FakeHTTPClient(post=httpx.ConnectError("network down"))
    adapter = _gd_adapter(client)

    payload = b"already-encrypted-bytes"
    with pytest.raises(StorageError) as exc:
        await adapter.upload(
            "backups/dump.enc",
            _bytes_source(payload),
            content_length=len(payload),
        )

    assert exc.value.operation == "upload"
    assert exc.value.provider == "google_drive"


@pytest.mark.asyncio
async def test_google_drive_download_failure_normalised_to_storage_error():
    client = _FakeHTTPClient(get=httpx.ConnectError("network down"))
    adapter = _gd_adapter(client)

    with pytest.raises(StorageError) as exc:
        await adapter.download("backups/dump.enc")

    assert exc.value.operation == "download"


# ---------------------------------------------------------------------------
# Google Drive — tokens excluded from error messages and logs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_google_drive_revoked_token_excludes_secrets(caplog):
    disconnected: list[int] = []

    async def _on_disconnected() -> None:
        disconnected.append(1)

    # No cached access token => the adapter refreshes; the token endpoint
    # rejects the refresh token (revoked), flipping to disconnected (Req 2.6).
    config = GoogleDriveConfig(
        refresh_token=_GD_REFRESH,
        access_token=None,
        token_expiry=None,
        client_id="cid",
        client_secret="csecret",
    )
    client = _FakeHTTPClient(post=_FakeResponse(400, json_data={"error": "invalid_grant"}))
    adapter = GoogleDriveAdapter(
        config,
        client=client,
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
        on_disconnected=_on_disconnected,
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageError) as exc:
            await adapter.list("backups/")

    assert exc.value.operation == "list"
    message = str(exc.value)
    assert _GD_REFRESH not in message
    assert _GD_ACCESS not in message
    assert _GD_REFRESH not in caplog.text
    assert _GD_ACCESS not in caplog.text
    # The revoked token flipped the connection to disconnected exactly once.
    assert disconnected == [1]


# ---------------------------------------------------------------------------
# OneDrive — error normalisation + token masking (mirrors Google Drive)
# ---------------------------------------------------------------------------
def _od_adapter(client: _FakeHTTPClient, **overrides) -> OneDriveAdapter:
    config = OneDriveConfig(
        refresh_token=_OD_REFRESH,
        access_token="SECRET-OD-ACCESS",
        token_expiry=_future(),
        client_id="cid",
        client_secret="csecret",
    )
    return OneDriveAdapter(
        config,
        client=client,
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
        **overrides,
    )


@pytest.mark.asyncio
async def test_onedrive_list_failure_normalised_to_storage_error():
    client = _FakeHTTPClient(get=httpx.ConnectError("network down"))
    adapter = _od_adapter(client)

    with pytest.raises(StorageError) as exc:
        await adapter.list("backups/")

    assert exc.value.operation == "list"
    assert exc.value.provider == "onedrive"


@pytest.mark.asyncio
async def test_onedrive_upload_failure_normalised_to_storage_error():
    client = _FakeHTTPClient(post=httpx.ConnectError("network down"))
    adapter = _od_adapter(client)

    payload = b"already-encrypted-bytes"
    with pytest.raises(StorageError) as exc:
        await adapter.upload(
            "backups/dump.enc",
            _bytes_source(payload),
            content_length=len(payload),
        )

    assert exc.value.operation == "upload"
    assert exc.value.provider == "onedrive"


@pytest.mark.asyncio
async def test_onedrive_revoked_token_excludes_secrets(caplog):
    config = OneDriveConfig(
        refresh_token=_OD_REFRESH,
        access_token=None,
        token_expiry=None,
        client_id="cid",
        client_secret="csecret",
    )
    client = _FakeHTTPClient(post=_FakeResponse(400, json_data={"error": "invalid_grant"}))
    adapter = OneDriveAdapter(
        config,
        client=client,
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageError) as exc:
            await adapter.list("backups/")

    assert exc.value.operation == "list"
    assert _OD_REFRESH not in str(exc.value)
    assert _OD_REFRESH not in caplog.text


# ---------------------------------------------------------------------------
# S3 — error normalisation, prior-state preservation, credential masking
# ---------------------------------------------------------------------------
def _s3_adapter(client: _FakeS3Client) -> S3Adapter:
    config = S3Config(
        access_key_id=_S3_KEY_ID,
        secret_access_key=_S3_SECRET,
        bucket="backups-bucket",
        region="us-east-1",
    )
    return S3Adapter(client=client, config=config, sleep=_noop_sleep, jitter=lambda: 0.0)


@pytest.mark.asyncio
async def test_s3_upload_failure_normalised_to_storage_error():
    client = _FakeS3Client(put_object=_FakeClientError("AccessDenied", 403))
    adapter = _s3_adapter(client)

    payload = b"already-encrypted-bytes"
    with pytest.raises(StorageError) as exc:
        await adapter.upload(
            "backups/dump.enc",
            _bytes_source(payload),
            content_length=len(payload),
        )

    assert exc.value.operation == "upload"
    assert exc.value.provider == "s3"


@pytest.mark.asyncio
async def test_s3_list_failure_normalised_to_storage_error():
    client = _FakeS3Client(get_paginator=_FakeClientError("NoSuchBucket", 404))
    adapter = _s3_adapter(client)

    with pytest.raises(StorageError) as exc:
        await adapter.list("backups/")

    assert exc.value.operation == "list"
    assert exc.value.provider == "s3"


@pytest.mark.asyncio
async def test_s3_delete_refused_under_object_lock_preserves_object():
    """A locked object is refused before any provider delete is attempted."""
    client = _FakeS3Client(
        get_object_retention={
            "Retention": {
                "Mode": "COMPLIANCE",
                "RetainUntilDate": datetime.now(timezone.utc) + timedelta(days=1),
            },
        },
        # delete_object intentionally unregistered: calling it raises
        # AssertionError, proving the delete was refused before any mutation.
    )
    adapter = _s3_adapter(client)

    with pytest.raises(StorageError) as exc:
        await adapter.delete("backups/locked.enc")

    assert exc.value.operation == "delete"
    # Prior state preserved: no delete_object call was made.
    assert all(name != "delete_object" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_s3_credentials_excluded_from_error_and_logs(caplog):
    client = _FakeS3Client(put_object=_FakeClientError("InvalidAccessKeyId", 403))
    adapter = _s3_adapter(client)

    payload = b"already-encrypted-bytes"
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageError) as exc:
            await adapter.upload(
                "backups/dump.enc",
                _bytes_source(payload),
                content_length=len(payload),
            )

    message = str(exc.value)
    assert _S3_KEY_ID not in message
    assert _S3_SECRET not in message
    assert _S3_KEY_ID not in caplog.text
    assert _S3_SECRET not in caplog.text


# ---------------------------------------------------------------------------
# NAS — error normalisation + credential masking
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nas_download_missing_object_normalised_to_storage_error(tmp_path):
    adapter = NasAdapter(
        NasConfig(share_path=str(tmp_path), access_mode="volume_path"),
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
    )

    with pytest.raises(StorageError) as exc:
        await adapter.download("backups/missing.enc")

    assert exc.value.operation == "download"
    assert exc.value.provider == "nas"


@pytest.mark.asyncio
async def test_nas_upload_failure_normalised_to_storage_error(tmp_path):
    # Point the share at a regular file so the artifact directory cannot be
    # created — a non-transient filesystem failure that must normalise.
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"x")
    adapter = NasAdapter(
        NasConfig(share_path=str(blocker), access_mode="volume_path"),
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
    )

    payload = b"already-encrypted-bytes"
    with pytest.raises(StorageError) as exc:
        await adapter.upload(
            "dump.enc",
            _bytes_source(payload),
            content_length=len(payload),
        )

    assert exc.value.operation == "upload"
    assert exc.value.provider == "nas"


@pytest.mark.asyncio
async def test_nas_credentials_excluded_from_error_and_logs(tmp_path, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"x")
    adapter = NasAdapter(
        NasConfig(
            share_path=str(blocker),
            access_mode="smb",
            username=_NAS_USER,
            password=_NAS_PASS,
        ),
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
    )

    payload = b"already-encrypted-bytes"
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageError) as exc:
            await adapter.upload(
                "dump.enc",
                _bytes_source(payload),
                content_length=len(payload),
            )

    message = str(exc.value)
    assert _NAS_USER not in message
    assert _NAS_PASS not in message
    assert _NAS_USER not in caplog.text
    assert _NAS_PASS not in caplog.text


@pytest.mark.asyncio
async def test_nas_empty_key_rejected_before_any_write(tmp_path):
    """A validation rejection attempts no write and still tags the operation."""
    adapter = NasAdapter(
        NasConfig(share_path=str(tmp_path), access_mode="volume_path"),
        sleep=_noop_sleep,
        jitter=lambda: 0.0,
    )

    payload = b"data"
    with pytest.raises(StorageError) as exc:
        await adapter.upload(
            "   ",
            _bytes_source(payload),
            content_length=len(payload),
        )

    assert exc.value.operation == "upload"
    # No artifact was written into the share directory.
    assert list(tmp_path.iterdir()) == []
