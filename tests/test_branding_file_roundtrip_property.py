"""Property-based tests for branding file upload round-trip.

Feature: file-storage-replication, Property 1: Branding file upload round-trip

For any valid branding file (logo, dark_logo, or favicon) with valid content
type and size within limits, uploading the file and then retrieving it via
``get_branding_file()`` SHALL return the same bytes with the correct
Content-Type, and the branding record's ``_url`` field SHALL point to the
database-backed serving endpoint.

**Validates: Requirements 1.4, 2.1, 2.5**

Uses Hypothesis to generate random file bytes, content types, and file types,
then verifies the round-trip through BrandingService against a real database.
"""

from __future__ import annotations

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
from app.modules.branding.service import BrandingService, DB_FILE_URL_PATTERN

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

# Valid content types for branding files (logos + favicons)
content_type_strategy = st.sampled_from([
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/svg+xml",
    "image/x-icon",
    "image/vnd.microsoft.icon",
])

# Random file bytes: 1 byte to 2 MB (the max logo size limit)
file_data_strategy = st.binary(min_size=1, max_size=2 * 1024 * 1024)

# Filename strategy
filename_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=1,
    max_size=50,
).map(lambda s: f"{s}.png")


# ---------------------------------------------------------------------------
# Per-test engine/session factory
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, object]:
    """Create a fresh engine + session for each test run.

    Uses a separate engine to avoid connection pool issues between
    Hypothesis examples.
    """
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


async def _create_branding_record(session: AsyncSession) -> PlatformBranding:
    """Create a minimal PlatformBranding record for testing.

    Returns the created record with its ID.
    """
    branding_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO platform_branding (
                id, platform_name, primary_colour, secondary_colour,
                auto_detect_domain, platform_theme, created_at, updated_at
            ) VALUES (
                :id, :name, :colour1, :colour2,
                true, 'classic', NOW(), NOW()
            )
        """),
        {
            "id": str(branding_id),
            "name": f"Test-{branding_id.hex[:8]}",
            "colour1": "#2563EB",
            "colour2": "#1E40AF",
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
# Property 1: Branding file upload round-trip
# Feature: file-storage-replication, Property 1: Branding file upload round-trip
# **Validates: Requirements 1.4, 2.1, 2.5**
# ---------------------------------------------------------------------------


class TestBrandingFileRoundTripProperty:
    """Property 1 — For any valid branding file, storing it via
    store_branding_file() and retrieving it via get_branding_file()
    SHALL return the same bytes with the correct Content-Type, and
    the URL SHALL point to the DB-backed endpoint."""

    @PBT_SETTINGS
    @given(
        file_type=file_type_strategy,
        file_data=file_data_strategy,
        content_type=content_type_strategy,
        filename=filename_strategy,
    )
    def test_roundtrip_preserves_bytes_and_content_type(
        self, file_type, file_data, content_type, filename,
    ):
        """Uploading a branding file and retrieving it returns identical
        bytes and the correct content type.

        **Validates: Requirements 1.4, 2.1, 2.5**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            branding_id = None
            try:
                async with session.begin():
                    branding_id = await _create_branding_record(session)

                # Store the file
                async with session.begin():
                    svc = BrandingService(session)
                    branding = await svc.store_branding_file(
                        file_type=file_type,
                        file_data=file_data,
                        content_type=content_type,
                        filename=filename,
                    )

                    # Verify the URL was updated to the DB-backed pattern
                    expected_url = DB_FILE_URL_PATTERN.format(file_type=file_type)
                    url_attr = f"{file_type}_url"
                    actual_url = getattr(branding, url_attr)
                    assert actual_url == expected_url, (
                        f"Expected URL {expected_url!r}, got {actual_url!r}"
                    )

                # Retrieve the file in a new transaction
                async with session.begin():
                    svc2 = BrandingService(session)
                    result = await svc2.get_branding_file(file_type)

                    assert result is not None, (
                        f"get_branding_file({file_type!r}) returned None "
                        f"after store"
                    )

                    retrieved_data, retrieved_ct, retrieved_fn = result

                    # Round-trip: bytes must be identical
                    assert retrieved_data == file_data, (
                        f"Round-trip bytes mismatch for {file_type}: "
                        f"stored {len(file_data)} bytes, "
                        f"retrieved {len(retrieved_data)} bytes"
                    )

                    # Content type must match
                    assert retrieved_ct == content_type, (
                        f"Content type mismatch: stored {content_type!r}, "
                        f"retrieved {retrieved_ct!r}"
                    )

                    # Filename must match
                    assert retrieved_fn == filename, (
                        f"Filename mismatch: stored {filename!r}, "
                        f"retrieved {retrieved_fn!r}"
                    )

            finally:
                # Cleanup
                if branding_id is not None:
                    try:
                        async with session.begin():
                            await _cleanup_branding(session, branding_id)
                    except Exception:
                        pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())

    @PBT_SETTINGS
    @given(
        file_type=file_type_strategy,
        file_data=file_data_strategy,
        content_type=content_type_strategy,
        filename=filename_strategy,
    )
    def test_url_points_to_db_backed_endpoint(
        self, file_type, file_data, content_type, filename,
    ):
        """After storing a branding file, the record's _url field SHALL
        point to /api/v1/public/branding/file/{file_type}.

        **Validates: Requirements 2.1, 2.5**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            branding_id = None
            try:
                async with session.begin():
                    branding_id = await _create_branding_record(session)

                async with session.begin():
                    svc = BrandingService(session)
                    branding = await svc.store_branding_file(
                        file_type=file_type,
                        file_data=file_data,
                        content_type=content_type,
                        filename=filename,
                    )

                    url_attr = f"{file_type}_url"
                    actual_url = getattr(branding, url_attr)

                    # URL must follow the DB-backed pattern
                    assert actual_url == f"/api/v1/public/branding/file/{file_type}", (
                        f"URL {actual_url!r} does not match expected "
                        f"DB-backed endpoint pattern for {file_type}"
                    )

                    # URL must NOT contain a UUID (old disk-based pattern)
                    parts = actual_url.split("/")
                    last_segment = parts[-1]
                    assert last_segment == file_type, (
                        f"URL last segment {last_segment!r} should be "
                        f"the file_type {file_type!r}, not a UUID"
                    )

            finally:
                if branding_id is not None:
                    try:
                        async with session.begin():
                            await _cleanup_branding(session, branding_id)
                    except Exception:
                        pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())
