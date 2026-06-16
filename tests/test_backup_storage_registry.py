"""Unit tests for the provider-agnostic storage registry (Task 4.2).

Verifies provider-name -> adapter resolution and the uniform "provider
unavailable" guarantee:
  - Unknown / unconfigured providers are rejected with ProviderUnavailableError
    and NO storage operation (upload/list/download/delete) is attempted
    (Requirements 3.5, 3.6).
  - A conforming adapter registered under its provider_type resolves with no
    change to calling logic (Requirement 3.4).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.backup_restore.storage import registry
from app.modules.backup_restore.storage.errors import (
    ProviderUnavailableError,
    StorageError,
)
from app.modules.backup_restore.storage.interface import (
    ConnectionState,
    RemoteObject,
    StorageInterface,
    UploadResult,
)


class _SpyAdapter(StorageInterface):
    """A conforming adapter that records whether any operation was attempted."""

    def __init__(self, config=None) -> None:
        self.config = config
        self.operations_attempted: list[str] = []

    async def upload(self, key, source, *, content_length, immutable_until=None):
        self.operations_attempted.append("upload")
        return UploadResult(key=key, size_bytes=content_length, checksum="x")

    async def list(self, prefix):
        self.operations_attempted.append("list")
        return [RemoteObject(key=prefix, size_bytes=0, modified_at=datetime.now())]

    async def download(self, key):
        self.operations_attempted.append("download")
        raise AssertionError("should not be called in these tests")

    async def delete(self, key):
        self.operations_attempted.append("delete")

    async def connection_status(self):
        self.operations_attempted.append("connection_status")
        return ConnectionState.connected


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot and restore the module-level registry around each test."""
    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


# ---------------------------------------------------------------------------
# Registration + resolution of a conforming adapter (Req 3.4)
# ---------------------------------------------------------------------------

def test_register_and_resolve_returns_adapter_instance():
    registry.register_adapter("s3", _SpyAdapter)

    adapter = registry.resolve_adapter("s3", {"bucket": "b"})

    assert isinstance(adapter, StorageInterface)
    assert isinstance(adapter, _SpyAdapter)
    assert adapter.config == {"bucket": "b"}


def test_decorator_registration():
    @registry.register("nas")
    def _build(config=None) -> StorageInterface:
        return _SpyAdapter(config)

    assert registry.is_registered("nas")
    assert isinstance(registry.resolve_adapter("nas"), _SpyAdapter)


def test_registered_providers_lists_only_registered():
    registry.register_adapter("s3", _SpyAdapter)
    registry.register_adapter("nas", _SpyAdapter)

    assert set(registry.registered_providers()) == {"s3", "nas"}


def test_register_unknown_provider_type_rejected():
    with pytest.raises(ValueError):
        registry.register_adapter("dropbox", _SpyAdapter)


# ---------------------------------------------------------------------------
# Uniform "provider unavailable" guarantee (Req 3.5, 3.6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", [None, ""])
def test_no_provider_configured_raises_provider_unavailable(missing):
    with pytest.raises(ProviderUnavailableError) as exc:
        registry.resolve_adapter(missing)
    assert exc.value.operation == "resolve"


def test_unregistered_provider_raises_provider_unavailable():
    # Known provider name, but no adapter registered for it.
    assert not registry.is_registered("google_drive")

    with pytest.raises(ProviderUnavailableError) as exc:
        registry.resolve_adapter("google_drive")

    assert exc.value.provider == "google_drive"
    assert "unavailable" in str(exc.value).lower()


def test_provider_unavailable_is_a_storage_error():
    # Backup/restore logic can catch the uniform StorageError type.
    with pytest.raises(StorageError):
        registry.resolve_adapter("onedrive")


@pytest.mark.asyncio
async def test_unavailable_provider_attempts_no_storage_operation():
    """Resolving an unavailable provider must not touch any adapter op."""
    spy = _SpyAdapter()

    # Register under a different provider so the requested one is unavailable.
    registry.register_adapter("s3", lambda *a, **k: spy)

    with pytest.raises(ProviderUnavailableError):
        registry.resolve_adapter("nas")

    # No upload/list/download/delete/connection_status was attempted.
    assert spy.operations_attempted == []


# ---------------------------------------------------------------------------
# Factory failure normalisation (Req 3.7)
# ---------------------------------------------------------------------------

def test_factory_raising_is_normalised_to_storage_error():
    def _boom(*a, **k):
        raise RuntimeError("sdk blew up")

    registry.register_adapter("s3", _boom)

    with pytest.raises(StorageError) as exc:
        registry.resolve_adapter("s3")

    assert exc.value.operation == "resolve"
    assert exc.value.provider == "s3"


def test_factory_returning_non_adapter_is_rejected():
    registry.register_adapter("s3", lambda *a, **k: object())

    with pytest.raises(StorageError):
        registry.resolve_adapter("s3")


def test_factory_storage_error_passes_through_unchanged():
    sentinel = StorageError("explicit", operation="resolve", provider="s3")

    def _factory(*a, **k):
        raise sentinel

    registry.register_adapter("s3", _factory)

    with pytest.raises(StorageError) as exc:
        registry.resolve_adapter("s3")
    assert exc.value is sentinel
