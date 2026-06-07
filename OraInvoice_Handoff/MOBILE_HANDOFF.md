# Mobile Handoff: OraInvoice Mobile App Redesign

A bold visual refresh of the **OraInvoice Mobile companion app** — the Capacitor + React phone
app that field staff, tradespeople, and business owners use on iOS/Android. This package pins
down the exact look, screen inventory, and interaction intent so a coding agent (Kiro / Claude
Code) can recreate the design **inside the existing `mobile/` codebase** while keeping every
backend call, calculation, and gating rule working exactly as it does today.

> **Companion document:** the desktop app-shell handoff lives in `README.md` /
> `IMPLEMENTATION_CHECKLIST.md` in this same folder. This file is the **mobile** equivalent and
> takes precedence for anything in `mobile/`.

---

## 0. TL;DR for the implementing agent

1. The target codebase already exists: **`mobile/`** (React 19 + Vite + Capacitor 7 + Tailwind).
   You are **restyling existing screens**, not building a new app from scratch.
2. The design source of truth is the prototype: **`OraInvoice Mobile Redesign.html`** + the
   `mobile-v2/` folder (design system in `mobile-v2/ds-mobile.css`, screens in the `*.jsx` files).
3. **Read `.kiro/steering/mobile-app.md` first** — it defines mobile scope, API conventions,
   gating, and touch-target rules. This handoff builds on it; it does not override it.
4. **Presentation only.** Do not touch calculations (GST/tax/totals), module/role/trade-family
   gating, data fetching, routing, or Capacitor native flows. See **§3 Guardrails**.
5. Wire every screen to the **real backend** via the existing `mobile/src/api/*` clients and the
   axios client at `mobile/src/api/client.ts` (`/api/v1` base; v2 endpoints use absolute
   `/api/v2/...`). Prefer **v2** endpoints where they exist.
6. **Drop Konsta.** The redesign uses the prototype's own Tailwind-based component language, not
   the `mobile/src/components/konsta/` wrappers. See **§9**.

---

## 1. Overview

The mobile app is a **companion app for organisation users only** — not an admin console. The
redesign keeps the desktop's refined blue accent (`#2F62F0`), IBM Plex Sans/Mono type, and
calm card-based language, re-expressed for touch: a 5-tab bottom bar, full-bleed list screens,
bottom-sheet quick-create forms, a full-screen global search, and read-only financial views for
owners monitoring the business in the field.

**Fidelity:** high. Colours, type, spacing, radii, shadows, and interaction states are specified
in `mobile-v2/ds-mobile.css` and should be matched closely. The figures in the prototype
(customer names, dollar amounts) are **sample data** — the layout and components are the
deliverable, not the numbers.

---

## 2. Scope — what's in and what's out (per `.kiro/steering/mobile-app.md`)

**In scope (build/restyle for mobile):**
- Invoicing, quoting, customer management
- Job cards, job board, time tracking, expenses, bookings
- Inventory **lookup** (read-only stock checks in the field)
- Compliance document upload (camera-based)
- Accounting / Banking / Tax — **view-only** for owners (module-gated)
- Reports — **read-only** summary views
- Notifications / push alerts
- POS (hospitality/retail, module-gated)
- Self-service: clock in/out, my payslips, leave requests

**Out of scope — never add to mobile:**
- Global-admin / platform screens (the entire `app/Admin*.html` set, HA replication, migration,
  feature flags, global user management, franchise head-office console)
- Org-admin destructive ops (data export/import, org deletion, deep integration management)
- Full deep-config settings panels — mobile Settings is a **read-only profile** plus
  notification + biometric toggles
- `global_admin` role must **never** see org-level settings on mobile

> The prototype intentionally excludes all `Admin*` screens. If you find yourself porting an
> admin console to mobile, stop — it's out of scope.

---

## 3. ⚠️ Guardrails — What NOT to Touch

**This is a presentation-only redesign.** Preserve all existing behaviour.

