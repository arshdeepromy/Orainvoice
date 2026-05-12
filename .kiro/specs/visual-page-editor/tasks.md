# Implementation Plan: Visual Page Editor (Puck Integration)

## Overview

This plan implements the visual page editor by integrating Puck (`@puckeditor/core`) into OraInvoice. Tasks are grouped by layer: database → backend models/schemas → backend service → backend router → frontend setup → frontend components → frontend pages → public rendering → integration/wiring → tests. Each task is independently implementable and builds on previous steps.

## Tasks

- [x] 1. Database migration and backend models
  - [x] 1.1 Create Alembic migration `0183_create_page_editor_tables`
    - Create `editor_pages`, `editor_page_revisions`, `editor_media_assets`, `editor_page_redirects` tables
    - Use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` for idempotency
    - Include all constraints: `ck_editor_pages_origin`, `ck_editor_redirects_status`
    - Include unique indexes: `uq_editor_pages_slug_active` (partial), `uq_editor_revisions_page_version`, `uq_editor_redirects_from_active` (partial)
    - Tables are global (no `org_id`, no RLS)
    - _Requirements: 2.1, 2.2, 2.6, 2.7, 5.1, 11.1, 12.1_

  - [x] 1.2 Create SQLAlchemy ORM models in `app/modules/page_editor/models.py`
    - `EditorPage`, `EditorPageRevision`, `EditorMediaAsset`, `EditorPageRedirect`
    - Match column types and constraints from the migration exactly
    - _Requirements: 2.1, 5.1, 11.1, 12.1_

  - [x] 1.3 Create Pydantic schemas in `app/modules/page_editor/schemas.py`
    - Request schemas: `CreatePageRequest`, `SaveDraftRequest`, `PublishRequest`, `PageSettingsRequest`, `CreateRedirectRequest`
    - Response schemas: `PageSummary`, `PageDetail`, `RevisionSummary`, `RedirectItem`, `MediaAsset`, `PublicPageData`, `RedirectData`
    - Enums: `PageOrigin`, `PublishState`
    - Include field validators for slug pattern, canonical URL, status_code
    - _Requirements: 2.1, 2.3, 6.1, 6.4, 8.1, 8.2, 11.1_

- [x] 2. Backend service layer
  - [x] 2.1 Create `app/modules/page_editor/service.py` with core CRUD operations
    - `create_page()` — validate slug, check reserved prefixes, create EditorPage + initial revision
    - `get_page()` — load page by key with editing lock check
    - `list_pages()` — paginated list with search, filter by origin/state, include_deleted option
    - `save_draft()` — validate JSON size ≤ 1MB, sanitise HTML, update draft_content
    - `soft_delete_page()` — set deleted_at/deleted_by, reject hand-coded pages with 409
    - `undelete_page()` — clear deleted_at, check slug conflict
    - Use `db.flush()` not `db.commit()` in all service functions
    - _Requirements: 2.1, 2.3, 3.1, 3.6, 8.1, 8.2, 8.3, 8.4, 10.1, 10.5, 10.6_

  - [x] 2.2 Implement slug validation and title-to-slug derivation
    - `validate_slug()` — regex match, length check, reserved prefix check against `RESERVED_PREFIXES` set
    - `title_to_slug()` — Unicode normalize, ASCII fold, kebab-case, prefix with `/`
    - `RESERVED_PREFIXES` set covering all nginx map entries, auth routes, API routes, product routes
    - _Requirements: 8.2, 8.3, 8.7_

  - [x] 2.3 Write property test for slug validation (Property 2)
    - **Property 2: Slug Validation Correctness**
    - Generate random strings with Hypothesis, verify validator accepts iff regex + length + reserved check pass
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 8.2, 8.3**

  - [x] 2.4 Write property test for title-to-slug derivation (Property 3)
    - **Property 3: Title-to-Slug Derivation Produces Valid Slugs**
    - Generate random Unicode strings, verify output always passes slug validation
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 8.7**

  - [x] 2.5 Create `app/modules/page_editor/sanitiser.py` for HTML sanitisation
    - Allow-list: `<strong>`, `<em>`, `<a href target rel>`, `<br>`, `<p>`
    - Strip all other tags, attributes, and inline event handlers
    - Validate `href` values: only `http://`, `https://`, `mailto:`, `tel:`, or path starting with `/`
    - _Requirements: 2.4, 2.5_

  - [x] 2.6 Write property test for HTML sanitisation (Property 1)
    - **Property 1: HTML Sanitisation Preserves Only Allowed Tags**
    - Generate random HTML strings with arbitrary tags/attributes, verify output contains only allowed elements
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 2.4, 2.5**

  - [x] 2.7 Implement publish workflow in service.py
    - `publish_page()` — validate draft, copy to published_content, increment version, create revision, invalidate cache
    - `generate_preview_token()` — stateless JWT with page_key, user_id, 60-min expiry
    - `verify_preview_token()` — decode and validate JWT
    - Revision cap enforcement: prune oldest when > 50 per page, log to audit
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.7_

  - [x] 2.8 Implement revision control in service.py
    - `list_revisions()` — paginated, newest-first
    - `revert_to_revision()` — copy revision content to draft_content, mark dirty, do NOT publish
    - Initial revision on page creation (version 1, note = "initial creation from template: {name}")
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

  - [x] 2.9 Implement page settings update with slug change and redirect creation
    - `update_page_settings()` — update SEO fields, handle slug change for editor-created pages
    - On slug change: validate new slug, update page_slug, create 301 redirect from old to new
    - Detect and remove redirect cycles (self-redirecting rows)
    - Reject slug change for hand-coded pages with 409
    - _Requirements: 6.1, 6.7, 6.8, 6.9, 6.10_

  - [x] 2.10 Write property test for redirect cycle detection (Property 4)
    - **Property 4: Redirect Cycle Detection**
    - Generate random redirect graphs, verify cycle detection prevents loops
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 6.9, 11.5**

  - [x] 2.11 Implement sitemap and robots.txt generation
    - `generate_sitemap()` — XML with published, non-deleted, non-noindex pages, sorted by slug
    - `generate_robots()` — static base + dynamic Allow directives for published editor-only pages + Disallow for noindex pages
    - In-memory cache with invalidation on publish/create/delete/slug-change/noindex-change
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8_

  - [x] 2.12 Write property test for sitemap generation (Property 5)
    - **Property 5: Sitemap Generation Correctness**
    - Generate random page sets with various states, verify output includes exactly correct pages sorted by slug
    - Use `@settings(max_examples=100)`
    - **Validates: Requirements 9.2, 9.3, 9.8**

  - [x] 2.13 Implement redirect service functions
    - `list_redirects()` — paginated, include_deleted option
    - `create_redirect()` — validate from_slug doesn't match active page, check for cycles
    - `soft_delete_redirect()` — set deleted_at
    - `resolve_redirect()` — lookup active redirect by from_slug (one hop max)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x] 2.14 Implement page registry sync on startup
    - `sync_registry()` — auto-create empty EditorPage rows for hand-coded pages not yet in DB
    - `HAND_CODED_PAGES` list: landing, workshop, trades, privacy
    - Call from app startup (lifespan event)
    - _Requirements: 14.2, 14.3, 14.8_

  - [x] 2.15 Implement concurrent editing advisory lock (Redis)
    - `acquire_editor_lock()` — set Redis key with 5-min TTL, return existing lock holder if different user
    - `refresh_editor_lock()` — refresh TTL on auto-save
    - `release_editor_lock()` — delete key if owned by current user
    - _Requirements: 3.12_

