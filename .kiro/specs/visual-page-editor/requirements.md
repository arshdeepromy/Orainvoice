# Requirements Document

## Introduction

OraInvoice currently exposes four hand-coded public marketing pages — `LandingPage.tsx`, `WorkshopPage.tsx`, `TradesPage.tsx`, and `PrivacyPage.tsx`. Every copy tweak requires a developer to edit React source, commit, and redeploy. This is slow and blocks non-technical administrators from iterating on marketing copy.

This feature integrates **Puck** (`@puckeditor/core`, MIT-licensed, ~50KB gzipped) as the visual page editor engine. Puck provides the editor UI, drag-and-drop canvas, component configuration panels, viewport controls, a structured JSON data model, and a `<Render>` component for public output. We do NOT build a custom drag-and-drop editor from scratch.

**What we build on top of Puck:**
- Custom Puck component configs matching our existing Tailwind page designs
- Backend storage (`editor_pages` table with draft/published JSON, revisions, SEO)
- Admin integration (Puck wrapped in AdminLayout, page list, create/delete flows)
- Draft/Publish workflow with revision history
- Public rendering via Puck's `<Render>` inside our existing page shell
- Dynamic sitemap and robots.txt
- Slug management with redirects
- Media handling (upload, WebP variants, Media Library as custom Puck field)
- Access control and audit logging

**What Puck handles (we do NOT build):**
- Editor canvas UI with drag-and-drop
- Component picker / widget library panel
- Per-component field configuration panels
- Responsive viewport preview controls
- JSON data model structure and manipulation

This is a ~1-week integration project, not a 4-week build-from-scratch.

## Glossary

- **Puck**: The open-source visual editor library (`@puckeditor/core`) that provides the editor UI, drag-and-drop, component config, and rendering. MIT licensed.
- **Puck_Config**: The configuration object passed to `<Puck>` and `<Render>` that defines all available components, their fields, and their render functions. Defined in `frontend/src/admin/page-editor/puckConfig.ts`.
- **Puck_Data**: The structured JSON output produced by Puck's editor. Stored as `draft_content` and `published_content` in the database. Puck owns this schema.
- **Page**: Any public URL managed by the editor, whether originally hand-coded or created through the editor.
- **Page_Record**: A row in the `editor_pages` table owning one `page_key`, its `page_slug`, `page_origin`, current `draft_content` (Puck_Data JSON), current `published_content` (Puck_Data JSON), SEO metadata, and publish state.
- **Page_Origin**: Enum on every Page_Record — `hand-coded` (has a React Fallback_Page) or `editor-created` (created through the editor, no fallback).
- **Hand_Coded_Page**: A Page with `page_origin = hand-coded`. Has a React Fallback_Page component and an entry in `_registry.ts`. Its `page_slug` is immutable in the editor.
- **Editor_Only_Page**: A Page with `page_origin = editor-created`. No React fallback. Created entirely through the editor. Slug is editable.
- **Page_Slug**: The URL path of a Page (e.g. `/`, `/workshop`, `/guides/nz-wof-rules`). Must be unique, match `^/(?:[a-z0-9-]+)(?:/[a-z0-9-]+){0,2}$`, max 80 characters, and not collide with reserved prefixes.
- **Reserved_Slug_List**: Union of all authenticated product prefixes from the nginx `$x_robots_tag` map, auth routes, API routes, token-based routes, alias redirects, and registered Page_Registry slugs.
- **Page_Registry**: Combined manifest of all manageable pages — frontend `_registry.ts` (hand-coded entries) plus `editor_pages` table (all pages).
- **Fallback_Page**: The original hand-coded React page that renders when a Hand_Coded_Page has no published Puck_Data or when published data fails validation.
- **Revision**: An immutable snapshot of published Puck_Data stored in `editor_page_revisions` with author, timestamp, and optional note.
- **Page_Template**: A named starter Puck_Data document used when creating new Editor_Only_Pages. Stored in `frontend/src/admin/page-editor/templates.ts`.
- **Media_Asset**: An uploaded image referenced by Puck components. Stored under `app_uploads` with WebP variants, metadata in `editor_media_assets`.
- **Dynamic_Sitemap**: The `/sitemap.xml` response served by the backend, regenerated from `editor_pages` on publish/create/delete/slug-change.
- **Dynamic_Robots**: The `/robots.txt` response served by the backend, appending dynamic `Allow:` directives for published Editor_Only_Pages.
- **Audit_Entry**: A row in the existing audit log capturing editor actions (open, save, publish, revert, create, delete, slug change, redirect change).