**Do NOT alter, remove, or "simplify":**
- **Business logic & calculations** — GST/tax math, line-item totals, subtotals, discounts,
  rounding, currency formatting (`Intl.NumberFormat`, never hardcode `$`), due-date logic,
  progress-claim / retention / variation maths, payslip & PAYE calculations. Keep byte-for-byte;
  move into an equivalent hook/util only if a restyle forces it, never rewrite.
- **Permission / role / module gating** — every `ModuleGate`, `moduleSlug`, `tradeFamily`,
  `allowedRoles`, plan/subscription gate, and quota gate (e.g. PPSR `402 ppsr_quota_exceeded`).
  A redesigned tab bar / More menu must hide **exactly** what the original hid for each role,
  module, and trade family.
- **Conditional rendering** — `&&`, ternaries, early returns, `Suspense`, loading/empty/error
  states. Re-skin them; don't delete them. Never leave a blank screen on error.
- **Data fetching & state** — queries, mutations, `useEffect` deps, `AbortController` cleanup,
  cache keys, optimistic updates, form submit/save paths, validation.
- **Routing** — route paths, params, `AuthGuard`/`GuestOnly` wrappers, deep links
  (`DeepLinkConfig.ts`), redirects, scroll preservation.
- **Capacitor native flows** — camera, biometrics, push, network, preferences, share. Keep the
  `isNativePlatform()` guards and try/catch wrappers.
- **Analytics / a11y / test hooks** — `aria-*`, `role`, `data-testid`.

**Rules of engagement:**
1. Change **markup + Tailwind classes / styling only**. Treat props, hooks, handlers, guards,
   and conditionals as immovable unless explicitly told otherwise.
2. If a styling change *requires* touching logic, **stop and flag it** rather than guess.
3. Preserve every existing prop, `key`, ref, and callback when restructuring JSX.
4. Keep `data-testid` / `aria` attributes so the Vitest + RTL suite and screen readers keep working.
5. After **every** phase: run lint + typecheck + the mobile test suite. Any new failure = a
   regression to fix before continuing.
6. Work in **small diffs, screen-by-screen, on a branch**; open a PR for review. Never edit `main`.

**Human verification per screen:** invoice totals/GST compute identically, module/role/trade
gates still hide the right things, create/edit **save** paths still work, loading/empty/error
states still render, and all touch targets are ≥ 44×44px.

---

## 4. Target codebase map (`mobile/`)

```
mobile/src/
  api/                 ← typed API clients (client.ts = axios; leave.ts, payslips.ts, ppsr.ts, schedule.ts, …)
  components/
    common/            ← ErrorBoundary, etc.
    gestures/          ← swipe/pull gesture helpers
    konsta/            ← Konsta UI wrappers  ⟵ being retired (see §9)
    layout/            ← shell, tab bar, headers
    ui/                ← MobileButton, MobileList, MobileSpinner, PullRefresh, ModuleGate, …
  contexts/            ← AuthContext, ModuleContext, BranchContext, ThemeContext, OfflineContext, BiometricContext
  hooks/
  native/              ← Capacitor plugin wrappers (camera, biometrics, push, …)
  navigation/
    StackRoutes.tsx    ← all routes (the canonical route table — see §6)
    TabConfig.ts       ← 5-tab bottom bar + dynamic 4th tab + gating helpers
    MoreMenuConfig.ts  ← More-tab grid items (moduleSlug / tradeFamily / roles per item)
    DeepLinkConfig.ts  ← deep-link routes
  screens/<feature>/   ← one folder per module (see §6 mapping)
```

