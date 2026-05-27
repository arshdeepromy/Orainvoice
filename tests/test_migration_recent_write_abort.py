"""Phase 8b migration test (task 8.5): recent-write abort.

The migration treats a fresh write to ``integration_configs[smtp]``
(within the last 5 minutes) as a sign that an admin is mid-edit
through the legacy form. Rather than silently overwriting their
in-progress change, the migration aborts with a clear
"reschedule maintenance window" error and leaves both rows untouched.

**Validates: Requirements 15.7, 21.10**
"""

from __future__ import annotations

import pytest

from tests._migration_0198_helpers import (
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


EXPECTED_ABORT_MESSAGE = (
    "Recent write to integration_configs[smtp] detected. "
    "Reschedule maintenance window."
)


@pytest.mark.asyncio
async def test_upgrade_aborts_when_legacy_row_was_written_recently() -> None:
    """A legacy row updated < 5 minutes ago aborts the migration.

    Setup:
      * Seed ``integration_configs[smtp]`` with ``updated_at = now() - 1
        minute`` (well inside the 5-minute window).
      * Reset ``email_providers.brevo`` to ``credentials_set=False`` so
        a successful upgrade WOULD have visible side-effects.

    Assertions:
      * ``upgrade()`` raises ``RuntimeError`` whose message exactly
        matches the documented wording from the migration body.
      * ``email_providers.brevo`` is still ``credentials_set=False``,
        ``is_active=False`` — i.e. nothing was written.
      * The legacy row is unchanged (same encrypted blob, same
        ``updated_at``).

    **Validates: Requirements 15.7, 21.10**
    """
    async with migration_engine() as engine:
        legacy_before = await snapshot_legacy_row(engine)
        provider_before = await snapshot_provider(engine, "brevo")
        assert provider_before is not None

        try:
            # Reset target row so any successful upgrade would show.
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

            # Seed legacy with a 1-minute-old write timestamp. Anything
            # < 300 seconds (5 minutes) trips the abort guard.
            await seed_legacy_smtp(
                engine,
                legacy_config={
                    "provider": "brevo",
                    "api_key": "should-not-be-applied",
                    "from_email": "noreply@example.test",
                },
                is_verified=False,
                updated_at_offset_seconds=60,
            )

            legacy_at_seed = await snapshot_legacy_row(engine)
            email_provider_at_seed = await snapshot_provider(engine, "brevo")
            assert legacy_at_seed is not None
            assert email_provider_at_seed is not None

            migration = load_migration_module()

            with pytest.raises(RuntimeError) as exc_info:
                await run_migration_upgrade(engine, migration)

            assert str(exc_info.value) == EXPECTED_ABORT_MESSAGE, (
                "Migration must raise the documented recent-write abort message"
            )

            # Verify nothing changed on either row.
            after_legacy = await snapshot_legacy_row(engine)
            after_provider = await snapshot_provider(engine, "brevo")
            assert after_legacy is not None
            assert after_provider is not None

            # Legacy ciphertext + updated_at unchanged. Compare bytes
            # explicitly — sqla can return memoryview vs bytes.
            assert bytes(after_legacy["config_encrypted"]) == bytes(
                legacy_at_seed["config_encrypted"]
            ), "Legacy row config_encrypted must be unchanged after abort"
            assert after_legacy["updated_at"] == legacy_at_seed["updated_at"], (
                "Legacy row updated_at must NOT have been touched by the aborted migration"
            )

            # Email provider row unchanged.
            assert (
                after_provider["credentials_set"]
                == email_provider_at_seed["credentials_set"]
                == False
            ), "email_providers.brevo.credentials_set must remain False after abort"
            assert (
                after_provider["is_active"]
                == email_provider_at_seed["is_active"]
                == False
            ), "email_providers.brevo.is_active must remain False after abort"
            assert (
                after_provider["credentials_encrypted"]
                == email_provider_at_seed["credentials_encrypted"]
                is None
            ), "email_providers.brevo.credentials_encrypted must remain NULL"
        finally:
            await delete_legacy_row(engine)
            await restore_legacy_row(engine, legacy_before)
            await restore_provider(engine, "brevo", provider_before)
