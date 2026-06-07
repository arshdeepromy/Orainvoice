# OraInvoice **Mobile** — Kiro Implementation Handoff

This is the handoff for the **mobile app** prototype in `mobile-v2/` (the phone-frame React/Babel
prototype: `OraInvoice Mobile Redesign.html` + `mobile-v2/*`). It tells the Kiro IDE agent how to
(1) reproduce the design **exactly**, (2) wire every screen to the **real working backend**, and
(3) re-use the **frontend-v2 desktop** calculations, validation, and **module gating** so mobile
behaves identically to desktop — never a parallel re-implementation of business rules.

> **Companion docs:** desktop shell/dashboard handoff lives in `OraInvoice_Handoff/`. The
> **Guardrails** there apply here too. This doc is mobile-specific and adds the **backend +
> logic-port** instructions that the prototype alone does not carry.

---

## 0. TL;DR for the agent
1. The `mobile-v2/` files are a **design reference**, not shippable code. Rebuild the screens in
   the existing **React 19 + Vite + Tailwind v4** app as a **mobile route tree / responsive layer**,
   re-using the existing components, hooks, API client, and guards.
2. **Do not invent backend calls.** Every list/detail/create screen must call the **same endpoints
   the desktop frontend-v2 already calls.** Re-use `frontend-v2/src/api/*` (axios `apiClient`) and the
   existing React Query hooks. If a hook exists, call it; do not write a new fetch.
3. **Port — never re-derive — calculations and gating.** GST/tax math, line totals, rounding,
   payroll/PAYE/KiwiSaver, due-dates, and every role/plan/feature-flag gate must come from the
   **same source modules** desktop uses. Add tests asserting identical output (§4, §5).
4. Work screen-by-screen on a branch; run lint + typecheck + tests after each; open PRs.

---

## ⚠️ Guardrails — what NOT to touch (same as desktop)
Presentation only. **Do NOT alter or "simplify":**
- **Business logic & calculations** — GST/tax, line-item subtotals/totals, discounts, rounding,
  currency formatting, due-date logic, payroll (PAYE/KiwiSaver/ACC/student-loan), retentions,
  progress-claim %s. Keep byte-for-byte; only relocate into an equivalent shared hook/util.
- **Permission / role / plan / feature-flag gating** — every `canX`, role check, subscription gate,
  and conditional that hides or disables a nav item, module, button, or route. Mobile must hide/disable
  **exactly** what desktop hides for the same user.
- **Conditional rendering** — `&&`, ternaries, early returns, `Suspense`/loading/empty/error states.
- **Data fetching & state** — queries, mutations, cache keys, `useEffect` deps, optimistic updates,
  form submit/save paths, validation schemas.
- **Routing & auth** — route params, guards, redirects, token refresh, MFA, CSRF, branch scoping.

If a styling change *requires* touching any of the above → **stop and flag it**, don't guess.

---

## 1. Backend connection — use the real API client (don't rebuild it)
The desktop already ships a complete, battle-tested API layer. **Mobile re-uses it as-is.**

**`frontend-v2/src/api/client.ts`** (the axios instance) already handles, and mobile must inherit
**all** of it unchanged:
- `baseURL: '/api/v1'`, `withCredentials: true` (sends the httpOnly refresh cookie).
- **Auth:** `Authorization: Bearer <access_token>` injected per request; automatic
  **401 → `/auth/token/refresh` → retry** with a single-flight refresh mutex; redirect to `/login`
  when refresh truly fails.
- **Branch scoping:** injects `X-Branch-Id` from `localStorage('selected_branch_id')` (omitted when
  "all"). Mobile's branch switcher must write the **same** localStorage key so every call stays scoped.
- **Portal CSRF:** double-submit `X-CSRF-Token` from the `portal_csrf` cookie on state-changing
  requests (for the customer Portal / public-booking / payment screens).
- **`/api/v2/...`** absolute paths bypass the `/api/v1` baseURL.

