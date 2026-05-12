# SEO Implementation — OraInvoice

**Status:** Implemented
**Last updated:** 2026-05-11
**Owner:** Frontend / Platform

This document captures the SEO work done on the OraInvoice public marketing
surface, and the matching noindex defences applied across the authenticated
product and all API endpoints. It is the reference to follow when adding new
public pages or when new authenticated routes are introduced.

---

## Goals

1. **Make the public marketing pages discoverable** in Google and other
   search engines, targeting NZ trade businesses (mechanics, electricians,
   plumbers, builders).
2. **Keep every authenticated page out of search indexes.** None of
   `/dashboard`, `/invoices`, `/customers`, `/admin/*`, `/portal/*`,
   `/pay/*`, `/kiosk` or the auth flow should appear in Google results.
3. **Keep every API endpoint (`/api/*`) out of search indexes.**
4. **Defence in depth.** Use at least two of `robots.txt`, per-page
   `<meta name="robots">`, and `X-Robots-Tag` HTTP header for anything that
   must not be indexed, so a failure in one layer does not leak private
   URLs into search results.

## Site URLs

- Primary: `https://one.oraflows.co.nz` (used in canonical URLs and the
  sitemap).
- Aliases: `https://invoice.oraflows.co.nz`, `https://one.oraflows.com`
  (included in `Organization.sameAs`).

## What Changed

### 1. `frontend/index.html` — HTML `<head>` SEO

Added:

- `<html lang="en-NZ">` — correct locale for NZ audience.
- `<title>` with product name and value proposition, 62 chars.
- `<meta name="description">` — ~190 chars. Slightly over the often-cited
  155-char limit because Google regularly shows longer descriptions and
  truncates the rest on mobile only.
- `<meta name="keywords">` — not used by Google as a ranking signal but
  kept because some other engines still read it and it has no cost.
- `<link rel="canonical" href="https://one.oraflows.co.nz/">` — avoids
  duplicate content issues when the site is reached via `invoice.oraflows.co.nz`
  or `one.oraflows.com`.
- Open Graph tags (`og:type`, `og:site_name`, `og:title`, `og:description`,
  `og:url`, `og:image`, `og:image:width/height/alt`, `og:locale`) — drives
  how LinkedIn, Facebook, WhatsApp and similar render link previews.
- Twitter Card tags (`twitter:card`, `twitter:title`, `twitter:description`,
  `twitter:image`, `twitter:image:alt`).
- `<meta name="author">`, existing `theme-color`, favicon, Apple touch icon,
  manifest.
- JSON-LD `@graph` containing an `Organization` entity (OraInvoice operated
  by Oraflows Limited, NZ area served, logo, `sameAs` aliases) and a
  `WebSite` entity. These are emitted on every page because they are
  site-level metadata.

### 2. `frontend/src/hooks/usePageMeta.ts` — per-page metadata hook

A small standalone hook (no third-party dependency) that imperatively
manages page-level `<head>` metadata and restores the previous value on
unmount. It can set `title`, `description`, `canonical`, `openGraph.*`
overrides, inject JSON-LD, and — crucially — add
`<meta name="robots" content="noindex, nofollow">` for authenticated pages.

Restoring previous values on unmount is important because React 19's
built-in metadata hoisting does not handle this case cleanly for
short-lived noindex tags.

### 3. Public page content

**`LandingPage.tsx` (`/`)**

- Added `usePageMeta` with page title, description, canonical URL pointing
  at the primary domain, and a JSON-LD `SoftwareApplication` entity
  describing the product (audience = NZ trade businesses, feature list,
  pricing offer).
- Confirmed the page uses semantic HTML: a single `<h1>` in the hero, `<h2>`
  per feature category and section, `<h3>` per feature card,
  `<main>`/`<section>` structure, `aria-hidden` on decorative emoji icons,
  `<blockquote>` for testimonials.

**`TradesPage.tsx` (`/trades`)**

- Added `usePageMeta` with page-specific title, description, canonical URL
  and a `BreadcrumbList` JSON-LD entity so Google can render breadcrumbs
  in SERP.