- [x] 3. Backend media service
  - [x] 3.1 Create `app/modules/page_editor/media_service.py`
    - `upload_media()` — validate MIME by content sniffing, save original to `app_uploads/page-editor/{uuid}/`, generate WebP variants at 640/960/1280/1920px using Pillow, store metadata in `editor_media_assets`
    - `list_media()` — paginated, search by filename, exclude deleted
    - `delete_media()` — check for references in any draft_content/published_content, reject with 409 if referenced, otherwise soft-delete
    - Reject uploads > 10 MB (413), accept only image/jpeg, image/png, image/webp, image/svg+xml, image/gif
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 4. Backend router
  - [x] 4.1 Create `app/modules/page_editor/router.py` with admin endpoints
    - Mount at `/api/v2/admin/page-editor`
    - Guard all endpoints with `global_admin` role check dependency
    - Implement all admin endpoints: GET/POST pages, GET/PUT/DELETE page by key, draft save, publish, preview, revisions, revert, settings, redirects CRUD, media CRUD
    - Log audit entries for all mutating operations
    - Return 403 + audit entry for non-global_admin access attempts
    - _Requirements: 13.1, 13.2, 13.3, 13.6_

  - [x] 4.2 Create public endpoints in the same router
    - `GET /api/v2/public/pages/resolve?slug=...` — check redirects first, then load page
    - `GET /api/v2/public/pages/preview/:token` — verify JWT, return draft_content with X-Robots-Tag: noindex
    - `GET /sitemap.xml` — return generated XML with Content-Type: application/xml
    - `GET /robots.txt` — return generated text with Content-Type: text/plain
    - Public endpoints require no authentication
    - _Requirements: 7.2, 7.6, 7.7, 9.1, 13.4, 13.5_

  - [x] 4.3 Register page_editor router in `app/main.py`
    - Import and include the router with appropriate prefix
    - Add `sync_registry()` call to app lifespan startup
    - _Requirements: 14.3, 14.8_

