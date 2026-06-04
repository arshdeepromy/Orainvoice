---
inclusion: auto
---

# Frontend Redesign — Steering Rules

## Golden Rule

**NEVER modify, delete, or rename any file inside `frontend/`.** The existing frontend remains untouched and continues to be deployed. All redesign work happens exclusively in `frontend-v2/`.

## Design Source

All design assets live in `OraInvoice_Handoff/` at the workspace root. This folder contains:

- `README.md` — full design spec (tokens, measurements, interactions, breakpoints, component specs)
- `IMPLEMENTATION_CHECKLIST.md` — phased implementation guide
- `OraInvoice Redesign (shell + dashboard).html` — the master shell + dashboard prototype
- `app/ds.css` — the design-system stylesheet (tokens + every component class). **Single source of truth for CSS.**
- `app/shell.js` — renders the sidebar + top bar (reference for structure, not to ship)
- `app/auth.css` — standalone auth/public page styles
- `app/admin-nav.js` — admin sub-tab row (reference for structure)
- `app/*.html` — individual page prototypes (150+ screens)
- `app/fleet/` — fleet portal pages (22 screens with own shell + CSS)

**These HTML files are HIGH-FIDELITY design references, NOT production code.** They pin down exact spacing, color, typography, and interaction intent. The task is to recreate this design in React + Tailwind, not to copy raw HTML.

## Project Structure

```
frontend-v2/
├── src/
│   ├── pages/          # Redesigned pages (mirrors frontend/src/pages/ structure)
│   ├── components/     # Redesigned shared components
│   ├── layouts/        # OrgLayout, AuthLayout, PortalLayout, KioskLayout
│   ├── hooks/          # Hooks (copied/adapted from frontend/src/hooks/)
│   ├── api/            # API client + typed endpoints
│   ├── contexts/       # Auth, Branch, Module, Theme contexts
│   ├── types/          # TypeScript types (copied from frontend/src/types/)
│   ├── utils/          # Utility functions
│   ├── styles/         # themes.css with design tokens from ds.css
│   └── App.tsx         # App shell + router
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.ts
└── tsconfig.json
```

## Design System (from OraInvoice_Handoff/README.md)

### Fonts
- **UI/body:** IBM Plex Sans
- **Numbers, IDs, labels, codes, counts, timestamps:** IBM Plex Mono with `font-feature-settings: "tnum" 1`

### Key Tokens
| Token | Value |
|-------|-------|
| `--accent` | `#2F62F0` |
| `--ink` | `#0B1220` |
| `--canvas` | `#F5F6F8` |
| `--card` | `#FFFFFF` |
| `--border` | `#E8EBF0` |
| `--r-card` | `14px` |
| `--r-ctl` | `10px` |
| `--pad` | `26px` |
| `--gap` | `22px` |
| Sidebar width | `264px` |

### Responsive Breakpoints
- `≤1080px`: main grid → 1 col; KPIs → 2 col
- `≤860px`: sidebar → off-canvas drawer; search → icon-only; branch chip hidden; "New" → icon-only
- `≤520px`: KPIs → 1 col; h1 → 22px

### Minimum Touch Targets
All interactive elements: 40–44px minimum.

## Implementation Rules

### Preserve All Functionality

When redesigning a page, you MUST preserve:

- Every button and its click handler
- Every API call (endpoint, method, params, response handling)
- Every form field and its validation
- Every calculation (totals, tax, discounts, GST math, rounding, currency formatting)
- Every conditional render (role gates, module gates, feature flags, trade family gates)
- Every loading state, error state, and empty state
- Every navigation action (links, redirects, back buttons)
- Every keyboard shortcut or accessibility feature
- Every AbortController cleanup in useEffect
- Every pagination parameter (`offset` not `skip`, `limit`)
- Every `aria-*`, `role`, `data-testid` attribute
- Every analytics/tracking call

### Safe API Consumption (same rules as existing frontend)

```typescript
const items = res.data?.items ?? []
const total = res.data?.total ?? 0
```

- Use typed generics on all API calls
- Use AbortController in every useEffect with an API call
- Never use `as any`
- Use `?.` and `?? []` / `?? 0` on all API data

### How to Redesign a Page

1. **Find the design reference** in `OraInvoice_Handoff/app/<PageName>.html`
2. **Read the ORIGINAL source** from `frontend/src/pages/<module>/<Page>.tsx` (and all sub-components it imports)
3. **Extract ALL logic**: state, effects, handlers, API calls, calculations, conditionals, gates
4. **Read `OraInvoice_Handoff/app/ds.css`** for the component classes and token values
5. **Create the new file** at `frontend-v2/src/pages/<module>/<Page>.tsx`
6. **Apply the new design** (layout, spacing, colors, typography from the HTML reference) while keeping all extracted logic intact
7. **Design missing elements on the fly** — if the original page has buttons, previews, panels, receipts, or functions NOT shown in the HTML prototype, design them using the same token system (colors, radii, shadows, typography from ds.css) to match the new aesthetic. Never drop functionality.
8. **Use Tailwind utilities** mapped to the design tokens — don't copy raw CSS from ds.css
9. **Update `docs/REDESIGN_TRACKER.md`** — mark the item as ✅

### Design-to-Code Mapping

| HTML prototype uses | In React use |
|---------------------|--------------|
| `ds.css` classes | Tailwind utilities with custom theme tokens |
| `shell.js` sidebar | `<OrgLayout>` component with NavLink routing |
| Raw SVG icons | Project's existing icon library (Lucide/Heroicons) |
| Inline chart SVG | Recharts `<AreaChart>` / `<BarChart>` |
| `admin-nav.js` tabs | React component with route-driven active state |
| Headless UI patterns | Headless UI components (Menu, Dialog, Transition) |

