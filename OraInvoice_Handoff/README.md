# Handoff: OraInvoice App Shell Redesign

> **📱 Looking for the MOBILE app?** This document covers the **desktop web app shell**. The
> mobile (Capacitor) app redesign has its own package in this folder:
> **`MOBILE_HANDOFF.md`** (scope + full screen→route→endpoint map), **`MOBILE_IMPLEMENTATION_CHECKLIST.md`**
> (phased tasks), and **`KIRO_AGENT_PROMPT.md`** (ready-to-paste agent instruction). Use those for
> anything under `mobile/`.

## Overview
A bold visual refresh of the OraInvoice (WorkshopPro NZ) application shell — the persistent
sidebar + top bar chrome that wraps every authenticated screen — plus a representative
Dashboard to prove the system. The goals were: a more **premium / trustworthy** feel, a
**calm & modern** aesthetic, better **mobile/tablet** behavior, and taming the original
**40-item flat navigation** into a scannable, grouped structure.

The redesign keeps a refined version of the original blue accent and introduces a
monospace type accent for numbers/IDs to give a technical, fintech-grade feel.

---

## ⚠️ Guardrails — What NOT to Touch

**This is a PRESENTATION-ONLY redesign.** The deliverable is markup + styling. The agent must
preserve all existing behavior. Read this before changing any file.

**Do NOT alter, remove, or "simplify" any of the following:**
- **Business logic & calculations** — GST/tax math, line-item totals, subtotals, discounts,
  rounding, currency formatting, due-date logic. If any of this lives inside a component you're
  restyling, keep it byte-for-byte; move it out only into an equivalent hook/util, never rewrite it.
- **Permission / role gating** — every `canX`, role check, feature flag, plan/subscription gate,
  and conditional that hides or disables UI (e.g. nav items, buttons, whole routes). A redesigned
  nav must still hide exactly what the original hid for each role.
- **Conditional rendering** — `&&`, ternaries, early returns, `Suspense`/loading/empty/error
  states. Re-skin them; don't delete them.
- **Data fetching & state** — queries, mutations, `useEffect` dependencies, cache keys,
  optimistic updates, form submit/save paths, validation.
- **Routing** — route paths, params, `NavLink`/`Outlet` wiring, redirects, guards.
- **Analytics / tracking / a11y attributes** — `aria-*`, `role`, `data-*` test hooks,
  event tracking calls.

**Rules of engagement for the agent:**
1. Change **markup structure and CSS/Tailwind classes only**. Treat props, hooks, handlers,
   guards, and conditionals as immovable unless explicitly told otherwise.
2. If a styling change *requires* touching logic, **stop and flag it** with a comment/PR note
   rather than guessing.
3. Preserve every existing prop, `key`, ref, and callback wiring when restructuring JSX.
4. Keep all existing **test IDs / `data-testid` / `aria` attributes** so the test suite and
   screen readers keep working.
5. After **every** phase, run the full **lint + typecheck + test** suite (the repo already has
   accessibility and page tests). Any new failure = a regression to fix before continuing.
6. Work in **small diffs, screen-by-screen, on a branch**, opening a PR for human review. Never
   edit `main` directly.

**Human verification checklist (per screen):** confirm invoice totals/GST compute identically,
role-gated items still hide for the right roles, create/edit **save** paths work, and
loading/empty/error states still render.

---

## Two Ways to Apply This Design

You can implement this redesign in one of two strategies. **Pick one and tell the agent which.**

### Option A — In-place restyle (modify the current frontend)
Edit the existing components (`OrgLayout.tsx`, dashboard, theme files) in your repo, on a branch.
- **Pro:** no duplication; logic stays exactly where it is.
- **Con:** the agent is editing live, logic-bearing files — higher risk of touching something it
  shouldn't (see Guardrails above). Requires careful diff review.

### Option B — Parallel redesign (build a NEW frontend, don't touch the current one) ✅ recommended for a bold rebuild
Stand up a **separate frontend app** that talks to the **same backend/API**, leaving the current
`frontend/` completely untouched and running in prod.
- **Why it's safer:** your business logic, calculations, GST math, and permission rules largely
  live behind the **API / server**. A fresh frontend that calls the *same endpoints* re-implements
  only the *presentation*, so there's no risk of corrupting the existing app while you build.
