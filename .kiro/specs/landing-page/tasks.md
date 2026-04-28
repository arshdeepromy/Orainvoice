# Implementation Plan: OraInvoice Public Landing Page

## Overview

Add three public-facing pages (Landing Page at `/`, Privacy Policy at `/privacy`, Supported Trades at `/trades`) with a demo request flow, privacy policy admin editor, and shared public page components. Implementation proceeds backend-first (endpoints needed by frontend), then shared components, then page components, then routing, then admin editor, then tests.

## Tasks

- [x] 1. Create backend public endpoints for demo request and privacy policy
  - [x] 1.1 Create the public landing page router at `app/modules/landing/router.py`
    - Create `app/modules/landing/__init__.py`
    - Create `app/modules/landing/router.py` with a public APIRouter (no auth dependencies)
    - Create `app/modules/landing/schemas.py` with Pydantic models:
      - `DemoRequestPayload`: `full_name` (str, min 1, max 200), `business_name` (str, min 1, max 200), `email` (EmailStr), `phone` (str | None, max 50), `message` (str | None, max 2000), `website` (str | None — honeypot)
      - `DemoRequestResponse`: `success` (bool), `message` (str)
      - `PrivacyPolicyResponse`: `content` (str | None), `last_updated` (str | None)
      - `PrivacyPolicyUpdatePayload`: `content` (str, min 1, max 100000)
      - `PrivacyPolicyUpdateResponse`: `success` (bool), `last_updated` (str)
    - _Requirements: 18.5, 18.6, 18.7, 21.3, 21.4, 21.9_

  - [x] 1.2 Implement `POST /api/v1/public/demo-request` endpoint
    - Check honeypot field — if `website` is non-empty, return 200 with success (silent rejection)
    - Check Redis rate limit: key `demo_request_rate:{client_ip}`, max 5 per hour, TTL 3600s
    - If rate limited, return 429 with message
    - If Redis unavailable, skip rate limiting (fail open), log warning
    - Query `EmailProvider` table for active providers with credentials, ordered by priority
    - Build MIME email with demo request details (name, business, email, phone, message, IP, timestamp)
    - Send to `arshdeep.romy@gmail.com` using first available provider, failover to next on error
    - Return 200 on success, 500 on all-providers-failed
    - _Requirements: 18.5, 18.6, 18.7, 18.8, 18.11_

  - [x] 1.3 Implement `GET /api/v1/public/privacy-policy` endpoint
    - Query `platform_settings` where `key = 'privacy_policy'`
    - If row exists, return `value["content"]` and `updated_at` as ISO string
    - If no row, return `{ content: null, last_updated: null }`
    - No auth required
    - _Requirements: 21.4, 21.5, 21.9_

  - [x] 1.4 Implement `PUT /api/v1/admin/privacy-policy` endpoint
    - Require `global_admin` role via `require_role("global_admin")` dependency
    - Upsert into `platform_settings` with key `privacy_policy`
    - Value: `{ "content": "<markdown>", "updated_by": "<user_id>" }`
    - `updated_at` auto-set by column default
    - Write audit log entry
    - Return success with timestamp
    - Use `flush()` not `commit()` (session.begin() auto-commits)
    - _Requirements: 21.1, 21.2, 21.3, 21.7_

  - [x] 1.5 Register the landing page routers in `app/main.py`
    - Import `public_router` and `admin_router` from `app.modules.landing.router`
    - Register `public_router` at prefix `/api/v1/public` with tags `["public-landing"]`
    - Register `admin_router` at prefix `/api/v1/admin` with tags `["admin"]`
    - _Requirements: 18.7, 21.4_

