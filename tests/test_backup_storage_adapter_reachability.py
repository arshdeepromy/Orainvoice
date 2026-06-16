"""Integration tests for backup storage adapter reachability (Task 4.8).

These are **integration tests** (explicitly NOT property-based tests). They
exercise each concrete :class:`StorageInterface` adapter against a *real*
destination to verify the wiring and externally observable behaviour of the
five-operation contract — upload, list, download, delete, and
connection-status — independent of which Cloud_Provider is active.

Coverage:

* ``NasAdapter`` with ``access_mode="volume_path"`` runs against a local
  temporary directory, so it needs **no external infrastructure** and is
  always executed in CI. It gives genuine coverage of the NAS write-then-delete
  reachability test (Req 29.5) and the uniform read/write/list/delete contract
  (Req 3.4).
* ``S3Adapter`` runs against a local MinIO (or any S3-compatible) endpoint and
  is **gated on environment variables**; it is skipped when the endpoint /
  credentials are absent or when ``boto3`` is not installed. It exercises the
  HeadBucket-or-put-then-delete reachability probe and a put/list/get/delete
  round-trip (Req 28.7).
* ``GoogleDriveAdapter`` and ``OneDriveAdapter`` run against real OAuth test
  accounts and are **gated on environment variables**; they are skipped when
  the refresh-token / client credentials are absent.

Every gated test skips cleanly (with a clear reason) when the required service
or credentials are unavailable, so the suite stays green in CI / this
environment while still providing executable coverage when the infrastructure
is present. See ``tests/README`` conventions: integration tests that touch
external services are marked ``@pytest.mark.integration`` and guarded by env.

_Requirements: 3.4, 28.7, 29.5_
"""

from __future__ import annotations

import os

import pytest

from app.modules.backup_restore.storage.interface import (
    ConnectionState,
    StorageInterface,
)

# All tests in this module talk to (real or local) external destinations.
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _byte_stream(payload: bytes, chunk: int = 64 * 1024):
    """Yield ``payload`` as an async byte stream for ``StorageInterface.upload``."""
    for start in range(0, len(payload), chunk):
        yield payload[start : start + chunk]
    if not payload:
        # An empty payload still needs to be a valid (empty) async generator.
        return


async def _drain(stream) -> bytes:
    """Collect an ``AsyncByteStream`` returned by ``download`` into bytes."""
    parts: list[bytes] = []
    async for piece in stream:
        parts.append(piece)
    return b"".join(parts)


async def _roundtrip(
    adapter: StorageInterface,
    key: str,
    payload: bytes,
) -> None:
    """Verify the uniform write/list/read/delete contract on any adapter.

    This is provider-independent on purpose (Req 3.4): the exact same sequence
    of Storage_Interface calls validates every destination type.
    """
    # write
    result = await adapter.upload(
        key, _byte_stream(payload), content_length=len(payload),
    )
    assert result.key == key
    assert result.size_bytes == len(payload)

    # list (the freshly written key must be discoverable by its prefix)
    listed = await adapter.list(key)
    assert any(obj.key == key for obj in listed), (
        f"uploaded key {key!r} was not returned by list()"
    )

    # read (bytes round-trip exactly)
    downloaded = await _drain(await adapter.download(key))
    assert downloaded == payload

    # delete (and confirm it is gone)
    await adapter.delete(key)
    listed_after = await adapter.list(key)
    assert not any(obj.key == key for obj in listed_after), (
        f"key {key!r} still listed after delete()"
    )


