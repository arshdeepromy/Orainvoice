# User Test Scenarios — Platform Feature Gaps

Manual test scenarios for the 63 requirements implemented in the platform-feature-gaps spec. Organised by functional area for efficient testing sessions.

## Test Documents

| Document | Area | Requirements | Scenarios |
|----------|------|-------------|-----------|
| [01-portal-landing-and-display.md](01-portal-landing-and-display.md) | Portal landing page, branding, summary cards | Req 1-6, 61-62 | 18 |
| [02-portal-security.md](02-portal-security.md) | Token validation, rate limiting, CSRF, sessions | Req 7-11, 39-43 | 22 |
| [03-portal-token-lifecycle.md](03-portal-token-lifecycle.md) | Token generation, delivery, TTL, recovery | Req 12-15, 52 | 16 |
| [04-portal-features.md](04-portal-features.md) | Jobs, claims, PDF, documents, profile, bookings, quotes | Req 16-24, 49-51 | 28 |
| [05-portal-ux-polish.md](05-portal-ux-polish.md) | Mobile links, pagination, i18n, refund status, loyalty, SMS | Req 25-30, 63 | 18 |
| [06-portal-compliance.md](06-portal-compliance.md) | Cookie consent, DSAR, portal enable/disable, analytics | Req 44-48 | 14 |
| [07-branch-transfers.md](07-branch-transfers.md) | Reject, product search, receive, detail, audit, partial, notifications | Req 31-35, 53-55 | 22 |
| [08-staff-schedule.md](08-staff-schedule.md) | Entry modal, drag-drop, recurring, templates, leave, print, mobile | Req 36-38, 56-60 | 20 |

## Prerequisites

- A test org with at least 1 customer, 2 invoices, 1 quote, 1 vehicle, 1 booking
- Customer has `enable_portal = true` and a valid `portal_token`
- Org has Stripe Connect configured (for payment tests)
- At least 2 locations configured (for transfer tests)
- At least 2 active staff members (for schedule tests)
- Access to the admin panel as `org_admin`

## Test Execution Notes

- **Portal tests**: Open the portal link in an incognito window to avoid session conflicts
- **Security tests**: Use browser dev tools Network tab to inspect headers and cookies
- **Mobile tests**: Use Chrome DevTools device emulation or a real mobile device
- **Rate limit tests**: Use a script or rapid manual clicking — hard to hit 60/min manually
