"""Provider-agnostic Storage_Interface and per-destination adapters."""

from .errors import ProviderUnavailableError, StorageError
from .interface import (
    AsyncByteStream,
    ConnectionState,
    RemoteObject,
    StorageInterface,
    UploadResult,
)
from .registry import (
    StorageAdapterFactory,
    is_registered,
    register,
    register_adapter,
    registered_providers,
    resolve_adapter,
    unregister,
)

# Import concrete adapters for their import-time registry side effects, so that
# ``resolve_adapter("google_drive", ...)`` works as soon as the storage package
# is imported (Req 3.4, 3.5). Each adapter module calls ``register_adapter`` at
# import time.
from .google_drive import GoogleDriveAdapter, GoogleDriveConfig  # noqa: E402
from .nas import NasAdapter, NasConfig  # noqa: E402
from .onedrive import OneDriveAdapter, OneDriveConfig  # noqa: E402
from .s3 import S3Adapter, S3Config  # noqa: E402

__all__ = [
    "AsyncByteStream",
    "ConnectionState",
    "GoogleDriveAdapter",
    "GoogleDriveConfig",
    "NasAdapter",
    "NasConfig",
    "OneDriveAdapter",
    "OneDriveConfig",
    "ProviderUnavailableError",
    "RemoteObject",
    "S3Adapter",
    "S3Config",
    "StorageAdapterFactory",
    "StorageError",
    "StorageInterface",
    "UploadResult",
    "is_registered",
    "register",
    "register_adapter",
    "registered_providers",
    "resolve_adapter",
    "unregister",
]
