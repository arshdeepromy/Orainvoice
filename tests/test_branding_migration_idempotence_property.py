"""Property-based tests for branding migration idempotence.

Feature: file-storage-replication, Property 4: Migration idempotence

For any database state, running the branding file migration multiple times SHALL
produce the same result — BYTEA columns that are already populated SHALL not be
modified, and no errors SHALL occur on subsequent runs.

**Validates: Requirements 3.5, 8.4, 9.3**

Uses Hypothesis to generate random file bytes and file extensions, writes them
to a temp disk path in the branding upload directory, creates a branding record
with the URL pointing to the disk file, runs migration TWICE, and verifies the
second run produces identical results with ``migrated: 0``.
"""

from __future__ import annotations

import mimetypes
import os
import uuid

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings as app_settings

# Import ORM models so SQLAlchemy can resolve relationships
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.branding import models as _branding_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401

from app.modules.branding.models import PlatformBranding
from app.modules.branding.service import (
    BrandingService,
    BRANDING_UPLOAD_DIR,
    DB_FILE_URL_PATTERN,
)

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid branding file types
file_type_strategy = st.sampled_from(["logo", "dark_logo", "favicon"])

# File extensions with known MIME types
extension_strategy = st.sampled_from([
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".ico",
])

# Random file bytes: 1 byte to 100 KB (keep small for speed)
file_data_strategy = st.binary(min_size=1, max_size=100 * 1024)


# ---------------------------------------------------------------------------
# Per-test engine/session factory
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, object]:
    """Create a fresh engine + session for each test run."""
    test_engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    session = factory()
    return session, test_engine


async def _create_branding_record(
    session: AsyncSession,
    file_type: str,
    disk_url: str,
) -> uuid.UUID:
    """Create a minimal PlatformBranding record with a disk-based URL.

    The ``_data`` column for the given file_type is left NULL so the
    migration has something to migrate.

    Uses a very early ``created_at`` so that ``get_branding()`` (which
    fetches the first row ordered by ``created_at``) returns this test
    record instead of any pre-existing production branding row.
    """
    branding_id = uuid.uuid4()
    url_col = f"{file_type}_url"

    await session.execute(
        text(f"""
            INSERT INTO platform_branding (
                id, platform_name, primary_colour, secondary_colour,
                auto_detect_domain, platform_theme, created_at, updated_at,
                {url_col}
            ) VALUES (
                :id, :name, :colour1, :colour2,
                true, 'classic',
                '2000-01-01T00:00:00+00:00',
                '2000-01-01T00:00:00+00:00',
                :url
            )
        """),
        {
            "id": str(branding_id),
            "name": f"IdempTest-{branding_id.hex[:8]}",
            "colour1": "#2563EB",
            "colour2": "#1E40AF",
            "url": disk_url,
        },
    )
    await session.flush()
    return branding_id


