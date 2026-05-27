"""CLI command to rotate the encryption master key.

Usage::

    python -m app.cli.rotate_keys --old-key <old> --new-key <new>

Re-encrypts all encrypted columns across IntegrationConfig,
SmsVerificationProvider, and EmailProvider tables within a single
database transaction.  Rolls back on any failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select, text

from app.core.database import async_session_factory
from app.core.encryption import rotate_master_key
from app.modules.admin.models import (
    EmailProvider,
    IntegrationConfig,
    SmsVerificationProvider,
)

# PostgreSQL advisory-lock key shared with the Phase 8b legacy-SMTP
# migration (alembic 0198). Both this rotate-keys job and that migration
# touch ``email_providers.credentials_encrypted``; the lock serialises
# them so a master-key rotation can never interleave with the legacy
# import. ``lock_timeout`` is set to 60s before acquiring so a live
# migration aborts the rotate cleanly rather than hanging the deploy.
_EMAIL_PROVIDER_LOCK_SQL_SET_TIMEOUT = "SET LOCAL lock_timeout = '60s'"
_EMAIL_PROVIDER_LOCK_SQL_ACQUIRE = (
    "SELECT pg_advisory_lock(hashtext('email_provider_rotate'))"
)
_EMAIL_PROVIDER_LOCK_SQL_RELEASE = (
    "SELECT pg_advisory_unlock(hashtext('email_provider_rotate'))"
)


async def rotate_all_keys(old_key: str, new_key: str) -> int:
    """Re-encrypt every encrypted column under *new_key*.

    Returns the total number of field values re-encrypted.
    Raises on any failure (the caller's transaction will roll back).
    """
    re_encrypted = 0

    async with async_session_factory() as session:
        async with session.begin():
            # --- IntegrationConfig.config_encrypted ---
            rows = (await session.execute(select(IntegrationConfig))).scalars().all()
            for row in rows:
                if row.config_encrypted:
                    row.config_encrypted = rotate_master_key(
                        old_key, new_key, row.config_encrypted
                    )
                    re_encrypted += 1

            # --- SmsVerificationProvider.credentials_encrypted ---
            sms_rows = (
                await session.execute(select(SmsVerificationProvider))
            ).scalars().all()
            for row in sms_rows:
                if row.credentials_encrypted:
                    row.credentials_encrypted = rotate_master_key(
                        old_key, new_key, row.credentials_encrypted
                    )
                    re_encrypted += 1

            # --- EmailProvider.credentials_encrypted ---
            # Acquire the same PG advisory lock that alembic 0198
            # (Phase 8b legacy SMTP migration) uses, so a rotation and
            # that migration can never interleave on
            # ``email_providers.credentials_encrypted``. The lock is
            # released in ``finally`` so a crash mid-loop still frees
            # it for the next process to acquire.
            await session.execute(text(_EMAIL_PROVIDER_LOCK_SQL_SET_TIMEOUT))
            await session.execute(text(_EMAIL_PROVIDER_LOCK_SQL_ACQUIRE))
            try:
                email_rows = (
                    await session.execute(select(EmailProvider))
                ).scalars().all()
                for row in email_rows:
                    if row.credentials_encrypted:
                        row.credentials_encrypted = rotate_master_key(
                            old_key, new_key, row.credentials_encrypted
                        )
                        re_encrypted += 1
            finally:
                await session.execute(text(_EMAIL_PROVIDER_LOCK_SQL_RELEASE))

    return re_encrypted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate the encryption master key for all encrypted columns.",
    )
    parser.add_argument("--old-key", required=True, help="Current master key")
    parser.add_argument("--new-key", required=True, help="New master key to rotate to")
    args = parser.parse_args()

    try:
        count = asyncio.run(rotate_all_keys(args.old_key, args.new_key))
        print(f"Key rotation complete. {count} field(s) re-encrypted.")
    except Exception as exc:
        print(f"Key rotation FAILED — transaction rolled back. Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