def _require_env(*names: str) -> dict[str, str]:
    """Return the named env vars, or skip the test when any are missing."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(
            "integration test requires environment variables: "
            + ", ".join(missing),
        )
    return {n: os.environ[n] for n in names}


# ===========================================================================
# NAS adapter — local volume_path (NOT skipped; real external behaviour)
# ===========================================================================
class TestNasAdapterReachabilityLocal:
    """Real read/write/list/delete + connection_status against a temp dir.

    ``access_mode="volume_path"`` treats the configured ``share_path`` as a
    pre-mounted local mount point, so this exercises genuine filesystem
    behaviour with no external NAS infrastructure (Req 29.5, 3.4).
    """

    def _adapter(self, base_dir, target_dir: str = "backups"):
        from app.modules.backup_restore.storage.nas import (
            NasAdapter,
            NasConfig,
        )

        return NasAdapter(
            NasConfig(
                share_path=str(base_dir),
                access_mode="volume_path",
                target_dir=target_dir,
            ),
        )

    @pytest.mark.asyncio
    async def test_connection_status_connected_round_trips_probe(self, tmp_path):
        """Req 29.5: the save-time probe writes then deletes a test artifact
        and only a successful round-trip reports ``connected``."""
        adapter = self._adapter(tmp_path)

        state = await adapter.connection_status()

        assert state is ConnectionState.connected
        # The probe must leave nothing behind — no leftover test artifact.
        base = tmp_path / "backups"
        leftovers = list(base.glob(".nas-connect-test*")) if base.exists() else []
        assert leftovers == []

    @pytest.mark.asyncio
    async def test_write_read_list_delete_round_trip(self, tmp_path):
        """Req 3.4: the uniform five-operation contract works end-to-end."""
        adapter = self._adapter(tmp_path)
        payload = b"orainvoice-encrypted-backup-artifact-" + os.urandom(32)

        await _roundtrip(adapter, "backups/job-1/dump.enc", payload)

    @pytest.mark.asyncio
    async def test_artifact_written_to_configured_directory(self, tmp_path):
        """The artifact lands under the resolved base directory on the share."""
        adapter = self._adapter(tmp_path, target_dir="nested/dir")
        payload = b"hello-nas"

        await adapter.upload(
            "a/b/c.enc", _byte_stream(payload), content_length=len(payload),
        )

        written = tmp_path / "nested" / "dir" / "a" / "b" / "c.enc"
        assert written.is_file()
        assert written.read_bytes() == payload

        # Clean up via the adapter (also re-exercises delete()).
        await adapter.delete("a/b/c.enc")
        assert not written.exists()


# ===========================================================================
# S3 adapter — local MinIO / S3-compatible endpoint (gated on env)
# ===========================================================================
class TestS3AdapterReachabilityMinio:
    """HeadBucket/connection_status + put/list/get/delete against MinIO.

    Gated on ``MINIO_ENDPOINT`` / ``MINIO_ACCESS_KEY`` / ``MINIO_SECRET_KEY`` /
    ``MINIO_BUCKET`` and on ``boto3`` being importable (Req 28.7).
    """

    def _adapter(self):
        pytest.importorskip("boto3", reason="S3 integration test requires boto3")
        env = _require_env(
            "MINIO_ENDPOINT",
            "MINIO_ACCESS_KEY",
            "MINIO_SECRET_KEY",
            "MINIO_BUCKET",
        )
        from app.modules.backup_restore.storage.s3 import S3Adapter, S3Config

        verify_tls = os.environ.get("MINIO_VERIFY_TLS", "false").lower() == "true"
        return S3Adapter(
            S3Config(
                access_key_id=env["MINIO_ACCESS_KEY"],
                secret_access_key=env["MINIO_SECRET_KEY"],
                bucket=env["MINIO_BUCKET"],
                endpoint_url=env["MINIO_ENDPOINT"],
                region=os.environ.get("MINIO_REGION", "us-east-1"),
                # MinIO defaults to path-style addressing.
                addressing_style="path_style",
                verify_tls=verify_tls,
            ),
        )

    @pytest.mark.asyncio
    async def test_connection_status_reaches_bucket(self):
        """Req 28.7: the reachability probe confirms ``connected`` for a
        reachable bucket with valid credentials."""
        adapter = self._adapter()

        assert await adapter.connection_status() is ConnectionState.connected

    @pytest.mark.asyncio
    async def test_put_list_get_delete_round_trip(self):
        """Req 3.4 / 28.7: the uniform contract round-trips against S3."""
        adapter = self._adapter()
        payload = b"s3-encrypted-artifact-" + os.urandom(48)

        await _roundtrip(adapter, "integration-tests/s3/dump.enc", payload)


# ===========================================================================
# Google Drive adapter — real OAuth test account (gated on env)
# ===========================================================================
class TestGoogleDriveAdapterReachability:
    """connection_status + upload/list/download/delete against a Drive test
    account. Gated on OAuth test-account credentials (Req 3.4)."""

    def _adapter(self):
        env = _require_env(
            "GOOGLE_DRIVE_TEST_REFRESH_TOKEN",
            "GOOGLE_DRIVE_TEST_CLIENT_ID",
            "GOOGLE_DRIVE_TEST_CLIENT_SECRET",
        )
        from app.modules.backup_restore.storage.google_drive import (
            GoogleDriveAdapter,
            GoogleDriveConfig,
        )

        return GoogleDriveAdapter(
            GoogleDriveConfig(
                refresh_token=env["GOOGLE_DRIVE_TEST_REFRESH_TOKEN"],
                client_id=env["GOOGLE_DRIVE_TEST_CLIENT_ID"],
                client_secret=env["GOOGLE_DRIVE_TEST_CLIENT_SECRET"],
                folder_id=os.environ.get("GOOGLE_DRIVE_TEST_FOLDER_ID"),
            ),
        )

    @pytest.mark.asyncio
    async def test_connection_status_connected(self):
        """A valid refresh token + reachable folder reports ``connected``."""
        adapter = self._adapter()
        try:
            assert await adapter.connection_status() is ConnectionState.connected
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_upload_list_download_delete_round_trip(self):
        """Req 3.4: the uniform contract round-trips against Google Drive."""
        adapter = self._adapter()
        payload = b"gdrive-encrypted-artifact-" + os.urandom(48)
        try:
            await _roundtrip(adapter, "orainvoice-it-gdrive.enc", payload)
        finally:
            await adapter.aclose()


# ===========================================================================
# OneDrive adapter — real OAuth test account (gated on env)
# ===========================================================================
class TestOneDriveAdapterReachability:
    """connection_status + upload/list/download/delete against a OneDrive test
    account. Gated on OAuth test-account credentials (Req 3.4)."""

    def _adapter(self):
        env = _require_env(
            "ONEDRIVE_TEST_REFRESH_TOKEN",
            "ONEDRIVE_TEST_CLIENT_ID",
            "ONEDRIVE_TEST_CLIENT_SECRET",
        )
        from app.modules.backup_restore.storage.onedrive import (
            OneDriveAdapter,
            OneDriveConfig,
        )

        return OneDriveAdapter(
            OneDriveConfig(
                refresh_token=env["ONEDRIVE_TEST_REFRESH_TOKEN"],
                client_id=env["ONEDRIVE_TEST_CLIENT_ID"],
                client_secret=env["ONEDRIVE_TEST_CLIENT_SECRET"],
                folder_path=os.environ.get(
                    "ONEDRIVE_TEST_FOLDER_PATH", "OraInvoiceBackupsIT",
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_connection_status_connected(self):
        """A valid refresh token + reachable folder reports ``connected``."""
        adapter = self._adapter()
        try:
            assert await adapter.connection_status() is ConnectionState.connected
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_upload_list_download_delete_round_trip(self):
        """Req 3.4: the uniform contract round-trips against OneDrive."""
        adapter = self._adapter()
        payload = b"onedrive-encrypted-artifact-" + os.urandom(48)
        try:
            await _roundtrip(adapter, "orainvoice-it-onedrive.enc", payload)
        finally:
            await adapter.aclose()