## Requirements

### Requirement 1: Puck Integration and Component Config

**User Story:** As a developer, I want Puck installed and configured with custom components matching our existing page designs, so that the editor produces pages visually consistent with the hand-coded marketing pages.

#### Acceptance Criteria

1. THE System SHALL install `@puckeditor/core` via `npm install @puckeditor/core` in the `frontend/` package and import Puck's CSS in the editor entry point. THE Puck editor CSS (`puck.css`) SHALL be scoped to the editor page only and SHALL NOT leak into AdminLayout's sidebar, header, or other admin pages. This SHALL be achieved by importing `puck.css` only in the `PageEditorEdit.tsx` component (lazy-loaded), not globally.
2. THE Puck_Config SHALL define the following custom components, each with typed fields and a Tailwind-based render function:
   - **Hero** — gradient background, H1 heading, sub-text paragraph, up to 2 CTA buttons (label, URL, style), trust badges row
   - **FeatureGrid** — array of cards each with icon (emoji or SVG), title, description; configurable column count (2/3/4)
   - **Section** — generic container with configurable background colour, padding, and max-width
   - **Columns** — 1/2/3/4 column layout with configurable gap
   - **Heading** — H1 through H6 with text content and alignment
   - **RichText** — paragraph text supporting bold, italic, and hyperlinks
   - **Image** — with alt text (required), srcset from Media_Asset variants, lazy loading
   - **VideoEmbed** — YouTube URL, Vimeo URL, or direct MP4 URL with lazy loading
   - **Button** — label, URL, style (primary/secondary/ghost), target (same tab/new tab), optional `rel="nofollow"`
   - **FAQAccordion** — array of question/answer pairs; render function emits `<details>`/`<summary>` and auto-generates `FAQPage` JSON-LD
   - **PricingCard** — plan name, price, currency, billing period, features list, CTA button
   - **TestimonialCard** — quote text, person name, business name
   - **CTABanner** — gradient background, heading, sub-text, buttons
   - **Spacer** — configurable height (sm/md/lg/xl)
   - **Divider** — horizontal rule with optional label
   - **Badge** — text content, colour variant
   - **List** — bullet or numbered, array of text items
   - **DemoRequestForm** — submits to existing public demo-request API endpoint; no new unauthenticated mutation
   - **NZTrustSignals** — row of NZ-specific trust badges (NZ hosted, CarJam, WOF/COF, Xero, NZD pricing)
3. EACH Puck component's render function SHALL use only Tailwind utility classes from the existing OraInvoice Tailwind configuration and SHALL NOT emit inline `style` attributes except for custom hex colours not in the palette.
4. THE Puck_Config SHALL be defined in a single module at `frontend/src/admin/page-editor/puckConfig.ts` so that both the editor (`<Puck>`) and the public renderer (`<Render>`) share the same config.
5. WHERE a component is a FAQAccordion, THE render function SHALL emit semantic `<details>`/`<summary>` HTML AND SHALL emit a `FAQPage` JSON-LD script tag within the component output.
6. WHERE a component is a VideoEmbed with a YouTube or Vimeo URL, THE render function SHALL emit the provider's standard `<iframe>` with `loading="lazy"`; WHERE the URL is a direct MP4, THE render function SHALL emit a `<video>` element with `loading="lazy"` and poster frame when supplied.
7. WHERE a component is a DemoRequestForm, THE render function SHALL submit form data through the existing public demo-request API endpoint and SHALL NOT expose any new unauthenticated mutation endpoint.
8. THE Puck_Config SHALL be extensible — adding a new component requires only adding an entry to the config object; no router, backend, or migration changes are needed.