**Rules:**
- Import and call the existing `apiClient` (and the typed modules already present:
  `api/leave.ts`, `api/payslips.ts`, `api/ppsr.ts`, `api/schedule.ts`, …) plus the existing
  React Query hooks. **No new base URL, no new auth code, no hard-coded links.**
- Backend base URL / env (`VITE_API_*`, proxy target) comes from the existing `.env` /
  Vite proxy config — **do not hard-code** an endpoint string in a component.
- Customer-facing screens (Portal, Public booking, Payment page) use the **portal session + CSRF**
  path, not the org JWT path — keep them on the existing portal auth flow.

> If a screen below has **no** existing endpoint/hook, that's a backend gap — **flag it**, don't
> fabricate a URL.

---

## 2. Screen → desktop route / source / data map
Rebuild each mobile screen against the **same** route data the desktop page uses. "Source" is the
desktop page module to mirror for fetching + gating + calc; reuse its hooks.

| Mobile screen (`mobile-v2`) | Desktop source (`frontend*/src/pages/…`) | Data via |
|---|---|---|
| Login / MFA / Reset / Signup / Setup wizard | `auth/*`, `public/*` | existing auth endpoints, MFA token, refresh-cookie flow |
| Home / Dashboard | org dashboard page | existing dashboard queries (org + branch + range) |
| Invoices list / detail / create | `invoices/*` | invoice hooks; **GST + totals from `InvoiceCreate.tsx` `computeTotals` (see Appendix A.3)** |
| Quotes list / detail / create | `quotes/*` | quote hooks; accept→convert reuses invoice-create path |
| Recurring invoices | `invoices/recurring` (Recurring) | recurring schedule hooks |
| Payments / Payment page | `payments/*`, portal pay | payment intent + portal CSRF |
| Expenses list / detail | `expenses/*` | expense hooks; GST-on-expense util |
| Banking / Reconciliation | `banking/*` | bank feed + reconcile hooks |
| GST return / Tax | `tax/*`, `gst/*` | GST101 box calc util — **port, don't re-derive** |
| Reports / Accounting | `reports/*`, `accounting/*` | report query hooks |
| Jobs / Job detail / Job Cards | `jobs/*`, `jobcards/*` | job hooks |
| Bookings / Booking detail / Schedule | `bookings/*`, `scheduling/*` | `api/schedule.ts` → `listEntries`/`bulkCreate`/`copyWeek` (`/api/v2/schedule*`) |
| Projects / Project detail | `projects/*` | project + milestone hooks |
| Construction (progress claims / variations / retentions) | `construction/*` | `utils/progressClaimCalcs.ts` + `utils/retentionCalcs.ts` + `utils/variationCalcs.ts` |
| Claims | `claims/*` | `useClaims` / `useCustomerClaims` / `useClaimsReports` hooks |
| Inventory / Item detail / Items / Catalogue / Purchase orders / Stock | `inventory/*`, `items/*`, `purchaseorders/*` | stock + PO hooks; `utils/inventoryCalcs.ts` (`filterLowStockProducts`) |
| Assets | `assets/*` | asset hooks |
| Vehicles / Vehicle detail | `vehicles/*` | vehicle hooks; `utils/buildVehicleDisplayFields.ts` + `vehicleHelpers.ts` (WOF/service) |
| PPSR | `ppsr/*` | `api/ppsr.ts` |
| Staff / Staff detail | `staff/*` | staff hooks; **role-gated** fields (pay rate) via `useAuth().user.role` |
| Payroll / Payslips | `payroll/*` | `api/payslips.ts` — **render** server PAYE/KiwiSaver/ACC, never recompute |
| Leave | `leave/*` | `api/leave.ts` + `useStaffLeave` |
| Roster / Shift swaps | `scheduling/*`, `swaps/*` | `useRosterWeek` + `api/schedule.ts`; **only account-linked staff schedulable** |
| Messages (SMS) | `sms/*` | SMS thread hooks; credit balance + opt-out gating |
| Loyalty | `loyalty/*` | loyalty hooks |
| Customer portal / Public booking | `portal/*`, `kiosk/booking` | portal session + CSRF |
| Notifications | `notifications/*` | notification hooks |
| Settings | `settings/*` | settings hooks |

