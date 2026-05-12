"""Pydantic v2 schemas for the visual page editor module.

Request schemas for page CRUD, draft saving, publishing, settings, and redirects.
Response schemas for page summaries, details, revisions, redirects, media, and public data.

Requirements: 2.1, 2.3, 6.1, 6.4, 8.1, 8.2, 11.1
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --- Enums ---


class PageOrigin(str, Enum):
    """Origin of a managed page."""

    hand_coded = "hand-coded"
    editor_created = "editor-created"


class PublishState(str, Enum):
    """Derived publish state for display in the page list."""

    never_published = "never-published"
    published = "published"
    draft_ahead = "draft-ahead"


# --- Request Schemas ---

_SLUG_PATTERN = re.compile(r"^/(?:[a-z0-9-]+)(?:/[a-z0-9-]+){0,2}$")


class CreatePageRequest(BaseModel):
    """Request body for creating a new editor page.

    Requirements: 8.1, 8.2
    """

    title: str = Field(..., min_length=1, max_length=120)
    page_slug: str = Field(..., max_length=80)
    template: str = Field(default="blank")
    content: dict | None = Field(
        default=None,
        description="Pre-filled Puck_Data for duplicate flow; overrides template.",
    )
    meta_title: str | None = Field(default=None, max_length=120)
    meta_description: str | None = Field(default=None, max_length=320)

    @field_validator("page_slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_PATTERN.match(v):
            raise ValueError(
                "Slug must match /segment or /seg/seg or /seg/seg/seg "
                "(lowercase alphanumeric and hyphens only)"
            )
        if len(v) > 80:
            raise ValueError("Slug must be at most 80 characters")
        return v


class SaveDraftRequest(BaseModel):
    """Request body for saving draft content.

    Requirements: 2.3
    """

    content: dict = Field(..., description="Puck_Data JSON")


class PublishRequest(BaseModel):
    """Request body for publishing a page."""

    note: str | None = Field(default=None, max_length=500)


class PageSettingsRequest(BaseModel):
    """Request body for updating page settings and SEO metadata.

    Requirements: 6.1, 6.4
    """

    title: str | None = Field(default=None, min_length=1, max_length=120)
    page_slug: str | None = Field(default=None, max_length=80)
    meta_title: str | None = Field(default=None, max_length=120)
    meta_description: str | None = Field(default=None, max_length=320)
    canonical: str | None = None
    noindex: bool | None = None
    og_image: str | None = None
    og_type: str | None = None
    twitter_card: str | None = None
    json_ld: list[dict] | None = None

    @field_validator("page_slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is not None:
            if not _SLUG_PATTERN.match(v):
                raise ValueError(
                    "Slug must match /segment or /seg/seg or /seg/seg/seg "
                    "(lowercase alphanumeric and hyphens only)"
                )
            if len(v) > 80:
                raise ValueError("Slug must be at most 80 characters")
        return v

    @field_validator("canonical")
    @classmethod
    def validate_canonical(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("Canonical URL must be a fully-qualified https:// URL")
        return v


class CreateRedirectRequest(BaseModel):
    """Request body for creating a slug redirect.

    Requirements: 11.1
    """

    from_slug: str = Field(..., max_length=80)
    to_slug_or_url: str = Field(..., max_length=500)
    status_code: int = Field(default=301)

    @field_validator("from_slug")
    @classmethod
    def validate_from_slug(cls, v: str) -> str:
        if not _SLUG_PATTERN.match(v):
            raise ValueError(
                "from_slug must match /segment or /seg/seg or /seg/seg/seg "
                "(lowercase alphanumeric and hyphens only)"
            )
        return v

    @field_validator("status_code")
    @classmethod
    def validate_status_code(cls, v: int) -> int:
        if v not in (301, 302):
            raise ValueError("status_code must be 301 or 302")
        return v


# --- Response Schemas ---


class EditingLock(BaseModel):
    """Advisory lock info when another user is editing the same page."""

    user_email: str
    opened_at: datetime


class PageSummary(BaseModel):
    """Summary representation of a page for list views.

    Requirements: 2.1
    """

    model_config = ConfigDict(from_attributes=True)

    page_key: str
    title: str
    page_slug: str
    page_origin: PageOrigin
    publish_state: PublishState
    noindex: bool = False
    published_at: datetime | None = None
    draft_updated_at: datetime | None = None
    published_version: int | None = None
    deleted_at: datetime | None = None


class PageDetail(BaseModel):
    """Full page representation including content and SEO for the editor.

    Requirements: 2.1
    """

    model_config = ConfigDict(from_attributes=True)

    page_key: str
    title: str
    page_slug: str
    page_origin: PageOrigin
    draft_content: dict | None = None
    published_content: dict | None = None
    published_version: int | None = None
    published_at: datetime | None = None
    published_by: uuid.UUID | None = None
    draft_updated_at: datetime | None = None
    draft_updated_by: uuid.UUID | None = None
    seo: dict | None = None
    noindex: bool = False
    deleted_at: datetime | None = None
    editing_lock: EditingLock | None = None


class RevisionSummary(BaseModel):
    """Summary of a page revision for the history panel."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    published_at: datetime | None = None
    published_by: uuid.UUID | None = None
    note: str | None = None
    created_at: datetime


class RedirectItem(BaseModel):
    """Redirect entry for the redirects management panel.

    Requirements: 11.1
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_slug: str
    to_slug_or_url: str
    status_code: int
    created_at: datetime
    created_by: uuid.UUID | None = None
    deleted_at: datetime | None = None


class MediaAsset(BaseModel):
    """Uploaded media asset for the media library."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    original_path: str
    content_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    variants: dict = Field(default_factory=dict)
    uploaded_at: datetime


class PublicPageData(BaseModel):
    """Public-facing page data returned by the resolve endpoint."""

    model_config = ConfigDict(from_attributes=True)

    page_key: str
    page_slug: str
    title: str
    published_content: dict | None = None
    seo: dict | None = None
    noindex: bool = False
    page_origin: PageOrigin


class RedirectData(BaseModel):
    """Redirect response for the public catch-all route."""

    to_slug_or_url: str
    status_code: int
