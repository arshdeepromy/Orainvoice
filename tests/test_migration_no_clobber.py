"""Phase 8b migration test (task 8.4): no-clobber rule.

If an admin has already configured a provider through the new
``email_providers`` UI, the legacy SMTP row's contents must NOT
overwrite that fresh configuration. This is the safety net that lets
the migration be re-run, and lets it apply on environments where the
GUI cutover has already populated one of the email_providers rows
directly.

**Validates: Requirements 15.4, 21.10**
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from app.core.encryption import envelope_encrypt

from tests._migration_0198_helpers import (
    decrypt_credentials,
    delete_legacy_row,
    load_migration_module,
    migration_engine,
    restore_legacy_row,
    restore_provider,
    run_migration_upgrade,
    seed_legacy_smtp,
    snapshot_legacy_row,
    snapshot_provider,
)


# Two distinct credentials so we can prove which set survives. If the
# migration's no-clobber rule fails, the legacy api_key would
# overwrite the pre-existing one.
EXISTING_BREVO_API_KEY = "pre-existing-brevo-key-already-configured"
LEGACY_BREVO_API_KEY = "legacy-key-must-not-clobber"


@pytest.mark.asyncio
async def test_existing_provider_credentials_are_not_clobbered() -> None:
    """An ``email_providers`` row with ``credentials_set=True`` is preserved.

    Setup:
      * Pre-populate ``email_providers.brevo`` with a known api_key
        and ``credentials_set=True``.
      * Seed ``integration_configs[smtp]`` with a *different* legacy
        api_key plus a Brevo provider tag.

    After running the migration:
      * ``email_providers.brevo.credentials_encrypted`` must still
        decrypt to the *pre-existing* api_key.
      * ``is_active``, ``priority``, and ``config`` must all be
        unchanged from their pre-migration state.

    **Validates: Requirements 15.4, 21.10**
    """
    async with migration_engine() as engine:
        legacy_before = await snapshot_legacy_row(engine)
        provider_before = await snapshot_provider(engine, "brevo")
        assert provider_before is not None

        # Build a deterministic "existing configuration" snapshot we can
        # later assert is bit-for-bit identical to the post-upgrade
        # state. We use a unique combination (priority=3,
        # is_active=False, distinctive config fields) so a future
        # regression cannot accidentally pass.
        existing_credentials_blob = envelope_encrypt(
            json.dumps({"api_key": EXISTING_BREVO_API_KEY})
        )
        existing_config = {
            "from_email": "alice@configured-by-admin.test",
            "from_name": "Pre-Existing Admin Sender",
            "reply_to": "noreply@configured-by-admin.test",
        }
        # Seed via direct UPDATE — the helper restore_provider only
        # accepts a snapshot, and we want to set credentials_encrypted
        # to a freshly-encrypted blob.
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE email_providers SET "
                    "credentials_encrypted = :blob, "
                    "credentials_set = true, "
                    "is_active = false, "
                    "priority = 3, "
                    "config = CAST(:config AS jsonb) "
                    "WHERE provider_key = 'brevo'"
                ),
                {
                    "blob": existing_credentials_blob,
                    "config": json.dumps(existing_config),
                },
            )

        try:
            # Seed legacy row with different content + a provider that
            # would otherwise map onto brevo.
            await seed_legacy_smtp(
                engine,
                legacy_config={
                    "provider": "brevo",
                    "api_key": LEGACY_BREVO_API_KEY,
                    "from_email": "should-not-appear@legacy.test",
                    "from_name": "Should Not Appear",
                    "reply_to": "no@legacy.test",
                },
                is_verified=True,
                updated_at_offset_seconds=3600,
            )

            # Capture exactly what we expect to remain after upgrade.
            pre_upgrade = await snapshot_provider(engine, "brevo")
            assert pre_upgrade is not None

            migration = load_migration_module()
            await run_migration_upgrade(engine, migration)

            after = await snapshot_provider(engine, "brevo")
            assert after is not None

            # Credentials: must still be the pre-existing api_key, not
            # the legacy one.
            decrypted = decrypt_credentials(after["credentials_encrypted"])
            assert decrypted.get("api_key") == EXISTING_BREVO_API_KEY, (
                "Req 15.4: pre-configured api_key must NOT be clobbered"
            )
            assert decrypted.get("api_key") != LEGACY_BREVO_API_KEY, (
                "Req 15.4: legacy api_key must NOT have overwritten pre-existing"
            )

            # No-clobber covers the entire row, not just credentials —
            # is_active, priority, config must all be untouched.
            assert after["credentials_set"] == pre_upgrade["credentials_set"]
            assert after["is_active"] == pre_upgrade["is_active"], (
                "is_active must not flip when no-clobber rule applies"
            )
            assert after["priority"] == pre_upgrade["priority"], (
                "priority must not be reset to 1 when no-clobber rule applies"
            )
            assert after["config"] == pre_upgrade["config"], (
                "config (from_email/from_name/reply_to) must not be overwritten"
            )

            # Ciphertext byte-equality is a stronger no-clobber signal
            # than just decrypted-value equality, because the migration
            # would otherwise have called envelope_encrypt(...) which
            # always picks a fresh DEK and IV.
            assert bytes(after["credentials_encrypted"]) == bytes(
                pre_upgrade["credentials_encrypted"]
            ), "credentials_encrypted bytes must be byte-identical after a no-clobber upgrade"
        finally:
            await delete_legacy_row(engine)
            await restore_legacy_row(engine, legacy_before)
            await restore_provider(engine, "brevo", provider_before)