- **How to set it up:**
  1. Create a new app folder, e.g. `frontend-next/` (new Vite + React + Tailwind v4 project), or a
     separate repo. **Do not import from or modify `frontend/`.**
  2. **Reuse the contract, not the code:** point it at the same REST/GraphQL endpoints. Copy
     **API client types / DTOs / schema** over so request/response shapes match exactly — but
     re-implement screens fresh against this design.
  3. **Port the load-bearing logic deliberately, not by guesswork:** for any calculation or gating
     that lives on the *client* today (totals, GST, role checks), copy those specific utils/hooks
     verbatim into the new app and **add unit tests that assert identical output** to the current
     app. Don't re-derive math by eye.
  4. Recreate the design from this package's `README.md` + checklist, screen by screen.
  5. Run both apps side by side (different port/subdomain) and **diff behavior** against the live
     app for each screen before switching any traffic.
  6. Cut over per-route or behind a feature flag once a screen reaches parity.
- **Watch-outs:** auth/session handling, CORS, env config, and **permission gating must be
  re-implemented faithfully** (don't assume the API enforces everything — mirror the client-side
  gates too). Keep the same `aria`/test hooks if you want to reuse tests.

> Whichever option you choose, the **Guardrails** rules about preserving calculations, gating, and
> conditional logic still apply — in Option B they apply to how you *port* that logic into the new app.

---

## About the Design Files
The files in this bundle are **design references created in HTML/CSS/JS** — a high-fidelity
prototype showing the intended look and behavior. **They are not production code to copy
directly.**

The original app is **React 19 + Vite + Tailwind CSS v4** (with Headless UI, Recharts,
React Router). The task is to **recreate this design inside that existing codebase** using
its established patterns — Tailwind utility classes / theme tokens, the existing
`OrgLayout.tsx` shell, NavLink-based routing, and Recharts for the chart — not to ship the
raw HTML. The HTML simply pins down exact spacing, color, type, and interaction intent.

The prototype's design tokens map cleanly onto Tailwind v4's `@theme` CSS-variable system,
which the project already uses in `src/styles/themes.css`.

---

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, radii, shadows, and interaction
states are all specified below and should be matched closely. Recreate pixel-for-pixel using
the codebase's Tailwind setup. The dashboard *content* (numbers, customer names) is sample
data — the layout and components are the deliverable, not the figures.

---

## Screens / Views

### 1. Application Shell (the deliverable)
**Purpose:** Persistent chrome around every org-scoped page. Replaces the current
`src/layouts/OrgLayout.tsx`.

**Layout:**
- Root: `display:flex; height:100vh; overflow:hidden`.
- **Sidebar**: fixed `264px` wide, full height, vertical flex (header / scrollable nav /
  footer). On screens `≤860px` it becomes a fixed off-canvas drawer
  (`transform: translateX(-100%)`) revealed by a hamburger, with a `rgba(11,18,32,.5)` scrim.
- **Main**: `flex:1`, vertical flex (top bar / scrolling content), `min-width:0`.

#### Sidebar — header (height 64px, 0 18px padding, bottom hairline border)
- **Logo mark**: 32×32, `border-radius:9px`, background = accent, white document glyph
  (stroke 2.2). Box-shadow `0 2px 8px var(--accent-soft)`.
- **Wordmark**: "Ora" weight 700 + "Invoice" weight 500 in `--sb-muted`. 16px, letter-spacing −0.01em.

#### Sidebar — nav (scrollable, padding 14px 12px 10px)
Grouped into labelled sections. Each group:
- **Group label**: mono, 10.5px, weight 500, letter-spacing 0.13em, uppercase,
  color `--sb-muted`, padding `0 12px 7px`.
- **Nav item**: 40px tall, `0 12px` padding, `border-radius: var(--r-ctl)` (10px),
  gap 11px, 13.5px / weight 500. Icon 18×18 (stroke 1.9, opacity .82).
  - Hover: background `--sb-hover`, text brightens to `--sb-text-strong`.
  - **Active**: background `--sb-active-bg`; 3px rounded accent bar pinned to the left
    edge (`::before`, inset 8px top/bottom); icon tinted accent (`#7FA0FF` in ink theme).
  - Optional **count pill** (mono 11px, pushed right with `margin-left:auto`, pill bg
    `--sb-hover`) OR a 7px **red dot** for alerts.