> Platform/global-admin pages are intentionally **excluded from mobile** (field & owner use only).

---

## 3. Module gating — mobile must mirror desktop exactly
The mobile "All screens" directory and tab bar are **prototype navigation aids**. In production:
- **Derive every nav/module entry from the same gating desktop uses** — role (`role_type`,
  owner/admin/employee/contractor), **subscription plan**, **feature flags**, and **trade-family**
  presets. A module that desktop hides for a plan/role **must not appear** in the mobile tab bar,
  the "Browse all screens" directory, or be reachable by deep link.
- Reuse the existing permission hooks/guards (e.g. `useCan*`, route guards, feature-flag context).
  **Do not** hand-roll a second gating table for mobile.
- Per-field gating too: e.g. Staff **pay rate** and Payroll are owner/admin-only on desktop — keep
  them gated on mobile. Customer-facing portal screens never expose org-internal data.
- Branch scoping (`X-Branch-Id`) must gate list contents identically.

**Acceptance:** for a given test user, the set of reachable mobile modules == the set desktop shows.

---

## 4. Calculations to port verbatim (add equality tests)
Copy the **exact** desktop utils/hooks; add unit tests asserting identical output to desktop for the
same inputs. Do **not** re-implement by eye.
- **Invoice/quote:** line total = qty × rate; subtotal; **GST 15%**; rounding; total; discounts;
  due-date from terms; currency formatting (tabular figures).
- **GST return:** GST101 box math (sales/purchases/net).
- **Payroll:** ordinary/OT hours → gross; **PAYE**, **KiwiSaver**, **ESCT/ACC**, student loan;
  employee vs contractor (withholding) handling; net pay; YTD.
- **Construction:** progress-claim % of contract; variations; **retentions** held/released.
- **Inventory:** margin = 1 − cost/price; reorder/low-stock threshold; stock adjustments.
- **Vehicles:** WOF/service status (valid / due / overdue) from dates + odometer.

> The prototype's numbers are **placeholders**. Replace with fetched data; the **math** must come
> from the desktop source.

---

## 5. Design fidelity — match the prototype exactly
The visual system is already specified in code; reproduce it precisely.
- **Tokens:** see `mobile-v2/ds-mobile.css` (the mobile design-system: colors, spacing, radii,
  shadows, the same blue accent + IBM Plex Sans / **IBM Plex Mono tabular** number treatment as
  desktop). Map these onto the project's Tailwind v4 `@theme` variables — don't introduce a parallel
  token set; extend the existing one with mobile values.
- **Components:** navbar, tab bar, cards, list rows (`.li`), KPI cards, status badges, segmented
  controls (`.seg`), chips, bottom-sheets, FAB, inputs/fields — all defined in `ds-mobile.css`.
  Reuse the app's existing component primitives; restyle to match.
- **Icons:** `mobile-v2/icons.jsx` is visually equivalent to the app's outline icon set — use the
  **project's** icon library, not these raw paths.
- **Interactions:** stack push/pop nav, bottom-sheet open/scrim, segmented-tab switching, FAB,
  pull-to-refresh where lists fetch. Tweaks panel (`mobile-v2/tweaks-panel.jsx`) is a
  **prototyping aid — do not ship.**
- **Responsive / touch:** min 44px hit targets; safe-area insets; the phone frame in the prototype
  is just a viewport — production renders full-bleed on device.
- **Per-screen reference:** `mobile-v2/SCREENS.md` lists every screen and grouping.

---

## 6. Suggested order of work
1. **Auth + shell** (tab bar, stack nav, branch switcher writing `selected_branch_id`) wired to the
   real session/refresh/MFA flow.
2. **Tokens & components** from `ds-mobile.css` into the Tailwind theme + shared primitives.
3. **Read-only money screens** (Invoices, Quotes, Expenses, Payments, Reports) — wire data, **port
   GST/total calc + tests**.
