"""Integration backup / restore compatibility tests (Phase 7, Req 14.7).

These tests cover ``export_integration_settings`` and
``import_integration_settings`` in ``app/modules/admin/service.py`` as
they exist after Phase 7 of the email-provider-unification spec:

1. **Both stores are exported.** A backup must include rows from
   both ``integration_configs`` and ``email_providers``. The unified
   sender reads ``email_providers`` exclusively, so a backup that
   forgot it would leave a restored environment unable to send mail
   even though the legacy ``integration_configs[smtp]`` row was
   present.

2. **Pre-Phase-8b backups still restore correctly.** A backup
   produced before the Phase 8b data migration only carries the
   legacy ``integration_configs[smtp]`` row. Restoring it must mirror
   that row into the matching ``email_providers`` row (mapping per
   the Phase 8b migration: ``brevo → brevo``, ``sendgrid →
   sendgrid``, ``smtp → custom_smtp``) and set ``credentials_set=true``
   so outbound mail works immediately after restore — without the
   admin having to re-enter API keys.

3. **No-clobber.** If the target ``email_providers`` row is already
   configured (``credentials_set=true``), the legacy mirror does
   nothing — same rule the Phase 8b migration enforces.

These tests use mocked DB sessions; ``envelope_encrypt`` /
``envelope_decrypt_str`` run for real so we can assert the encrypted
blobs round-trip cleanly.

Validates: Requirements 14.7.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import all ORM models so SQLAlchemy can resolve string-based
# relationship references before any select() statement constructs a
# mapper. Mirrors the import block used by other admin-service unit tests
# (see tests/test_notification_log_provider_columns.py) and works around
# the pre-existing PartSupplier ↔ Supplier mapper-config drift logged
# under ISSUE-150.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.invoices import attachment_models as _invoice_attachment_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401

from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.admin.service import (
    export_integration_settings,
    import_integration_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_integration_config_row(name: str, payload: dict, *, is_verified: bool = False):
    """Build a fake IntegrationConfig row with a real encrypted blob."""
    row = MagicMock()
    row.name = name
    row.config_encrypted = envelope_encrypt(json.dumps(payload))
    row.is_verified = is_verified
    return row


def _make_email_provider_row(
    *,
    provider_key: str,
    display_name: str = "Provider",
    is_active: bool = False,
    credentials_set: bool = False,
    credentials: dict | None = None,
    config: dict | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_encryption: str | None = "tls",
    priority: int = 1,
):
    """Build a fake EmailProvider row backed by real envelope encryption."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.provider_key = provider_key
    row.display_name = display_name
    row.description = None
    row.is_active = is_active
    row.priority = priority
    row.smtp_host = smtp_host
    row.smtp_port = smtp_port
    row.smtp_encryption = smtp_encryption
    row.config = config or {}
    row.credentials_set = credentials_set
    row.credentials_encrypted = (
        envelope_encrypt(json.dumps(credentials)) if credentials else None
    )
    return row


