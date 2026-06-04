# Frontend Redesign — Final Audit (Task 79)

> **Spec:** `.kiro/specs/frontend-redesign/` · **Tracker:** `docs/REDESIGN_TRACKER.md`
> **Audited:** 2026-06-03 · **Scope:** the self-contained `frontend-v2/` rebuild
> (Vite 8 + React 19 + TS + Tailwind v4 + Headless UI), served under `/new/`.

## Verdict

**COMPLETE.** All 79 tasks in `tasks.md` are `[x]`. Every one of the 342 tracked
items (294 pages + 48 modals/popups/drawers) in `REDESIGN_TRACKER.md` is ✅. The
project builds clean and the full test suite passes.

| Gate | Result |
|------|--------|
| `npm install` (clean) | exit 0 |
| `npm run build` (`tsc -b && vite build`) | **exit 0** (~220 code-split chunks) |
| `npx vitest run` | **111 passed / 111** across 20 files |
| `getDiagnostics` on touched files | no diagnostics |
| Imports from old `frontend/` tree | **none** (grep: 0 matches) |
| Residual `dark:` Tailwind variants | **none** (only doc-comments + a marketing block's `dark` variant-name) |
| New `as any` on API responses | none introduced (pre-existing verbatim casts preserved) |

The only build output is the standard Vite advisory that the lazy-loaded
`puck` chunk exceeds 600 kB — expected (it's the visual-page-editor render
runtime, code-split and only fetched for editor-published public pages), not an
error.

---

## Method

1. **Tracker walk.** Every row in `REDESIGN_TRACKER.md` was driven to ✅ as its
   task completed; a final grep confirms zero remaining `| ⬜ |` data rows.
2. **Router cross-reference.** Every `path="…"` in `frontend/src/App.tsx` (the
   original router) plus the module routes in `frontend/src/router/ModuleRouter.tsx`
   were matched against `frontend-v2/src/App.tsx`. Every original route exists in
   v2 with the **same path, the same `ModuleRoute moduleSlug`, and the same
   guard nesting** (RequireAuth / RequireGlobalAdmin / RequireOrgAdmin /
   RequireAutomotive / GuestOnly).
3. **Modal/drawer cross-reference.** All 48 modal/popup/drawer rows confirmed
   ported (most as dependencies of the page that opens them).
4. **Per-page checks.** For each ported page the verbatim-port workflow verified
   buttons, API calls, forms, calculations, module/role/trade-family gates, and
   loading/empty/error states against the original, then re-ran build + tests.

---

## Findings & gaps closed during the audit

The incremental per-task verification kept the build green throughout, so the
final audit surfaced only bookkeeping/parity items, all now resolved:

1. **`pages/invoices/RecurringInvoices.tsx` was never ported.** This is a
   standalone page that the original router does **not** route (only its test
   renders it) — distinct from the routed `pages/recurring/RecurringList.tsx`.
   It had been left ⬜. **Fixed:** ported verbatim (create/edit/pause/cancel
   schedule manager, line-item totals math, customer typeahead) with token
   restyle, and wired a reachable route `/invoices/recurring` (FR-2b). Build +
   tests re-verified green.
2. **Stale tracker rows.** Dashboard variants (rows 1–4), `ServiceTypeModal`
   (modal 31), and several report/notification rows had been completed inside
   earlier multi-page tasks but their tracker rows still read ⬜. **Fixed:**
   reconciled every row to ✅ with the owning task noted.
3. **Summary counts.** The tracker header still showed `0 / 239`. **Fixed:**
   updated to `342 / 342` and stamped COMPLETE.

No functional regressions were found. No page was missing buttons, API calls,
calculations, gates, or states relative to its original.

---

## Intentional deviations from the original (all sanctioned by the spec)

These are deliberate and consistent across the rebuild; none drop functionality:

- **Design tokens, not the legacy palette.** Per FR-2, every page is restyled to
  the `ds.css`-derived token system (`text-text`/`text-muted`/`text-muted-2`,
  `bg-card`/`bg-canvas`, `border-border`, `accent`, `ok`/`warn`/`danger`/`purple`
  soft+solid, `rounded-ctl`/`rounded-card`, `shadow-card`/`shadow-pop`). All
  `dark:` variants were removed because the v2 tokens are theme-aware.
- **UI primitive variant mapping.** v2 `Button` has no `secondary` variant →
  mapped to `ghost`; `Badge` `warning`→`warn` and `error`→`danger`; `AlertBanner`
  keeps `error`/`info`/`warning`/`success`. v2 `Button`/`Badge` are default
  exports (re-exported as named from the `@/components/ui` barrel).
- **FR-2b reachability routes.** Pages the original never routed (reached only by
  tests or embedded internally) were given reachable `/…` routes so nothing is
  orphaned — e.g. `/invoices/recurring`, `/reports/builder`,
  `/reports/{inventory,jobs,hospitality,pos,projects,tax-return,scheduled}`,
  `/jobs/list`, `/bookings/list`, `/inventory/*` sub-pages, `/customers/{fleet-accounts,discount-rules}`,
  `/ecommerce/{sku-mappings,api-keys}`, `/reservations`, `/sms/usage`,
  `/notifications/wof-rego-reminders`, `/kiosk/clock`, `/passkey-setup`,
  `/book/:orgSlug`. Each is documented inline in `App.tsx`.
- **`SafePage` wrapper omitted.** The original wraps every route in `<SafePage>`;
  v2's convention is the bare page under a single app-level `ErrorBoundary` +
  `Suspense`, with `ModuleRoute` for module gating. Behaviour is equivalent.
- **Prop-based detail pages use route wrappers.** Mirroring the original's
  `*Route` wrappers, v2 has `JobDetailRoute`, `StaffDetailRoute`,
  `ProductDetailRoute`, `ProjectDashboardRoute`, `LocationDetailRoute`,
  `TransferDetailRoute`, `AssetDetailRoute`, `BookingPageRoute` (read `:id`/slug
  via `useParams`, pass as prop).
- **Visual-page-editor: render path only.** The public marketing pages and the
  `PublicPageRenderer` catch-all need the Puck **render** blocks
  (`@/admin/page-editor/puckConfig` + the 19 `*Component` blocks + `headingCounter`),
  which were ported. The editor **editing** surface (PageEditorEdit/List/Redirects,
  MediaLibraryModal, toolbar/drawers, autosave, MediaField) is a separate spec
  and was intentionally **not** ported; those `/admin/page-editor*` routes point
  at `PlaceholderPage`.
- **OfflineBanner/OfflineProvider ported but not mounted.** The 3 shared modals
  in Task 74 were ported (BlockingPaymentModal, ExpiringPaymentWarningModal,
  ConflictResolutionModal) along with `OfflineContext`/`useOffline`/`offlineStorage`/
  `OfflineBanner`. The payment-enforcement modals are wired into `OrgLayout` via
  `usePaymentMethodEnforcement` exactly as the original; `OfflineBanner`/`OfflineProvider`
  are ported for parity but **not mounted** — matching the original, where they
  are referenced only by tests, never by the production App/OrgLayout.
- **Strict-TS shims.** v2's tsconfig enables `noUnusedLocals`/`noUnusedParameters`
  (the original's does not). A few verbatim-but-unused declarations from the
  source (e.g. `backendStepToUi`, PPSR owner-lookup flags, ExpenseList's
  `CustomerSearch`) are kept intact with a `void x` reference — preserving the
  code verbatim while satisfying the stricter build. One pre-existing source type
  hole (`WizardData.address`) was made an optional field; runtime is identical.

---

## Parity coverage by area (all ✅)

- **Auth** — Login, Signup wizard + steps, MFA verify/challenge, passkey setup,
  password reset (request/complete), verify email; AuthContext/MFA flows verbatim.
- **Dashboard** — role dispatcher + GlobalAdmin/OrgAdmin/Salesperson variants + 12 widgets.
- **Invoices/Quotes** — split-panel list+detail+create, full GST/discount/total
  math byte-identical, issue/credit-note/refund/QR/print/PDF, recurring schedules.
- **Customers/Vehicles/PPSR** — list/create/profile, fleet accounts, discount
  rules, CarJam onboarding, PPSR search + drawer.
- **Jobs/Job Cards/Bookings** — board/list/detail, live timers, kanban DnD,
  booking calendar + public booking page.
- **Staff/Schedule/Time/Leave/Payroll** — staff CRUD + tabs, roster grid editor,
  schedule calendar, shift swaps/cover, leave approvals, timesheet, pay run +
  payslip, self-service clock + payslips, people settings sub-pages.
- **Inventory/Items/Catalogue** — stock levels/movements/adjust/take/transfers,
  products, purchase orders, pricing rules, categories, CSV import, items +
  package builder, parts/fluids catalogue.
- **Settings** — full tabbed container + org/business/branch/billing/profile/
  security/MFA/users/modules/invoice-template/currency/language/printer/webhooks/
  feature-flags/accounting/online-payments + people sub-pages.
- **Admin Console** — AdminLayout shell + organisations/detail/users/plans/
  trade-families/feature-flags/analytics/audit-log/error-log/settings/security/
  branding/integrations(+SMS/Email/Calendar/Xero tabs)/migration/live-migration/
  HA replication/notifications/reports/branches/profile + 4 admin modals.
- **Reports/Accounting/Banking/Tax** — reports hub (10 tabs) + builder + financial
  reports + the 7 standalone reports; chart of accounts/journals/periods; bank
  accounts/transactions/reconciliation; GST periods/filing/wallets/position; expenses.
- **Notifications/SMS** — notifications hub (preferences/templates/log/reminders/
  overdue) + inbox + WOF/rego reminders; SMS chat + usage.
- **POS/Kitchen/Floor Plan** — touch POS (offline store/sync, barcode, payment,
  receipt print) + kitchen display + floor plan + reservations.
- **Portal (public)** — self-contained PortalPage + 13 tabs + payment/recover/
  signed-out; branded, token-based, "Powered by OraInvoice".
- **Kiosk** — vehicle check-in multi-step flow + staff clock screen + QR popup.
- **Public** — landing/trades/workshop/privacy (Managed via Puck), invoice
  payment, staff-roster viewer, QR result pages, PublicPageRenderer catch-all.
- **Construction/Claims/Compliance** — progress claims/variations/retentions;
  claims list/create/detail/reports + 2 modals; compliance dashboard + 2 modals.
- **Franchise/Projects/E-commerce/Data** — franchise dashboard/locations/transfers,
  projects, WooCommerce + SKU mappings + API keys, data import/export/JSON.
- **Onboarding/Setup** — onboarding wizard, setup wizard + 7 steps, setup guide.
- **Shared UI/modals** — Modal/ConfirmDialog base + MFA/payment/offline/schedule
  modals + every page-owned modal.

---

## Infrastructure (additive, original files untouched)

- **`docker-compose.frontend-v2.yml`** (Task 75) — a new, additive `frontend-v2`
  service (Vite dev server on 5174, source bind-mounted, node_modules in a named
  volume). Validated with `docker compose config` both standalone and layered on
  the existing stack. **No existing service/compose file was modified.**
- **`nginx/frontend-v2.new-location.conf`** (Task 76) — a documented, opt-in
  `location /new/` reverse-proxy snippet + enablement instructions. The live
  `nginx/nginx.conf` is **left untouched**; `/api/` continues to route to the
  backend for `/new/` pages unchanged.

The original `frontend/`, all `docker-compose*.yml`, and the live nginx config
were never modified, satisfying the hard constraint for the redesign.

---

## Recommended follow-ups (out of scope for this spec)

- Port the visual-page-editor **editing** surface if `/admin/page-editor*` needs
  to be live in v2 (currently placeholders).
- Add an e2e smoke pass (Playwright) against `/new/` once the gateway snippet is
  enabled in a real environment.
- Promote `frontend-v2` from the Vite dev-server container to a production static
  build + `frontend_v2_dist` volume (the nginx snippet documents the static-block
  swap) ahead of any cutover.
- Mount `OfflineBanner`/`OfflineProvider` in `OrgLayout` if/when offline sync is
  desired in v2 (the components are ported and ready).
