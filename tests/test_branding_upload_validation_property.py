"""Property-based tests for branding upload input validation.

Feature: file-storage-replication, Property 2: Branding upload input validation

For any file upload attempt, if the file size exceeds the limit (2 MB for logos,
512 KB for favicons) the upload SHALL be rejected with HTTP 413, and if the
content type is not in the allowed set the upload SHALL be rejected with HTTP 415.
Files within limits and with allowed types SHALL be accepted.

**Validates: Requirements 1.5, 1.6**

Uses Hypothesis to generate random file sizes (0 to 5 MB) and random MIME types,
then verifies accept/reject matches the validation rules in the router's
``_handle_branding_upload`` function.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
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

from app.modules.branding.router import (
    _handle_branding_upload,
    ALLOWED_FAVICON_TYPES,
    ALLOWED_IMAGE_TYPES,
    MAX_FAVICON_SIZE,
    MAX_LOGO_SIZE,
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
# Constants
# ---------------------------------------------------------------------------

# All valid content types across both logo and favicon
ALL_VALID_CONTENT_TYPES = list(set(ALLOWED_IMAGE_TYPES.keys()) | set(ALLOWED_FAVICON_TYPES.keys()))

# Some invalid content types for testing rejection
INVALID_CONTENT_TYPES = [
    "text/plain",
    "application/json",
    "application/pdf",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "video/mp4",
    "audio/mpeg",
    "application/octet-stream",
    "text/html",
    "multipart/form-data",
]

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# File size: 0 to 5 MB (covers both within-limit and over-limit cases)
file_size_strategy = st.integers(min_value=0, max_value=5 * 1024 * 1024)

# Content type: mix of valid and invalid types
content_type_strategy = st.sampled_from(ALL_VALID_CONTENT_TYPES + INVALID_CONTENT_TYPES)

# Upload kind: logo or favicon (determines size limit and allowed types)
upload_kind_strategy = st.sampled_from(["logo", "favicon"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upload_file(content: bytes, content_type: str, filename: str = "test.bin") -> UploadFile:
    """Create a FastAPI UploadFile from raw bytes and content type."""
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},
    )


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


async def _create_branding_record(session: AsyncSession) -> uuid.UUID:
    """Create a minimal PlatformBranding record for testing."""
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
# Property 2: Branding upload input validation
# Feature: file-storage-replication, Property 2: Branding upload input validation
# **Validates: Requirements 1.5, 1.6**
# ---------------------------------------------------------------------------


class TestBrandingUploadValidationProperty:
    """Property 2 — For any file upload attempt, if the file size exceeds
    the limit (2 MB for logos, 512 KB for favicons) the upload SHALL be
    rejected with HTTP 413, and if the content type is not in the allowed
    set the upload SHALL be rejected with HTTP 415. Files within limits
    and with allowed types SHALL be accepted."""

    @PBT_SETTINGS
    @given(
        file_size=file_size_strategy,
        content_type=content_type_strategy,
        upload_kind=upload_kind_strategy,
    )
    def test_upload_validation_matches_rules(
        self, file_size, content_type, upload_kind,
    ):
        """For any combination of file size, content type, and upload kind,
        the validation outcome SHALL match the expected rules:
        - Invalid content type → HTTP 415
        - Empty file (0 bytes) → HTTP 400
        - File too large → HTTP 413
        - Valid content type + non-empty + within size limit → accepted

        **Validates: Requirements 1.5, 1.6**
        """
        import asyncio

        async def _run():
            # Determine the allowed types and max size for this upload kind
            if upload_kind == "logo":
                allowed_types = ALLOWED_IMAGE_TYPES
                max_size = MAX_LOGO_SIZE
                max_dim = 512
                label = "logo"
                file_type = "logo"
            else:
                allowed_types = ALLOWED_FAVICON_TYPES
                max_size = MAX_FAVICON_SIZE
                max_dim = 128
                label = "favicon"
                file_type = "favicon"

            # Determine expected outcome
            is_valid_type = content_type in allowed_types
            is_empty = file_size == 0
            is_too_large = file_size > max_size

            # Generate file content of the requested size
            content = b"\x89PNG" * (file_size // 4 + 1)  # PNG-like header padding
            content = content[:file_size]

            upload_file = _make_upload_file(content, content_type)

            if not is_valid_type:
                # Should reject with 415
                session, engine = await _make_session()
                try:
                    with pytest.raises(HTTPException) as exc_info:
                        await _handle_branding_upload(
                            file=upload_file,
                            db=session,
                            max_size=max_size,
                            allowed_types=allowed_types,
                            max_dim=max_dim,
                            label=label,
                            file_type=file_type,
                        )
                    assert exc_info.value.status_code == 415, (
                        f"Expected 415 for content_type={content_type!r}, "
                        f"got {exc_info.value.status_code}"
                    )
                finally:
                    await session.close()
                    await engine.dispose()

            elif is_empty:
                # Should reject with 400 (empty file)
                session, engine = await _make_session()
                try:
                    with pytest.raises(HTTPException) as exc_info:
                        await _handle_branding_upload(
                            file=upload_file,
                            db=session,
                            max_size=max_size,
                            allowed_types=allowed_types,
                            max_dim=max_dim,
                            label=label,
                            file_type=file_type,
                        )
                    assert exc_info.value.status_code == 400, (
                        f"Expected 400 for empty file, "
                        f"got {exc_info.value.status_code}"
                    )
                finally:
                    await session.close()
                    await engine.dispose()

            elif is_too_large:
                # Should reject with 413
                session, engine = await _make_session()
                try:
                    with pytest.raises(HTTPException) as exc_info:
                        await _handle_branding_upload(
                            file=upload_file,
                            db=session,
                            max_size=max_size,
                            allowed_types=allowed_types,
                            max_dim=max_dim,
                            label=label,
                            file_type=file_type,
                        )
                    assert exc_info.value.status_code == 413, (
                        f"Expected 413 for file_size={file_size} > max_size={max_size}, "
                        f"got {exc_info.value.status_code}"
                    )
                finally:
                    await session.close()
                    await engine.dispose()

            else:
                # Valid type, non-empty, within size limit → should be accepted
                # Need a real branding record in the DB for the store to succeed
                session, engine = await _make_session()
                branding_id = None
                try:
                    async with session.begin():
                        branding_id = await _create_branding_record(session)

                    async with session.begin():
                        result = await _handle_branding_upload(
                            file=upload_file,
                            db=session,
                            max_size=max_size,
                            allowed_types=allowed_types,
                            max_dim=max_dim,
                            label=label,
                            file_type=file_type,
                        )

                        # Should return a success dict with expected keys
                        assert isinstance(result, dict), (
                            f"Expected dict result for valid upload, got {type(result)}"
                        )
                        assert "url" in result, "Result should contain 'url' key"
                        assert "message" in result, "Result should contain 'message' key"
                        assert result["url"] == f"/api/v1/public/branding/file/{file_type}", (
                            f"Expected URL pattern, got {result['url']!r}"
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