### Shared Code Strategy

- **Types/interfaces**: Copy into `frontend-v2/src/types/` (fully independent)
- **API client**: New axios instance in `frontend-v2/src/api/client.ts` with same baseURL
- **Contexts**: Re-implement in `frontend-v2/src/contexts/` with same interface
- **Hooks**: Copy and adapt into `frontend-v2/src/hooks/`
- **Utility functions**: Copy into `frontend-v2/src/utils/`
- **Calculations (GST, totals, etc.)**: Copy VERBATIM — do not rewrite math

This keeps `frontend-v2` fully independent — no cross-project imports.

### Tech Stack

- React 18 + TypeScript (match existing)
- Vite 6
- Tailwind CSS v4 (with `@theme` CSS-variable system for design tokens)
- IBM Plex Sans + IBM Plex Mono (self-hosted or Google Fonts)
- Headless UI for accessible primitives
- Recharts for charts (not raw SVG)
- React Router DOM for routing
- Axios for API calls
- Same backend API — no backend changes needed

### What NOT to Do

- ❌ Do NOT modify anything in `frontend/`
- ❌ Do NOT add `frontend-v2` to Docker Compose or deployment configs
- ❌ Do NOT create new backend endpoints for the redesign
- ❌ Do NOT change API response shapes
- ❌ Do NOT remove features because the design doesn't show them — design them on the fly using ds.css tokens
- ❌ Do NOT introduce new state management libraries unless explicitly approved
- ❌ Do NOT skip error/loading/empty states even if the design doesn't show them
- ❌ Do NOT ship the prototype-only files (tweaks-panel, tweaks-app, raw HTML)
- ❌ Do NOT paste raw SVG paths from the HTML — use the icon library
- ❌ Do NOT rewrite business logic / math — copy it verbatim

### Designing Missing Elements On-the-Fly

The HTML prototypes are presentation references and may NOT cover every UI element in the original page. Common gaps:
- Invoice/quote HTML preview panels and PDF preview
- POS receipt preview and print layout
- Print buttons, export buttons, secondary action menus
- Inline edit forms, drag-and-drop zones
- File upload areas, camera capture UI
- Progress indicators, step wizards beyond what's shown
- Toast notifications, confirmation banners
- QR code displays, payment waiting screens
- Vehicle info cards, compliance document viewers

**When you encounter these:** design them using the established token system:
- Cards: `bg-card border border-border rounded-[14px] shadow-card`
- Buttons: follow `.btn-primary`, `.btn-ghost`, `.btn-quiet` patterns
- Text: `font-sans text-text` for body, `font-mono` for numbers/IDs/codes
- Spacing: use `--pad` (26px) and `--gap` (22px) rhythm
- Status colors: ok/warn/danger with their soft variants for backgrounds
- Never leave a blank space — if the original has it, the redesign must have it

### Tracking Progress

After completing each page or modal, update `docs/REDESIGN_TRACKER.md`:
- Change status from ⬜ to ✅
- Add any notes about deviations or decisions in the Notes column

### Per-Page Verification (Mandatory — Do This For EVERY Page)

After integrating each page, before moving to the next:
1. Compare the new `.tsx` against the original source — line by line
2. Confirm every button exists and is wired to its click handler
3. Confirm every API call is preserved (endpoint, method, params, response handling)
4. Confirm every form field + validation + submit path exists
5. Confirm every conditional render (role/module/feature gates, loading/error/empty states)
6. Confirm every calculation (totals, tax, discounts, rounding) is copied verbatim
7. If ANYTHING is missing — add it immediately, do not move on

### Closing Design Gaps

If a page, modal, popup, widget, or any UI element exists in `frontend/` but has NO corresponding HTML prototype in `OraInvoice_Handoff/`:
- Design it from scratch using the token system
- Match the patterns from nearby pages that DO have prototypes
- Use the same card/button/table/badge components
- Never skip it, never leave it for later — close the gap immediately

### Final Audit (Task 79)

After all pages are done:
1. Walk every entry in `docs/REDESIGN_TRACKER.md` — all must be ✅
2. Cross-reference the original router against frontend-v2 routes — no missing routes
3. Cross-reference all modals/popups/drawers — no missing dialogs
4. Cross-reference shared components — no missing widgets
5. Find any pages/modals in `frontend/` not in the tracker — add and implement
6. Document in `docs/REDESIGN_AUDIT.md`

### Deployment

`frontend-v2/` is NOT deployed. No Docker config, no nginx config, no CI/CD. It exists purely for development and review. At cutover time, `frontend/` will be archived and `frontend-v2/` renamed to `frontend/`.

## File Mapping (Design → Source → Target)

| Design HTML | Current Source | New Target |
|-------------|---------------|------------|
| `OraInvoice_Handoff/app/Dashboard.html` | `frontend/src/pages/dashboard/Dashboard.tsx` | `frontend-v2/src/pages/dashboard/Dashboard.tsx` |
| `OraInvoice_Handoff/app/Invoices.html` | `frontend/src/pages/invoices/InvoiceList.tsx` | `frontend-v2/src/pages/invoices/InvoiceList.tsx` |
| `OraInvoice_Handoff/app/InvoiceDetail.html` | `frontend/src/pages/invoices/InvoiceDetail.tsx` | `frontend-v2/src/pages/invoices/InvoiceDetail.tsx` |
| ... (same pattern for all pages) | | |

The naming convention: find the matching `.html` in `OraInvoice_Handoff/app/`, read the original `.tsx` from `frontend/src/pages/`, output to `frontend-v2/src/pages/`.