def _make_db_with_results(*, integrations: list, sms_providers: list, email_providers: list):
    """Build a mocked DB whose ``execute`` returns a queue of results."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    # Each call to db.execute returns the next result in sequence.
    # Order mirrors export/import code: integrations → sms_providers →
    # email_providers, then any post-loop lookups.
    results: list = []

    def _make_scalars_result(rows):
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    results.append(_make_scalars_result(integrations))
    results.append(_make_scalars_result(sms_providers))
    results.append(_make_scalars_result(email_providers))

    return db, results


# ---------------------------------------------------------------------------
# Export — both stores included (Requirement 14.7, sentence 1)
# ---------------------------------------------------------------------------


class TestExportIncludesBothStores:
    @pytest.mark.asyncio
    async def test_export_emits_both_integration_configs_and_email_providers(self):
        """Export must walk both tables — the unified sender reads
        ``email_providers`` exclusively, so a backup that forgot it
        would leave outbound mail dark after restore."""
        legacy_smtp = _make_integration_config_row(
            "smtp",
            {
                "provider": "brevo",
                "api_key": "xkeysib-legacy",
                "host": "",
                "port": 587,
                "username": "",
                "password": "",
                "domain": "legacy.test",
                "from_email": "noreply@legacy.test",
                "from_name": "Legacy",
                "reply_to": "support@legacy.test",
            },
        )
        brevo_provider = _make_email_provider_row(
            provider_key="brevo",
            display_name="Brevo",
            is_active=True,
            credentials_set=True,
            credentials={"api_key": "xkeysib-new"},
            config={"from_email": "noreply@new.test", "from_name": "New"},
        )

        db, results = _make_db_with_results(
            integrations=[legacy_smtp],
            sms_providers=[],
            email_providers=[brevo_provider],
        )
        db.execute = AsyncMock(side_effect=results)

        backup = await export_integration_settings(db)

        # Both tables present
        assert "smtp" in backup["integrations"]
        assert backup["email_providers"], "email_providers must be exported"
        assert backup["email_providers"][0]["provider_key"] == "brevo"
        # Sensitive fields redacted in the dumped config
        assert backup["integrations"]["smtp"]["config"]["api_key"] == "***REDACTED***"
        assert backup["email_providers"][0]["credentials"]["api_key"] == "***REDACTED***"


# ---------------------------------------------------------------------------
# Import — legacy-only backup mirrors into email_providers (Req 14.7, sentence 2)
# ---------------------------------------------------------------------------


class TestImportLegacyOnlyBackup:
    """A backup predating Phase 8b carries only the legacy
    ``integration_configs[smtp]`` row. After restore, the matching
    ``email_providers`` row must be populated so outbound mail works
    without the admin re-entering API keys.
    """

    def _legacy_only_backup(self, *, provider: str, credentials_field: dict) -> dict:
        config = {
            "provider": provider,
            "api_key": "",
            "host": "",
            "port": 587,
            "username": "",
            "password": "",
            "domain": "old.test",
            "from_email": "noreply@old.test",
            "from_name": "Old",
            "reply_to": "support@old.test",
        }
        config.update(credentials_field)
        return {
            "version": 1,
            "integrations": {
                "smtp": {
                    "config": config,
                    "is_verified": True,
                },
            },
            "sms_providers": [],
            "email_providers": [],
        }

    def _setup_db_for_legacy_import(self, *, target_row):
        """Mock a DB that returns ``target_row`` for the EmailProvider
        lookup at the end of ``import_integration_settings`` and ``None``
        for the IntegrationConfig lookup (so the legacy row is created)."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Sequence of execute returns:
        #   1) IntegrationConfig where name='smtp'  → None (no existing row)
        #   2) EmailProvider where provider_key=<target>  → target_row
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        target_lookup = MagicMock()
        target_lookup.scalar_one_or_none.return_value = target_row

        db.execute = AsyncMock(side_effect=[no_existing, target_lookup])
        return db

    @pytest.mark.asyncio
    async def test_brevo_legacy_backup_populates_email_provider_row(self):
        backup = self._legacy_only_backup(
            provider="brevo",
            credentials_field={"api_key": "xkeysib-restored"},
        )
        target = _make_email_provider_row(
            provider_key="brevo",
            credentials_set=False,
        )
        db = self._setup_db_for_legacy_import(target_row=target)

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            await import_integration_settings(
                db, data=backup, imported_by=uuid.uuid4()
            )

        assert target.credentials_set is True
        assert target.is_active is True
        assert target.priority == 1
        decrypted = json.loads(envelope_decrypt_str(target.credentials_encrypted))
        assert decrypted == {"api_key": "xkeysib-restored"}
        assert target.config["from_email"] == "noreply@old.test"

    @pytest.mark.asyncio
    async def test_sendgrid_legacy_backup_populates_email_provider_row(self):
        backup = self._legacy_only_backup(
            provider="sendgrid",
            credentials_field={"api_key": "SG.restored"},
        )
        target = _make_email_provider_row(
            provider_key="sendgrid",
            credentials_set=False,
        )
        db = self._setup_db_for_legacy_import(target_row=target)

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            await import_integration_settings(
                db, data=backup, imported_by=uuid.uuid4()
            )

        assert target.credentials_set is True
        decrypted = json.loads(envelope_decrypt_str(target.credentials_encrypted))
        assert decrypted == {"api_key": "SG.restored"}

    @pytest.mark.asyncio
    async def test_custom_smtp_legacy_backup_maps_to_custom_smtp(self):
        """``provider='smtp'`` in the legacy row maps to ``custom_smtp``
        in the new schema (per Phase 8b migration mapping)."""
        backup = self._legacy_only_backup(
            provider="smtp",
            credentials_field={
                "username": "smtp-user",
                "password": "smtp-pass",
                "host": "mail.example.com",
                "port": 25,
            },
        )
        # The host/port from credentials_field overrides the defaults
        backup["integrations"]["smtp"]["config"]["host"] = "mail.example.com"
        backup["integrations"]["smtp"]["config"]["port"] = 25
        target = _make_email_provider_row(
            provider_key="custom_smtp",
            credentials_set=False,
        )
        db = self._setup_db_for_legacy_import(target_row=target)

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            await import_integration_settings(
                db, data=backup, imported_by=uuid.uuid4()
            )

        assert target.credentials_set is True
        decrypted = json.loads(envelope_decrypt_str(target.credentials_encrypted))
        assert decrypted == {"username": "smtp-user", "password": "smtp-pass"}
        assert target.smtp_host == "mail.example.com"
        assert target.smtp_port == 25


