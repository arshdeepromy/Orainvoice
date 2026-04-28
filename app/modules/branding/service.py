"""Business logic for the platform branding module.

Provides:
- get_branding(): fetch the singleton branding row
- update_branding(): update branding fields
- get_powered_by_config(): branding subset for PDF/email footers
- is_white_label(): check if an org can remove Powered By
- store_branding_file(): store file bytes in BYTEA columns
- get_branding_file(): retrieve file bytes from BYTEA columns
- migrate_disk_files_to_db(): auto-migrate disk-based branding files to DB

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branding.models import PlatformBranding
from app.modules.branding.schemas import PoweredByConfig

logger = logging.getLogger(__name__)

# Valid file types for branding file storage
VALID_FILE_TYPES = {"logo", "dark_logo", "favicon"}

# Upload directory for legacy disk-based branding files
BRANDING_UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads")) / "branding"

# URL pattern for DB-backed branding file serving
DB_FILE_URL_PATTERN = "/api/v1/public/branding/file/{file_type}"


class BrandingService:
    """Service layer for platform branding operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_branding(self) -> PlatformBranding | None:
        """Return the singleton platform branding row."""
        result = await self._db.execute(
            select(PlatformBranding).order_by(PlatformBranding.created_at).limit(1)
        )
        return result.scalar_one_or_none()

    async def update_branding(self, **kwargs: object) -> PlatformBranding:
        """Update branding fields. Only non-None values are applied."""
        branding = await self.get_branding()
        if branding is None:
            raise ValueError("Platform branding not configured")

        fields = {k: v for k, v in kwargs.items() if v is not None}
        if not fields:
            return branding

        fields["updated_at"] = datetime.now(timezone.utc)
        await self._db.execute(
            update(PlatformBranding)
            .where(PlatformBranding.id == branding.id)
            .values(**fields)
        )
        await self._db.flush()
        # Re-fetch to get updated values
        result = await self._db.execute(
            select(PlatformBranding).where(PlatformBranding.id == branding.id)
        )
        return result.scalar_one()

    async def get_powered_by_config(
        self,
        org_white_label_enabled: bool = False,
    ) -> PoweredByConfig:
        """Return the branding subset used in PDF/email footers.

        If the org has white-label enabled, ``show_powered_by`` is False.
        """
        branding = await self.get_branding()
        if branding is None:
            return PoweredByConfig(
                platform_name="OraInvoice",
                show_powered_by=not org_white_label_enabled,
            )
        return PoweredByConfig(
            platform_name=branding.platform_name,
            logo_url=branding.logo_url,
            signup_url=branding.signup_url,
            website_url=branding.website_url,
            show_powered_by=not org_white_label_enabled,
        )

    async def store_branding_file(
        self,
        file_type: str,
        file_data: bytes,
        content_type: str,
        filename: str,
    ) -> PlatformBranding:
        """Store file bytes in the corresponding BYTEA column and update the URL.

        Args:
            file_type: One of "logo", "dark_logo", or "favicon".
            file_data: Processed image bytes to store.
            content_type: MIME type, e.g. "image/png".
            filename: Original filename.

        Returns:
            The updated PlatformBranding record.

        Raises:
            ValueError: If file_type is invalid or branding is not configured.
        """
        if file_type not in VALID_FILE_TYPES:
            raise ValueError(f"Invalid file_type: {file_type}. Must be one of {VALID_FILE_TYPES}")

        branding = await self.get_branding()
        if branding is None:
            raise ValueError("Platform branding not configured")

        # Build the DB-backed public URL
        public_url = DB_FILE_URL_PATTERN.format(file_type=file_type)

        # Map file_type to column names
        fields = {
            f"{file_type}_data": file_data,
            f"{file_type}_content_type": content_type,
            f"{file_type}_filename": filename,
            f"{file_type}_url": public_url,
            "updated_at": datetime.now(timezone.utc),
        }

        await self._db.execute(
            update(PlatformBranding)
            .where(PlatformBranding.id == branding.id)
            .values(**fields)
        )
        await self._db.flush()
        await self._db.refresh(branding)
        return branding

    async def get_branding_file(
        self, file_type: str
    ) -> tuple[bytes, str, str] | None:
        """Return (data, content_type, filename) or None if not stored.

        Args:
            file_type: One of "logo", "dark_logo", or "favicon".

        Returns:
            A tuple of (file_data, content_type, filename) or None if the
            BYTEA column is NULL.
        """
        if file_type not in VALID_FILE_TYPES:
            return None

        branding = await self.get_branding()
        if branding is None:
            return None

        data = getattr(branding, f"{file_type}_data", None)
        if data is None:
            return None

        ct = getattr(branding, f"{file_type}_content_type", None) or "application/octet-stream"
        fn = getattr(branding, f"{file_type}_filename", None) or f"{file_type}.bin"

        return (data, ct, fn)

    async def migrate_disk_files_to_db(self) -> dict:
        """Auto-migrate existing disk-based branding files to DB. Idempotent.

        For each file type (logo, dark_logo, favicon):
        - If the _url points to a disk-based file (not already a DB-backed URL)
          and the _data column is NULL, read the file from disk and store it.
        - If the disk file is missing, log a warning and skip.
        - If _data is already populated, skip (idempotent).

        Returns:
            A dict with keys: migrated (int), skipped (int), warnings (list[str]).
        """
        branding = await self.get_branding()
        if branding is None:
            logger.info("No branding record found — nothing to migrate")
            return {"migrated": 0, "skipped": 0, "warnings": []}

        migrated = 0
        skipped = 0
        warnings: list[str] = []

        for file_type in VALID_FILE_TYPES:
            data_col = f"{file_type}_data"
            url_col = f"{file_type}_url"
            ct_col = f"{file_type}_content_type"
            fn_col = f"{file_type}_filename"

            # Skip if BYTEA already populated
            existing_data = getattr(branding, data_col, None)
            if existing_data is not None:
                skipped += 1
                logger.debug("Skipping %s — already migrated", file_type)
                continue

            # Check if there's a URL pointing to a disk file
            url_value = getattr(branding, url_col, None)
            if not url_value:
                skipped += 1
                continue

            # If URL already points to the DB-backed endpoint, skip
            db_url = DB_FILE_URL_PATTERN.format(file_type=file_type)
            if db_url in url_value:
                skipped += 1
                continue

            # Extract the filename from the URL (last path segment)
            # URL format: {proto}://{host}/api/v1/public/branding/file/{uuid_filename}
            try:
                file_id = url_value.rstrip("/").split("/")[-1]
            except (AttributeError, IndexError):
                msg = f"Could not parse filename from URL for {file_type}: {url_value}"
                logger.warning(msg)
                warnings.append(msg)
                skipped += 1
                continue

            # Read the file from disk
            disk_path = BRANDING_UPLOAD_DIR / file_id
            if not disk_path.is_file():
                msg = f"Disk file missing for {file_type}: {disk_path}"
                logger.warning(msg)
                warnings.append(msg)
                skipped += 1
                continue

            try:
                file_bytes = disk_path.read_bytes()
            except OSError as exc:
                msg = f"Failed to read disk file for {file_type}: {exc}"
                logger.warning(msg)
                warnings.append(msg)
                skipped += 1
                continue

            # Determine MIME type from file extension
            mime_type, _ = mimetypes.guess_type(file_id)
            if mime_type is None:
                mime_type = "application/octet-stream"

            # Store in DB
            new_url = DB_FILE_URL_PATTERN.format(file_type=file_type)
            fields = {
                data_col: file_bytes,
                ct_col: mime_type,
                fn_col: file_id,
                url_col: new_url,
                "updated_at": datetime.now(timezone.utc),
            }

            await self._db.execute(
                update(PlatformBranding)
                .where(PlatformBranding.id == branding.id)
                .values(**fields)
            )
            await self._db.flush()
            migrated += 1
            logger.info("Migrated %s from disk to DB (%d bytes)", file_type, len(file_bytes))

        # Refresh the branding object if any changes were made
        if migrated > 0:
            await self._db.refresh(branding)

        result = {"migrated": migrated, "skipped": skipped, "warnings": warnings}
        logger.info("Branding migration result: %s", result)
        return result

    @staticmethod
    def is_white_label(
        white_label_enabled: bool,
        subscription_plan: str | None = None,
    ) -> bool:
        """Check whether an org qualifies for white-label (no Powered By).

        Only Enterprise-tier orgs with ``white_label_enabled=True`` qualify.
        """
        enterprise_plans = {"enterprise", "Enterprise", "ENTERPRISE"}
        if subscription_plan not in enterprise_plans:
            return False
        return white_label_enabled