- [x] 2. Checkpoint — Verify backend endpoints
  - Ensure all tests pass, ask the user if questions arise.
  - Test commands:
    - Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_landing_page.py -x -v`

- [x] 3. Create shared public page components
  - [x] 3.1 Create `LandingHeader` component at `frontend/src/components/public/LandingHeader.tsx`
    - Sticky top navigation bar with dark background
    - Display platform logo/name from `usePlatformBranding()` with "OraInvoice" fallback
    - Navigation links: Features (`#features` anchor), Trades (`/trades`), Pricing (`#pricing` anchor), Privacy (`/privacy`)
    - Login button → `/login`, Sign Up button → `/signup`
    - Mobile responsive: hamburger menu below 768px with slide-out nav panel
    - Use semantic `<nav>` element
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 15.7, 17.2, 17.3_

  - [x] 3.2 Create `LandingFooter` component at `frontend/src/components/public/LandingFooter.tsx`
    - Footer with columns: Product links, Legal links (Privacy `/privacy`, Terms), Contact info, Copyright
    - Display platform name from `usePlatformBranding()` with "OraInvoice" fallback
    - Copyright: `© {currentYear} {platformName || 'Oraflows Ltd'}. All rights reserved.`
    - Responsive: stack columns vertically below 768px
    - Use semantic `<footer>` element
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 15.7, 17.3_

  - [x] 3.3 Create `DemoRequestModal` component at `frontend/src/components/public/DemoRequestModal.tsx`
    - Modal popup with form fields: Full Name (required), Business Name (required), Email (required, validated), Phone (optional), Message (optional)
    - Hidden honeypot field (`website` — hidden via CSS `position: absolute; left: -9999px`)
    - Description text explaining the demo process
    - Submit to `POST /api/v1/public/demo-request` using axios (no auth header)
    - Show success message on 200: "Thank you! Our team will be in touch within 24 hours to schedule your demo."
    - Show error on 429: "Too many requests. Please try again later."
    - Show error on failure: "Something went wrong. Please email us directly at arshdeep.romy@gmail.com"
    - Use safe API consumption patterns (`res.data?.success`, etc.)
    - Props: `open: boolean`, `onClose: () => void`
    - _Requirements: 18.2, 18.3, 18.4, 18.5, 18.9, 18.10, 18.11_

  - [x] 3.4 Create `frontend/src/components/public/index.ts` barrel export
    - Export LandingHeader, LandingFooter, DemoRequestModal
    - _Requirements: N/A (code organisation)_

- [x] 4. Create the Landing Page component
  - [x] 4.1 Create `LandingPage` at `frontend/src/pages/public/LandingPage.tsx`
    - Wrap in LandingHeader + LandingFooter
    - Hero section: dark gradient background (slate-900 → indigo-900), headline about automotive businesses, subheadline, "Get Started" → `/signup`, "Request Free Demo" → opens DemoRequestModal, "100% NZ Hosted" badge
    - Feature sections: 8 category groups (Core, Automotive-Specific, Sales & Quoting, Operations, Inventory, Finance, Compliance, Additional) with icons, names, descriptions
    - Alternating white/gray-50 backgrounds per category
    - 3-column grid on lg, 1-column on mobile
    - Pricing section: "Mech Pro Plan" card with placeholder price, feature checklist, "Start Free Trial" → `/signup`, "Request Free Demo" → DemoRequestModal, NZD + GST note
    - Testimonials section: 3 placeholder cards with quote, name, business name (with code comment to replace with real testimonials)
    - CTA section: dark gradient, heading, signup button
    - Smooth scroll via `scroll-behavior: smooth` on `<html>` element
    - Use semantic HTML (`<main>`, `<section>`, `<h1>`–`<h3>`)
    - Responsive from 320px to 1920px
    - _Requirements: 1.1, 1.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 18.1, 19.1, 19.2, 19.3_

- [x] 5. Create the Privacy Policy page component
  - [x] 5.1 Create `PrivacyPage` at `frontend/src/pages/public/PrivacyPage.tsx`
    - Wrap in LandingHeader + LandingFooter
    - Fetch custom content from `GET /api/v1/public/privacy-policy` with AbortController cleanup
    - If custom content exists (`content` is non-null): render Markdown content using a simple Markdown-to-HTML renderer
    - If no custom content (`content` is null): render the hardcoded default NZ Privacy Act 2020 policy covering all 13 IPPs, data collection disclosure, breach notification, data portability/deletion, contact/complaints, children's data, data sovereignty
    - Table of contents with anchor links at top
    - Max content width: `max-w-3xl` (768px), min body font 16px
    - Display "Last Updated" date from API response or hardcoded date
    - Use safe API patterns: guard `res.data?.content`, handle fetch errors gracefully (show default policy)
    - Use semantic HTML headings, numbered lists, readable typography
    - _Requirements: 1.5, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 11.11, 11.12, 11.13, 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.3, 14.4, 16.1, 16.2, 16.3, 17.4, 19.4, 19.5, 21.5, 21.6, 21.8_

- [x] 6. Create the Trades page component
  - [x] 6.1 Create `TradesPage` at `frontend/src/pages/public/TradesPage.tsx`
    - Wrap in LandingHeader + LandingFooter
    - Hero section with heading about multi-trade support
    - Trade cards in a responsive grid: icon, trade name, status badge ("Available" green / "Coming Soon" amber), description
    - Available trades: Automotive & Transport (full description with CarJam, WOF, odometer, job cards), General Invoicing (core features for any business)
    - Coming Soon trades: Plumbing & Gas, Electrical & Mechanical (with descriptions)
    - Available cards: "Get Started" → `/signup`
    - Coming Soon cards: "Request Free Demo" → opens DemoRequestModal
    - Explanatory section below cards about core features working for all business types
    - Same design system as Landing and Privacy pages
    - _Requirements: 1.6, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9_