**Nav groups & items (grouped from the original flat nav):**
| Group | Items (count/▪dot) |
|---|---|
| Overview | Dashboard *(active)*, Reports |
| Sales | Invoices `18`, Quotes `7`, Recurring, POS |
| Work | Job Cards `14`, Bookings ▪, Schedule, **Staff Schedule**, Projects, Time Tracking |
| People & Stock | Customers, Vehicles, Staff, Inventory, Items, Purchase Orders |
| Money | Accounting, Banking, Tax / GST, Expenses |
| *(ungrouped, bottom)* | Settings, Admin Console |

#### Sidebar — footer (top hairline border, padding 12px)
- **Org switcher** row: 30×30 gradient avatar (`135deg, #2F62F0→#6D5AE6`, radius 8px, white
  initials 700/13px), name (13px/600) + plan line ("PRO · 12 SEATS", mono 10.5px
  `--sb-muted`), up/down chevron pushed right. Hover background `--sb-hover`.

#### Top bar (height 64px, padding `0 var(--pad)`, white bg, bottom hairline border, gap 14px)
Left→right:
- **Hamburger** icon button — only visible `≤860px`.
- **Search field**: flex-grow, `max-width:440px`, 40px tall, canvas bg, 1px border,
  `border-radius: var(--r-ctl)`. Magnifier icon + placeholder "Search customers, invoices,
  jobs…" + `⌘K` kbd hint pushed right (mono 11px, bordered). Collapses to a 40px icon-only
  button `≤860px`.
- Flex spacer.
- **Branch chip**: pill (`border-radius:20px`, 36px tall), green status dot + "Kerikeri ·
  BR-01" (mono branch code). Hidden `≤860px`.
- **Notifications** icon button (40×40, bordered) with 7px red badge dot (2px white ring).
- **"New" primary button**: 40px, accent bg, white, `+` icon + label, weight 600,
  shadow `0 1px 2px rgba(16,24,40,.18)` + inset top highlight. Collapses to icon-only `≤860px`.
- **Avatar**: 40px circle, ink bg, white initials.

Icon buttons: 40×40, `border-radius: var(--r-ctl)`, 1px border, muted icon; hover → canvas
bg, text color, stronger border.

### 2. Dashboard (representative content)
**Purpose:** Landing page; owner's at-a-glance health check.

**Layout:** centered `max-width:1320px`, padding `var(--pad)`.
- **Page header**: eyebrow (mono date) + `<h1>` greeting (26px/700, −0.02em) + subtitle
  (14px muted), with a right-aligned **segmented control** (7D / 30D / QTR / YR; mono;
  active segment = accent-soft bg + accent text).
- **KPI row**: 4-up grid (`repeat(4,1fr)`, gap `var(--gap)`), → 2-up `≤1080px`, → 1-up `≤520px`.
  Each KPI card: label + 32px tinted icon chip (blue/green/amber/red soft variants), big mono
  value (27px/600, currency symbol dimmed via `.c`), and a delta line (mono 12px; up=green
  with ↗ glyph, down=red).
- **Main grid**: `1.7fr / 1fr`, collapses to single column `≤1080px`.
  - Left stack: **Revenue card** (area chart) + **Recent invoices table**.
  - Right stack: **Activity feed** + **Upcoming bookings**.

**Revenue chart:** inline SVG area chart, viewBox `0 0 720 220`, `preserveAspectRatio:none`,
height 200px. Accent stroke 2.5px, gradient fill (accent .20 → 0 alpha), horizontal gridlines
`#EEF0F4`, 4.5px end-point dot with white ring. Mono x-axis labels below. **In the real app,
replace with Recharts `<AreaChart>` using the same accent + gradient.**

**Recent invoices table:** columns Invoice (mono id) / Customer (600) / Status badge / Amount
(mono, right-aligned). Row hover = canvas bg, hairline row separators.