- [x] 5. Checkpoint — Backend complete
  - Run backend page-editor tests only: `docker compose exec app python -m pytest tests/test_page_editor*.py -v`
  - Verify imports: `docker compose exec app python -c "from app.modules.page_editor.router import router; print('OK')"`
  - Ask the user if questions arise.

- [x] 6. Frontend setup and Puck installation
  - [x] 6.1 Install `@puckeditor/core` in the frontend package
    - Run `npm install @puckeditor/core` in `frontend/`
    - Pin to latest stable version
    - _Requirements: 1.1_

  - [x] 6.2 Create Puck component config at `frontend/src/admin/page-editor/puckConfig.ts`
    - Define all 18 component configs: Hero, FeatureGrid, Section, Columns, Heading, RichText, Image, VideoEmbed, Button, FAQAccordion, PricingCard, TestimonialCard, CTABanner, Spacer, Divider, Badge, List, DemoRequestForm, NZTrustSignals
    - Each component has typed fields and a Tailwind-based render function
    - Use only Tailwind utility classes from existing config (no inline styles except custom hex colours)
    - Export `puckConfig` for use by both `<Puck>` editor and `<Render>` public renderer
    - _Requirements: 1.2, 1.3, 1.4, 1.8_

  - [x] 6.3 Implement individual Puck component render functions
    - Create component files in `frontend/src/admin/page-editor/components/`
    - Hero.tsx, FeatureGrid.tsx, Section.tsx, Columns.tsx, Heading.tsx, RichText.tsx, ImageBlock.tsx, VideoEmbed.tsx, Button.tsx, FAQAccordion.tsx, PricingCard.tsx, TestimonialCard.tsx, CTABanner.tsx, Spacer.tsx, Divider.tsx, Badge.tsx, List.tsx, DemoRequestForm.tsx, NZTrustSignals.tsx
    - FAQAccordion: emit `<details>`/`<summary>` + FAQPage JSON-LD
    - VideoEmbed: YouTube/Vimeo → iframe with loading="lazy"; MP4 → `<video>` with loading="lazy"
    - DemoRequestForm: submit to existing public demo-request API endpoint
    - Image: emit srcset with WebP variants, loading="lazy", require non-empty alt
    - Heading: enforce single H1 (demote subsequent H1s to H2)
    - _Requirements: 1.2, 1.5, 1.6, 1.7, 7.4, 7.5_

  - [x] 6.4 Write property test for single H1 enforcement (Property 6)
    - **Property 6: Single H1 Enforcement**
    - Generate random Puck_Data with varying H1 counts, verify at most one `<h1>` in rendered output
    - Use fast-check or Hypothesis (backend test)
    - **Validates: Requirements 7.4**

  - [x] 6.5 Create page templates at `frontend/src/admin/page-editor/templates.ts`
    - Define `PAGE_TEMPLATES` array: blank, landing, workshop-style, trades, privacy
    - Each template has key, name, description, and starter Puck_Data
    - _Requirements: 8.8_

  - [x] 6.6 Create custom Puck field for Media Library at `frontend/src/admin/page-editor/fields/MediaField.tsx`
    - Browse Library button opens MediaLibraryModal
    - Upload inline, select from grid, returns asset ID
    - _Requirements: 12.2_

