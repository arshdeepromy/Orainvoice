# Design Document: OraInvoice Public Landing Page

## Overview

This feature adds three public-facing pages to the existing React SPA — a marketing Landing Page (`/`), a Privacy Policy page (`/privacy`), and a Supported Trades page (`/trades`) — along with two new backend endpoints for demo request submission and privacy policy content management. The pages are accessible without authentication and share a common design system (LandingHeader, LandingFooter, DemoRequestModal). Authenticated users visiting `/` are redirected to their role-appropriate dashboard.

The backend adds:
- `POST /api/v1/public/demo-request` — accepts demo form data, sends email via existing EmailProvider SMTP, rate-limited
- `GET /api/v1/public/privacy-policy` — returns stored privacy policy content from `platform_settings`
- `PUT /api/v1/admin/privacy-policy` — global admin endpoint to save/update privacy policy content

The existing `GET /api/v1/public/branding` endpoint (already consumed by `PlatformBrandingContext`) is reused for landing page branding.

### Key Design Decisions

1. **Reuse PlatformBrandingContext** — The `PlatformBrandingProvider` already wraps the entire app and fetches from `GET /api/v1/public/branding`. Public pages use `usePlatformBranding()` directly rather than creating a separate fetch.

2. **Store privacy policy in `platform_settings`** — Uses the existing JSONB key-value table with a new key `privacy_policy`. No migration needed. Follows the same pattern as `terms_and_conditions` and `announcement_banner`.

3. **EmailProvider-based SMTP for demo requests** — Uses the same `EmailProvider` model and failover pattern from `app/modules/email_providers/service.py` (same as invoice and quote emails). Does not use the old `brevo.py` integration.

4. **Redis-based rate limiting for demo requests** — 5 requests per IP per hour, using the existing Redis instance. Implemented as a simple key with TTL, not the middleware rate limiter (which is per-user/per-org).

5. **Auth-aware routing at `/`** — The existing `GuestOnly` wrapper in `App.tsx` already redirects authenticated users by role. The landing page route is placed inside the `GuestOnly` wrapper, and `/privacy` and `/trades` are placed outside it (always accessible).

6. **Default hardcoded privacy policy** — The frontend ships with a complete NZ Privacy Act 2020 compliant default policy. If the API returns no custom content, the default renders. This ensures the privacy page always has content even before the admin configures it.

## Architecture

```mermaid
graph TB
    subgraph "Frontend (React SPA)"
        A[App.tsx Router] --> B{Auth State?}
        B -->|Unauthenticated| C[GuestOnly Wrapper]
        C --> D[LandingPage /]
        B -->|Authenticated| E[Redirect by Role]
        E -->|org_admin/salesperson| F[/dashboard]
        E -->|global_admin| G[/admin/dashboard]
        E -->|kiosk| H[/kiosk]
        
        A --> I[PrivacyPage /privacy]
        A --> J[TradesPage /trades]
        
        D --> K[LandingHeader]
        D --> L[LandingFooter]
        D --> M[DemoRequestModal]
        I --> K
        I --> L
        J --> K
        J --> L
        J --> M
        
        K --> N[usePlatformBranding]
    end
    
    subgraph "Backend (FastAPI)"
        O[POST /api/v1/public/demo-request]
        P[GET /api/v1/public/privacy-policy]
        Q[PUT /api/v1/admin/privacy-policy]
        R[GET /api/v1/public/branding]
        
        O --> S[EmailProvider SMTP]
        O --> T[Redis Rate Limit]
        P --> U[platform_settings table]
        Q --> U
        R --> V[PlatformBranding Config]
    end
    
    M -->|POST| O
    I -->|GET| P
    N -->|GET| R
```

## Components and Interfaces

### Frontend Components

#### Shared Components (`frontend/src/components/public/`)

**LandingHeader**
- Sticky top navigation bar used on all three public pages
- Displays platform logo/name from `usePlatformBranding()` with "OraInvoice" fallback
- Navigation links: Features (anchor `#features`), Trades (`/trades`), Pricing (anchor `#pricing`), Privacy (`/privacy`)
- Login button → `/login`, Sign Up button → `/signup`
- Mobile responsive: hamburger menu below 768px with slide-out nav
- Props: none (reads branding from context)

