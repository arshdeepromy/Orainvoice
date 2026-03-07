"""Tests for Task 38.2 — Data residency and backup configuration.

Verifies:
  - Backup retention is 30 days by default (Requirement 53.2)
  - Backup encryption is enforced (Requirement 53.3)
  - Data residency validation rejects non-NZ/AU regions (Requirement 53.1)
  - Point-in-time recovery is configured (Requirement 53.2)
  - Configurable retention policy within allowed range (Requirement 53.4)
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.backup import (
    APPROVED_REGION_NAMES,
    APPROVED_REGIONS,
    BackupConfig,
    BackupEncryption,
    BackupStatus,
    DataResidencyConfig,
    validate_backup_config,
    validate_data_residency,
    verify_backup_age,
    verify_backup_encryption,
    verify_backup_region,
)


# ---------------------------------------------------------------------------
# Backup retention tests (Requirement 53.2)
# ---------------------------------------------------------------------------

class TestBackupRetention:
    """Verify 30-day backup retention with point-in-time recovery."""

    def test_default_retention_is_30_days(self):
        config = BackupConfig()
        assert config.retention_days == 30

    def test_default_pitr_enabled(self):
        config = BackupConfig()
        assert config.point_in_time_recovery is True

    def test_retention_within_valid_range_passes(self):
        for days in (7, 30, 60, 90):
            config = BackupConfig(retention_days=days)
            result = validate_backup_config(config)
            assert result.is_valid, f"Expected valid for {days} days"

    def test_retention_below_minimum_fails(self):
        config = BackupConfig(retention_days=3)
        result = validate_backup_config(config)
        assert not result.is_valid
        assert any("between 7 and 90" in e for e in result.errors)

    def test_retention_above_maximum_fails(self):
        config = BackupConfig(retention_days=120)
        result = validate_backup_config(config)
        assert not result.is_valid
        assert any("between 7 and 90" in e for e in result.errors)

    def test_pitr_disabled_fails_validation(self):
        config = BackupConfig(point_in_time_recovery=False)
        result = validate_backup_config(config)
        assert not result.is_valid
        assert any("Point-in-time recovery" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Backup encryption tests (Requirement 53.3)
# ---------------------------------------------------------------------------

class TestBackupEncryption:
    """Verify backup encryption is enforced."""

    def test_default_encryption_enabled(self):
        config = BackupConfig()
        assert config.encryption_enabled is True

    def test_default_encryption_is_aes_256(self):
        config = BackupConfig()
        assert config.encryption in (
            BackupEncryption.AES_256_CBC,
            BackupEncryption.AES_256_GCM,
        )

    def test_encryption_disabled_fails_validation(self):
        config = BackupConfig(encryption_enabled=False)
        result = validate_backup_config(config)
        assert not result.is_valid
        assert any("encryption must be enabled" in e for e in result.errors)

    def test_encrypted_backup_passes_verification(self):
        backup = BackupStatus(
            backup_id="bk-001",
            timestamp=dt.datetime.now(dt.timezone.utc),
            is_encrypted=True,
            region="ap-southeast-2",
        )
        result = verify_backup_encryption(backup)
        assert result.is_valid

    def test_unencrypted_backup_fails_verification(self):
        backup = BackupStatus(
            backup_id="bk-002",
            timestamp=dt.datetime.now(dt.timezone.utc),
            is_encrypted=False,
            region="ap-southeast-2",
        )
        result = verify_backup_encryption(backup)
        assert not result.is_valid
        assert any("not encrypted" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Data residency validation tests (Requirement 53.1)
# ---------------------------------------------------------------------------

class TestDataResidency:
    """Verify NZ/AU data residency enforcement."""

    def test_approved_regions_include_nz_au_only(self):
        # All approved regions should be in AU/NZ geography
        for provider, regions in APPROVED_REGIONS.items():
            for region in regions:
                assert any(
                    keyword in region
                    for keyword in ("australia", "ap-southeast-2")
                ), f"Region '{region}' for {provider} may not be NZ/AU"

    def test_default_config_is_valid(self):
        config = DataResidencyConfig()
        result = validate_data_residency(config)
        assert result.is_valid

    def test_aws_sydney_region_valid(self):
        config = DataResidencyConfig(
            cloud_provider="aws",
            primary_region="ap-southeast-2",
            backup_region="ap-southeast-2",
        )
        result = validate_data_residency(config)
        assert result.is_valid

    def test_azure_australia_regions_valid(self):
        config = DataResidencyConfig(
            cloud_provider="azure",
            primary_region="australiaeast",
            backup_region="australiasoutheast",
        )
        result = validate_data_residency(config)
        assert result.is_valid

    def test_gcp_australia_regions_valid(self):
        config = DataResidencyConfig(
            cloud_provider="gcp",
            primary_region="australia-southeast1",
            backup_region="australia-southeast2",
        )
        result = validate_data_residency(config)
        assert result.is_valid

    def test_us_region_rejected(self):
        config = DataResidencyConfig(
            cloud_provider="aws",
            primary_region="us-east-1",
            backup_region="ap-southeast-2",
        )
        result = validate_data_residency(config)
        assert not result.is_valid
        assert any("not an approved NZ/AU region" in e for e in result.errors)

    def test_eu_region_rejected(self):
        config = DataResidencyConfig(
            cloud_provider="aws",
            primary_region="eu-west-1",
            backup_region="ap-southeast-2",
        )
        result = validate_data_residency(config)
        assert not result.is_valid

    def test_unsupported_provider_rejected(self):
        config = DataResidencyConfig(
            cloud_provider="digitalocean",
            primary_region="sgp1",
            backup_region="sgp1",
        )
        result = validate_data_residency(config)
        assert not result.is_valid
        assert any("Unsupported cloud provider" in e for e in result.errors)

    def test_backup_in_non_approved_region_rejected(self):
        config = DataResidencyConfig(
            cloud_provider="aws",
            primary_region="ap-southeast-2",
            backup_region="us-west-2",
        )
        result = validate_data_residency(config)
        assert not result.is_valid
        assert any("Backup region" in e and "not an approved" in e for e in result.errors)

    def test_backup_region_validated_in_backup_config(self):
        config = BackupConfig(
            cloud_provider="aws",
            backup_region="us-east-1",
        )
        result = validate_backup_config(config)
        assert not result.is_valid
        assert any("not an approved NZ/AU region" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Backup age verification tests
# ---------------------------------------------------------------------------

class TestBackupAgeVerification:
    """Verify backup freshness checks."""

    def test_recent_backup_passes(self):
        now = dt.datetime(2024, 6, 15, 12, 0, tzinfo=dt.timezone.utc)
        backup = BackupStatus(
            backup_id="bk-003",
            timestamp=dt.datetime(2024, 6, 15, 10, 0, tzinfo=dt.timezone.utc),
            is_encrypted=True,
            region="ap-southeast-2",
        )
        result = verify_backup_age(backup, max_age_hours=25, now=now)
        assert result.is_valid

    def test_stale_backup_fails(self):
        now = dt.datetime(2024, 6, 15, 12, 0, tzinfo=dt.timezone.utc)
        backup = BackupStatus(
            backup_id="bk-004",
            timestamp=dt.datetime(2024, 6, 13, 10, 0, tzinfo=dt.timezone.utc),
            is_encrypted=True,
            region="ap-southeast-2",
        )
        result = verify_backup_age(backup, max_age_hours=25, now=now)
        assert not result.is_valid
        assert any("exceeding" in e for e in result.errors)

    def test_naive_timestamp_treated_as_utc(self):
        now = dt.datetime(2024, 6, 15, 12, 0, tzinfo=dt.timezone.utc)
        backup = BackupStatus(
            backup_id="bk-005",
            timestamp=dt.datetime(2024, 6, 15, 11, 0),  # naive
            is_encrypted=True,
            region="ap-southeast-2",
        )
        result = verify_backup_age(backup, max_age_hours=25, now=now)
        assert result.is_valid


# ---------------------------------------------------------------------------
# Backup region verification tests
# ---------------------------------------------------------------------------

class TestBackupRegionVerification:
    """Verify backup region compliance."""

    def test_approved_region_passes(self):
        backup = BackupStatus(
            backup_id="bk-006",
            timestamp=dt.datetime.now(dt.timezone.utc),
            is_encrypted=True,
            region="ap-southeast-2",
        )
        result = verify_backup_region(backup)
        assert result.is_valid

    def test_non_approved_region_fails(self):
        backup = BackupStatus(
            backup_id="bk-007",
            timestamp=dt.datetime.now(dt.timezone.utc),
            is_encrypted=True,
            region="us-east-1",
        )
        result = verify_backup_region(backup)
        assert not result.is_valid
        assert any("not an approved NZ/AU region" in e for e in result.errors)

    def test_custom_allowed_regions(self):
        backup = BackupStatus(
            backup_id="bk-008",
            timestamp=dt.datetime.now(dt.timezone.utc),
            is_encrypted=True,
            region="australiaeast",
        )
        result = verify_backup_region(
            backup, allowed_regions={"australiaeast", "australiasoutheast"}
        )
        assert result.is_valid


# ---------------------------------------------------------------------------
# Full backup config validation (all requirements combined)
# ---------------------------------------------------------------------------

class TestFullBackupValidation:
    """Verify that the default configuration passes all checks."""

    def test_default_backup_config_is_valid(self):
        config = BackupConfig()
        result = validate_backup_config(config)
        assert result.is_valid
        assert result.errors == []

    def test_multiple_violations_reported(self):
        config = BackupConfig(
            retention_days=3,
            encryption_enabled=False,
            point_in_time_recovery=False,
            cloud_provider="aws",
            backup_region="us-east-1",
        )
        result = validate_backup_config(config)
        assert not result.is_valid
        assert len(result.errors) >= 3