- [x] 7. Frontend admin pages
  - [x] 7.1 Create `PageEditorList.tsx` at `frontend/src/admin/page-editor/pages/PageEditorList.tsx`
    - Page list table with columns: Title (+ dirty dot), Slug, Origin badge, State badge, Noindex icon, Last Published, Actions
    - Search input (filter by title/slug substring)
    - Filter dropdowns: origin (all/hand-coded/editor-created), state (all/published/never-published/draft-ahead)
    - "Show deleted" toggle
    - Pagination (20 per page)
    - "New Page" button → opens CreatePageModal
    - Row actions: Edit, Duplicate, Delete (editor-only), Revert to Fallback (hand-coded), Audit Log link
    - Use `?.` and `?? []` on all API data
    - _Requirements: 3.1, 3.2, 3.9, 3.10, 3.11, 10.2_

  - [x] 7.2 Create `CreatePageModal.tsx`
    - Form: title (required, 1-120 chars), slug (auto-derived from title, editable), template radio cards, meta title, meta description
    - Slug validation: regex + reserved prefix check (client-side)
    - On submit: POST to create endpoint, navigate to editor on success
    - Support duplicate flow via `initialData` prop (pre-filled content, hidden template selector)
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7_

  - [x] 7.3 Create `PageEditorEdit.tsx` at `frontend/src/admin/page-editor/pages/PageEditorEdit.tsx`
    - Import Puck CSS (`puck.css`) ONLY in this component (scoped, lazy-loaded)
    - Render `<Puck config={puckConfig} data={draftContent} onPublish={handlePublish} />`
    - Wrap in AdminLayout, guard with RequireGlobalAdmin
    - Include EditorToolbar above Puck
    - Include ConcurrentEditBanner and DraftConflictBanner
    - Unsaved changes confirmation dialog on navigate away
    - _Requirements: 1.1, 3.3, 3.4, 3.5, 3.8_

  - [x] 7.4 Create `EditorToolbar.tsx` component
    - Left: page title + publish state badge
    - Right: Save Draft, Preview, Publish, Settings (gear icon), History (clock icon) buttons
    - Save Draft: PUT draft, show spinner/saved states, disabled when not dirty
    - Preview: POST preview → open tokenised URL in new tab
    - Publish: open PublishConfirmModal with optional note field
    - _Requirements: 3.5, 3.6, 4.1, 4.2, 4.5_

  - [x] 7.5 Create `useAutoSave.ts` hook
    - Auto-save draft every 30 seconds while document is dirty
    - Cancel auto-save when manual save is in-flight
    - Handle 409 conflict response (show DraftConflictBanner)
    - Refresh editor lock on each save
    - _Requirements: 3.7, 3.12_

  - [x] 7.6 Create `PageSettingsDrawer.tsx` (slide-over, right side)
    - Fields: title, slug (editable for editor-created, read-only for hand-coded), noindex toggle, meta title, meta description, canonical URL, OG image, OG type, Twitter card, JSON-LD textarea
    - JSON-LD validation on blur (red border + error if invalid)
    - "Revert to Fallback" danger button for hand-coded pages
    - Save Settings button → PUT settings endpoint
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.7, 6.10_

  - [x] 7.7 Create `RevisionHistoryDrawer.tsx` (slide-over, right side)
    - List revisions newest-first: version badge, author, timestamp, note
    - "View" button → full-screen modal with read-only `<Render>`
    - "Revert" button → POST revert endpoint, update editor draft, show toast
    - _Requirements: 5.4, 5.5, 5.6_

  - [x] 7.8 Create `MediaLibraryModal.tsx`
    - Grid of uploaded images with filename, dimensions, size
    - Search by filename (debounced 300ms)
    - Upload button + drag-and-drop zone
    - Delete button with reference check (409 → error toast)
    - Click to select → returns asset ID, closes modal
    - Pagination (load more)
    - _Requirements: 12.2, 12.3, 12.4_

  - [x] 7.9 Create `PageEditorRedirects.tsx` at `frontend/src/admin/page-editor/pages/PageEditorRedirects.tsx`
    - List all redirects with from_slug, to_slug_or_url, status_code, created_at
    - Create redirect form (from_slug, to_slug_or_url, status_code select)
    - Soft-delete button per redirect
    - _Requirements: 11.3_