**LandingFooter**
- Footer used on all three public pages
- Columns: Product links, Legal links (Privacy, Terms), Contact info, Copyright
- Displays platform name from branding context
- Copyright: `© {currentYear} {platformName || 'Oraflows Ltd'}. All rights reserved.`
- Props: none (reads branding from context)

**DemoRequestModal**
- Modal popup with demo request form
- Fields: Full Name (required), Business Name (required), Email (required, validated), Phone (optional), Message (optional)
- Hidden honeypot field (`website` — hidden via CSS `position: absolute; left: -9999px`)
- Description text explaining the demo process
- Submits to `POST /api/v1/public/demo-request`
- Shows success message on 200, error message on failure with fallback email
- Props: `open: boolean`, `onClose: () => void`

#### Page Components (`frontend/src/pages/public/`)

**LandingPage** (`frontend/src/pages/public/LandingPage.tsx`)
- Sections in order: Hero, Features (8 category groups), Pricing, Testimonials, CTA
- Hero: dark gradient background (slate-900 → indigo-900), headline, subheadline, "Get Started" and "Request Free Demo" buttons, "100% NZ Hosted" badge
- Features: alternating white/gray-50 backgrounds, 3-column grid on lg, 1-column on mobile
- Pricing: single "Mech Pro Plan" card with placeholder price, feature checklist, "Start Free Trial" and "Request Free Demo" buttons
- Testimonials: 3 placeholder cards with quote, name, business name
- CTA: dark gradient, heading, signup button
- Smooth scroll via `scroll-behavior: smooth` on `<html>`

**PrivacyPage** (`frontend/src/pages/public/PrivacyPage.tsx`)
- Fetches custom content from `GET /api/v1/public/privacy-policy`
- If custom content exists: renders Markdown content using a simple Markdown-to-HTML renderer
- If no custom content: renders the hardcoded default NZ Privacy Act 2020 policy
- Table of contents with anchor links at top
- Max content width: `max-w-3xl` (768px)
- Displays "Last Updated" date from API response or hardcoded date

**TradesPage** (`frontend/src/pages/public/TradesPage.tsx`)
- Hero section with heading about multi-trade support
- Trade cards in a grid: icon, trade name, status badge ("Available" green / "Coming Soon" amber), description
- Available trades: "Get Started" → `/signup`
- Coming Soon trades: "Request Free Demo" → opens DemoRequestModal
- Explanatory section about core features working for all business types

### Backend Endpoints

#### `POST /api/v1/public/demo-request`

```python
# Router: app/modules/public/router.py
# No auth required

class DemoRequestPayload(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    business_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)
    message: str | None = Field(None, max_length=2000)
    website: str | None = None  # honeypot field

class DemoRequestResponse(BaseModel):
    success: bool
    message: str
```

**Flow:**
1. Check honeypot field — if `website` is non-empty, return 200 with success (silent rejection)
2. Check Redis rate limit: key `demo_request:{client_ip}`, max 5 per hour
3. If rate limited, return 429
4. Query `EmailProvider` table for active providers with credentials, ordered by priority
5. Build MIME email with demo request details
6. Send to `arshdeep.romy@gmail.com` using first available provider, failover to next on error
7. Return 200 on success, 500 on all-providers-failed

#### `GET /api/v1/public/privacy-policy`

```python
class PrivacyPolicyResponse(BaseModel):
    content: str | None  # Markdown content, null if no custom policy saved
    last_updated: str | None  # ISO timestamp
```

**Flow:**
1. Query `platform_settings` where `key = 'privacy_policy'`
2. If row exists, return `value.content` and `updated_at`
3. If no row, return `{ content: null, last_updated: null }`

#### `PUT /api/v1/admin/privacy-policy`

```python
# Requires global_admin role

class PrivacyPolicyUpdatePayload(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)

class PrivacyPolicyUpdateResponse(BaseModel):
    success: bool
    last_updated: str
```

**Flow:**
1. Upsert into `platform_settings` with key `privacy_policy`
2. Value: `{ "content": "<markdown>", "updated_by": "<user_id>" }`
3. `updated_at` is auto-set by the column default
4. Write audit log entry
5. Return success with timestamp

### Route Configuration (App.tsx)

