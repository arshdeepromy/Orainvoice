# OraInvoice Mobile Redesign — Implementation Checklist

A phased task list for an AI coding agent (Kiro / Claude Code) to apply the mobile redesign in the
**`mobile/` React 19 + Vite + Capacitor 7 + Tailwind** app. Work top to bottom, committing after
each phase. Full specs live in `MOBILE_HANDOFF.md` — read it **and** `.kiro/steering/mobile-app.md`
first.

> **Setup:** branch first → `git checkout -b redesign-mobile-app`.
> Do **not** ship the prototype HTML or `tweaks-*.jsx`. Do **not** modify `frontend/` or `app/`
> (backend) for presentation work.

> **Before you start:** read **§3 Guardrails** and **§7 Backend connection** in `MOBILE_HANDOFF.md`.
> Presentation-only: preserve calculations, module/role/trade gating, conditional rendering, data
> fetching, routing, and Capacitor flows. If a styling change needs logic changes, **stop and flag**.

---

## Phase 0 — Read & orient
- [ ] Read `MOBILE_HANDOFF.md` end to end (scope, tokens, screen map, conventions).
- [ ] Read `.kiro/steering/mobile-app.md`, `safe-api-consumption.md`, `project-overview.md`,
      and `trade-family-gating-for-new-features.md`.
- [ ] Open `OraInvoice Mobile Redesign.html` in a browser to see target look & behaviour.
- [ ] Locate the files you'll touch:
  - [ ] `mobile/src/navigation/{StackRoutes,TabConfig,MoreMenuConfig}.tsx/.ts`
  - [ ] `mobile/src/components/ui/*` and `components/konsta/*`
  - [ ] `mobile/src/api/client.ts` + per-feature `api/*` clients
  - [ ] `mobile/src/contexts/*` (Auth, Module, Branch, Theme, Offline, Biometric)
  - [ ] the theme/token layer (Tailwind config + CSS variables / `index.css`)
- [ ] Confirm the test commands (Vitest + RTL) and run the suite green **before** changing anything.

## Phase 1 — Design tokens & fonts
- [ ] Add **IBM Plex Sans** + **IBM Plex Mono** to the mobile font pipeline.
- [ ] Port every token from `mobile-v2/ds-mobile.css` into the Tailwind `@theme` / CSS-variable
      layer: accent (+ press/soft), ink, canvas, card/card-2, border/border-strong, text/muted/
      muted-2, ok/warn/danger/purple (+ soft tints), radii (16/12/9), shadows (card/pop/fab),
      spacing (`--pad/--gap/--row-pad-y/--card-pad`), nav-h 52 / tab-h 60.
- [ ] Wire **dark mode** (`[data-theme="dark"]` palette → Tailwind `dark:` variants) and the
      **density** variants (compact/comfy). Verify against ThemeContext.
- [ ] Add a `.mono` / `font-mono` utility with tabular figures (`font-feature-settings:"tnum" 1`).
- [ ] Verify tokens resolve in both themes (temporary swatch screen or devtools).

## Phase 2 — Shared UI components (`components/ui/`)
Build the redesigned primitives to match the prototype, each with dark-mode + ≥44px targets:
- [ ] `Icon` (single component; reuse existing icon set or the prototype's 24×24/1.8-stroke set).
- [ ] `MobileButton` (primary / ghost / icon variants) — restyle existing, keep its API.
- [ ] `Card`, `ListRow`/`MobileList`, `Avatar`, `Badge`/`StatusBadge`, `KpiCard`, `SegmentedControl`,
      `Chip`, `SearchBar`, `EmptyState`, `ErrorState`, `Skeleton`, `Toast`.
- [ ] `BottomSheet` (portal to app root, scrim, drag handle, safe-area aware).
- [ ] `SearchOverlay` (full-screen, portaled, debounced).
- [ ] Confirm loading/empty/error patterns match `MobileSpinner` usage already in screens.

## Phase 3 — Navigation shell
- [ ] Restyle the **5-tab bottom bar** (Home · Invoices · Customers · <dynamic 4th> · More) to the
      prototype. **Keep** `buildTabs()` / `resolveFourthTab()` / `isNavigationItemVisible()` and all
      gates in `TabConfig.ts` exactly.
- [ ] Restyle the top **nav bar** (title, back, actions) and the **More menu** grid; keep
      `MoreMenuConfig.ts` items, `moduleSlug` / `tradeFamily` / `roles` gates intact.
- [ ] Restyle the **FAB / quick-create** entry points; wire to existing create routes/handlers.
- [ ] Verify `AuthGuard` / `GuestOnly` wrappers and scroll preservation are untouched.

## Phase 4 — Konsta migration (incremental)
- [ ] Replace Konsta components screen-by-screen with the new `components/ui/*` equivalents.
- [ ] Keep `TabConfig.ts` gate/resolution logic framework-agnostic.
- [ ] After the last screen, remove the Konsta dependency + delete `components/konsta/`.

## Phase 5 — Screen restyle (work module-by-module, commit per module)
For each screen in the **§6 mapping table** of `MOBILE_HANDOFF.md`: restyle JSX/classes only,
keep the `api/*` calls, query/mutation logic, `ModuleGate`, and route. Verify data still loads,
save paths still work, and gates still hide correctly.
- [ ] **Core:** Dashboard, Invoices (list/detail/create), Customers (list/detail/create/edit), Jobs
      (list/detail/board/cards), More.
- [ ] **Sales:** Quotes, Recurring, POS, Payments / public payment.
- [ ] **Work:** Bookings, Schedule, Time tracking, Clock, Expenses, Projects, Construction.
- [ ] **Stock:** Inventory (read-only), Items/Catalogue, Purchase orders, Assets, Vehicles.
- [ ] **People:** Staff, Payslips (self-service).
- [ ] **Money (view-only):** Accounting, Banking, GST/Tax, Reports.
- [ ] **Other:** Compliance (camera upload), SMS, Notifications, Settings (read-only profile),
      Portal, Fleet, Kiosk.
- [ ] **Auth:** Login, MFA, Forgot/Reset password, Sign up, Biometric lock, Verify email, Landing.

## Phase 6 — Confirm gaps before building (don't assume)
- [ ] Raise with product owner + check backend (`app/main.py`): **PPSR search**, **Leave**,
      **Roster/shift swaps**, **Loyalty**, **insurance/warranty Claims**, **Setup wizard**,
      **Booking detail / Expense detail**. Add routes only after confirmation; gate appropriately.

## Phase 7 — Verify & ship
- [ ] Run lint + typecheck + Vitest/RTL suite — fix any new failures.
- [ ] Manual per-screen pass: totals/GST identical, module/role/trade gates correct, create/edit
      saves, loading/empty/error render, ≥44px targets, safe-area insets, dark mode.
- [ ] Test on a real device / simulator (iOS + Android) for Capacitor flows (camera, biometrics,
      push) behind `isNativePlatform()` guards.
- [ ] Open PRs per module for human review; cut over behind a flag if desired.

---

### Definition of done (per screen)
Restyled to the prototype • same data & save paths • same gates • dark mode • ≥44px targets •
no new test/lint/type failures • no blank error states.
