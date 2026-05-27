"""Phase 8b migration test (task 8.3): legacy SMTP → email_providers.

Drives the actual migration body of
``alembic/versions/2026_05_27_1200-0198_migrate_legacy_smtp_to_email_provider.py``
against the configured Postgres test database. Real PG is required —
the migration uses ``pg_advisory_lock``, ``hashtext``, ``interval``,
``ON CONFLICT (name)``, and ``jsonb`` casts. Tests that find no DB
reachable will be skipped via the helper rather than failing red.

**Validates: Requirements 15.1, 15.8, 21.10**

Scenarios covered:
  * Upgrade: a Brevo-shaped legacy row populates ``email_providers.brevo``
    with ``credentials_set=True``, ``is_active=True``, and the API key
    survives a round-trip through envelope encryption.
  * ``is_verified`` (legacy column) does NOT carry over to the new row
    — operators must re-test post-migration (Req 15.8).
  * Downgrade: re-encrypting back into ``integration_configs[smtp]``
    restores the legacy shape and decrypts cleanly.
"""

from __future__ import annotations

import pytest

from app.core.encryption import envelope_decrypt_str

from tests._migration_0198_helpers import (
    decrypt_credentials,
    delete_legacy_row,
    load_migration_module,
    migration_engine,
    restore_legacy_row,
    restore_provider,
    run_migration_downgrade,
    run_migration_upgrade,
    seed_legacy_smtp,
    snapshot_legacy_row,
    snapshot_provider,
)


# Legacy payload the operator would have saved through the (now-410)
# Admin → Integrations → SMTP form. Includes both REST and SMTP-shape
# fields so the helper can build the right credentials dict.
LEGACY_BREVO_CONFIG: dict = {
    "provider": "brevo",
    "api_key": "test-brevo-rest-key-abc123",
    "from_email": "noreply@example.test",
    "from_name": "Example Workshop",
    "reply_to": "support@example.test",
}


@pytest.mark.asyncio
async def test_upgrade_migrates_legacy_brevo_into_email_providers() -> None:
    """A Brevo-shaped legacy row populates ``email_providers.brevo``.

    Asserts:
      * After upgrade, ``email_providers.brevo.credentials_set=True``
      * ``is_active=True`` and ``priority=1`` per Requirement 15.3
      * The API key decrypts back to the seeded value
      * ``config`` carries the from_email / from_name / reply_to
      * The legacy row's ``is_verified`` is NOT propagated (Req 15.8)

    **Validates: Requirements 15.1, 15.3, 15.8, 21.10**
    """
    async with migration_engine() as engine:
        legacy_before = await snapshot_legacy_row(engine)
        provider_before = await snapshot_provider(engine, "brevo")
        assert provider_before is not None, (
            "email_providers.brevo seed row missing; migration 0065 should have created it"
        )

        try:
            # Reset: clear any pre-existing legacy row, drop any existing
            # credentials on the brevo row so the no-clobber rule does
            # not prevent the upgrade from applying.
            await delete_legacy_row(engine)
            await restore_provider(
                engine,
                "brevo",
                {
                    **provider_before,
                    "credentials_encrypted": None,
                    "credentials_set": False,
                    "is_active": False,
                    "priority": 1,
                    "config": {},
                },
            )

            # Seed the legacy row well outside the 5-minute recent-write
            # window (1 hour into the past) and with is_verified=True
            # which the migration MUST NOT carry over.
            await seed_legacy_smtp(
                engine,
                legacy_config=LEGACY_BREVO_CONFIG,
                is_verified=True,
                updated_at_offset_seconds=3600,
            )

            # Run the upgrade.
            migration = load_migration_module()
            await run_migration_upgrade(engine, migration)

            # Inspect the result.
            after = await snapshot_provider(engine, "brevo")
            assert after is not None
            assert after["credentials_set"] is True, (
                "Req 15.3: credentials_set must be true after upgrade"
            )
            assert after["is_active"] is True, "Req 15.3: is_active must be true"
            assert after["priority"] == 1, "Req 15.3: priority must be 1"

            creds = decrypt_credentials(after["credentials_encrypted"])
            assert creds == {"api_key": LEGACY_BREVO_CONFIG["api_key"]}, (
                "Decrypted credentials must round-trip the seeded api_key"
            )

            cfg = after["config"] or {}
            assert cfg.get("from_email") == LEGACY_BREVO_CONFIG["from_email"]
            assert cfg.get("from_name") == LEGACY_BREVO_CONFIG["from_name"]
            assert cfg.get("reply_to") == LEGACY_BREVO_CONFIG["reply_to"]

            # Req 15.8: is_verified does not exist as a column on
            # email_providers, so there is nothing to inherit. We assert
            # the explicit non-goal: nothing in the new row signals
            # "verified" — the operator must re-test through the new UI.
            # The `email_providers` schema has no is_verified column at
            # all, so the only way for the migration to surface
            # verification state would be misusing config["is_verified"]
            # — which it does not.
            assert "is_verified" not in cfg, (
                "Req 15.8: is_verified must NOT carry over from the legacy row"
            )
        finally:
            # Restore environment: reset both rows to their captured state
            # so other suites running in the same DB are unaffected.
            await delete_legacy_row(engine)
            await restore_legacy_row(engine, legacy_before)
            await restore_provider(engine, "brevo", provider_before)


