# Frontend Redesign — Design

## Architecture

### Project Independence
`frontend-v2/` is a standalone Vite + React + Tailwind project. It shares NO code with `frontend/` at build time. Logic, types, hooks, and utilities are copied verbatim (not imported).

### Routing Strategy
- `base: '/new/'` in vite.config.ts — all routes prefixed with `/new/`
- React Router with the same route structure as the existing app
- Lazy-loaded route components for code splitting
- API calls go to `/api/v1/` and `/api/v2/` (same backend, no prefix change needed since nginx proxies)

### Design Token System
Tokens from `OraInvoice_Handoff/app/ds.css` are mapped into Tailwind v4's `@theme` CSS-variable system in `src/styles/tokens.css`:

```css
@theme {
  --color-accent: #2F62F0;
  --color-accent-press: #2450D0;
  --color-accent-soft: rgba(47, 98, 240, 0.12);
  --color-ink: #0B1220;
  --color-canvas: #F5F6F8;
  --color-card: #FFFFFF;
  --color-border: #E8EBF0;
  --color-border-strong: #D7DCE3;
  --color-text: #111722;
  --color-muted: #687283;
  --color-muted-2: #97A0AE;
  --color-ok: #1F8A5B;
  --color-ok-soft: #E4F4EC;
  --color-warn: #B5740F;
  --color-warn-soft: #FBEFD9;
  --color-danger: #C8412F;
  --color-danger-soft: #FBE7E3;
  --radius-card: 14px;
  --radius-ctl: 10px;
  --radius-chip: 8px;
  --shadow-card: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.04);
  --shadow-pop: 0 12px 32px -8px rgba(11,18,32,0.22), 0 2px 6px rgba(11,18,32,0.08);
  --spacing-pad: 26px;
  --spacing-gap: 22px;
  --width-rail: 264px;
}
```

### Layout System
Four layout shells:
1. **OrgLayout** — sidebar + top bar (most pages)
2. **AuthLayout** — split-screen brand panel + form (login, signup, etc.)
3. **PortalLayout** — customer portal with branded header
4. **KioskLayout** — full-screen touch-optimized

### Component Hierarchy
```
App.tsx
├── AuthLayout (login, signup, password reset, verify email, MFA)
├── KioskLayout (kiosk screens)
├── PortalLayout (customer portal)
└── OrgLayout (all authenticated org pages)
    ├── Sidebar (grouped nav, org switcher)
    ├── TopBar (search, branch, notifications, new, avatar)
    └── <Outlet /> (page content)
```

### Sidebar Navigation Groups
From the design spec:
| Group | Items |
|-------|-------|
| Overview | Dashboard, Reports |
| Sales | Invoices, Quotes, Recurring, POS |
| Work | Job Cards, Bookings, Schedule, Staff Schedule, Projects, Time Tracking |
| People & Stock | Customers, Vehicles, Staff, Inventory, Items, Purchase Orders |
| Money | Accounting, Banking, Tax / GST, Expenses |
| (bottom) | Settings, Admin Console |

### Responsive Behavior
- `≤1080px`: main grid → 1 col; KPIs → 2 col
- `≤860px`: sidebar → off-canvas drawer; hamburger shown; search → icon-only; branch chip hidden; "New" → icon-only
- `≤520px`: KPIs → 1 col; h1 → 22px

### Deployment (Side-by-Side Testing)
```
nginx location /new/ {
  proxy_pass http://frontend-v2:5174/new/;
}
```
A new Docker service `frontend-v2` runs the Vite dev server (or serves built assets) on port 5174. Nginx routes `/new/` to it. The existing frontend at `/` is unaffected.

## File-by-File Porting Strategy

For each page:
1. Read original `.tsx` from `frontend/src/pages/<module>/`
2. Read design `.html` from `OraInvoice_Handoff/app/`
3. Create new `.tsx` at `frontend-v2/src/pages/<module>/`
4. Keep all logic, replace all markup/styling with new design
5. Update tracker

## Phase Breakdown

| Phase | Scope | Tasks |
|-------|-------|-------|
| P0 | Project scaffold + design tokens + fonts | 5 |
| P1 | App shell (OrgLayout, Sidebar, TopBar, responsive) | 6 |
| P2 | Auth layout + auth pages (12 pages) | 4 |
| P3 | Dashboard (4 pages + 12 widgets) | 3 |
| P4 | Invoices + Quotes (7 pages + 7 modals) | 4 |
| P5 | Customers + Vehicles (7 pages + 5 modals) | 3 |
| P6 | Jobs + Job Cards + Bookings (14 pages + 2 modals) | 4 |
| P7 | Staff + Schedule + Time (16 pages + 12 modals) | 5 |
| P8 | Inventory + Items + Catalogue (26 pages + 3 modals) | 4 |
| P9 | Settings (25 pages) | 3 |
| P10 | Admin console (25 pages + 4 modals) | 4 |
| P11 | Reports (23 pages) | 3 |
| P12 | Accounting + Banking + Tax + Expenses (11 pages) | 3 |
| P13 | Notifications + SMS (10 pages) | 2 |
| P14 | POS + Kitchen + Floor Plan (9 pages + 1 modal) | 2 |
| P15 | Portal (20 pages) | 3 |
| P16 | Kiosk (7 pages + 1 modal) | 2 |
| P17 | Public pages (9 pages + 1 modal) | 2 |
| P18 | Construction + Claims + Compliance (14 pages + 4 modals) | 3 |
| P19 | Franchise + Projects + E-commerce + Data (16 pages) | 3 |
| P20 | Remaining (Payroll, Leave, Swaps, Recurring, PO, Assets, Loyalty, Onboarding, Setup) | 4 |
| P21 | UI base components (Modal, ConfirmDialog, shared) | 2 |
| P22 | Docker + nginx wiring for `/new/` | 2 |
| P23 | Final integration test + polish | 2 |