- Uses `<article>` for each trade card — already correct semantic markup.

**`WorkshopPage.tsx` (`/workshop`, aliases `/mechanics` and `/garage`)**

- Added 2026-05-12. Dedicated, SEO-optimised landing page targeting the
  workshop / mechanic / garage software keyword cluster (see
  `docs/SEO_WORKSHOP_PAGE_STRATEGY.md` for the full competitor analysis).
- Emits three JSON-LD entities: `SoftwareApplication` (with NZD offer and
  feature list), `FAQPage` (mirrors the on-page FAQ accordion), and
  `BreadcrumbList` (Home → Workshop Software).
- `/mechanics` and `/garage` are alias routes — they render a
  `<Navigate to="/workshop" replace />` so the browser URL bar rewrites
  to the canonical path. The canonical `<link rel="canonical">` on
  `/workshop` further consolidates link-equity to the single URL. Google
  is expected to drop the aliases from the index once it sees the
  canonical tag.
- NZ-specific positioning: CarJam integration, WOF/COF expiry workflow,
  NZ hosting, NZD pricing — the gaps our three main competitors
  (`workshopsoftware.com`, `mechanicdesk.com.au`, `auxosoftware.com`) all
  leave open.

**`PrivacyPage.tsx` (`/privacy`)**

- Added `usePageMeta` with page-specific title, description, canonical URL
  and `BreadcrumbList` JSON-LD.
- Already uses strong heading hierarchy (h1, h2 per IPP, h3 for
  sub-sections) and a full table of contents `<nav>`.

### 4. Authenticated routes — noindex defences

Applied at two layers.

**Layer A — layouts** (`OrgLayout.tsx`, `AdminLayout.tsx`)

Both layouts now call `usePageMeta({ noindex: true })`. This injects
`<meta name="robots" content="noindex, nofollow">` on every page served
under those layouts. Since every authenticated product route uses one of
these two layouts, this single change covers:

- `/dashboard`, `/customers/*`, `/vehicles/*`, `/invoices/*`, `/quotes/*`,
  `/job-cards/*`, `/jobs/*`, `/bookings`, `/inventory`, `/items`,
  `/catalogue`, `/staff/*`, `/projects/*`, `/expenses`,
  `/accounting/*`, `/reports/*`, `/tax/*`, `/banking/*`, `/time-tracking`,
  `/pos`, `/schedule`, `/recurring`, `/purchase-orders/*`, `/data`,
  `/progress-claims`, `/variations`, `/retentions`, `/floor-plan`,
  `/kitchen`, `/franchise`, `/locations/*`, `/stock-transfers/*`,
  `/branch-transfers`, `/claims/*`, `/staff-schedule`, `/assets/*`,
  `/compliance`, `/loyalty`, `/ecommerce`, `/sms`, `/settings*`,
  `/notifications`, `/setup`, `/setup-guide`
- `/admin/*` (every admin page)

**Layer B — `<NoIndexRoute />`** (`frontend/src/components/common/NoIndexRoute.tsx`)

A small route-level wrapper that calls `usePageMeta({ noindex: true })`
and renders an `<Outlet />`. Applied in `App.tsx` around:

- Auth routes: `/login`, `/signup`, `/mfa-verify`, `/forgot-password`,
  `/reset-password`, `/verify-email`
- `/kiosk`
- Customer portal routes: `/portal/signed-out`, `/portal/recover`,
  `/portal/:token`, `/portal/:token/payment-success`
- `/pay/:token`

The landing page (`/`) is deliberately NOT wrapped — it is the one route
served through `<GuestOnly />` that must be indexable.

### 5. `frontend/public/robots.txt`

New file. Vite copies everything under `frontend/public/` into the build
output so it is served at the site root by nginx.

- Explicitly `Allow:` the three indexable paths (`/`, `/trades`,
  `/privacy`) plus static assets.
- `Disallow:` every API path, every auth path, every authenticated product
  path, `/admin/*`, `/portal/`, `/pay/`, `/kiosk`.
