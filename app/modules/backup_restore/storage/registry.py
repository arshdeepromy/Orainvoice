"""Provider registry: resolve a provider name to a Storage_Interface adapter.

The Backup_System never imports a concrete adapter directly. Instead, each
adapter (``google_drive.py``, ``onedrive.py``, ``s3.py``, ``nas.py`` — tasks
4.3-4.6) registers a factory here under its ``provider_type`` string, and the
backup/restore code resolves the active adapter at runtime from the
Global-Admin destination configuration (Requirement 3.5).

Resolution is the *only* place a provider name is turned into an adapter, so it
is also the single choke point for the "provider unavailable" guarantee: if the
configuration identifies no provider, or a provider that has no registered
factory, :func:`resolve_adapter` raises :class:`ProviderUnavailableError`
*before* any adapter is constructed — so no upload, list, download, or delete
is attempted (Requirement 3.6).

Because resolution is membership-driven, any adapter that conforms to the five
:class:`StorageInterface` operations is supported with no change to backup or
restore logic simply by registering it here (Requirement 3.4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.backup_restore.models import PROVIDER_TYPES

from .errors import ProviderUnavailableError, StorageError
from .interface import StorageInterface

# A factory builds a configured adapter instance. It receives whatever
# provider-independent configuration the caller resolved (for example the
# decrypted destination config) and returns a ready-to-use StorageInterface.
StorageAdapterFactory = Callable[..., StorageInterface]

# provider_type -> factory. Populated at import time by each adapter module
# calling register_adapter / @register.
_REGISTRY: dict[str, StorageAdapterFactory] = {}


def register_adapter(
    provider_type: str, factory: StorageAdapterFactory,
) -> None:
    """Register ``factory`` as the adapter builder for ``provider_type``.

    ``provider_type`` must be one of the known :data:`PROVIDER_TYPES`
    (``google_drive``, ``onedrive``, ``s3``, ``nas``); registering an unknown
    provider name is a programming error and is rejected so a typo cannot
    silently shadow a real provider.
    """
    if provider_type not in PROVIDER_TYPES:
        raise ValueError(
            f"Cannot register adapter for unknown provider_type "
            f"{provider_type!r}; expected one of {PROVIDER_TYPES}",
        )
    if not callable(factory):
        raise TypeError("factory must be callable")
    _REGISTRY[provider_type] = factory


def register(provider_type: str) -> Callable[[StorageAdapterFactory], StorageAdapterFactory]:
    """Decorator form of :func:`register_adapter`.

    Example::

        @register("s3")
        def _build_s3(config) -> StorageInterface:
            return S3Adapter(config)
    """

    def _decorator(factory: StorageAdapterFactory) -> StorageAdapterFactory:
        register_adapter(provider_type, factory)
        return factory

    return _decorator


def unregister(provider_type: str) -> None:
    """Remove a registered adapter (primarily for tests). No-op if absent."""
    _REGISTRY.pop(provider_type, None)


def is_registered(provider_type: str | None) -> bool:
    """Return True only if a usable adapter is registered for ``provider_type``."""
    return bool(provider_type) and provider_type in _REGISTRY


def registered_providers() -> tuple[str, ...]:
    """Return the provider types that currently have a registered adapter."""
    return tuple(_REGISTRY.keys())


def resolve_adapter(
    provider_type: str | None, *args: Any, **kwargs: Any,
) -> StorageInterface:
    """Resolve ``provider_type`` to a constructed :class:`StorageInterface`.

    Any extra positional/keyword arguments are forwarded to the registered
    factory (typically the provider-independent destination configuration).

    Raises :class:`ProviderUnavailableError` — the uniform "provider
    unavailable" error — when ``provider_type`` is empty/missing or has no
    registered adapter, guaranteeing that no storage operation is attempted
    (Requirements 3.5, 3.6). If a registered factory itself fails to build an
    adapter, the failure is normalised to a uniform :class:`StorageError`
    identifying the ``resolve`` operation (Requirement 3.7).
    """
    if not provider_type:
        raise ProviderUnavailableError(
            "No backup storage provider is configured.",
            operation="resolve",
            provider=None,
        )

    factory = _REGISTRY.get(provider_type)
    if factory is None:
        raise ProviderUnavailableError(
            f"Backup storage provider {provider_type!r} is unavailable: "
            f"no adapter is registered for it.",
            operation="resolve",
            provider=provider_type,
        )

    try:
        adapter = factory(*args, **kwargs)
    except StorageError:
        # Already a uniform storage error — re-raise unchanged.
        raise
    except Exception as exc:  # noqa: BLE001 - normalise to uniform error
        raise StorageError(
            f"Failed to initialise the {provider_type!r} storage adapter.",
            operation="resolve",
            provider=provider_type,
        ) from exc

    if not isinstance(adapter, StorageInterface):
        raise StorageError(
            f"The registered factory for {provider_type!r} did not return a "
            f"StorageInterface implementation.",
            operation="resolve",
            provider=provider_type,
        )
    return adapter