4. **Work screens** (Jobs, Bookings, Schedule, Projects, Construction) — data + gating.
5. **Catalogue** (Inventory, Items, PO, Assets, Vehicles, PPSR).
6. **People & payroll** (Staff, Payroll, Payslips, Leave, Roster, Swaps) — **port payroll calc +
   role gating + tests**.
7. **Customer-facing** (Portal, Public booking, Payment page) on the **portal/CSRF** path.
8. **Onboarding** (Signup, Setup wizard, Reset, MFA).
9. **Gating audit** (§3 acceptance) + a11y + responsive pass + full test suite, then cut over
   per-route behind a feature flag.

---

## 7. Definition of done (per screen)
- [ ] Matches the prototype's layout/tokens (spot-checked against `mobile-v2/*` + `SCREENS.md`).
- [ ] Reads/writes via the **existing API client + hooks** (no new fetch, no hard-coded URL).
- [ ] All money/tax/payroll figures computed by the **ported desktop util**; equality test passes.
- [ ] Visible/enabled modules & fields match desktop **gating** for the test role/plan/flags.
- [ ] Branch scoping (`X-Branch-Id`) correct; loading/empty/error states present.
- [ ] Auth/refresh/MFA/CSRF intact; lint + typecheck + tests green; PR opened.

---

## Appendix A — Real repo symbols (verified against `frontend-v2`)
These are the **actual** files, hooks, contexts, endpoints and functions in the repo. Import and
reuse them — **do not** re-create equivalents. (Paths are under `frontend-v2/src/`.)

### A.1 Backend / API layer
- `api/client.ts` → default-export **`apiClient`** (axios). Also exports `setAccessToken`,
  `getAccessToken`, `isAccessTokenValid`, `doTokenRefresh`. Handles Bearer + 401→refresh +
  `X-Branch-Id` + portal CSRF. **Reuse as-is.**
