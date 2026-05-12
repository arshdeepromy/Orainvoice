"""Create page editor tables.

Creates the editor_pages, editor_page_revisions, editor_media_assets,
and editor_page_redirects tables for the visual page editor feature.
All tables are global (no org_id, no RLS).

Revision ID: 0183
Revises: 0182
Create Date: 2026-05-10

Requirements: 2.1, 2.2, 2.6, 2.7, 5.1, 11.1, 12.1
"""

from __future__ import annotations

from alembic import op

revision: str = "0183"
down_revision: str = "0182"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # editor_pages — one row per managed page
    op.execute("""
        CREATE TABLE IF NOT EXISTS editor_pages (
            page_key        VARCHAR(120)    PRIMARY KEY,
            page_origin     VARCHAR(20)     NOT NULL,
            page_slug       VARCHAR(80)     NOT NULL,
            title           VARCHAR(120)    NOT NULL DEFAULT '',
            draft_content   JSONB,
            published_content JSONB,
            published_version INTEGER,
            draft_updated_at  TIMESTAMPTZ,
            draft_updated_by  UUID,
            published_at    TIMESTAMPTZ,
            published_by    UUID,
            seo             JSONB           NOT NULL DEFAULT '{}'::jsonb,
            noindex         BOOLEAN         NOT NULL DEFAULT false,
            deleted_at      TIMESTAMPTZ,
            deleted_by      UUID,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
            CONSTRAINT ck_editor_pages_origin CHECK (page_origin IN ('hand-coded', 'editor-created'))
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_editor_pages_slug_active
            ON editor_pages (page_slug) WHERE deleted_at IS NULL;
    """)

    # editor_page_revisions — immutable publish snapshots
    op.execute("""
        CREATE TABLE IF NOT EXISTS editor_page_revisions (
            id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            page_key        VARCHAR(120)    NOT NULL REFERENCES editor_pages(page_key),
            version         INTEGER         NOT NULL,
            content         JSONB           NOT NULL,
            published_at    TIMESTAMPTZ,
            published_by    UUID,
            note            VARCHAR(500),
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_editor_revisions_page_version
            ON editor_page_revisions (page_key, version);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_editor_revisions_page_key
            ON editor_page_revisions (page_key, version DESC);
    """)

    # editor_media_assets — uploaded images with variant metadata
    op.execute("""
        CREATE TABLE IF NOT EXISTS editor_media_assets (
            id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            filename        VARCHAR(255)    NOT NULL,
            original_path   VARCHAR(500)    NOT NULL,
            content_type    VARCHAR(100)    NOT NULL,
            size_bytes      INTEGER         NOT NULL,
            width           INTEGER,
            height          INTEGER,
            variants        JSONB           NOT NULL DEFAULT '{}'::jsonb,
            uploaded_by     UUID,
            uploaded_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            deleted_at      TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_editor_media_uploaded
            ON editor_media_assets (uploaded_at DESC) WHERE deleted_at IS NULL;
    """)

    # editor_page_redirects — slug redirects (301/302)
    op.execute("""
        CREATE TABLE IF NOT EXISTS editor_page_redirects (
            id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            from_slug       VARCHAR(80)     NOT NULL,
            to_slug_or_url  VARCHAR(500)    NOT NULL,
            status_code     INTEGER         NOT NULL DEFAULT 301,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
            created_by      UUID,
            deleted_at      TIMESTAMPTZ,
            CONSTRAINT ck_editor_redirects_status CHECK (status_code IN (301, 302))
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_editor_redirects_from_active
            ON editor_page_redirects (from_slug) WHERE deleted_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS editor_page_redirects CASCADE;")
    op.execute("DROP TABLE IF EXISTS editor_media_assets CASCADE;")
    op.execute("DROP TABLE IF EXISTS editor_page_revisions CASCADE;")
    op.execute("DROP TABLE IF EXISTS editor_pages CASCADE;")