```tsx
// Public pages — outside RequireAuth, outside GuestOnly
<Route path="/privacy" element={<SafePage name="privacy"><PrivacyPage /></SafePage>} />
<Route path="/trades" element={<SafePage name="trades"><TradesPage /></SafePage>} />

// Landing page — inside GuestOnly (redirects authenticated users)
<Route element={<GuestOnly />}>
  <Route path="/" element={<SafePage name="landing"><LandingPage /></SafePage>} />
  {/* existing auth routes... */}
</Route>
```

The `/privacy` and `/trades` routes are placed before the `GuestOnly` wrapper so they're accessible regardless of auth state. The `/` route stays inside `GuestOnly` which already handles role-based redirects via the existing `GuestOnly` component.

### Global Admin Privacy Policy Editor

Added as a new tab "Privacy Policy" in the existing `frontend/src/pages/admin/Settings.tsx` component, following the same pattern as the existing "T&C" tab:

- Textarea with Markdown input
- Preview button that renders the Markdown as HTML
- Save button that calls `PUT /api/v1/admin/privacy-policy`
- Displays "Last Updated" timestamp after save
- "Reset to Default" button that clears custom content (privacy page falls back to hardcoded default)

## Data Models

### `platform_settings` Table (Existing)

No migration needed. A new key `privacy_policy` is added at runtime when the admin first saves custom content.

| Column | Type | Value for privacy_policy key |
|--------|------|------------------------------|
| `key` | VARCHAR(100) | `'privacy_policy'` |
| `value` | JSONB | `{ "content": "<markdown>", "updated_by": "<uuid>" }` |
| `version` | INT | `1` (incremented on each save) |
| `updated_at` | TIMESTAMPTZ | Auto-set on save |

### Demo Request Email

No database storage for demo requests. The email is sent directly via SMTP. The email body contains:

```
Subject: New Demo Request from {full_name} — {business_name}

New demo request received:

Name: {full_name}
Business: {business_name}
Email: {email}
Phone: {phone or 'Not provided'}

Message:
{message or 'No message provided'}

---
Sent from OraInvoice Landing Page
IP: {client_ip}
Timestamp: {utc_now}
```

### Redis Rate Limit Key

```
Key:    demo_request_rate:{client_ip}
Value:  integer (request count)
TTL:    3600 seconds (1 hour)
```

Incremented on each valid (non-honeypot) request. If value >= 5, return 429.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Auth-aware redirect by role

*For any* authenticated user visiting `/`, the system SHALL redirect to the correct dashboard based on their role: org-level users (org_admin, salesperson) → `/dashboard`, global_admin → `/admin/dashboard`, kiosk → `/kiosk`.

**Validates: Requirements 1.2**

### Property 2: Branding display with fallback

*For any* branding API response, the Landing_Header and Landing_Footer SHALL display the platform name from the response if present, or fall back to "OraInvoice" if the platform name is empty or null. Similarly, the logo SHALL display from the response URL if present, or fall back to the text "OraInvoice".

**Validates: Requirements 17.2, 17.3**

### Property 3: Branding API failure graceful degradation

*For any* failure of the branding API (network error, 500, timeout), the Landing_Page SHALL render with hardcoded defaults (logo text "OraInvoice", company name "Oraflows Limited") without errors or blank sections.

**Validates: Requirements 17.5**

### Property 4: Demo form submission with valid data

*For any* valid demo request form data (non-empty name, non-empty business name, valid email), submitting the form SHALL result in a POST request to `/api/v1/public/demo-request` with the correct payload fields.

**Validates: Requirements 18.5**

### Property 5: Demo request rate limiting

*For any* IP address, after 5 successful demo request submissions within a 1-hour window, subsequent requests from that IP SHALL be rejected with a 429 status code.

**Validates: Requirements 18.8**

### Property 6: Honeypot bot rejection

*For any* demo request submission where the honeypot field (`website`) is non-empty, the backend SHALL return a 200 success response without sending an email, silently discarding the submission.

**Validates: Requirements 18.11**

### Property 7: Trade card CTA matches availability status

*For any* trade card, if the trade status is "Available" then the card SHALL display a "Get Started" button linking to `/signup`, and if the status is "Coming Soon" then the card SHALL display a "Request Free Demo" button that opens the DemoRequestModal.

