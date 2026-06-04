# Frontend Redesign — Requirements

## Overview

Complete visual redesign of the OraInvoice frontend application. The new frontend (`frontend-v2/`) is built from scratch using the high-fidelity HTML prototypes in `OraInvoice_Handoff/` as the design reference. The existing `frontend/` remains untouched and continues serving production traffic.

## Functional Requirements

### FR-1: Zero Functionality Regression
Every page in `frontend-v2/` must preserve 100% of the functionality from its `frontend/` counterpart:
- All API calls (endpoints, methods, params, response handling)
- All form fields and validations
- All calculations (GST, totals, discounts, rounding, currency)
- All conditional rendering (role gates, module gates, feature flags, trade family gates)
- All loading, error, and empty states
- All navigation actions
- All keyboard shortcuts and accessibility features

### FR-2: Design Fidelity
Each page must match the corresponding HTML prototype in `OraInvoice_Handoff/app/`:
- Colors, spacing, typography from `ds.css` token system
- IBM Plex Sans (UI) + IBM Plex Mono (numbers/IDs/codes)
- Responsive breakpoints: 1080px, 860px, 520px
- Minimum 40-44px touch targets
- Ink sidebar with grouped navigation
- Redesigned top bar with search, branch chip, notifications, avatar

### FR-2b: Design-on-the-Go for Missing Elements
The HTML prototypes are presentation references and may NOT cover every button, modal, preview panel, receipt view, or secondary function that exists in the original page. When the original `frontend/` page has UI elements not present in the HTML prototype:
- Design those elements on the fly using the new design system tokens (`ds.css`)
- Match the visual language: same colors, radii, shadows, typography, spacing
- Use the same component patterns established in the prototype (cards, tables, badges, buttons)
- Examples of commonly missing elements: invoice HTML/PDF preview panels, POS receipt previews, print buttons, secondary action menus, inline edit forms, drag-and-drop zones, file upload areas, progress indicators, toast notifications
- Never drop functionality because the prototype doesn't show it — design it to fit the new aesthetic
- If an entire page, modal, popup, widget, or component has NO design prototype at all, design it from scratch using the token system — close the gap immediately, do not skip it

### FR-2c: Per-Page Verification (Mandatory)
After integrating each page (whether from a design prototype or designed on the fly):
1. Compare the new page against the original source file line by line
2. Verify every button is present and wired to its handler
3. Verify every API call is preserved with correct endpoint, method, and params
4. Verify every form field, validation, and submit path exists
5. Verify every conditional render (role gate, module gate, feature flag, loading/error/empty state)
6. Verify every calculation (totals, tax, discounts) is copied verbatim
7. If anything is missing — add it immediately before moving to the next page

### FR-2d: Final Audit
After all pages are complete, perform a comprehensive audit:
1. Walk through every entry in `docs/REDESIGN_TRACKER.md` — confirm each is ✅
2. Cross-reference every route in the original `frontend/` router against `frontend-v2/` — no missing routes
3. Cross-reference every modal/popup/drawer — no missing dialogs
4. Cross-reference every shared component used across pages — no missing widgets
5. Identify any pages, modals, or UI elements that exist in `frontend/` but were not in the tracker — add and implement them
6. Document the audit results in `docs/REDESIGN_AUDIT.md`

### FR-3: Independent Build
`frontend-v2/` must be a fully self-contained project:
- Own package.json, vite.config.ts, tsconfig.json, tailwind config
- No imports from `frontend/` — all shared code is copied
- Served at `/new/` path prefix for side-by-side testing
- Same backend API endpoints (no backend changes)

### FR-4: Side-by-Side Deployment
Both frontends run simultaneously:
- Existing frontend at `localhost/` (unchanged)
- New frontend at `localhost/new/` (via nginx location block)
- Shared backend API at `/api/`

## Non-Functional Requirements

### NFR-1: No Production Impact
The redesign must not affect the running production system in any way. No changes to `frontend/`, `docker-compose.yml`, or nginx configs that serve the existing app.

### NFR-2: Accessibility
Preserve all existing `aria-*` attributes, `role` attributes, and `data-testid` hooks. Add focus rings and keyboard navigation per the design spec.

### NFR-3: Performance
- Code-split by route (lazy imports)
- Chunk heavy deps (Recharts, Stripe, Firebase, DnD)
- Target < 600KB main bundle

## Design Source Reference

- `OraInvoice_Handoff/README.md` — full design specification
- `OraInvoice_Handoff/IMPLEMENTATION_CHECKLIST.md` — phased guide
- `OraInvoice_Handoff/app/ds.css` — design system tokens (single source of truth)
- `OraInvoice_Handoff/app/shell.js` — app shell structure reference
- `OraInvoice_Handoff/app/*.html` — per-page prototypes (150+ screens)
- `OraInvoice_Handoff/app/fleet/` — fleet portal (22 screens)

## Scope

- 294 pages/screens
- 48 modals/popups/drawers
- 342 total items tracked in `docs/REDESIGN_TRACKER.md`