### Requirement 2: Backend Content Storage

**User Story:** As a developer, I want page content stored as Puck's structured JSON in a well-defined schema, so that the data is safe, validated, and easy to query.

#### Acceptance Criteria

1. THE System SHALL persist one `editor_pages` row per `page_key` with columns: `page_key` (string, primary), `page_origin` (enum `hand-coded` | `editor-created`, NOT NULL), `page_slug` (string, NOT NULL, unique where `deleted_at IS NULL`), `title` (VARCHAR(120), NOT NULL, default ''), `draft_content` (JSONB — Puck_Data), `published_content` (JSONB, nullable — Puck_Data), `published_version` (integer, nullable), `draft_updated_at`, `published_at` (nullable), `draft_updated_by`, `published_by`, `seo` (JSONB), `noindex` (boolean, default false), `deleted_at` (nullable), `deleted_by` (nullable).
2. THE `editor_pages` table SHALL enforce a UNIQUE constraint on `page_slug` WHERE `deleted_at IS NULL` and a UNIQUE constraint on `page_key`; slugs of soft-deleted pages SHALL NOT block re-use.
3. WHEN Puck_Data is saved (draft or publish), THE System SHALL validate that the JSON is parseable and does not exceed 1 MB, rejecting with 422 or 413 respectively.
4. THE System SHALL sanitise any HTML string fields within the Puck_Data on save using a server-side allow-list limited to `<strong>`, `<em>`, `<a href target rel>`, `<br>`, and `<p>` tags, stripping all other tags, attributes, and inline event handlers.
5. THE System SHALL reject any `href` value in Puck_Data that does not use `http://`, `https://`, `mailto:`, `tel:`, or a path beginning with `/`.
6. THE `editor_pages`, `editor_page_revisions`, `editor_media_assets`, and `editor_page_redirects` tables SHALL be global (not tenant-scoped), SHALL NOT have an `org_id` column, and SHALL NOT be subject to RLS policies.
7. THE editor migrations SHALL follow the numbered Alembic convention (next available after current head) and SHALL be idempotent (`CREATE TABLE IF NOT EXISTS`).

### Requirement 3: Admin Page Editor UI

**User Story:** As a Global Administrator, I want the Puck editor wrapped in our AdminLayout with a page list and management controls, so that I can manage all marketing pages from one place.

#### Acceptance Criteria