**Reusable building blocks (reuse, don't reinvent):** `MobileButton`, `MobileList`,
`MobileSpinner`, `PullRefresh`, `ModuleGate`, `ErrorBoundary`. The prototype's bottom-sheet,
search overlay, segmented control, KPI card, and badge are **new shared components** you'll add
under `components/ui/` (see §8).

---

## 5. Design system → Tailwind tokens

All exact values live in **`mobile-v2/ds-mobile.css`** — port them into the mobile app's Tailwind
`@theme` / CSS-variable layer (the project already uses CSS variables; mirror the desktop
`themes.css` approach). Headline tokens:

| Token | Light | Notes |
|---|---|---|
| `--accent` | `#2F62F0` | primary blue; `--accent-press` = 84% on black; `--accent-soft` = 12% tint |
| `--ink` | `#0B1220` | dark surfaces / brand panel |
| `--canvas` | `#F4F6F9` | app background |
| `--card` / `--card-2` | `#fff` / `#F7F9FC` | surfaces |
| `--border` / `--border-strong` | `#E7EBF1` / `#D6DCE5` | hairlines |
| `--text` / `--muted` / `--muted-2` | `#111722` / `#687283` / `#98A1B0` | type |
| `--ok` / `--warn` / `--danger` / `--purple` | `#1F8A5B` / `#B5740F` / `#C8412F` / `#6D5AE6` | + soft tints via `color-mix` |

- **Type:** IBM Plex Sans (UI) + IBM Plex Mono (numbers/IDs/codes, tabular figures `"tnum" 1`).
- **Radii:** card `16px`, control `12px`, chip `9px`.
- **Shadows:** `--shadow-card`, `--shadow-pop`, `--shadow-fab` (accent-tinted).
- **Density:** `[data-density="compact|comfy"]` re-scale `--pad/--gap/--row-pad-y/--card-pad`.
  Wire to a settings toggle if desired; keep default comfortable.
- **Dark mode:** every component must support it. The prototype defines a full
  `[data-theme="dark"]` palette — port it to Tailwind `dark:` variants.
- **Chrome:** nav bar `52px`, tab bar `60px`; respect safe-area insets (`env(safe-area-inset-*)`,
  `pb-safe`).

> **Icons:** reuse the icon set already in the mobile app (or the prototype's 24×24 / 1.8-stroke
> set in `mobile-v2/icons.jsx`). Don't paste raw SVG path strings into every component — define
> one `<Icon name>` component.

---

## 6. Screen mapping — prototype → real route → component → endpoint

Every prototype screen below maps to a **real route in `mobile/src/navigation/StackRoutes.tsx`**
and an existing screen component. Restyle the component; keep its route, data, and gates.

### Always-visible tabs & core
| Prototype screen | Route | Component file | Module gate | Primary endpoint(s) |
|---|---|---|---|---|
| Login | `/login` | `auth/LoginScreen.tsx` | — (GuestOnly) | `POST /auth/login`, `/auth/token/refresh` |
| Two-factor | `/mfa-verify` | `auth/MfaScreen.tsx` | — | `POST /auth/mfa/*`, `/auth/passkey/login/*` |
| Password reset | `/forgot-password`, `/reset-password` | `auth/ForgotPasswordScreen.tsx`, `auth/ResetPasswordScreen.tsx` | — | `POST /auth/password/*` |
| Sign up | `/signup` | `auth/SignupScreen.tsx` | — | `POST /auth/signup` |
| Dashboard (Home) | `/` | `dashboard/DashboardScreen.tsx` | none (always) | dashboard KPIs/widgets (branch + dateRange scoped) |
| Invoices list | `/invoices` | `invoices/InvoiceListScreen.tsx` | none | `GET /invoices` |
| Invoice detail | `/invoices/:id` | `invoices/InvoiceDetailScreen.tsx` | none | `GET /invoices/:id` |
| Invoice create/edit | `/invoices/new`, `/invoices/:id/edit` | `invoices/InvoiceCreateScreen.tsx` | none | `POST/PUT /invoices` |
| Customers list | `/customers` | `customers/CustomerListScreen.tsx` | none | `GET /customers` |
| Customer detail | `/customers/:id` | `customers/CustomerProfileScreen.tsx` | none | `GET /customers/:id` |
| Customer create/edit | `/customers/new`, `/customers/:id/edit` | `customers/CustomerCreateScreen.tsx`, `CustomerEditScreen.tsx` | none | `POST/PUT /customers` (only First Name required) |
| Jobs list | `/jobs` | `jobs/JobListScreen.tsx` | `jobs` | `GET /jobs` |
| Job detail | `/jobs/:id` | `jobs/JobDetailScreen.tsx` | `jobs` | `GET /jobs/:id` |
| (Job board) | `/jobs/board` | `jobs/JobBoardScreen.tsx` | `jobs` | — |
| Job cards | `/jobs/cards`, `/jobs/cards/:id`, `/jobs/cards/new` | `jobs/JobCard*Screen.tsx` | `jobs` | `GET/POST /job-cards` |
| More menu | `/more` | `more/MoreMenuScreen.tsx` | none | driven by `MoreMenuConfig.ts` |

### More-menu modules
| Prototype screen | Route | Component file | Module gate | Primary endpoint(s) |
|---|---|---|---|---|
| Quotes list / detail / create | `/quotes`, `/quotes/:id`, `/quotes/new` | `quotes/Quote*Screen.tsx` | `quotes` | `GET/POST /quotes` |
| Recurring invoices | `/recurring`, `/recurring/:id` | `recurring/Recurring*Screen.tsx` | `recurring` | `GET /api/v2/recurring` |
| Bookings | `/bookings`, `/bookings/new` | `bookings/Booking*Screen.tsx` | `bookings` | `GET/POST /bookings` |
| Schedule | `/schedule` | `schedule/ScheduleCalendarScreen.tsx` | `scheduling` | `GET /api/v2/schedule` |
| Time tracking | `/time-tracking` | `time-tracking/TimeTrackingScreen.tsx` | `time_tracking` | `GET/POST /api/v2/time-entries` |
| Clock in/out | `/clock` | `clock/ClockScreen.tsx` | (self-service) | `POST /api/v2/time-entries` |
| Expenses list / create | `/expenses`, `/expenses/new` | `expenses/Expense*Screen.tsx` | `expenses` | `GET/POST /api/v2/expenses` |
| Inventory list / detail | `/inventory`, `/inventory/:id` | `inventory/Inventory*Screen.tsx` | `inventory` | `GET /inventory` (read-only in field) |
| Items & catalogue | `/items` | `inventory/CatalogueItemsScreen.tsx` | `inventory` | `GET /items` |
| Purchase orders | `/purchase-orders`, `/purchase-orders/:id` | `purchase-orders/PO*Screen.tsx` | `purchase_orders` | `GET /api/v2/purchase-orders` |
| Vehicles list / profile | `/vehicles`, `/vehicles/:id` | `vehicles/Vehicle*Screen.tsx` | `vehicles` | `GET /vehicles` (+ CarJam/WOF/COF) |
| Projects list / detail | `/projects`, `/projects/:id` | `projects/Project*Screen.tsx` | `projects` | `GET /projects` |
| Staff list / detail | `/staff`, `/staff/:id` | `staff/Staff*Screen.tsx` | `staff` | `GET /api/v2/staff` |
| Payslips (self-service) | `/payslips` | `payslips/PayslipsScreen.tsx` | (self-service) | `GET /api/v2/...` payslips |
| Reports menu / view | `/reports`, `/reports/:type` | `reports/Reports*Screen.tsx` | none (read-only) | report endpoints per `:type` |
| Accounting | `/accounting`, `/accounting/journals(/:id)` | `accounting/*Screen.tsx` | `accounting` (view-only) | `GET /accounting/*` |
| Banking | `/banking`, `/banking/:id/transactions`, `/banking/reconciliation` | `accounting/Bank*Screen.tsx`, `ReconciliationScreen.tsx` | `banking` (view-only) | `GET /banking/*` |
| GST / Tax | `/tax`, `/tax/:id`, `/tax/position` | `accounting/Gst*Screen.tsx`, `TaxPositionScreen.tsx` | `tax` (view-only) | `GET /tax/*` |
| Compliance | `/compliance`, `/compliance/upload` | `compliance/Compliance*Screen.tsx` | `compliance` | `GET/POST /api/v2/compliance-docs` (camera) |
| Construction (claims/variations/retentions) | `/construction/claims`, `/variations`, `/retentions`, `/construction/:id` | `construction/*Screen.tsx` | `construction` | `GET /construction/*` |
| Assets | `/assets`, `/assets/:id` | `assets/Asset*Screen.tsx` | `assets` | `GET /assets` |
| SMS | `/sms` | `sms/SMSComposeScreen.tsx` | `sms` | `POST /sms/*` (Connexus) |
| POS | `/pos` | `pos/POSScreen.tsx` | `pos` | `GET/POST /pos/*` |
| Notifications | `/notifications`, `/notifications/:id` | `notifications/Notification*Screen.tsx` | none | `GET /notifications` |
| Settings (read-only profile) | `/settings` | `settings/SettingsScreen.tsx` | `owner`/`admin` only | profile + notif/biometric toggles |
| Portal | `/portal` | `portal/PortalScreen.tsx` | (customer portal) | portal endpoints |
| Public payment | `/pay/:token` | `auth/PublicPaymentScreen.tsx` | — (public) | `GET/POST /pay/:token` (CSRF) |
| Fleet portal | `/fleet`, `/fleet/vehicles(/:id)`, `/fleet/checklists`, `/fleet/bookings` | `fleet/Fleet*Screen.tsx` | `fleet` | `GET /api/v2/...` fleet |
| Kiosk | `/kiosk` | `kiosk/KioskScreen.tsx` | `kiosk` role | kiosk check-in flow |

### Prototype-only helpers (do NOT create as real screens)
- **Browse all screens / directory** — a review aid for this prototype only. The real equivalent
  is the **More menu** (`MoreMenuConfig.ts`).
- **Component states demo** — a prototype showcase of loading/empty/error skeletons. Port the
  *patterns* into the real `MobileSpinner` / empty / error components; don't ship the demo screen.

### ⚠️ Screens in the prototype with NO existing route — confirm before building
These appear in the prototype but are **not** in `StackRoutes.tsx`. Treat as gaps to confirm with
the product owner (and check the backend route exists in `app/main.py`) **before** adding routes:
- **PPSR search** — API client exists (`api/ppsr.ts`, `/api/v2/ppsr/*`, quota-gated) but no mobile
  route. If approved, add `/ppsr` gated by the PPSR/vehicle module + quota.
- **Leave requests/approvals** — API exists (`api/leave.ts`) but no route. Self-service request is
  in mobile scope; approvals may be owner/admin-gated.
- **Roster / shift swaps** — relate to `/schedule`; confirm whether a dedicated screen is wanted.
- **Loyalty** — no mobile route/API confirmed; likely out of scope. Confirm.
- **Insurance/warranty Claims** — the prototype's "Claims" differs from Construction progress
  claims. Confirm which the business means before wiring.
- **Setup wizard / onboarding** — confirm against the web onboarding flow.
- **Booking detail / Expense detail** — the real app currently has list + create only. Add detail
  routes only if the product owner wants them.

---

## 7. Backend connection — how to wire data (mandatory conventions)

All from `mobile/src/api/client.ts` and `.kiro/steering/{mobile-app,safe-api-consumption}.md`:

- **Base URL** `/api/v1`; **v2 endpoints use absolute paths** `/api/v2/...` (the client strips the
  v1 base when a URL starts with `/api/`). **Prefer v2** where it exists (time-entries, expenses,
  staff, schedule, purchase-orders, recurring, compliance-docs, franchise, modules).
- **Auth:** JWT Bearer injected by the request interceptor; httpOnly refresh cookie; a single
  refresh mutex; 401 → refresh → retry → else redirect to `/login`. **Don't reimplement** — call
  through the existing client.
- **Branch scoping:** `X-Branch-Id` header is auto-added from `localStorage.selected_branch_id`
  (omitted when `all`). Keep the branch context wiring intact.
- **CSRF:** portal/state-changing requests send `X-CSRF-Token` (double-submit). Keep it.
- **List shape:** every list returns `{ items, total }`. Always consume safely:
  `const items = res.data?.items ?? []; const total = res.data?.total ?? 0`.
- **Pagination:** `offset` + `limit` (NEVER `skip` — it's silently ignored).
- **Typing:** typed generics on every call; never `as any`.
- **Cancellation:** every `useEffect` API call uses an `AbortController` and returns
  `() => controller.abort()`; forward `signal` to the api fn.
- **Currency/locale:** `Intl.NumberFormat` with the org locale — never hardcode `$`.
- **Native:** guard all Capacitor calls with `isNativePlatform()` + try/catch.

When restyling a screen, **keep its existing `api/*` import and query/mutation calls verbatim.**
You are reskinning the JSX around the same data.

---

## 8. Mobile interaction patterns (from the prototype)

Add these as shared components under `components/ui/`, wired to the **existing** data/handlers:

- **5-tab bottom bar** — Home · Invoices · Customers · <dynamic 4th> · More. The 4th tab resolves
  via `resolveFourthTab()` in `TabConfig.ts` (Jobs → Quotes → Bookings → Reports). Jobs tab is
  `jobs`-gated. Keep `buildTabs()` / `isNavigationItemVisible()` as the gate source of truth.
- **Bottom-sheet quick-create** — the prototype opens create forms as bottom sheets. The real app
  currently uses full-screen create routes (`/invoices/new`, etc.). **Two valid approaches:**
  (a) keep the existing create *routes/components* and simply restyle them, or (b) introduce a
  shared `<BottomSheet>` that hosts the **same** create form component + submit/validation. Either
  way, **reuse the existing create screen's form logic and save path** — do not rewrite validation
  or the POST/PUT call. Confirm with the owner which approach they want.
- **Full-screen search overlay** — searches customers/invoices/jobs/modules. Wire to the real
  search endpoint(s); debounce; show empty/loading/error states. Must cover the screen (portal to
  app root), not sit inside the header.
- **Filter / sort sheet** — list-screen filters map to the real query params (`offset/limit` +
  server-side filters like the PPSR `rego/match/date_from/date_to` pattern).
- **Pull-to-refresh** — reuse the existing `PullRefresh` component.
- **Segmented date range** (7D/30D/QTR/YR) on Dashboard & Reports — drives the existing
  `dateRange` query param; don't store a parallel copy.
- **Touch targets ≥ 44×44**, safe-area insets, dark-mode variants on every new component.

---

## 9. Konsta → out

The existing app has a `mobile/src/components/konsta/` wrapper layer and Konsta-flavoured tab/
nav exports (e.g. `KonstaTabbar` referenced in `TabConfig.ts`). **The redesign does not use
Konsta.** Migrate to the prototype's own Tailwind-based components:

- Replace Konsta `Page/Navbar/Tabbar/List/Block/Button` usages with the redesigned
  `components/ui/*` equivalents that match `ds-mobile.css`.
- Remove the Konsta dependency once no screen imports it (check `package.json` +
  `components/konsta/`), and delete the `konsta/` folder in a final cleanup commit.
- Keep the **gating + tab-resolution logic** in `TabConfig.ts` (`buildTabs`, `resolveFourthTab`,
  `isNavigationItemVisible`) — that's framework-agnostic and must survive the Konsta removal.

Do this incrementally (screen-by-screen) so the app keeps building; don't rip Konsta out in one
commit before the replacements exist.

---

## 10. About the design files

The files in `mobile-v2/` and `OraInvoice Mobile Redesign.html` are **HTML/CSS/JS design
references** — a high-fidelity prototype of look and behaviour. **They are not production code to
copy.** The real app is React 19 + TypeScript + Vite + Capacitor + Tailwind. Recreate the design
using the codebase's patterns (Tailwind tokens, `components/ui/*`, React Router routes,
`ModuleGate`) — not the raw prototype HTML or its `tweaks-panel.jsx` / `tweaks-app.jsx`
(prototyping aids only).

---

See **`MOBILE_IMPLEMENTATION_CHECKLIST.md`** for the phased task list, and
**`KIRO_AGENT_PROMPT.md`** for a ready-to-paste instruction block for the Kiro IDE agent.