# ---------------------------------------------------------------------------
# Import — no-clobber when target is already configured (Req 14.7, sentence 2)
# ---------------------------------------------------------------------------


class TestImportNoClobber:
    @pytest.mark.asyncio
    async def test_legacy_mirror_skips_when_target_already_configured(self):
        """If the ``email_providers`` row for the mapped provider is
        already configured, the legacy mirror is a no-op — same rule the
        Phase 8b migration enforces, so we never overwrite a fresh
        admin-configured provider with a stale backup blob.
        """
        backup = {
            "version": 1,
            "integrations": {
                "smtp": {
                    "config": {
                        "provider": "brevo",
                        "api_key": "xkeysib-stale",
                        "host": "",
                        "port": 587,
                        "username": "",
                        "password": "",
                        "domain": "old.test",
                        "from_email": "noreply@old.test",
                        "from_name": "Old",
                        "reply_to": "",
                    },
                    "is_verified": False,
                },
            },
            "sms_providers": [],
            "email_providers": [],
        }
        original_creds = {"api_key": "xkeysib-current"}
        target = _make_email_provider_row(
            provider_key="brevo",
            credentials_set=True,  # Already configured
            credentials=original_creds,
        )
        original_blob = target.credentials_encrypted

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        target_lookup = MagicMock()
        target_lookup.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(side_effect=[no_existing, target_lookup])

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            await import_integration_settings(
                db, data=backup, imported_by=uuid.uuid4()
            )

        # Untouched: the existing credentials blob is unchanged
        assert target.credentials_encrypted == original_blob
        decrypted = json.loads(envelope_decrypt_str(target.credentials_encrypted))
        assert decrypted == original_creds


# ---------------------------------------------------------------------------
# Roundtrip — export → import preserves email_providers state
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_email_provider_with_credentials_roundtrips(self):
        """Export then re-import an EmailProvider with real credentials.

        The backup carries the credentials in plaintext-redacted form;
        on import they're re-encrypted into the target row. This test
        asserts the roundtrip by injecting a non-redacted backup
        (matching what an operator would produce by passing a
        pre-redaction copy to ``import_integration_settings``).
        """
        original_creds = {"api_key": "xkeysib-roundtrip"}
        original_config = {
            "from_email": "noreply@example.test",
            "from_name": "Example",
            "reply_to": "support@example.test",
        }

        # Backup shape that would be produced from a real export plus
        # operator-provided credentials (since the export redacts).
        backup = {
            "version": 1,
            "integrations": {},
            "sms_providers": [],
            "email_providers": [
                {
                    "provider_key": "brevo",
                    "display_name": "Brevo",
                    "description": None,
                    "smtp_host": None,
                    "smtp_port": None,
                    "smtp_encryption": "tls",
                    "priority": 2,
                    "is_active": True,
                    "config": original_config,
                    "credentials_set": True,
                    "credentials": original_creds,
                },
            ],
        }
        target = _make_email_provider_row(
            provider_key="brevo",
            credentials_set=False,
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        # Single lookup: EmailProvider where provider_key='brevo'
        # (no integration_configs[smtp] in the backup, so the legacy
        # mirror block does NOT run a second lookup)
        target_lookup = MagicMock()
        target_lookup.scalar_one_or_none.return_value = target
        db.execute = AsyncMock(side_effect=[target_lookup])

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            await import_integration_settings(
                db, data=backup, imported_by=uuid.uuid4()
            )

        assert target.credentials_set is True
        assert target.is_active is True
        assert target.priority == 2
        assert target.config == original_config
        decrypted = json.loads(envelope_decrypt_str(target.credentials_encrypted))
        assert decrypted == original_creds