@pytest.mark.asyncio
async def test_downgrade_restores_legacy_row_from_email_providers() -> None:
    """Downgrade re-encrypts the new row back into ``integration_configs[smtp]``.

    Process:
      1. Upgrade carries the seeded Brevo legacy row into ``email_providers.brevo``.
      2. The legacy row is then deleted (the spec considers it migrated).
      3. Downgrade reconstructs the legacy row from ``email_providers.brevo``.
      4. The decrypted legacy payload matches the original shape: same
         provider, same api_key, same sender identity fields.

    **Validates: Requirements 15.8, 21.10 (downgrade path)**
    """
    async with migration_engine() as engine:
        legacy_before = await snapshot_legacy_row(engine)
        provider_before = await snapshot_provider(engine, "brevo")
        assert provider_before is not None

        try:
            # Setup: clean slate then seed legacy.
            await delete_legacy_row(engine)
            await restore_provider(
                engine,
                "brevo",
                {
                    **provider_before,
                    "credentials_encrypted": None,
                    "credentials_set": False,
                    "is_active": False,
                    "priority": 1,
                    "config": {},
                },
            )
            await seed_legacy_smtp(
                engine,
                legacy_config=LEGACY_BREVO_CONFIG,
                is_verified=True,
                updated_at_offset_seconds=3600,
            )

            migration = load_migration_module()
            await run_migration_upgrade(engine, migration)

            # Simulate the post-Phase-8b world: legacy row removed
            # because it has been superseded. Downgrade must rebuild it.
            await delete_legacy_row(engine)

            await run_migration_downgrade(engine, migration)

            restored = await snapshot_legacy_row(engine)
            assert restored is not None, (
                "Downgrade must reinstate integration_configs[smtp]"
            )

            decrypted_payload = envelope_decrypt_str(bytes(restored["config_encrypted"]))
            import json

            payload = json.loads(decrypted_payload)
            assert payload["provider"] == "brevo", (
                "Downgrade must reverse-map provider_key 'brevo' → legacy 'brevo'"
            )
            assert payload["api_key"] == LEGACY_BREVO_CONFIG["api_key"], (
                "Downgrade must round-trip the api_key through re-encryption"
            )
            assert payload["from_email"] == LEGACY_BREVO_CONFIG["from_email"]
            assert payload["from_name"] == LEGACY_BREVO_CONFIG["from_name"]
            assert payload["reply_to"] == LEGACY_BREVO_CONFIG["reply_to"]
            # is_verified is reset to false on the rebuilt legacy row —
            # the operator has not actually re-tested anything.
            assert restored["is_verified"] is False, (
                "Downgrade-rebuilt legacy row must default is_verified=False"
            )
        finally:
            await delete_legacy_row(engine)
            await restore_legacy_row(engine, legacy_before)
            await restore_provider(engine, "brevo", provider_before)