**Status badges:** pill (`border-radius:20px`, 11.5px/500) with 6px leading dot:
- Paid → green soft / green
- Sent → accent soft / accent
- Overdue → red soft / red
- Draft → `#EEF0F4` / muted

**Activity feed:** rows of 34px tinted icon chip + title (13.5/600) + subtext (12.5 muted) +
mono relative time pushed right.

**Upcoming bookings:** rows with a 46px date block (mono day 18px/600 + uppercase month 10px),
title + subtext, mono amount pushed right.

---

## Screens added in this iteration

> **Coverage note:** the `app/` folder now mirrors **every page module in the repo** —
> all in-app screens, the full platform-admin console, the auth & public marketing surface,
> and the standalone kiosk / customer-portal / error apps. Sections 3–7 below describe the
> groups added on top of the original shell + dashboard.

These build on the same shell + `ds.css` token system. Three groups: **Staff management**
(redesigned from new pushed source), **Auth & public** (standalone, outside the app shell),
and **Platform Admin** (inside the shell, `data-active="admin"`).

### 3. Staff management (`Staff.html`, `StaffDetail.html`, `StaffSchedule.html`)
Redesigned to match the **new staff schema** that was pushed to the repo
(`pages/staff/StaffList.tsx`, `StaffDetail.tsx`, `pages/scheduling/StaffSchedule.tsx`):
`first_name` / `last_name`, `employee_id`, `position`, `role_type` (employee / contractor),
`reports_to`, hourly + overtime rates, `skills[]`, a weekly `work_schedule` map, and an
optional **linked user account**.

- **Staff list** — KPI strip (total / employees / with-login / avg rate), search + role +
  status segmented filters, table with avatar, employee ID, position, contact, a 7-day
  **work-days pip row**, reports-to, and status. Row actions: Edit · Deactivate/Activate ·
  Delete. **Add/Edit modal** (`.modal.wide`) carries every schema field plus a **work-schedule
  editor** (per-day toggle + start/end time) and a *“Also create as a user”* block that reveals
  user-role + branch selects (employee-with-login flow). **Delete modal** confirms and offers a
  linked *“also delete user account”* checkbox (only when an account exists).
- **Staff detail** — read → edit on one page (toggle `.editing` on the page root swaps
  read-only `.ro` rows for inputs). Sections: Personal information, Employment details, Work
  schedule (same editor). Sidebar: this-month stats, **Account** card (login state / user role /
  last sign-in), and a *“Create user account”* modal for staff with no login.
- **Staff schedule** — weekly **roster grid** (staff rows × 7 day columns) with per-shift chips
  tinted by branch, hover “+” to add a shift, branch segmented filter, Calendar/List view toggle,
  prev/next week nav, and an **Add-shift modal** (only staff *with accounts* are schedulable
  — mirrors the source’s constraint). Lives under **Work → Staff Schedule** in the nav.

### 4. Auth & public (standalone — `auth.css` + `ds.css`, no app shell)
A shared **split-screen** pattern: an ink brand panel (radial accent/purple glows, pitch +
feature list + HA node status) beside a centered form column. Brand panel hides `≤900px`; a
mobile logo appears in the form head. All live in `auth.css`.

- **`Login.html`** — email + password (show/hide peek), remember-device, Google + Passkey SSO
  buttons, and an **MFA modal** with 6-digit auto-advancing OTP inputs.
- **`Signup.html`** — 4-step wizard (Business → Admin → Plan → Confirm) with a numbered
  progress rail, password strength meter, monthly/annual plan toggle, plan cards, and a review
  summary. Maps to `PublicSignupRequest` / `signup-types.ts`.
- **`PasswordReset.html`** — single file, four states (request → sent → set-new → success);
  a `?token=` param jumps straight to set-new.
- **`VerifyEmail.html`** — invite activation: set a password for a pre-filled invited email
  (`verify-email` flow), success state → dashboard.
- **`MfaVerify.html`** — centered card on the ink gradient; Authenticator (OTP, paste-aware) /
  Backup-code tabs, trust-device option.
- **`LandingPage.html`** — marketing page: sticky nav, gradient hero, app-shot mock, logo wall,
  feature grid, 3-tier pricing, CTA band, footer. CTAs route to Signup/Login/Dashboard.