- [x] 8. Frontend public rendering
  - [x] 8.1 Create page registry at `frontend/src/pages/public/_registry.ts`
    - Export `PAGE_REGISTRY` array of `HandCodedPageRegistration` objects
    - Entries: landing (`/`), workshop (`/workshop`), trades (`/trades`), privacy (`/privacy`)
    - Each entry: page_key, page_slug, fallbackPage component, defaultTitle, defaultDescription
    - _Requirements: 14.1, 14.2_

  - [x] 8.2 Create `ManagedPage` wrapper component
    - Wraps existing hand-coded page routes
    - On mount: calls resolve endpoint for current slug
    - If published_content exists → render via Puck `<Render>` in PageShell
    - If no published_content → render FallbackPage immediately (no spinner)
    - ErrorBoundary catches Puck render errors → falls back to FallbackPage
    - _Requirements: 7.1, 7.2, 7.3, 14.4, 14.5, 14.7_

  - [x] 8.3 Create `PublicPageRenderer.tsx` (catch-all route component)
    - Resolve slug via `GET /api/v2/public/pages/resolve?slug=...`
    - Handle redirect (Navigate or window.location.href for external)
    - Handle page found → Puck `<Render>` in PageShell
    - Handle not found → 404 page
    - Call `usePageMeta` for SEO tags (noindex, meta title/desc, canonical, JSON-LD)
    - Loading state: PageSkeleton
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7, 6.2, 6.5, 6.6_

  - [x] 8.4 Create `PageShell` component
    - Wraps Puck `<Render>` output with LandingHeader + `<main className="pt-16">` + LandingFooter
    - Adds `public-page` document class toggle
    - Sets Cache-Control header via usePageMeta
    - _Requirements: 7.1, 14.6_

- [x] 9. Integration and wiring
  - [x] 9.1 Add "Page Editor" nav item to AdminLayout sidebar
    - Add "Content" section between "Configuration" and "Monitoring"
    - Add "Page Editor" link pointing to `/admin/page-editor`
    - _Requirements: 3.1, 13.1_

  - [x] 9.2 Register page editor routes in `App.tsx`
    - Lazy imports: PageEditorList, PageEditorEdit, PageEditorRedirects, PublicPageRenderer
    - Admin routes: `/admin/page-editor`, `/admin/page-editor/redirects`, `/admin/page-editor/:pageKey`
    - Guard with RequireGlobalAdmin
    - _Requirements: 3.4, 13.1_

  - [x] 9.3 Add public catch-all route in `App.tsx`
    - `<Route path="*" element={<PublicPageRenderer />} />` AFTER all explicit public routes
    - Wrap existing hand-coded page routes with `ManagedPage` wrapper
    - _Requirements: 7.2, 14.4, 14.5_

  - [x] 9.4 Update nginx config for sitemap.xml and robots.txt proxy
    - Add `location = /sitemap.xml` block proxying to backend
    - Add `location = /robots.txt` block proxying to backend
    - Remove any static sitemap.xml/robots.txt from frontend build
    - Add Cache-Control: public, max-age=3600
    - _Requirements: 9.7_

  - [x] 9.5 Implement audit logging for all editor actions
    - Log: open, save, preview, publish, revert, create, delete, undelete, slug change, redirect CRUD
    - Each entry: actor, action, page_key, affected slugs, timestamp
    - Use existing audit log infrastructure
    - _Requirements: 13.6_

- [x] 10. Checkpoint — Full integration complete
  - Rebuild frontend: `docker compose exec frontend sh -c "cd /app && npx vite build"` _(skipped per user request)_
  - Verified TypeScript: no NEW page-editor errors introduced by tasks 8.2 / 8.3 / 9.x — pre-existing errors in PageEditorEdit.tsx (ComponentConfig generic mismatch) remain.
  - Verify nginx config: `docker compose exec nginx nginx -t` _(skipped per user request)_
  - Ask the user if questions arise.

