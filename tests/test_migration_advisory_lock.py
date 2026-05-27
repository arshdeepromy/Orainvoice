"""Phase 8b migration test (task 8.6): advisory-lock contention.

The migration acquires ``pg_advisory_lock(hashtext('email_provider_rotate'))``
to serialise with ``app/cli/rotate_keys.py``. When the lock is already
held by another connection, ``SET LOCAL lock_timeout`` makes the
acquisition itself raise after the configured timeout, surfaced to the
caller as ``RuntimeError("Could not acquire ...")``.

This test:
  1. Acquires the lock from one async connection (simulating
     ``rotate_keys.py``).
  2. Patches the migration's lock-timeout helper to use 200 ms instead
     of the production 60 s — a normal CI run should not wait a full
     minute just to assert "yes, it timed out".
  3. Invokes the migration on a separate connection; asserts it raises
     ``RuntimeError`` with the documented "Could not acquire" wording
     within a generous wallclock budget.
  4. Releases the external lock and re-runs the migration; asserts it
     now succeeds and applies its changes.

**Validates: Requirements 15.5, 15.6, 21.10**
"""

from __future__ import annotations

import time
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests._migration_0198_helpers import (
    acquire_external_advisory_lock,
    decrypt_credentials,
    delete_legacy_row,
    load_migration_module,
    migration_engine,
    release_external_advisory_lock,
    restore_legacy_row,
    restore_provider,
    run_migration_upgrade,
    seed_legacy_smtp,
    snapshot_legacy_row,
    snapshot_provider,
)


EXPECTED_LOCK_MESSAGE_PREFIX = "Could not acquire email_provider_rotate advisory lock"
"""Prefix of the ``RuntimeError`` raised when lock acquisition times out.

The migration body's wording: 'Could not acquire email_provider_rotate
advisory lock. Is rotate_keys.py running? Wait for it to finish, then
retry.'  We assert on the prefix to keep the test stable against
trailing-text edits."""


def _patch_short_lock_timeout(migration: ModuleType, timeout_ms: int = 200) -> None:
    """Patch ``_acquire_advisory_lock`` to use a millisecond-scale timeout.

    The production migration sets ``SET LOCAL lock_timeout = '60s'`` so
    a stuck rotate_keys.py would block the deploy for at most a minute
    before bailing. For tests, 200 ms is enough to prove the timeout
    fires while keeping the suite responsive.
    """

    def _patched(bind: Any) -> None:
        bind.execute(sa.text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
        try:
            bind.execute(
                sa.text("SELECT pg_advisory_lock(hashtext('email_provider_rotate'))")
            )
        except sa.exc.DBAPIError as exc:
            raise RuntimeError(
                "Could not acquire email_provider_rotate advisory lock. "
                "Is rotate_keys.py running? Wait for it to finish, then retry."
            ) from exc

    migration._acquire_advisory_lock = _patched  # type: ignore[attr-defined]


async def _seed_brevo_for_lock_test(engine: AsyncEngine) -> None:
    """Seed legacy row + reset email_providers.brevo to a clean state."""
    await delete_legacy_row(engine)
    await seed_legacy_smtp(
        engine,
        legacy_config={
            "provider": "brevo",
            "api_key": "advisory-lock-test-key",
            "from_email": "noreply@advisory-lock-test.example",
        },
        is_verified=False,
        updated_at_offset_seconds=3600,
    )


@pytest.mark.asyncio
async def test_upgrade_aborts_when_advisory_lock_held_by_another_connection() -> None:
    """An external lock holder forces the migration to abort within ``lock_timeout``.

    Once the external lock is released, a re-run of the migration must
    succeed: the second part of this test exercises the recovery path
    end-to-end.

    **Validates: Requirements 15.5, 15.6, 21.10**
    """
    async with migration_engine() as engine:
        legacy_before = await snapshot_legacy_row(engine)
        provider_before = await snapshot_provider(engine, "brevo")
        assert provider_before is not None

        try:
            # Reset email_providers.brevo so a successful upgrade WILL
            # produce visible state changes.
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
            await _seed_brevo_for_lock_test(engine)

            # Hold the lock from a second connection. We open it
            # explicitly (not as a `begin()` context) so the
            # session-level lock survives across the migration call
            # below.
            holder = await engine.connect()
            try:
                await acquire_external_advisory_lock(holder)

                migration = load_migration_module()
                _patch_short_lock_timeout(migration, timeout_ms=200)

                start = time.monotonic()
                with pytest.raises(RuntimeError) as exc_info:
                    await run_migration_upgrade(engine, migration)
                elapsed = time.monotonic() - start

                assert str(exc_info.value).startswith(EXPECTED_LOCK_MESSAGE_PREFIX), (
                    "Migration must raise the documented 'Could not acquire ...' message; "
                    f"got: {exc_info.value!r}"
                )
                # We patched lock_timeout to 200ms; 30 seconds is a
                # very generous upper bound that still proves the test
                # is not silently hanging on the production 60s lock.
                assert elapsed < 30.0, (
                    f"Migration aborted, but took {elapsed:.2f}s — did the patched lock_timeout apply?"
                )

                # Verify the migration touched nothing while it held no
                # lock (everything inside upgrade() runs *after* the
                # lock is acquired, so the abort path leaves
                # email_providers.brevo and integration_configs[smtp]
                # exactly as they were before).
                after_provider = await snapshot_provider(engine, "brevo")
                assert after_provider is not None
                assert after_provider["credentials_set"] is False
                assert after_provider["credentials_encrypted"] is None
            finally:
                # Release the external lock and close the holder so the
                # subsequent retry-success path has a clean slate.
                await release_external_advisory_lock(holder)
                await holder.close()

            # ── Recovery path ──────────────────────────────────────────
            # With the lock released the same migration body must
            # complete successfully. Loading a fresh module ensures we
            # start from the un-patched ``_acquire_advisory_lock``
            # (otherwise the millisecond timeout is still in effect —
            # which would still pass since nothing else holds the lock,
            # but using the production code path is closer to reality).
            migration_fresh = load_migration_module()
            await run_migration_upgrade(engine, migration_fresh)

            after_success = await snapshot_provider(engine, "brevo")
            assert after_success is not None
            assert after_success["credentials_set"] is True, (
                "Migration must succeed after the external lock is released"
            )
            assert after_success["is_active"] is True
            assert (
                decrypt_credentials(after_success["credentials_encrypted"]).get(
                    "api_key"
                )
                == "advisory-lock-test-key"
            ), "Recovery-path upgrade must apply the seeded api_key"
        finally:
            await delete_legacy_row(engine)
            await restore_legacy_row(engine, legacy_before)
            await restore_provider(engine, "brevo", provider_before)