- [x] 7. Configure routes in App.tsx
  - [x] 7.1 Update `frontend/src/App.tsx` with public page routes
    - Add lazy imports for LandingPage, PrivacyPage, TradesPage from `@/pages/public/`
    - Add `/privacy` and `/trades` routes OUTSIDE the `GuestOnly` wrapper (accessible regardless of auth state), wrapped in `<SafePage>`
    - Add `/` route for LandingPage INSIDE the `GuestOnly` wrapper (redirects authenticated users by role)
    - Ensure existing `GuestOnly` component handles role-based redirects: org users → `/dashboard`, global_admin → `/admin/dashboard`, kiosk → `/kiosk`
    - Add `scroll-behavior: smooth` to the `<html>` element (via index.css or inline)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 8. Checkpoint — Verify frontend pages render correctly
  - Ensure all tests pass, ask the user if questions arise.
  - Test commands:
    - Frontend: `npx vitest run --reporter=verbose` (from `frontend/` directory)

- [x] 9. Add Privacy Policy editor tab to Global Admin Settings
  - [x] 9.1 Add "Privacy Policy" tab to `frontend/src/pages/admin/Settings.tsx`
    - Add a new tab "Privacy Policy" following the same pattern as the existing "T&C" tab
    - Textarea with Markdown input for editing privacy policy content
    - Preview button that renders the Markdown as HTML
    - Save button that calls `PUT /api/v1/admin/privacy-policy`
    - Display "Last Updated" timestamp after save
    - "Reset to Default" button that clears custom content (sets content to empty string or deletes the key)
    - Fetch current content on tab mount from `GET /api/v1/public/privacy-policy`
    - Use safe API patterns: `res.data?.content ?? ''`, AbortController cleanup
    - _Requirements: 21.1, 21.2, 21.3, 21.7, 21.8_

- [x] 10. Checkpoint — Verify admin editor and full flow
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Write backend tests
  - [x] 11.1 Create test file `tests/test_landing_page.py` with unit and integration tests
    - Test `POST /api/v1/public/demo-request` with valid data returns 200
    - Test `POST /api/v1/public/demo-request` with missing required fields returns 422
    - Test `POST /api/v1/public/demo-request` with invalid email returns 422
    - Test honeypot rejection: non-empty `website` field returns 200 without sending email
    - Test rate limiting: 6th request within 1 hour returns 429
    - Test `GET /api/v1/public/privacy-policy` returns null content when no custom policy saved
    - Test `GET /api/v1/public/privacy-policy` returns content after save
    - Test `PUT /api/v1/admin/privacy-policy` requires global_admin role (403 for org_admin)
    - Test `PUT /api/v1/admin/privacy-policy` saves content and returns timestamp
    - Test `PUT /api/v1/admin/privacy-policy` with content exceeding 100000 chars returns 422
    - _Requirements: 18.5, 18.6, 18.7, 18.8, 18.11, 21.3, 21.4, 21.9_

  - [x] 11.2 Write property test: Demo form validation (Property 4)
    - **Property 4: Demo form submission with valid data**
    - Generate random valid form payloads (non-empty name, non-empty business name, valid email) using Hypothesis
    - Verify POST returns 200 with `success: true`
    - **Validates: Requirements 18.5**

  - [x] 11.3 Write property test: Rate limiting (Property 5)
    - **Property 5: Demo request rate limiting**
    - Generate sequences of N requests (N drawn from 1–20) from the same IP
    - Verify first 5 succeed, all subsequent return 429
    - **Validates: Requirements 18.8**

  - [x] 11.4 Write property test: Honeypot rejection (Property 6)
    - **Property 6: Honeypot bot rejection**
    - Generate random non-empty honeypot values
    - Verify all return 200 success without triggering email send
    - **Validates: Requirements 18.11**

  - [x] 11.5 Write property test: Privacy policy round-trip (Property 8)
    - **Property 8: Privacy policy content round-trip**
    - Generate random Markdown strings (1–10000 chars)
    - Save via PUT, fetch via GET, verify content matches exactly and `last_updated` is non-null
    - **Validates: Requirements 21.3**

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Test commands:
    - Frontend: `npx vitest run --reporter=verbose` (from `frontend/` directory)
    - Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python -m pytest tests/test_landing_page.py -x -v`

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The `platform_settings` table already exists — no migration needed for privacy policy storage
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in service functions
- EmailProvider SMTP with failover follows the same pattern as invoice and quote emails
- Redis rate limiting uses a simple key with TTL, separate from the middleware rate limiter
- Frontend must follow safe API consumption patterns: `?.`, `?? []`, `?? 0`, AbortController cleanup
- Properties 2, 3, 7, 9 from the design are better suited to example-based frontend tests (React component rendering) and are covered by the unit test tasks rather than PBT