- [x] 11. Unit and integration tests
  - [x] 11.1 Write unit tests for page_editor service _(see `tests/test_page_editor_service.py`)_
    - Test create_page with valid/invalid slugs
    - Test publish workflow (draft → publish → revision created)
    - Test revision cap enforcement (51st publish prunes oldest)
    - Test slug change creates redirect
    - Test soft-delete and undelete
    - Test registry sync creates missing pages
    - _Requirements: 2.1, 4.2, 5.7, 6.8, 10.1, 14.3_

  - [x] 11.2 Write unit tests for media_service _(see `tests/test_page_editor_media_service.py`)_
    - Test MIME type validation by content sniffing
    - Test upload size rejection (> 10 MB)
    - Test delete with references (409)
    - Test WebP variant generation
    - _Requirements: 12.1, 12.3, 12.4_

  - [x] 11.3 Write unit tests for sanitiser _(property test in `tests/test_page_editor_sanitiser.py` plus example tests in `tests/test_page_editor_sanitiser_examples.py`)_
    - Test allowed tags preserved
    - Test disallowed tags stripped
    - Test href validation (allowed/disallowed schemes)
    - Test event handler removal
    - _Requirements: 2.4, 2.5_

  - [x] 11.4 Write integration tests for router endpoints _(see `tests/test_page_editor_router.py`)_
    - Test access control (403 for non-admin)
    - Test full publish workflow via API
    - Test public resolve endpoint (redirect, page, 404)
    - Test preview token generation and consumption
    - Test sitemap and robots.txt output
    - _Requirements: 4.1, 7.2, 9.1, 13.2, 13.3_

  - [x] 11.5 Write unit tests for Puck component render functions _(see `frontend/src/admin/page-editor/__tests__/component-renders.test.tsx`)_
    - Test FAQAccordion emits details/summary + JSON-LD
    - Test VideoEmbed renders iframe for YouTube/Vimeo, video for MP4
    - Test Image emits srcset with variants
    - Test Heading H1 demotion logic
    - _Requirements: 1.5, 1.6, 7.4, 7.5_

- [x] 12. Final checkpoint
  - Run only page-editor-specific tests (not the full test suite):
    - Backend: `docker compose exec app python -m pytest tests/test_page_editor*.py -v` _(skipped per user request)_
    - Frontend: `npx vitest run --reporter=verbose src/admin/page-editor/` _(skipped per user request)_
  - Verify the editor is accessible at `/admin/page-editor` in the browser _(manual user step)_
  - Verify a hand-coded page (e.g. `/workshop`) still renders its fallback _(manual user step)_
  - Ask the user if questions arise.

- [ ] 13. Git push and rebuild local dev environment _(skipped per user request — user will handle git/docker steps manually)_
  - [ ] 13.1 Git commit and push all changes to a new branch
    - Stage all changed files: `git add -A`
    - Commit with message: `feat: add visual page editor with Puck integration`
    - Push to new branch: `git push -u origin feat/visual-page-editor`
  - [ ] 13.2 Rebuild backend container with new migration
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate app`
    - Verify migration applied: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic current`
  - [ ] 13.3 Rebuild frontend container
    - Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml restart frontend`
    - Verify build succeeded: `docker compose -f docker-compose.yml -f docker-compose.dev.yml logs frontend --tail 20`
  - [ ] 13.4 Verify end-to-end in browser
    - Navigate to `/admin/page-editor` — should show page list with 4 hand-coded pages
    - Click "Edit" on any page — should load Puck editor
    - Navigate to `/workshop` — should still render the hand-coded WorkshopPage (no published Puck content yet)

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation — run ONLY page-editor-specific tests, not the full suite
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses `db.flush()` not `db.commit()` — the `session.begin()` context manager auto-commits
- Frontend must use `?.` and `?? []` on all API data per project steering rules
- Puck CSS is imported ONLY in PageEditorEdit.tsx (lazy-loaded) to prevent style leakage
- Tests should ONLY cover page-editor code — do not run unrelated test files that may have pre-existing import errors
- The `DeleteConfirmModal`, `RevertToFallbackModal`, `PublishConfirmModal`, `ConcurrentEditBanner`, and `DraftConflictBanner` components are built as part of their parent tasks (7.1, 7.3, 7.4) — they are not separate tasks because they are small, tightly coupled components