- `Sitemap:` pointing at the sitemap on the primary domain.

### 6. `frontend/public/sitemap.xml`

New file listing only the three indexable public URLs:

- `/` (priority 1.0, weekly)
- `/trades` (priority 0.8, monthly)
- `/privacy` (priority 0.4, yearly)

Authenticated routes, payment token links, portal links and API endpoints
are deliberately omitted — a URL in the sitemap is a hint to Google to
crawl it, which is the opposite of what we want for private pages.

### 7. `nginx/nginx.conf`

Added HTTP headers and served the new static files:

- `X-Robots-Tag: noindex, nofollow` on `/api/`, `/health`, `/docs`,
  `/redoc`, `/openapi.json`. This prevents any accidentally-crawled API
  response (for example, a `GET /api/v1/public/privacy-policy` hit by a
  crawler) from being indexed.

**Critical nginx gotcha (fixed 2026-05-11):**

The original implementation used a regex `location ~ ^/(admin|dashboard|...)` block
with `add_header X-Robots-Tag` and `try_files $uri $uri/ /index.html`.
**This did not work.** When `try_files` falls back to `/index.html`, nginx
does an internal redirect that re-enters `location /`, which loses all
`add_header` directives from the preceding regex location block.

The fix uses a `map` variable at the `http` level and emits the header
from the default `location /` block so it applies after SPA fallback:

```nginx
map $request_uri $x_robots_tag {
    default                                                      "";
    ~^/api/                                                      "noindex, nofollow";
    ~^/(login|signup|...|verify-email|onboarding)(/|$|\?)        "noindex, nofollow";
    ~^/(admin|dashboard|customers|invoices|...)(/|$|\?)          "noindex, nofollow";
    ~^/(kiosk|portal|pay)(/|$|\?)                                "noindex, nofollow";
    ~^/mobile(/|$)                                               "noindex, nofollow";
}

location / {
    add_header X-Robots-Tag $x_robots_tag always;
    try_files $uri $uri/ /index.html;
}
```

**Key insight:** we map against `$request_uri` (the original URI) not
`$uri` (which changes to `/index.html` after `try_files` rewrites).
Mapping against `$uri` would cause every SPA route to match the default
and get no header.

- Explicit `location = /robots.txt` and `location = /sitemap.xml` blocks
  that set the correct `Content-Type` (`text/plain` and
  `application/xml` respectively) and a short cache lifetime.

### 8. Untouched (intentionally)

- The overall landing page design and copy.
- Routing behaviour and auth guards.
- Backend endpoints.
- The existing nginx `/assets/` cache rules.

## Why Each Change Matters

| Change | Ranking signal | User-visible effect |
|---|---|---|
| `<title>`, meta description | Yes | SERP click-through rate |
| `<link rel="canonical">` | Yes | Prevents duplicate-content dilution across the three domain aliases |
| Open Graph / Twitter Card | Indirect (social referral traffic) | Rich link previews on social and messaging apps |
| JSON-LD (Organization, WebSite, SoftwareApplication, BreadcrumbList) | Yes — rich results eligibility | Knowledge panel and breadcrumb display in SERP |
| Heading hierarchy (h1/h2/h3) | Yes | Screen-reader navigation; Google's content understanding |
| Semantic HTML (`main`, `section`, `article`, `nav`) | Yes | Assistive tech support |
| `robots.txt` | Crawl-budget directive | Keeps Googlebot focused on public pages |
| `sitemap.xml` | Discovery signal | Faster and more reliable indexing of public pages |
| Per-page `noindex` meta on auth'd pages | Yes | Prevents private URLs from ever appearing in SERP |
| `X-Robots-Tag: noindex` on `/api/` and auth'd SPA paths | Yes | Defence in depth — covers cached static responses where the React meta tag hasn't executed yet |

## How to Verify

### Local / staging smoke tests

1. Build the frontend: `cd frontend && npx vite build`.
2. Confirm output files exist:
   - `frontend/dist/robots.txt`
   - `frontend/dist/sitemap.xml`
   - `frontend/dist/index.html` contains `<link rel="canonical"` and
     `application/ld+json`.