- Typed API modules (call their exported fns, don't re-fetch):
  - `api/schedule.ts` → `listEntries`, `bulkCreate`, `copyWeek`, `listTemplates`
    → endpoints `GET /api/v2/schedule`, `POST /api/v2/schedule/bulk`,
    `POST /api/v2/schedule/copy-week`, `GET /api/v2/schedule/templates`.
  - `api/leave.ts`, `api/payslips.ts`, `api/ppsr.ts` → use their exported request fns.
- Data hooks already written (`src/hooks/`): `useClaims`, `useClaimsReports`,
  `useCustomerClaims`, `useRosterWeek`, `useStaffLeave`, `usePaymentMethodEnforcement`,
  `useOffline`, `usePageMeta`, `useTabHash`. **Call these from the mobile screens.**
- Known endpoints observed: `POST /api/v1/auth/token/refresh`, `GET /api/v2/modules`,
  `GET /api/v2/flags`, plus the `/api/v2/schedule*` set above. Everything else resolves through
  `apiClient` (`/api/v1` base) — find the desktop page's existing call; **don't invent a path.**

### A.2 Gating — reuse these exact guards
- **Modules:** `contexts/ModuleContext.tsx` → `ModuleProvider`, `useModules()` →
  `{ modules, enabledModules, isEnabled(slug), isLoading, refetch }`. Backed by `GET /api/v2/modules`
  (skipped for `global_admin`). 
- **Module route guard:** `hooks/useModuleGuard.ts` → **`useModuleGuard(moduleSlug)`** — redirects to
  `/dashboard` with a warning toast when a module is disabled. **Wrap every gated mobile route with it.**
- **Feature flags:** `contexts/FeatureFlagContext.tsx` → `useFeatureFlags()`, **`useFlag(flagKey)`**,
  and the **`<FeatureGate flagKey fallback>`** component. Backed by `GET /api/v2/flags`.
- **Auth/role/branch:** `contexts/AuthContext.tsx` (`useAuth()` → `user.role`, `org_id`,
  `isAuthenticated`), `contexts/BranchContext.tsx`, `contexts/TenantContext.tsx`,
  `contexts/TerminologyContext.tsx` (trade-family wording), `contexts/PlatformBrandingContext.tsx`.
- Helper: `utils/moduleCalcs.ts`, `utils/featureFlagCalcs.ts` for any derived gating math.

> **Mobile gating rule:** the tab bar + "Browse all screens" directory must be built by filtering
> through `isEnabled(slug)` + `useFlag()` + `user.role` — identical inputs to desktop. A module the
> guard hides must be unreachable by deep link too (wrap its route in `useModuleGuard`).

### A.3 Calculation utils — import verbatim, add equality tests
The repo already keeps money/business math in **pure, separately-tested** utils. Reuse them; the
repo's own pattern is "copied VERBATIM … guarding against drift" with a `*.calculations.test.tsx`.
- **Invoice/quote GST & totals** — formulas live in `pages/invoices/InvoiceCreate.tsx`, locked by
  `pages/invoices/InvoiceCreate.calculations.test.tsx`. Port these **exactly**:
  - `calcLineAmount = round(qty × rate × 100) / 100`
  - GST-inclusive ex-rate = `round((inclPrice / 1.15) × 100) / 100`
  - per-line GST (inclusive) = `round((round(qty × inclPrice × 100)/100) − amount) × 100)/100`
    — *keeps the extra cent; do not substitute `amount × 0.15`*
  - per-line GST (exclusive) = `round(amount × tax_rate) / 100`
  - discount(%) = `subTotal × value/100`; discount(fixed) = `value`
  - `total = (subTotal − discount) + tax + shipping + adjustment`
  - **GST rate is 15%.** Copy the mobile screen's `computeTotals` from this file and reuse its test.
- `utils/currencyCalcs.ts` → **`formatCurrencyAmount(amount, code)`**, `getCurrencyFormat`,
  `isMissingExchangeRate`, `CURRENCY_REGISTRY` (org base currency drives symbol/decimals — NZD `$`,
  2dp). Use for every money string instead of ad-hoc formatting.
- `utils/progressClaimCalcs.ts` → `calculateProgressClaimFields()` (revised contract, work-this-period,
  amount due, completion %), `validateCumulativeNotExceeded()`.
- `utils/retentionCalcs.ts` → `calculateOutstandingRetention()`, `validateReleaseAmount()`,
  `calculateRetentionPercentage()`.
- `utils/variationCalcs.ts` (variations), `utils/jobCalcs.ts` → `isValidStatusTransition(from,to)`
  (status machine: draft→quoted→accepted→in_progress→completed→invoiced), `calculateJobProfitability()`.
- `utils/inventoryCalcs.ts` → `filterLowStockProducts()` (low = `stock_level ≤ reorder_point`),
  `detectPricingRuleOverlap()`.
- `utils/timeTrackingCalcs.ts` → `detectOverlap()`, `aggregateTimeByProject()`,
  `canConvertToInvoice()`.
- `utils/loyaltyCalcs.ts`, `utils/tippingCalcs.ts`, `utils/tableCalcs.ts`,
  `utils/buildVehicleDisplayFields.ts` + `utils/vehicleHelpers.ts` (WOF/service display),
  `utils/bookingFormHelpers.ts`, `utils/invoiceReceiptMapper.ts`.

> Payroll PAYE/KiwiSaver/ACC math is computed **server-side** and returned by the payslip endpoints
> (`api/payslips.ts`) — mobile **renders** those values, never recomputes them. Same for GST-return
> box totals: fetch, don't re-derive.

### A.4 Convention to follow (the repo already does this)
- Utils are **pure + unit-tested**; when you port one, copy its matching test (e.g.
  `*.calculations.test.tsx` / property tests) so mobile asserts byte-identical output.
- API consumers use safe access (`?.` + `?? []`/`?? 0`) and thread an `AbortSignal` from
  `useEffect` cleanup — mirror this in mobile data calls.
- If the repo carries `.kiro/steering/*` docs (e.g. safe-API-consumption patterns), **read and
  obey them** — this handoff sits on top of, not instead of, those.
