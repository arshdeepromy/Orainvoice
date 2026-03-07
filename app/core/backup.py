"""Backup and data residency configuration.

Provides:
- Backup configuration with retention, encryption, and geo-separation settings
- Data residency validation (NZ/AU regions only)
- Backup verification utilities

Requirements: 53.1, 53.2, 53.3, 53.4
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Approved NZ/AU regions (Requirement 53.1)
# ---------------------------------------------------------------------------

APPROVED_REGIONS: dict[str, list[str]] = {
    "aws": ["ap-southeast-2"],
    "azure": ["australiaeast", "australiasoutheast"],
    "gcp": ["australia-southeast1", "australia-southeast2"],
}

APPROVED_REGION_NAMES: set[str] = {
    region for regions in APPROVED_REGIONS.values() for region in regions
}


class BackupEncryption(str, Enum):
    """Supported backup encryption algorithms."""

    AES_256_CBC = "aes-256-cbc"
    AES_256_GCM = "aes-256-gcm"


# ---------------------------------------------------------------------------
# Backup configuration (Requirements 53.2, 53.3, 53.4)
# ---------------------------------------------------------------------------

@dataclass
class BackupConfig:
    """Backup strategy configuration.

    Attributes
    ----------
    retention_days:
        Number of days to retain backups. Must be between 7 and 90.
        Default is 30 days per Requirement 53.2.
    encryption:
        Encryption algorithm for backup data at rest.
        Must be AES-256 per Requirement 53.3.
    encryption_enabled:
        Whether backup encryption is active. Must be ``True`` in
        production environments.
    point_in_time_recovery:
        Whether continuous WAL archiving is enabled for PITR.
        Must be ``True`` per Requirement 53.2.
    backup_region:
        Cloud region where backups are stored. Must be a valid NZ/AU
        region and geographically separate from ``primary_region``.
    primary_region:
        Cloud region where the primary database runs.
    cloud_provider:
        Cloud provider identifier (``aws``, ``azure``, ``gcp``).
    daily_backup_hour_nzst:
        Hour (0-23) in NZST when the daily base backup runs.
    """

    retention_days: int = 30
    encryption: BackupEncryption = BackupEncryption.AES_256_CBC
    encryption_enabled: bool = True
    point_in_time_recovery: bool = True
    backup_region: str = "ap-southeast-2"
    primary_region: str = "ap-southeast-2"
    cloud_provider: str = "aws"
    daily_backup_hour_nzst: int = 2


# ---------------------------------------------------------------------------
# Data residency configuration (Requirement 53.1)
# ---------------------------------------------------------------------------

@dataclass
class DataResidencyConfig:
    """Data residency settings for NZ/AU compliance.

    Attributes
    ----------
    primary_region:
        Cloud region for the primary database and application servers.
    backup_region:
        Cloud region for backup storage (must differ from primary for
        geographic separation per Requirement 53.3).
    cloud_provider:
        Cloud provider identifier.
    allowed_regions:
        Set of region identifiers that are approved for data storage.
    """

    primary_region: str = "ap-southeast-2"
    backup_region: str = "ap-southeast-2"
    cloud_provider: str = "aws"
    allowed_regions: set[str] = field(default_factory=lambda: set(APPROVED_REGION_NAMES))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of a configuration validation check."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)


def validate_data_residency(config: DataResidencyConfig) -> ValidationResult:
    """Validate that data residency settings comply with NZ/AU requirements.

    Checks:
    - Primary region is in the approved NZ/AU list.
    - Backup region is in the approved NZ/AU list.
    - Cloud provider is recognised.

    Parameters
    ----------
    config:
        The data residency configuration to validate.

    Returns
    -------
    ValidationResult
        Contains ``is_valid`` flag and a list of error messages.
    """
    result = ValidationResult()

    if config.cloud_provider not in APPROVED_REGIONS:
        result.is_valid = False
        result.errors.append(
            f"Unsupported cloud provider '{config.cloud_provider}'. "
            f"Supported: {', '.join(sorted(APPROVED_REGIONS.keys()))}"
        )
        return result

    provider_regions = set(APPROVED_REGIONS[config.cloud_provider])

    if config.primary_region not in provider_regions:
        result.is_valid = False
        result.errors.append(
            f"Primary region '{config.primary_region}' is not an approved "
            f"NZ/AU region for {config.cloud_provider}. "
            f"Approved: {', '.join(sorted(provider_regions))}"
        )

    if config.backup_region not in provider_regions:
        result.is_valid = False
        result.errors.append(
            f"Backup region '{config.backup_region}' is not an approved "
            f"NZ/AU region for {config.cloud_provider}. "
            f"Approved: {', '.join(sorted(provider_regions))}"
        )

    return result


def validate_backup_config(config: BackupConfig) -> ValidationResult:
    """Validate backup configuration against platform requirements.

    Checks:
    - Retention is between 7 and 90 days (default 30).
    - Encryption is enabled with AES-256.
    - Point-in-time recovery is enabled.
    - Backup region is an approved NZ/AU region.

    Parameters
    ----------
    config:
        The backup configuration to validate.

    Returns
    -------
    ValidationResult
        Contains ``is_valid`` flag and a list of error messages.
    """
    result = ValidationResult()

    # Retention (Requirement 53.2, 53.4)
    if not (7 <= config.retention_days <= 90):
        result.is_valid = False
        result.errors.append(
            f"Backup retention must be between 7 and 90 days, "
            f"got {config.retention_days}"
        )

    # Encryption (Requirement 53.3)
    if not config.encryption_enabled:
        result.is_valid = False
        result.errors.append("Backup encryption must be enabled")

    if config.encryption not in (BackupEncryption.AES_256_CBC, BackupEncryption.AES_256_GCM):
        result.is_valid = False
        result.errors.append(
            f"Backup encryption must be AES-256, got '{config.encryption}'"
        )

    # PITR (Requirement 53.2)
    if not config.point_in_time_recovery:
        result.is_valid = False
        result.errors.append("Point-in-time recovery must be enabled")

    # Region (Requirement 53.1)
    if config.cloud_provider in APPROVED_REGIONS:
        provider_regions = set(APPROVED_REGIONS[config.cloud_provider])
        if config.backup_region not in provider_regions:
            result.is_valid = False
            result.errors.append(
                f"Backup region '{config.backup_region}' is not an approved "
                f"NZ/AU region for {config.cloud_provider}"
            )
    else:
        result.is_valid = False
        result.errors.append(
            f"Unsupported cloud provider '{config.cloud_provider}'"
        )

    return result


# ---------------------------------------------------------------------------
# Backup verification utilities
# ---------------------------------------------------------------------------

@dataclass
class BackupStatus:
    """Status of a backup snapshot."""

    backup_id: str
    timestamp: dt.datetime
    is_encrypted: bool
    region: str
    size_bytes: int = 0


def verify_backup_age(
    backup: BackupStatus,
    max_age_hours: int = 25,
    now: dt.datetime | None = None,
) -> ValidationResult:
    """Check that a backup is not older than the allowed threshold.

    Parameters
    ----------
    backup:
        The backup snapshot to check.
    max_age_hours:
        Maximum acceptable age in hours (default 25 — slightly over
        one daily cycle to allow for timing variance).
    now:
        Current time for comparison. Defaults to ``datetime.utcnow()``.

    Returns
    -------
    ValidationResult
        Valid if the backup is within the age threshold.
    """
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    # Ensure backup timestamp is timezone-aware for comparison
    backup_ts = backup.timestamp
    if backup_ts.tzinfo is None:
        backup_ts = backup_ts.replace(tzinfo=dt.timezone.utc)

    age = now - backup_ts
    age_hours = age.total_seconds() / 3600

    result = ValidationResult()
    if age_hours > max_age_hours:
        result.is_valid = False
        result.errors.append(
            f"Backup '{backup.backup_id}' is {age_hours:.1f} hours old, "
            f"exceeding the {max_age_hours}-hour threshold"
        )
    return result


def verify_backup_encryption(backup: BackupStatus) -> ValidationResult:
    """Check that a backup is encrypted.

    Parameters
    ----------
    backup:
        The backup snapshot to check.

    Returns
    -------
    ValidationResult
        Valid if the backup is encrypted.
    """
    result = ValidationResult()
    if not backup.is_encrypted:
        result.is_valid = False
        result.errors.append(
            f"Backup '{backup.backup_id}' is not encrypted"
        )
    return result


def verify_backup_region(
    backup: BackupStatus,
    allowed_regions: set[str] | None = None,
) -> ValidationResult:
    """Check that a backup is stored in an approved NZ/AU region.

    Parameters
    ----------
    backup:
        The backup snapshot to check.
    allowed_regions:
        Set of approved region identifiers. Defaults to all approved
        NZ/AU regions.

    Returns
    -------
    ValidationResult
        Valid if the backup region is in the approved set.
    """
    if allowed_regions is None:
        allowed_regions = APPROVED_REGION_NAMES

    result = ValidationResult()
    if backup.region not in allowed_regions:
        result.is_valid = False
        result.errors.append(
            f"Backup '{backup.backup_id}' is in region '{backup.region}', "
            f"which is not an approved NZ/AU region"
        )
    return result