- **`InvoicePayment.html`** — customer-facing pay-an-invoice page: the tax-invoice document
  beside a sticky **pay panel** (card vs bank-transfer toggle, Stripe-style card input,
  surcharge note) and a payment-received confirmation. Re-uses the invoice `.doc` styles.

### 5. Platform Admin — full console (`Admin*.html`, 24 screens)
Inside the app shell (`data-active="admin"`), unified by a **shared sub-tab row** injected by
`admin-nav.js` (host element `<div id="admin-nav" data-active="…">`, styled by `.admin-tabs`
in `ds.css`). To add or reorder admin tabs, edit the `TABS` array in `admin-nav.js` once —
every page updates.

- **Console / Overview** (`AdminConsole.html`) — platform health cards + status.
- **Organisations** (`AdminOrganisations.html`) — tenant list: KPIs, plan pill, seat-usage
  mini-bar, MRR, status; rows → **Org detail** (`AdminOrgDetail.html`): hero, sub-tabs, users,
  activity, subscription + usage cards, danger zone.
- **Users** (`AdminUserManagement.html`) — platform admin users, roles, 2FA, invite modal.
- **Analytics** (`AdminAnalytics.html`) — MRR bars, plan-mix donut, signups, top orgs.
- **Plans & billing** (`AdminSubscriptionPlans.html`) — plan cards + promo coupons + coupon modal.
- **Feature flags** (`AdminFeatureFlags.html`) — global toggles with rollout %.
- **Trade families** (`AdminTradeFamilies.html`) — industry presets.
- **Email / SMS providers** (`AdminEmailProviders.html`, `AdminSmsProviders.html`) — routing,
  failover, volume & spend.
- **Email health** (`AdminEmailDeliveryHealth.html`) — deliverability funnel + suppression list.
- **Notifications** (`AdminNotificationManager.html`) — event → channel matrix (toggleable).
- **Integrations** (`AdminIntegrations.html`) — connection catalogue. **Xero**
  (`AdminXeroCredentials.html`) — OAuth app + tenant connections. **Calendar sync**
  (`AdminCalendarSync.html`) — Google/Outlook links.
- **Branding** (`AdminBranding.html`) — white-label accent/logo with live preview.
- **Security** (`AdminSecurity.html`) — auth policy, sessions, IP allowlist.
- **Branch overview** (`AdminBranchOverview.html`) — all branches across tenants.
- **Error log** (`AdminErrorLog.html`) — exceptions with expandable stack traces.
- **Audit log** (`AdminAuditLog.html`) — privileged-action trail.
- **HA & replication** (`AdminHAReplication.html`) — cluster topology + node health.
- **Migration** (`AdminMigration.html`) — schema migrations + live import progress.
- **Reports** (`AdminReports.html`) — platform report catalogue.
- **Settings** (`AdminSettings.html`) — global config + danger zone.
- **My profile** (`AdminProfile.html`) — admin account + 2FA.

### 6. Standalone apps (no org shell)
- **`Kiosk.html`** — in-branch self-check-in: welcome → rego entry (touch keypad) →
  vehicle summary → details form → success, with auto-return countdown. Big 44px+ hit targets,
  full-screen, branded. Mirrors `pages/kiosk/*` screen state machine.
- **`Portal.html`** — customer self-service hub keyed to a magic-link token: branded header,
  summary cards (balance / invoices / paid), My Details, and tabbed content (Invoices, Vehicles,
  Quotes, Bookings, Loyalty, Documents, Messages) with a "Powered by OraInvoice" footer.
  Accent driven by `--portal-accent` so tenants can re-skin. Mirrors `pages/portal/*`.
- **`ErrorPage.html`** — one file, four states (404 / feature-not-available gate /
  portal signed-out / 500) with a top switcher. Maps to `pages/common/FeatureNotAvailable.tsx`
  and the router's catch-all.

### 7. Auth & public (continued)
- **`PasskeySetup.html`** — WebAuthn enrolment (intro steps → device prompt → success).
- **`Privacy.html`** — legal page with sticky TOC + scroll-spy.
- **`Trades.html`**, **`Workshop.html`** — industry-specific marketing landings.
- **`Managed.html`** — help-centre / managed-content page (search, category grid, popular articles).