3. Start the full stack with docker compose and hit the site on the local
   environment:
   - `curl -I http://localhost/` → no `X-Robots-Tag` header.
   - `curl -I http://localhost/dashboard` → `X-Robots-Tag: noindex, nofollow`.
   - `curl -I http://localhost/api/v1/health` (if available) →
     `X-Robots-Tag: noindex, nofollow`.
   - `curl http://localhost/robots.txt` → returns our robots.txt content
     (Content-Type: text/plain).
   - `curl http://localhost/sitemap.xml` → returns our sitemap XML
     (Content-Type: application/xml).
4. View source of `/`, `/trades`, `/privacy` and verify the per-page
   title, description, canonical, and JSON-LD are present.
5. View source of `/login`, `/dashboard`, `/admin/dashboard`, `/kiosk`
   and confirm `<meta name="robots" content="noindex, nofollow">` is
   present.

### Google Search Console (production)

1. Add `https://one.oraflows.co.nz` as a property in Google Search
   Console ([search.google.com/search-console](https://search.google.com/search-console)).
2. Verify ownership via DNS TXT record or an HTML file upload.
3. Submit the sitemap: **Sitemaps → enter `sitemap.xml` → Submit**.
4. Use **URL Inspection** on:
   - `https://one.oraflows.co.nz/` → should report "URL is on Google"
     within a few days of submission.
   - `https://one.oraflows.co.nz/dashboard` → should report "Excluded by
     'noindex' tag".
5. Check **Coverage / Pages** after a week:
   - `Indexed` should contain only the three public pages.
   - `Excluded → blocked by robots.txt` and `Excluded → noindex` should
     cover everything else.
6. Use **Rich Results Test**
   ([search.google.com/test/rich-results](https://search.google.com/test/rich-results))
   on `https://one.oraflows.co.nz/` — should detect Organization, WebSite
   and SoftwareApplication structured data.

### Additional tools

- [PageSpeed Insights](https://pagespeed.web.dev/) — run against the
  landing page; fix any "Largest Contentful Paint" or "Cumulative Layout
  Shift" regressions.
- [Google Mobile-Friendly Test](https://search.google.com/test/mobile-friendly)
  — already passes; re-run if the landing page is substantially
  redesigned.
- [Schema.org validator](https://validator.schema.org/) — paste the
  landing page URL to confirm JSON-LD is parsed correctly.
- [Ahrefs Webmaster Tools](https://ahrefs.com/webmaster-tools) — free
  backlink tracking for the site.

## Future Improvements

### Content
- **Blog / guides** — NZ-specific guides ("How to invoice for a WOF",
  "Xero vs manual invoicing for workshops", "Setting up CarJam for your
  workshop") will drive long-tail search traffic. Hosting the blog on the
  same domain (`/blog/*`) is preferable to a subdomain for SEO.
- **Customer success stories** — replace the placeholder testimonials in
  `LandingPage.tsx` with real quotes once they are available; real names
  and business names carry more weight than anonymous quotes.
- **Per-trade landing pages** — dedicated pages like `/for-mechanics`,
  `/for-electricians`, `/for-plumbers` with the trade-specific feature
  list and FAQs targeting trade-specific keywords. Add each to the
  sitemap.

### Technical
- **Image optimisation** — add a hero image and export it as WebP with a
  `<picture>` element and descriptive alt text; Google ranks pages with
  relevant imagery higher.
- **Core Web Vitals** — the main SPA chunk is ~1.1MB. Further code
  splitting on the landing page would improve LCP. Consider extracting
  only the marketing-specific bundle for `/`, `/trades`, `/privacy`.
- **Pre-rendering or SSR** — the current SPA emits only an empty `#root`
  div on first byte. Googlebot handles JS but many social crawlers do not,
  which is why the Open Graph / Twitter Card tags live in the static
  `index.html`. For maximum reach, consider pre-rendering the three
  public pages at build time (`vite-plugin-ssr`, `prerender-spa-plugin`
  or similar).
- **hreflang** — only relevant if we launch in other regions (`en-AU`,
  `en-GB`).
- **Structured FAQs** — adding a `FAQPage` schema to the landing page
  with real customer questions can earn FAQ-style rich results.

### Off-page
- **Backlinks** — list OraInvoice in NZ business directories (MBIE
  business directory, NZBN, Chamber of Commerce listings, industry
  association directories for MTA, Master Builders, Master Electricians,
  Master Plumbers).
- **Google Business Profile** — useful for local searches and map results.
- **Product Hunt / Hacker News launch** — one-time spike in backlinks
  and direct traffic.

## Adding New Public Pages

When adding a new public, indexable page:

1. Place it under `frontend/src/pages/public/`.
2. Register the route in `App.tsx` **outside** `<NoIndexRoute />` — ideally
   as a sibling of the existing `/privacy` and `/trades` routes.
3. Call `usePageMeta` in the page component with a unique `title`,
   `description`, `canonical` URL (using `https://one.oraflows.co.nz`),
   and page-appropriate JSON-LD (usually `BreadcrumbList`).
4. Add an `Allow:` line to `frontend/public/robots.txt`.
5. Add a `<url>` entry to `frontend/public/sitemap.xml` with an appropriate
   `priority` and `changefreq`.
6. Re-submit the sitemap in Google Search Console.

## Adding New Authenticated Routes

No action needed — any route rendered inside `<OrgLayout />` or
`<AdminLayout />` automatically receives the noindex meta tag, and the
nginx regex block already matches all known authenticated prefixes.

If a new authenticated prefix is added (e.g. `/new-feature`):

1. Add the prefix to the regex in the nginx `location ~` block in
   `nginx/nginx.conf`.
2. Add a matching `Disallow:` line in `frontend/public/robots.txt`.

## Files Changed

| File | Change |
|---|---|
| `frontend/index.html` | Full SEO `<head>` with meta, OG, Twitter, canonical, JSON-LD Organization + WebSite |
| `frontend/src/hooks/usePageMeta.ts` | **New.** Per-page meta-management hook |
| `frontend/src/components/common/NoIndexRoute.tsx` | **New.** Route wrapper for noindex pages |
| `frontend/src/pages/public/LandingPage.tsx` | Added `usePageMeta` + SoftwareApplication JSON-LD |
| `frontend/src/pages/public/TradesPage.tsx` | Added `usePageMeta` + BreadcrumbList JSON-LD |
| `frontend/src/pages/public/WorkshopPage.tsx` | **New (2026-05-12).** `/workshop` SEO landing page for NZ mechanics — hero with CarJam/WOF/COF trust badges, 11-card feature grid, Made-for-NZ section, switch-reasons comparison, $60 NZD pricing card, 8-item FAQ accordion backed by `FAQPage` JSON-LD, `SoftwareApplication` + `BreadcrumbList` structured data. Aliases `/mechanics` and `/garage` redirect to `/workshop` via `<Navigate replace>`. |
| `frontend/src/pages/public/PrivacyPage.tsx` | Added `usePageMeta` + BreadcrumbList JSON-LD |
| `frontend/src/layouts/OrgLayout.tsx` | Calls `usePageMeta({ noindex: true })` |
| `frontend/src/layouts/AdminLayout.tsx` | Calls `usePageMeta({ noindex: true })` |
| `frontend/src/App.tsx` | Wraps auth / kiosk / portal / pay routes in `<NoIndexRoute />`; registers `/workshop` public route plus `/mechanics` and `/garage` alias redirects |
| `frontend/public/robots.txt` | **New.** Allow public, disallow everything else, reference sitemap. `/workshop`, `/mechanics`, `/garage` explicitly allowed |
| `frontend/public/sitemap.xml` | **New.** Four public URLs: `/` (1.0), `/workshop` (0.9, weekly), `/trades` (0.8), `/privacy` (0.4) |
| `nginx/nginx.conf` | `X-Robots-Tag` on `/api/` + auth'd paths; explicit robots.txt / sitemap.xml serving |