1. WHEN a `global_admin` navigates to `/admin/page-editor`, THE System SHALL render a page list showing all Page_Records sourced from the backend, displaying: page title, `page_slug`, `page_origin` badge, publish state (`never-published` / `published` / `draft-ahead`), last-published timestamp, and an "Edit" link.
2. THE page list SHALL expose a "New Page" action button that opens the Create New Page flow (Requirement 8).
3. WHEN a `global_admin` clicks "Edit" on a page, THE System SHALL navigate to `/admin/page-editor/:pageKey` and render the Puck editor via `<Puck config={puckConfig} data={draftContent} onPublish={handlePublish} />`.
4. THE Puck editor SHALL be wrapped in the existing `AdminLayout` and the route SHALL be guarded by `RequireGlobalAdmin`.
5. THE editor page SHALL include a toolbar above Puck with: page title, "Save Draft" button, "Preview" button, "Publish" button, "Revision History" button, and "Page Settings" button.
6. WHEN a `global_admin` clicks "Save Draft", THE System SHALL POST the current Puck_Data to the backend, updating `draft_content` only without affecting `published_content`.
7. THE editor SHALL auto-save `draft_content` to the backend every 30 seconds while the document is dirty.
8. WHEN a `global_admin` attempts to navigate away with unsaved changes, THE Editor SHALL display a confirmation dialog.
9. WHEN a `global_admin` clicks "Duplicate" on a page in the page list, THE editor SHALL open the Create New Page dialog pre-filled with the source page's `draft_content` (or `published_content` if no draft), a suggested title of "{original title} (Copy)", and a suggested slug of "{original-slug}-copy". The duplicated page SHALL be a new Editor_Only_Page regardless of the source page's origin.
10. THE page list SHALL support text search (filtering by title or slug substring) and filtering by `page_origin` (all / hand-coded / editor-created) and publish state (all / published / never-published / draft-ahead).
11. THE page list SHALL support pagination (20 pages per page) when the total exceeds 20.
12. WHEN a `global_admin` opens a page for editing, THE System SHALL record the editor session (user_id, page_key, opened_at) in a lightweight lock (Redis key with 5-minute TTL, refreshed on auto-save). IF another `global_admin` attempts to open the same page, THE editor SHALL display a warning: "This page is currently being edited by {user_email}. Changes may be overwritten." The warning SHALL NOT block access — it is advisory only.

### Requirement 4: Publishing Workflow

**User Story:** As a Global Administrator, I want an explicit publish action with preview, so that I never accidentally push broken content to production.

#### Acceptance Criteria