### 8. Payroll, scheduling extras, comms & the full Reports suite (latest iteration)
All built on the same shell + `ds.css`. **Payroll** is registered as a new nav item under **Work**;
the rest are reachable via the ⌘K command palette and contextual cross-links (Vehicle detail → PPSR,
Staff Schedule → Swaps, Staff → Leave, Notifications → SMS).

- **Payroll** (`Payroll.html`) — pay-run with a 4-step progress (Import → Review → Approve → Pay & file),
  gross/PAYE/KiwiSaver+ACC/net KPIs, per-employee table (ord/OT hours, gross, PAYE, KiwiSaver, net),
  employee vs contractor (withholding tax) handling. Maps to `pages/payroll/PayRunPage.tsx`.
- **Payslip detail** (`PayslipDetail.html`) — earnings (ordinary/OT/allowances/holiday/public-holiday),
  deductions (PAYE/KiwiSaver/student loan), employer contributions (KiwiSaver/ESCT/ACC), net-pay block,
  this-period + YTD + leave-balance sidebars. Maps to `pages/payroll/PayslipDetail.tsx`.
- **Staff self-service** — `MyPayslips.html` (own payslip history + leave balances + YTD) and
  `ClockScreen.html` (live clock, clock-in/out + break, job assignment, today's timeline, week summary).
  Map to `pages/staff/me/MyPayslipsPage.tsx` and `SelfServiceClockScreen.tsx`.
- **PPSR search** (`PPSRSearch.html`) — Personal Property Securities Register lookup: search form
  (rego/VIN/debtor), result banner, financing-statement cards (secured party, debtor, dates, collateral),
  search-history table, vehicle sidebar. Maps to `pages/ppsr/PPSRSearchPage.tsx` + `PpsrResultPanel`/`PpsrHistoryTable`.
- **SMS conversations** (`SmsChat.html`) — master–detail two-way SMS: conversation list (unread pips,
  opt-out state, credit balance), thread bubbles (in/out, delivery status), quick-reply templates, composer.
  Maps to `pages/sms/SmsChat.tsx`.
- **Shift swaps & cover** (`ShiftSwaps.html`) — tabbed (Swaps / Cover / History) approval queue with
  requester→peer shift chips, approve/decline, broadcast-cover. Maps to `pages/swaps/ShiftSwapPage.tsx`
  + `ShiftCoverPage.tsx`.
- **Leave approvals** (`LeaveApprovals.html`) — pending-request queue: type (annual/sick/bereavement),
  dates, days, balance-after bar, approve/decline. Maps to `pages/leave/ApprovalQueue.tsx`.

**Reports suite** — `Reports.html` now has a grouped **report library** (22 cards / 6 groups) linking to
real detail pages. Each report follows one pattern: crumbs → header (date-range segmented control + export)
→ KPI strip → chart/visual → data table. Built this iteration (the 3 originals — ProfitLoss, BalanceSheet,
AgedReceivables — already existed):
`RevenueSummary`, `OutstandingInvoices`, `CustomerStatement` (running-balance statement + aged summary),
`InvoiceStatus`, `InventoryReport`, `JobReport`, `FleetReport`, `HospitalityReport`, `POSReport`,
`ProjectReport`, `GstReturnSummary` (GST101 boxes), `TaxReturnReport` (provisional-tax instalments),
`WageVariance` (rostered vs actual), `TopServices`, `CarjamUsage`, `SmsUsage`, `StorageUsage`,
`ScheduledReports`, and `ReportBuilder` (config panel + live preview). Map to `pages/reports/*`.

> All section-8 screens are **presentation references with placeholder figures** — wire to real
> fetched data and preserve all payroll/tax math, gating, and Twilio/PPSR/IRD integration logic when porting.

> **Production mapping:** auth/public pages correspond to `pages/auth/*` and `pages/public/*`;
> admin pages to `pages/admin/*`; kiosk/portal to `pages/kiosk/*` and `pages/portal/*`. As with
> the shell, these are **presentation references** — re-skin the existing React routes/components
> against them; keep all auth, billing, gating, Stripe/MFA, and WebAuthn logic intact.

---

## Interactions & Behavior
- **Nav selection**: clicking a nav item moves the active state (single active at a time).
  In production, drive this from the router's active route (`NavLink` `isActive`).
- **Mobile drawer**: hamburger toggles `.nav-open` on the root; sidebar slides in
  (`transform` transition `.26s cubic-bezier(.4,0,.2,1)`); scrim fades in
  (`opacity .26s`) and closes the drawer on click; selecting a nav item also closes it.
- **Segmented date range**: clicking a segment moves the `.on` state (would refetch dashboard
  data for that range).
- **Search**: `⌘K` hint implies a command palette / global search modal (not built in the
  prototype — wire to the app's existing search).
- **Hover states**: defined for nav items, icon buttons, table rows, org switcher, primary
  button (darkens to `--accent-press`, 1px press translate).
- **Chart**: redraws on accent/theme change (via a `MutationObserver` in the prototype —
  not needed in React; just pass the accent token to Recharts).

**Responsive breakpoints:**
- `≤1080px`: main grid → 1 col; KPIs → 2 col.
- `≤860px`: sidebar → off-canvas drawer; hamburger shown; search → icon-only; branch chip
  hidden; "New" → icon-only.
- `≤520px`: KPIs → 1 col; h1 → 22px.

Minimum touch target 40–44px throughout.

---

## State Management
- `activeRoute` — derived from router (drives nav active state). **Don't** store separately;
  use `NavLink`.
- `navOpen` (boolean) — mobile drawer open/closed.
- `dateRange` — `'7D' | '30D' | 'QTR' | 'YR'`, drives dashboard queries.
- `commandPaletteOpen` (boolean) — for ⌘K search.
- Dashboard data (revenue series, KPI figures, recent invoices, activity, bookings) — fetched
  per current org + branch + dateRange. The numbers in the prototype are placeholders.
- **Theme tokens** (`accent`, `sidebar` ink/light, `density`, `radius`) are demonstrated via
  the prototype's Tweaks panel. In production these map to the existing theme system in
  `src/styles/themes.css` / `src/themes/registry.ts` — the ink sidebar should become a new
  registered theme (or a `data-sidebar` modifier). **The Tweaks panel itself is a
  prototyping aid and should NOT be shipped.**

---

## Design Tokens

### Colors
| Token | Value | Use |
|---|---|---|
| `--accent` | `#2F62F0` | Primary actions, active accents, chart |
| `--accent-press` | `#2450D0` | Primary button pressed |
| `--accent-soft` | `rgba(47,98,240,.12)` | Active nav / badge / icon-chip bg |
| `--ink` | `#0B1220` | Ink sidebar bg, avatar |
| `--canvas` | `#F5F6F8` | App background |
| `--card` | `#FFFFFF` | Card / top bar / sidebar(light) bg |
| `--border` | `#E8EBF0` | Hairline borders |
| `--border-strong` | `#D7DCE3` | Hover borders |
| `--text` | `#111722` | Primary text |
| `--muted` | `#687283` | Secondary text |
| `--muted-2` | `#97A0AE` | Tertiary / axis / placeholders |
| `--ok` / `--ok-soft` | `#1F8A5B` / `#E4F4EC` | Paid, positive |
| `--warn` / `--warn-soft` | `#B5740F` / `#FBEFD9` | In-progress |
| `--danger` / `--danger-soft` | `#C8412F` / `#FBE7E3` | Overdue, alerts |

**Ink sidebar palette:** bg `#0B1220`; text `rgba(255,255,255,.66)`; strong `#fff`;
muted `rgba(255,255,255,.34)`; hover `rgba(255,255,255,.06)`; active bg `rgba(255,255,255,.07)`;
border `rgba(255,255,255,.08)`; active icon tint `#7FA0FF`.
A **light sidebar** variant is also defined (bg white, text `#4A5363`, active bg = accent-soft)
for users who want to stay closer to the original.

### Typography
- **UI / body:** `'IBM Plex Sans', system-ui, sans-serif`.
- **Numbers, IDs, labels, eyebrows, counts:** `'IBM Plex Mono', ui-monospace, monospace`
  with `font-feature-settings: "tnum" 1` (tabular figures). This mono accent is core to the
  intended feel — use it for every monetary value, invoice/branch code, KPI, group label,
  and relative timestamp.
- Scale: h1 26/700 (−0.02em) · card title 15/600 · KPI value 27/600 · chart big 30/600 ·
  body 13.5–14 · labels 12.5 · mono micro-labels 10.5–11 (0.08–0.13em tracking, uppercase).

### Spacing
- `--pad` (page/topbar padding): 26px (compact 18 / comfy 34).
- `--gap` (grid/card gap): 22px (compact 14 / comfy 30).
- Sidebar rail width: 264px.

### Border radius
- `--r-card` 14px (sharp 4 / soft 20) · `--r-ctl` 10px (controls) · `--r-chip` 8px.

### Shadows
- `--shadow-card`: `0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.04)`.
- `--shadow-pop`: `0 12px 32px -8px rgba(11,18,32,.22), 0 2px 6px rgba(11,18,32,.08)`
  (drawer / popovers).

---

## Assets
- **Icons:** inline 24×24 stroke SVGs (stroke-width ~1.9–2), defined in the `ICON` map in the
  HTML. Visually equivalent to Lucide/Heroicons-outline — in production use the project's
  existing icon set (the original app already uses outline icons) rather than these paths.
- **Logo:** the document glyph in the logo mark is a **placeholder**. Swap in the real
  OraInvoice logo.
- **Fonts:** IBM Plex Sans + IBM Plex Mono via Google Fonts. Self-host or add to the project's
  font pipeline for production.
- **No raster images** are used.

---

## Files
- `OraInvoice Redesign.html` — the full hi-fi prototype (shell + dashboard). All tokens,
  markup, and interactions live here; this is the primary reference.
- `tweaks-panel.jsx` / `tweaks-app.jsx` — the live theming/Tweaks panel used in the prototype
  only (accent, sidebar ink/light, density, radius). **Prototyping aid — do not ship.**

**Per-screen prototypes (in `app/`, all share `ds.css` + `shell.js`):**
- `ds.css` — the design-system stylesheet (tokens + every component class). Single source of truth.
- `shell.js` — renders the sidebar + top bar into every in-app page (`data-active` / `data-title`).
- `auth.css` — extra styles for the standalone auth/public pages (split-screen, wizard, OTP, plans).
- `admin-nav.js` — injects the shared platform-admin sub-tab row (edit its `TABS` array to change nav).
- **Staff:** `Staff.html`, `StaffDetail.html`, `StaffSchedule.html`.
- **Auth/public:** `Login.html`, `Signup.html`, `PasswordReset.html`, `VerifyEmail.html`,
  `MfaVerify.html`, `PasskeySetup.html`, `LandingPage.html`, `Trades.html`, `Workshop.html`,
  `Managed.html`, `Privacy.html`, `InvoicePayment.html`.
- **Admin (24):** `AdminConsole.html` + `Admin*.html` (Organisations, OrgDetail, UserManagement,
  Analytics, SubscriptionPlans, FeatureFlags, TradeFamilies, EmailProviders, SmsProviders,
  EmailDeliveryHealth, NotificationManager, Integrations, XeroCredentials, CalendarSync, Branding,
  Security, BranchOverview, ErrorLog, AuditLog, HAReplication, Migration, Reports, Settings, Profile).
- **Standalone apps:** `Kiosk.html`, `Portal.html`, `ErrorPage.html`.
- Plus the rest of the in-app screens (Invoices, Quotes, Job Cards, Accounting, etc.).

### Mapping to the existing codebase
- Replaces/updates: `frontend/src/layouts/OrgLayout.tsx` (shell), the org dashboard page,
  and theme definitions in `frontend/src/styles/themes.css` + `frontend/src/themes/registry.ts`.
- Staff redesign maps to `frontend/src/pages/staff/*` + `pages/scheduling/StaffSchedule.tsx`.
- Auth/public map to `frontend/src/pages/auth/*` and `pages/public/*`; admin to `pages/admin/*`.
- Keep using: React Router `NavLink` for nav, Recharts for the revenue chart, Tailwind v4
  `@theme` variables for tokens, Headless UI for the org-switcher / menus.