async def _cleanup_branding(session: AsyncSession, branding_id: uuid.UUID) -> None:
    """Delete the test branding record."""
    await session.execute(
        text("DELETE FROM platform_branding WHERE id = :id"),
        {"id": str(branding_id)},
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Property 4: Migration idempotence
# Feature: file-storage-replication, Property 4: Migration idempotence
# **Validates: Requirements 3.5, 8.4, 9.3**
# ---------------------------------------------------------------------------


class TestBrandingMigrationIdempotenceProperty:
    """Property 4 — For any database state, running the branding file migration
    multiple times SHALL produce the same result — BYTEA columns that are
    already populated SHALL not be modified, and no errors SHALL occur on
    subsequent runs."""

    @PBT_SETTINGS
    @given(
        file_type=file_type_strategy,
        file_data=file_data_strategy,
        extension=extension_strategy,
    )
    def test_migration_idempotence_second_run_is_noop(
        self, file_type, file_data, extension,
    ):
        """Running migration twice produces identical DB state; the second run
        reports ``migrated: 0`` and does not modify already-populated BYTEA
        columns.

        **Validates: Requirements 3.5, 8.4, 9.3**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            branding_id = None
            disk_path = None
            try:
                # --- Setup: write file to disk in the branding upload dir ---
                os.makedirs(BRANDING_UPLOAD_DIR, exist_ok=True)
                filename = f"{uuid.uuid4().hex}{extension}"
                disk_path = BRANDING_UPLOAD_DIR / filename
                disk_path.write_bytes(file_data)

                # Build a disk-based URL (simulates the old pattern)
                disk_url = f"http://localhost/api/v1/public/branding/file/{filename}"

                # --- Create branding record with disk URL, _data = NULL ---
                async with session.begin():
                    branding_id = await _create_branding_record(
                        session, file_type, disk_url,
                    )

                # --- First migration run ---
                async with session.begin():
                    svc = BrandingService(session)
                    result1 = await svc.migrate_disk_files_to_db()
                    assert result1["migrated"] >= 1, (
                        f"First migration should migrate at least 1 file, got {result1}"
                    )

                # --- Capture state after first migration ---
                async with session.begin():
                    row = await session.execute(
                        text(f"""
                            SELECT {file_type}_data,
                                   {file_type}_content_type,
                                   {file_type}_url
                            FROM platform_branding
                            WHERE id = :id
                        """),
                        {"id": str(branding_id)},
                    )
                    record_after_first = row.one()
                    first_data = bytes(record_after_first[0])
                    first_content_type = record_after_first[1]
                    first_url = record_after_first[2]

                    # Sanity: first migration populated the data
                    assert first_data == file_data, (
                        "First migration data mismatch"
                    )

                # --- Second migration run (should be a no-op) ---
                async with session.begin():
                    svc2 = BrandingService(session)
                    result2 = await svc2.migrate_disk_files_to_db()
                    assert result2["migrated"] == 0, (
                        f"Second migration should migrate 0 files, got {result2}"
                    )
                    assert len(result2.get("warnings", [])) == 0, (
                        f"Second migration should produce no warnings, got {result2['warnings']}"
                    )

                # --- Capture state after second migration ---
                async with session.begin():
                    row2 = await session.execute(
                        text(f"""
                            SELECT {file_type}_data,
                                   {file_type}_content_type,
                                   {file_type}_url
                            FROM platform_branding
                            WHERE id = :id
                        """),
                        {"id": str(branding_id)},
                    )
                    record_after_second = row2.one()
                    second_data = bytes(record_after_second[0])
                    second_content_type = record_after_second[1]
                    second_url = record_after_second[2]

                # --- Verify: state is identical after both runs ---
                assert second_data == first_data, (
                    f"BYTEA data changed after second migration: "
                    f"first={len(first_data)} bytes, second={len(second_data)} bytes"
                )
                assert second_content_type == first_content_type, (
                    f"Content type changed after second migration: "
                    f"{first_content_type!r} -> {second_content_type!r}"
                )
                assert second_url == first_url, (
                    f"URL changed after second migration: "
                    f"{first_url!r} -> {second_url!r}"
                )

                # --- Verify: served file is still the original bytes ---
                async with session.begin():
                    svc3 = BrandingService(session)
                    file_result = await svc3.get_branding_file(file_type)
                    assert file_result is not None, (
                        f"get_branding_file({file_type!r}) returned None "
                        f"after second migration"
                    )
                    served_data, served_ct, served_fn = file_result
                    assert served_data == file_data, (
                        f"Served bytes differ after second migration: "
                        f"expected {len(file_data)} bytes, got {len(served_data)} bytes"
                    )

            finally:
                # Cleanup: remove temp disk file
                if disk_path is not None:
                    try:
                        disk_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                # Cleanup: remove test branding record
                if branding_id is not None:
                    try:
                        async with session.begin():
                            await _cleanup_branding(session, branding_id)
                    except Exception:
                        pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())