**Validates: Requirements 20.5, 20.6**

### Property 8: Privacy policy content round-trip

*For any* valid Markdown string saved via `PUT /api/v1/admin/privacy-policy`, subsequently fetching via `GET /api/v1/public/privacy-policy` SHALL return the same content string and a non-null `last_updated` timestamp.

**Validates: Requirements 21.3**

### Property 9: Privacy policy default fallback

*For any* state where no custom privacy policy has been saved (API returns `content: null`), the Privacy_Page SHALL render the complete default hardcoded NZ Privacy Act 2020 policy without errors.

**Validates: Requirements 21.6**

## Error Handling

### Frontend

| Scenario | Handling |
|----------|----------|
| Branding API fails | `PlatformBrandingContext` already catches errors and uses `DEFAULTS`. No change needed. |
| Privacy policy API fails | Show default hardcoded policy. Log error to console. |
| Demo request API returns 429 | Show message: "Too many requests. Please try again later." |
| Demo request API returns 500 | Show message: "Something went wrong. Please email us directly at arshdeep.romy@gmail.com" |
| Demo request network error | Same as 500 handling. |
| Invalid email format in demo form | Client-side validation prevents submission. HTML5 `type="email"` + regex check. |

### Backend

| Scenario | Handling |
|----------|----------|
| No active EmailProvider configured | Return 500 with `{ success: false, message: "Email service not configured" }` |
| All SMTP providers fail | Return 500 with `{ success: false, message: "Failed to send email" }`. Log error with provider details. |
| Redis unavailable for rate limiting | Skip rate limiting (fail open). Log warning. Allow the request through. |
| Invalid demo request payload | Return 422 (FastAPI automatic Pydantic validation). |
| Privacy policy content too large | Pydantic validation rejects content > 100,000 characters. Return 422. |
| Database error on privacy policy save | Return 500. Transaction auto-rolls-back via `session.begin()`. |

## Testing Strategy

### Property-Based Tests (Hypothesis)

Property-based testing is appropriate for this feature because several acceptance criteria express universal properties over input domains (role-based redirects, branding fallbacks, rate limiting, honeypot filtering, content round-trips).

**Library:** Hypothesis (Python, already used in the project — see `.hypothesis/` directory)
**Minimum iterations:** 100 per property test
**Tag format:** `Feature: landing-page, Property {number}: {title}`

Properties to implement as PBT:
- Property 1: Auth redirect by role — generate random users with roles, verify redirect target
- Property 4: Demo form validation — generate random valid/invalid form payloads, verify API behavior
- Property 5: Rate limiting — generate sequences of requests, verify cutoff at 5
- Property 6: Honeypot rejection — generate random honeypot values, verify silent rejection
- Property 8: Privacy policy round-trip — generate random Markdown strings, verify save/load identity

Properties 2, 3, 7, 9 are better suited to example-based tests because they test React component rendering behavior which is more naturally tested with specific scenarios in React Testing Library.

### Unit Tests

- LandingHeader: renders logo, nav links, login/signup buttons; mobile menu toggle
- LandingFooter: renders privacy link, copyright with current year
- DemoRequestModal: form validation (required fields, email format), honeypot field hidden, success/error states
- LandingPage: all sections render (hero, features, pricing, testimonials, CTA)
- PrivacyPage: renders default policy when API returns null, renders custom content when API returns data
- TradesPage: renders trade cards with correct status badges and CTAs
- Auth redirect: org user → /dashboard, global_admin → /admin/dashboard, kiosk → /kiosk

### Integration Tests

- `POST /api/v1/public/demo-request`: valid submission sends email, honeypot rejection, rate limiting, missing fields return 422
- `GET /api/v1/public/privacy-policy`: returns null when no custom policy, returns content after save
- `PUT /api/v1/admin/privacy-policy`: requires global_admin role, saves content, returns timestamp
- Branding API reuse: verify `GET /api/v1/public/branding` returns expected shape for landing page consumption

### Manual Testing

- WCAG 2.1 AA colour contrast verification (requires assistive technology tools)
- Responsive layout at 320px, 768px, 1024px, 1920px viewports
- Smooth scroll behavior on anchor links
- Mobile hamburger menu interaction
- Visual regression on all three pages
