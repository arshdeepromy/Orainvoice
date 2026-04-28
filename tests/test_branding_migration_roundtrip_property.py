"""Property-based tests for branding disk-to-database migration round-trip.

Feature: file-storage-replication, Property 3: Disk-to-database migration round-trip

For any branding record where a ``_url`` field points to an existing disk-based
file and the corresponding ``_data`` column is NULL, running the migration SHALL
populate the BYTEA column with the file's bytes, set the ``_content_type``
column based on the file extension, and update the ``_url`` to the
database-backed endpoint.  Serving the file after migration SHALL return the
original disk file's bytes.

**Validates: Requirements 3.1, 3.2, 3.3**

Uses Hypothesis to generate random file bytes and file extensions, writes them
to a temp disk path in the branding upload directory, creates a branding record
with the URL pointing to the disk file, then verifies the migration populates
the DB correctly and the file can be served.
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
            "name": f"MigTest-{branding_id.hex[:8]}",
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
# Property 3: Disk-to-database migration round-trip
# Feature: file-storage-replication, Property 3: Disk-to-database migration round-trip
# **Validates: Requirements 3.1, 3.2, 3.3**
# ---------------------------------------------------------------------------


class TestBrandingMigrationRoundTripProperty:
    """Property 3 — For any branding record where a _url field points to an
    existing disk-based file and the corresponding _data column is NULL,
    running the migration SHALL populate the BYTEA column with the file's
    bytes, set the _content_type column based on the file extension, and
    update the _url to the database-backed endpoint.  Serving the file
    after migration SHALL return the original disk file's bytes."""

    @PBT_SETTINGS
    @given(
        file_type=file_type_strategy,
        file_data=file_data_strategy,
        extension=extension_strategy,
    )
    def test_migration_populates_bytea_and_updates_url(
        self, file_type, file_data, extension,
    ):
        """After migration, the BYTEA column contains the disk file's bytes,
        the content_type is set from the extension, the URL points to the
        DB-backed endpoint, and get_branding_file() returns the original bytes.

        **Validates: Requirements 3.1, 3.2, 3.3**
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

                # --- Run migration ---
                async with session.begin():
                    svc = BrandingService(session)
                    result = await svc.migrate_disk_files_to_db()
                    assert result["migrated"] >= 1, (
                        f"Expected at least 1 migrated file, got {result}"
                    )

                # --- Verify: BYTEA column is populated with file bytes ---
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
                    record = row.one()
                    db_data = record[0]
                    db_content_type = record[1]
                    db_url = record[2]

                    # 1. BYTEA column populated with the file's bytes
                    assert db_data is not None, (
                        f"BYTEA column {file_type}_data is still NULL after migration"
                    )
                    assert bytes(db_data) == file_data, (
                        f"BYTEA data mismatch: expected {len(file_data)} bytes, "
                        f"got {len(db_data)} bytes"
                    )

                    # 2. Content type set based on file extension
                    expected_mime, _ = mimetypes.guess_type(filename)
                    if expected_mime is None:
                        expected_mime = "application/octet-stream"
                    assert db_content_type == expected_mime, (
                        f"Content type mismatch: expected {expected_mime!r}, "
                        f"got {db_content_type!r}"
                    )

                    # 3. URL updated to DB-backed endpoint
                    expected_url = DB_FILE_URL_PATTERN.format(file_type=file_type)
                    assert db_url == expected_url, (
                        f"URL not updated: expected {expected_url!r}, "
                        f"got {db_url!r}"
                    )

                # --- Verify: get_branding_file() returns original bytes ---
                async with session.begin():
                    svc2 = BrandingService(session)
                    file_result = await svc2.get_branding_file(file_type)
                    assert file_result is not None, (
                        f"get_branding_file({file_type!r}) returned None "
                        f"after migration"
                    )
                    served_data, served_ct, served_fn = file_result
                    assert served_data == file_data, (
                        f"Served bytes mismatch: expected {len(file_data)} bytes, "
                        f"got {len(served_data)} bytes"
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