1. WHEN a `global_admin` clicks "Preview", THE System SHALL return a short-lived tokenised URL (valid 60 minutes) that renders `draft_content` through Puck's `<Render>` with `X-Robots-Tag: noindex` on the response.
2. WHEN a `global_admin` triggers publish (via Puck's `onPublish` callback or the toolbar "Publish" button), THE System SHALL: (a) validate `draft_content`, (b) copy `draft_content` into `published_content`, (c) increment `published_version`, (d) set `published_at` and `published_by`, (e) create a Revision, (f) invalidate any cache for the affected route.
3. IF validation fails during publish, THEN THE System SHALL NOT update `published_content` and SHALL return a 422 with error details.
4. THE System SHALL NOT auto-publish. Publishing SHALL occur only on explicit administrator action.
5. WHERE a publish has occurred, THE editor toolbar SHALL display the last published time, author, and version number.

### Requirement 5: Revision Control

**User Story:** As a Global Administrator, I want a history of every published version, so that I can revert if a publish introduces a problem.

#### Acceptance Criteria

1. THE System SHALL persist at least the 50 most recent Revisions per `page_key` in `editor_page_revisions` with columns: `id`, `page_key`, `version`, `content` (JSONB — Puck_Data snapshot), `published_at`, `published_by`, and optional `note`.
2. WHEN a publish occurs, THE System SHALL create a new Revision row before updating `published_content`.
3. WHEN a new Editor_Only_Page is created, THE System SHALL write an initial Revision (version 1, `note = "initial creation from template: {template_name}"`, `published_at = NULL`) so the full history from creation is visible.
4. WHEN a `global_admin` opens the Revision History panel, THE editor SHALL list revisions newest-first with version, author, timestamp, and note.
5. WHEN a `global_admin` clicks "View" on a revision, THE editor SHALL render a read-only preview of that revision's Puck_Data using `<Render>`.
6. WHEN a `global_admin` clicks "Revert" on a revision, THE System SHALL copy that revision's content into `draft_content` without publishing, marking the document dirty for review.
7. WHEN the 50-revision cap is reached, THE System SHALL prune the oldest revision and log the pruning in the audit log.
8. WHEN a Page is soft-deleted, its Revisions SHALL be retained indefinitely for audit.

### Requirement 6: Page Settings and SEO

**User Story:** As a Global Administrator, I want to edit page meta, canonical URL, Open Graph, and JSON-LD, so that I preserve the current SEO work when editing pages.

#### Acceptance Criteria

1. THE editor SHALL provide a Page Settings panel exposing: page title, `page_slug` (editable for Editor_Only_Pages, read-only for Hand_Coded_Pages), `noindex` toggle, meta title, meta description, canonical URL, Open Graph image URL, Open Graph type, Twitter card type, and JSON-LD document(s).
2. WHEN Page Settings are saved, THE public renderer SHALL emit the corresponding `<meta>`, `<link rel="canonical">`, and `<script type="application/ld+json">` tags via the existing `usePageMeta` hook.
3. THE JSON-LD editor SHALL accept valid JSON, validate on save, and support an array of JSON-LD documents per page.
4. THE System SHALL validate that `canonical` is a fully-qualified `https://` URL on save.
5. IF a FAQAccordion component is present on a page, THEN THE renderer SHALL automatically synthesise a `FAQPage` JSON-LD entry and merge it with any administrator-supplied JSON-LD.
6. WHERE a Page has `noindex = true`, THE renderer SHALL emit `<meta name="robots" content="noindex, nofollow">` AND the backend SHALL emit `X-Robots-Tag: noindex, nofollow` AND the page SHALL be excluded from the Dynamic_Sitemap.
7. IF a `global_admin` attempts to edit the `page_slug` of a Hand_Coded_Page, THEN THE System SHALL reject with 409 and display the slug as read-only.
8. WHEN a `global_admin` changes the `page_slug` of an Editor_Only_Page, THE System SHALL: (a) validate the new slug, (b) update `editor_pages.page_slug`, (c) create an `editor_page_redirects` row (301) from old to new, (d) regenerate Dynamic_Sitemap, (e) record an Audit_Entry.
9. IF a slug change would create a redirect cycle, THEN THE System SHALL detect and remove the self-redirecting rows rather than creating a loop.
10. THE Page Settings panel SHALL include a "Page Title" field (1–120 chars) that is stored in `editor_pages.title` and used as the display name in the page list. This is separate from the SEO "Meta Title" which may differ.

### Requirement 7: Public Page Rendering

**User Story:** As a visitor, I want pages rendered with the same quality, SEO, and performance as the current hand-coded pages.

#### Acceptance Criteria

1. THE public renderer SHALL use Puck's `<Render config={puckConfig} data={publishedData} />` component wrapped in the existing page shell: `LandingHeader`, `<main className="pt-16">`, `LandingFooter`, including the `public-page` document class toggle.
2. THE renderer SHALL be invoked through a dynamic catch-all route that resolves incoming paths as follows:
   - IF path matches `editor_page_redirects.from_slug` → respond with redirect (301/302)
   - IF path matches `editor_pages.page_slug` (where `deleted_at IS NULL`) → load Page_Record and render
   - OTHERWISE → fall through to existing 404 handling
3. WHEN rendering a Page_Record, THE renderer SHALL load `published_content`. IF `published_content` is null or invalid:
   - WHERE `page_origin = hand-coded` → render the React Fallback_Page
   - WHERE `page_origin = editor-created` → return 404
4. THE renderer SHALL enforce one `<h1>` per page by accepting the first H1 Heading component and demoting subsequent H1s to H2 at render time.
5. WHERE an Image component is rendered, THE renderer SHALL emit `srcset` with WebP variants, `loading="lazy"`, and require non-empty `alt` (or explicit `alt=""` with `role="presentation"` for decorative images).
6. THE renderer SHALL cache `published_content` per `page_key` in memory with a 5-minute TTL, invalidated on publish.
7. THE renderer SHALL emit `Cache-Control: public, max-age=60, stale-while-revalidate=300` on managed page responses.

### Requirement 8: Create New Pages

**User Story:** As a Global Administrator, I want to create new public pages through the editor with a custom URL and template, so that I can launch landing pages without a developer.

#### Acceptance Criteria

1. WHEN a `global_admin` clicks "New Page", THE editor SHALL open a dialog collecting: page title (required, 1–120 chars), `page_slug` (required), Page_Template choice (`blank`, `landing`, `trades`, `privacy`, `workshop-style`), initial meta title (optional), initial meta description (optional, 0–320 chars).
2. THE `page_slug` SHALL match `^/(?:[a-z0-9-]+)(?:/[a-z0-9-]+){0,2}$`, be at most 80 characters, and not collide with the Reserved_Slug_List.
3. WHEN a collision is detected, THE System SHALL return 409 identifying the conflicting source.
4. WHEN validation passes, THE System SHALL create a new `editor_pages` row with `page_origin = editor-created`, the template's starter Puck_Data as `draft_content`, `published_content = null`, and `noindex = false`.
5. THE System SHALL create an initial Revision (version 1, note = "initial creation from template: {template_name}").
6. WHEN creation succeeds, THE editor SHALL immediately open the new page in the Puck editor and display a toast that the page is not publicly visible until published.
7. THE editor SHALL suggest a default slug derived from the title (kebab-cased, ASCII-folded, prefixed with `/`).
8. THE set of Page_Templates SHALL be defined in `frontend/src/admin/page-editor/templates.ts` so new templates can be added without backend changes.

### Requirement 9: Dynamic Sitemap and Robots.txt

**User Story:** As a site operator, I want `/sitemap.xml` and `/robots.txt` to reflect every managed page automatically.

#### Acceptance Criteria

1. THE backend SHALL expose `GET /sitemap.xml` (Content-Type: `application/xml`) and `GET /robots.txt` (Content-Type: `text/plain`), both publicly accessible.
2. THE Dynamic_Sitemap SHALL list every Page_Record where `published_content IS NOT NULL`, `deleted_at IS NULL`, and `noindex = false`, with absolute URLs built from the canonical host and `page_slug`.
3. THE Dynamic_Sitemap SHALL include both Hand_Coded_Pages and Editor_Only_Pages; alias redirects (`/mechanics`, `/garage`) SHALL NOT appear.
4. THE Dynamic_Sitemap SHALL emit `<lastmod>` from `published_at` (ISO 8601) and optional `<priority>`/`<changefreq>` from SEO settings.
5. THE Dynamic_Robots SHALL serve the existing static base content AND append `Allow:` directives for published, non-noindex Editor_Only_Page slugs, plus `Sitemap: https://{host}/sitemap.xml`.
6. WHEN any Page_Record is published, created, deleted, restored, or has slug/noindex changed, THE System SHALL invalidate cached sitemap and robots responses.
7. THE nginx `location = /sitemap.xml` and `location = /robots.txt` blocks SHALL be updated to proxy to the backend; the static files SHALL be removed from the frontend build.
8. THE Dynamic_Sitemap output SHALL be sorted by `page_slug` for stable diffing.

### Requirement 10: Page Deletion and Soft-Delete

**User Story:** As a Global Administrator, I want to delete Editor_Only_Pages while keeping audit history.

#### Acceptance Criteria

1. WHEN a `global_admin` confirms deletion of an Editor_Only_Page, THE System SHALL soft-delete by setting `deleted_at` and `deleted_by`.
2. THE editor page list SHALL hide deleted pages by default but offer a "Show deleted" filter.
3. AFTER soft-delete, the public catch-all route SHALL return 404 for the deleted page's slug.
4. Revisions for deleted pages SHALL be retained indefinitely.
5. IF a `global_admin` attempts to delete a Hand_Coded_Page, THEN THE System SHALL reject with 409 and offer "Revert to Fallback" (clears `published_content` to NULL).
6. THE System SHALL provide an undelete endpoint that clears `deleted_at`/`deleted_by`, allowed only if the original slug does not conflict with another active page.
7. Hard-delete is NOT provided in this release.

### Requirement 11: Slug Redirects

**User Story:** As a Global Administrator, I want old URLs to keep working after page renames.

#### Acceptance Criteria

1. THE System SHALL persist redirects in `editor_page_redirects` with columns: `id` (uuid), `from_slug` (unique where `deleted_at IS NULL`), `to_slug_or_url`, `status_code` (301 or 302), `created_at`, `created_by`, `deleted_at`.
2. WHEN an Editor_Only_Page slug changes, THE System SHALL auto-create a 301 redirect from old to new slug.
3. THE editor SHALL provide a Redirects panel at `/admin/page-editor/redirects` for listing, creating, and soft-deleting redirects.
4. THE dynamic catch-all route SHALL consult redirects BEFORE rendering pages, so redirects take priority.
5. THE renderer SHALL resolve at most one redirect hop per request to prevent loops.
6. WHEN a redirect's `from_slug` matches an active Page_Record, creation SHALL be rejected with 409.
7. Soft-deleted redirects SHALL NOT be consulted by the catch-all route.

### Requirement 12: Media Handling

**User Story:** As a Global Administrator, I want to upload and manage images used on marketing pages.

#### Acceptance Criteria

1. WHEN a `global_admin` uploads an image, THE System SHALL persist the original to `app_uploads`, generate WebP variants at widths 640, 960, 1280, and 1920px, and record variant URLs in `editor_media_assets`.
2. THE editor SHALL provide a Media Library browser (implemented as a custom Puck field type for Image components) listing uploaded assets with filename, dimensions, size, and upload date.
3. THE System SHALL reject uploads larger than 10 MB (413) and accept only `image/jpeg`, `image/png`, `image/webp`, `image/svg+xml`, `image/gif` validated by content sniffing.
4. WHEN a Media_Asset is deleted, THE System SHALL check for references in any `draft_content` or `published_content`; IF referenced, reject with 409 listing the referencing pages.
5. WHERE a VideoEmbed uses YouTube/Vimeo, THE System SHALL NOT download the video — the renderer emits the provider's iframe.
6. WHERE a VideoEmbed uses a direct MP4 URL, THE System SHALL validate it is `https://` and returns `Content-Type: video/mp4` on HEAD at save time.

### Requirement 13: Access Control and Audit

**User Story:** As a security administrator, I want the editor locked to Global Admins with full audit trail.

#### Acceptance Criteria

1. THE editor route `/admin/page-editor` SHALL be wrapped in `RequireGlobalAdmin` and `AdminLayout`.
2. THE editor APIs SHALL be under `/api/v2/admin/page-editor/...` guarded by global-admin role check.
3. IF a non-`global_admin` user attempts any editor API, THEN THE System SHALL respond 403 and log an audit entry.
4. THE Preview endpoint SHALL use a short-lived signed token (60-minute expiry) generated only by `global_admin` sessions.
5. Public rendering endpoints (catch-all, sitemap, robots) SHALL remain publicly accessible without authentication.
6. WHEN a `global_admin` opens, saves, previews, publishes, reverts, creates, deletes, changes slug, or manages redirects, THE System SHALL write an Audit_Entry with actor, action, `page_key`, affected slugs, and timestamp.
7. THE System SHALL expose an observability view showing per-page: `published_version`, last publish time, draft dirty flag, `page_slug`, `page_origin`, `noindex` state, and link to audit entries.

### Requirement 14: Backward Compatibility and Page Registry

**User Story:** As a developer, I want hand-coded pages to continue working as a safety net and new hand-coded pages to require only one registry entry to appear everywhere.

#### Acceptance Criteria

1. THE existing `LandingPage.tsx`, `WorkshopPage.tsx`, `TradesPage.tsx`, and `PrivacyPage.tsx` SHALL remain in the codebase as Fallback_Page components.
2. THE frontend Page_Registry at `frontend/src/pages/public/_registry.ts` SHALL export an array of `HandCodedPageRegistration` objects declaring: `page_key`, default `page_slug`, `fallbackPage` component, `defaultTitle`, `defaultDescription`, `defaultCanonical`, optional `defaultJsonLd`.
3. WHEN the backend starts, THE System SHALL sync the frontend registry to the database, auto-creating empty Page_Records for any registered `page_key` not yet in `editor_pages`.
4. WHEN a Hand_Coded_Page has no `published_content`, THE renderer SHALL render its Fallback_Page unchanged.
5. WHEN a Hand_Coded_Page has valid `published_content`, THE renderer SHALL render from Puck_Data via `<Render>`.
6. THE existing `usePageMeta`, `LandingHeader`, `LandingFooter`, `DemoRequestModal`, and `NoIndexRoute` SHALL be reused by the renderer.
7. IF the renderer encounters a fatal error rendering `published_content`, THE page-level ErrorBoundary SHALL catch it and fall back to the Fallback_Page.
8. WHEN a developer adds a new hand-coded page (React component + `_registry.ts` entry), the editor page list, backend Page_Record, Dynamic_Sitemap, and Dynamic_Robots SHALL all include it automatically on next app restart.
9. THE CI pipeline SHALL include a check that fails if `_registry.ts` exports diverge from the backend seed.
10. THE existing alias redirects (`/mechanics` → `/workshop`, `/garage` → `/workshop`) SHALL continue to be served by the existing static React routes, not by the dynamic catch-all.

## Non-Goals

- Building a custom drag-and-drop editor from scratch (Puck provides this).
- Building a custom widget library panel (Puck's component picker handles this).
- Building custom per-widget styling panels (Puck's field configuration handles this).
- Building responsive preview controls (Puck has viewport controls built in).
- A full CMS for authenticated product pages.
- A blog system with taxonomies, authors, or feeds.
- User-generated content. Only `global_admin` may use the editor.
- Per-tenant or org-scoped pages. Managed pages are global.
- Replacing the frontend framework. The app remains React + Tailwind + Vite.
- Removing Fallback_Page components. They remain as the safety net.
- A/B testing, split-testing, or personalisation.
- Multi-language / i18n content.
- Workflow stages beyond Draft → Publish (no approval chains, no scheduled publish).
- Hard-deletion of pages.
- Analytics or heat-map overlays in the editor.
- AI-assisted content generation.
- Nested URL depth beyond 3 segments.
- SSR/pre-rendering (deferred to a follow-up — initial release uses client-side rendering with the existing SPA fallback pattern; crawlers see meta tags from `usePageMeta` which injects into `<head>` before paint).

## Open Questions

1. **Puck plugin for Media Library** — Should the Media Library be a custom Puck field type (inline in the Image component config) or a separate modal triggered by a button? Leaning toward custom field type for better UX.
2. **Puck version pinning** — Pin to the latest stable at implementation time. Monitor for breaking changes in minor versions.
3. **SSR for crawlers** — The initial release uses client-side rendering (same as current hand-coded pages). If Google Search Console shows indexing issues, a follow-up adds Vite SSR or a pre-render step. The `usePageMeta` hook already injects meta tags synchronously before first paint, which is sufficient for most crawlers.
4. **Orphaned hand-coded pages** — If a `page_key` in `editor_pages` with `page_origin = hand-coded` no longer has a matching `_registry.ts` entry (developer removed the page), should the system mark it `orphaned` and hide it, or leave it visible with a warning badge? Leaning toward warning badge.
5. **Global styles** — Puck supports plugins. Should we build a "Global Styles" plugin that injects palette/font choices into all components, or handle this via Tailwind config (simpler, less flexible)? Leaning toward Tailwind config for v1.
6. **Puck JSON schema migration** — If a future Puck version changes the `Data` type structure, we need a migration script that transforms existing `draft_content`/`published_content` rows. For v1, pin to a specific Puck version and document the upgrade path.
