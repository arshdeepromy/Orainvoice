import { NavLink } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useFeatureFlags } from '@/contexts/FeatureFlagContext'
import { useAuth } from '@/contexts/AuthContext'
import { useTenant } from '@/contexts/TenantContext'
import OrgSwitcher from '@/components/shell/OrgSwitcher'
import { useComplianceBadgeCount } from '@/hooks/useComplianceBadgeCount'

/**
 * Sidebar — 264px ink navigation rail (left region of OrgLayout).
 *
 * Real implementation (Task 7). Matches the prototype's `.sidebar` flex column
 * (head / scrollable nav / foot) from OraInvoice_Handoff/app/ds.css and the
 * NAV / FOOT structure from OraInvoice_Handoff/app/shell.js, while wiring the
 * authoritative routes + conditional-render gates copied from the existing app
 * (frontend/src/layouts/OrgLayout.tsx → navItems / visibleNavItems).
 *
 * Structure source: design.md "Sidebar Navigation Groups" table
 *   Overview · Sales · Work · People & Stock · Money + footer Settings / Admin.
 * Route paths + gating (module / feature-flag / role / trade-family) mirror the
 * real OrgLayout so links resolve against the real router and the same items
 * show/hide. Per FR-1 (zero functionality regression) the gate logic is copied
 * verbatim from OrgLayout's `visibleNavItems` filter.
 *
 * Gating contexts (useModules / useFeatureFlags / useAuth / useTenant) are
 * imported from the real `@/contexts/...` paths. Those context files are
 * currently lightweight "show-everything" SHIMS (see each contexts/*.tsx) so
 * this compiles today; Task 15 drops in the verbatim real contexts + mounts the
 * providers in App.tsx, at which point the Sidebar starts gating against real
 * org module/flag/role/trade state with no changes needed here.
 *
 * Count pills + alert dots: the Compliance item shows a real "needs attention"
 * count (expired + expiring-soon docs) from GET /api/v2/compliance-docs/badge-
 * count, ported from the original sidebar's NotificationBadge. Other items have
 * no real count source in this backend (the prototype's Invoices 18 / Quotes 7 /
 * Job Cards 14 / Bookings dot were demo-only placeholders) so they render no
 * badge rather than a fake number. TODO(Task 18+): add real counts for other
 * items if/when count endpoints land (e.g. shift-swaps awaiting-manager).
 *
 * Drawer hooks (Task 9) preserved exactly as the stub: `data-open={open}` on the
 * root <aside>, an in-drawer close button wired to `onClose`, and every nav item
 * also calls `onClose` so activating a link dismisses the ≤860px drawer.
 */
export interface SidebarProps {
  /**
   * Whether the mobile off-canvas drawer is open (≤860px breakpoint). Ignored
   * at wider widths where the rail is always docked. Surfaced on the root as
   * `data-open` so Task 9 can wire the slide-in transform without restructuring.
   */
  open: boolean
  /**
   * Dismiss the mobile drawer. Wired to the in-drawer close button, and called
   * on every nav-item activation. Task 9 also wires it to the scrim overlay.
   */
  onClose: () => void
}

/* ── Nav item model — mirrors OrgLayout's NavItem + adds the prototype icon ── */
interface NavItem {
  id: string
  to: string
  label: string
  /** SVG path `d` from shell.js ICON map (24×24 viewBox, stroke-based). */
  icon: string
  /** Exact-match active state (avoids a parent staying active on child routes). */
  end?: boolean
  /** Shown only when the module is enabled. */
  module?: string
  /** Shown only when the feature flag is enabled (when no module gate applies). */
  flagKey?: string
  /** Only org_admin / global_admin can see this item. */
  adminOnly?: boolean
  /** Only global_admin can see this item (Admin Console). */
  globalAdminOnly?: boolean
  /** Only shown when the org trade family matches (null treated as automotive). */
  tradeFamily?: string
}

interface NavGroup {
  label: string
  items: NavItem[]
}

/* ── SVG path data, copied verbatim from OraInvoice_Handoff/app/shell.js ICON ── */
const ICON = {
  dash: 'M3 12l2-2 7-7 7 7 2 2M5 10v10a1 1 0 001 1h3m10-11v11a1 1 0 01-1 1h-3m-6 0h6m-6 0v-6h6v6',
  reports: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
  inv: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z',
  quote: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
  recur: 'M4 4v5h.6M20 20v-5h-.6m0 0a8 8 0 01-15.3-2m15.4 2H15M4.6 9A8 8 0 0119.9 11M4.6 9H9',
  pos: 'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.3 2.3c-.6.6-.2 1.7.7 1.7H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z',
  job: 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.4-9.4a2 2 0 112.8 2.8L11.8 15H9v-2.8l8.6-8.6z',
  booking: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
  schedule: 'M8 7V3m8 4V3M3 11h18M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
  project: 'M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z',
  time: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
  cust: 'M17 20h5v-2a3 3 0 00-5.4-1.9M17 20H7m10 0v-2c0-.7-.1-1.3-.4-1.9M7 20H2v-2a3 3 0 015.4-1.9M7 20v-2c0-.7.1-1.3.4-1.9m0 0a5 5 0 019.3 0M15 7a3 3 0 11-6 0 3 3 0 016 0z',
  car: 'M5 11l1.5-4.5A2 2 0 018.4 5h7.2a2 2 0 011.9 1.5L19 11m-14 0h14m-14 0a2 2 0 00-2 2v3a1 1 0 001 1h1m14-6a2 2 0 012 2v3a1 1 0 01-1 1h-1M7 17v1a1 1 0 01-1 1H5a1 1 0 01-1-1v-1m3 0h10m0 0v1a1 1 0 001 1h1a1 1 0 001-1v-1M7 14h.01M17 14h.01',
  staff: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  inventory: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
  items: 'M12 6.3v13m0-13C10.8 5.5 9.2 5 7.5 5S4.2 5.5 3 6.3v13C4.2 18.5 5.8 18 7.5 18s3.3.5 4.5 1.3m0-13C13.2 5.5 14.8 5 16.5 5s3.3.5 4.5 1.3v13C19.8 18.5 18.2 18 16.5 18s-3.3.5-4.5 1.3',
  po: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
  accounting: 'M4 4h16v16H4zM12 6v12m0-9H9m6 6H9',
  banking: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
  tax: 'M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z',
  expense: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2z',
  settings: 'M10.3 4.3c.4-1.8 2.9-1.8 3.3 0a1.7 1.7 0 002.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 001 2.5c1.8.5 1.8 3 0 3.4a1.7 1.7 0 00-1 2.6c.9 1.5-.8 3.3-2.4 2.4a1.7 1.7 0 00-2.6 1c-.4 1.8-2.9 1.8-3.3 0a1.7 1.7 0 00-2.6-1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 00-1-2.6c-1.8-.4-1.8-3 0-3.4a1.7 1.7 0 001-2.5C4.7 6.2 6.5 4.5 8 5.4a1.7 1.7 0 002.5-1zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
  server: 'M5 3h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2zm0 10h14a2 2 0 012 2v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4a2 2 0 012-2zm3-6h.01M8 17h.01',
  // ── Added (Sidebar parity fix) — icons for the module-gated nav items that
  //    were missing from the v2 curated list but exist in the original
  //    frontend/src/layouts/OrgLayout.tsx navItems. Stroke-based 24×24 paths.
  payroll: 'M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6',
  ppsr: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4',
  claims: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
  compliance: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
  loyalty: 'M11.48 3.5l2.6 5.27 5.82.85-4.21 4.1 1 5.79-5.21-2.74-5.2 2.74 1-5.79-4.22-4.1 5.82-.85L11.48 3.5z',
  ecommerce: 'M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z',
  sms: 'M8 10h.01M12 10h.01M16 10h.01M21 12a9 9 0 01-13 8l-5 1 1-4a9 9 0 1117-5z',
  construction: 'M9 17v-2m3 2v-4m3 4v-6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5l5 5v11a2 2 0 01-2 2z',
  floorplan: 'M4 4h7v7H4zM13 4h7v4h-7zM13 11h7v9h-7zM4 13h7v7H4z',
  kitchen: 'M3 3v6a2 2 0 002 2 2 2 0 002-2V3M5 11v10M17 3c-1.7 0-3 2-3 5s1 4 3 4v9',
  franchise: 'M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01',
  assets: 'M7 7h.01M7 3h5a2 2 0 011.4.6l7 7a2 2 0 010 2.8l-5.6 5.6a2 2 0 01-2.8 0l-7-7A2 2 0 013 7.6V5a2 2 0 012-2z',
  bell: 'M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 00-4-5.7V5a2 2 0 10-4 0v.3A6 6 0 006 11v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9',
  data: 'M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
} as const

/**
 * Grouped navigation — structure from design.md's sidebar table, routes + gates
 * from the real frontend OrgLayout `navItems`.
 *
 * Gating provenance (frontend/src/layouts/OrgLayout.tsx):
 *   quotes        → module 'quotes', flag 'quotes'
 *   recurring     → module 'recurring_invoices', flag 'recurring'
 *   pos           → module 'pos', flag 'pos'
 *   job-cards     → module 'jobs', flag 'jobs'
 *   bookings      → module 'bookings', flag 'bookings'
 *   schedule      → module 'scheduling', flag 'scheduling'
 *   staff-schedule→ module 'branch_management', adminOnly
 *   projects      → module 'projects', flag 'projects'
 *   time-tracking → module 'time_tracking', flag 'time_tracking'
 *   vehicles      → module 'vehicles', flag 'vehicles', tradeFamily 'automotive-transport'
 *   staff         → module 'staff', flag 'staff'
 *   inventory     → module 'inventory', flag 'inventory'
 *   items         → module 'inventory'
 *   purchase-orders → module 'purchase_orders', flag 'purchase_orders'
 *   accounting / banking / tax → module 'accounting'
 *   expenses      → module 'expenses', flag 'expenses'
 *   settings      → adminOnly
 */
const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { id: 'dashboard', to: '/dashboard', label: 'Dashboard', icon: ICON.dash, end: true },
      { id: 'reports', to: '/reports', label: 'Reports', icon: ICON.reports },
    ],
  },
  {
    label: 'Sales',
    items: [
      { id: 'invoices', to: '/invoices', label: 'Invoices', icon: ICON.inv },
      { id: 'quotes', to: '/quotes', label: 'Quotes', icon: ICON.quote, module: 'quotes', flagKey: 'quotes' },
      { id: 'recurring', to: '/recurring', label: 'Recurring', icon: ICON.recur, module: 'recurring_invoices', flagKey: 'recurring' },
      { id: 'pos', to: '/pos', label: 'POS', icon: ICON.pos, module: 'pos', flagKey: 'pos' },
    ],
  },
  {
    label: 'Work',
    items: [
      { id: 'job-cards', to: '/job-cards', label: 'Job Cards', icon: ICON.job, module: 'jobs', flagKey: 'jobs' },
      { id: 'jobs', to: '/jobs', label: 'Jobs', icon: ICON.job, module: 'jobs', flagKey: 'jobs' },
      { id: 'bookings', to: '/bookings', label: 'Bookings', icon: ICON.booking, module: 'bookings', flagKey: 'bookings' },
      { id: 'schedule', to: '/schedule', label: 'Schedule', icon: ICON.schedule, module: 'scheduling', flagKey: 'scheduling' },
      { id: 'staff-schedule', to: '/staff-schedule', label: 'Staff Schedule', icon: ICON.schedule, module: 'branch_management', adminOnly: true },
      { id: 'projects', to: '/projects', label: 'Projects', icon: ICON.project, module: 'projects', flagKey: 'projects' },
      { id: 'time-tracking', to: '/time-tracking', label: 'Time Tracking', icon: ICON.time, module: 'time_tracking', flagKey: 'time_tracking' },
      { id: 'timesheets', to: '/timesheets', label: 'Timesheets', icon: ICON.time, module: 'timesheets' },
      // Construction (module-gated, mirrors original navItems).
      { id: 'progress-claims', to: '/progress-claims', label: 'Progress Claims', icon: ICON.construction, module: 'progress_claims', flagKey: 'progress_claims' },
      { id: 'variations', to: '/variations', label: 'Variations', icon: ICON.construction, module: 'variations', flagKey: 'variations' },
      { id: 'retentions', to: '/retentions', label: 'Retentions', icon: ICON.construction, module: 'retentions', flagKey: 'retentions' },
      // Hospitality.
      { id: 'floor-plan', to: '/floor-plan', label: 'Floor Plan', icon: ICON.floorplan, module: 'tables', flagKey: 'tables' },
      { id: 'kitchen', to: '/kitchen', label: 'Kitchen Display', icon: ICON.kitchen, module: 'kitchen_display', flagKey: 'kitchen_display' },
    ],
  },
  {
    label: 'People',
    items: [
      { id: 'customers', to: '/customers', label: 'Customers', icon: ICON.cust },
      { id: 'staff', to: '/staff', label: 'Staff', icon: ICON.staff, module: 'staff', flagKey: 'staff' },
      { id: 'leave-approvals', to: '/leave/approvals', label: 'Leave Approvals', icon: ICON.staff, module: 'staff_management', adminOnly: true },
      { id: 'leave-balances', to: '/leave/balances', label: 'Leave Balances', icon: ICON.staff, module: 'staff_management' },
      { id: 'shift-swaps', to: '/shift-swaps', label: 'Shift swaps', icon: ICON.schedule, module: 'staff_management' },
      { id: 'shift-cover', to: '/shift-cover', label: 'Open shifts', icon: ICON.schedule, module: 'staff_management' },
      { id: 'payroll', to: '/payroll/run', label: 'Payroll', icon: ICON.payroll, module: 'payroll' },
    ],
  },
  {
    label: 'Vehicles & Stock',
    items: [
      { id: 'vehicles', to: '/vehicles', label: 'Vehicles', icon: ICON.car, module: 'vehicles', flagKey: 'vehicles', tradeFamily: 'automotive-transport' },
      { id: 'ppsr', to: '/ppsr/search', label: 'PPSR Check', icon: ICON.ppsr, module: 'ppsr', flagKey: 'ppsr' },
      { id: 'inventory', to: '/inventory', label: 'Inventory', icon: ICON.inventory, module: 'inventory', flagKey: 'inventory' },
      { id: 'items', to: '/items', label: 'Items', icon: ICON.items, module: 'inventory' },
      { id: 'catalogue', to: '/catalogue', label: 'Catalogue', icon: ICON.items, module: 'inventory' },
      { id: 'purchase-orders', to: '/purchase-orders', label: 'Purchase Orders', icon: ICON.po, module: 'purchase_orders', flagKey: 'purchase_orders' },
      { id: 'assets', to: '/assets', label: 'Assets', icon: ICON.assets, module: 'assets', flagKey: 'assets' },
      { id: 'branch-transfers', to: '/branch-transfers', label: 'Branch Transfers', icon: ICON.inventory, module: 'branch_management', adminOnly: true },
    ],
  },
  {
    label: 'Money',
    items: [
      { id: 'accounting', to: '/accounting', label: 'Accounting', icon: ICON.accounting, module: 'accounting' },
      { id: 'banking', to: '/banking/accounts', label: 'Banking', icon: ICON.banking, module: 'accounting' },
      { id: 'tax', to: '/tax/gst-periods', label: 'Tax / GST', icon: ICON.tax, module: 'accounting' },
      { id: 'expenses', to: '/expenses', label: 'Expenses', icon: ICON.expense, module: 'expenses', flagKey: 'expenses' },
    ],
  },
  {
    label: 'Engage',
    items: [
      { id: 'claims', to: '/claims', label: 'Claims', icon: ICON.claims, module: 'customer_claims' },
      { id: 'compliance', to: '/compliance', label: 'Compliance', icon: ICON.compliance, module: 'compliance_docs', flagKey: 'compliance_docs' },
      { id: 'loyalty', to: '/loyalty', label: 'Loyalty', icon: ICON.loyalty, module: 'loyalty', flagKey: 'loyalty' },
      { id: 'franchise', to: '/franchise', label: 'Franchise', icon: ICON.franchise, module: 'franchise', flagKey: 'franchise' },
      { id: 'ecommerce', to: '/ecommerce', label: 'Ecommerce', icon: ICON.ecommerce, module: 'ecommerce', flagKey: 'ecommerce' },
      { id: 'sms', to: '/sms', label: 'SMS', icon: ICON.sms, module: 'sms', flagKey: 'sms' },
      { id: 'notifications', to: '/notifications', label: 'Notifications', icon: ICON.bell },
      { id: 'data', to: '/data', label: 'Data', icon: ICON.data },
    ],
  },
]

/**
 * Footer nav group — Settings + Admin Console. Matches the prototype, which
 * renders these as the final `.nav-group` at the bottom of `.sb-scroll`
 * (margin-top:6px) just above the bordered `.sb-foot` org switcher.
 *
 *   settings → adminOnly (org_admin / global_admin), route '/settings'
 *   admin    → global_admin only, route '/admin' (real AdminLayout landing)
 */
const FOOTER_ITEMS: NavItem[] = [
  { id: 'settings', to: '/settings', label: 'Settings', icon: ICON.settings, adminOnly: true },
  { id: 'admin', to: '/admin', label: 'Admin Console', icon: ICON.server, globalAdminOnly: true },
]

/** Per-item badge data. Sourced from real backend queries (see Sidebar). */
interface NavBadgeData {
  /** Numeric count pill (hidden when 0/undefined). */
  count?: number
  /** Plain alert dot (no number). */
  dot?: boolean
  /** Render the count pill in the danger tone (an "attention" alert). */
  danger?: boolean
}

/** Stroke-based 18×18 nav icon, matching `.nav-item svg` in ds.css. */
function NavIcon({ d, active }: { d: string; active: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`h-[18px] w-[18px] flex-shrink-0 ${active ? 'text-accent-fg opacity-100' : 'opacity-[0.82]'}`}
    >
      <path d={d} />
    </svg>
  )
}

/** Right-aligned count pill / alert dot (matches `.nav-item .count` / `.dot`). */
function NavBadge({ count, dot, danger }: NavBadgeData) {
  if (dot) {
    return <span className="ml-auto h-[7px] w-[7px] flex-shrink-0 rounded-full bg-danger" aria-hidden="true" />
  }
  if (count != null && count > 0) {
    return danger ? (
      <span className="ml-auto inline-flex h-5 min-w-[20px] flex-shrink-0 items-center justify-center rounded-full bg-danger px-1.5 text-[11px] font-semibold leading-none text-white">
        {count}
      </span>
    ) : (
      <span className="mono ml-auto flex-shrink-0 rounded-[20px] bg-sb-hover px-[7px] py-px text-[11px] font-medium text-sb-text-strong">
        {count}
      </span>
    )
  }
  return null
}

/** A single nav row — NavLink with active state, icon, label, optional badge. */
function NavRow({ item, onClose, badge }: { item: NavItem; onClose: () => void; badge?: NavBadgeData }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onClose}
      aria-label={item.label}
      className={({ isActive }) =>
        `group relative flex h-10 items-center gap-[11px] rounded-ctl px-3 text-[13.5px] font-medium transition-colors duration-150 ${
          isActive
            ? 'bg-sb-active-bg text-sb-text-strong'
            : 'text-sb-text hover:bg-sb-hover hover:text-sb-text-strong'
        }`
      }
    >
      {({ isActive }) => (
        <>
          {/* Active accent indicator bar (matches .nav-item.active::before). */}
          {isActive && (
            <span
              className="absolute -left-3 bottom-2 top-2 w-[3px] rounded-r-[3px] bg-accent-fg"
              aria-hidden="true"
            />
          )}
          <NavIcon d={item.icon} active={isActive} />
          <span className="shell-nav-label truncate">{item.label}</span>
          {badge && <NavBadge {...badge} />}
        </>
      )}
    </NavLink>
  )
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const { isEnabled } = useModules()
  const { flags } = useFeatureFlags()
  const { user } = useAuth()
  const { tradeFamily } = useTenant()
  const userRole = user?.role

  // Real "needs attention" count for the Compliance nav item (expired +
  // expiring-soon docs). Only fetched when the compliance_docs module is on.
  const complianceCount = useComplianceBadgeCount(isEnabled('compliance_docs'))

  /** Real per-item badge data, keyed by nav-item id. Items absent here render
   *  no badge (the old DEMO_BADGES placeholders had no backend count source). */
  const badgeFor = (id: string): NavBadgeData | undefined => {
    if (id === 'compliance' && complianceCount > 0) {
      return { count: complianceCount, danger: true }
    }
    return undefined
  }

  /**
   * Visibility gate — copied verbatim from OrgLayout's `visibleNavItems` filter
   * so frontend-v2 hides/shows exactly the items the production app does, with
   * the global-admin-only Admin Console gate added for the footer.
   */
  const isVisible = (item: NavItem): boolean => {
    // Global-admin-only items (Admin Console).
    if (item.globalAdminOnly && userRole !== 'global_admin') return false
    // Admin-only items hidden from non-admin roles.
    if (item.adminOnly && userRole !== 'org_admin' && userRole !== 'global_admin') return false
    // Trade family gating — null tradeFamily treated as automotive for back-compat.
    if (item.tradeFamily && (tradeFamily ?? 'automotive-transport') !== item.tradeFamily) return false
    // If the item has a module gate, module enablement is sufficient.
    if (item.module) return isEnabled(item.module)
    // Items without a module gate fall back to a feature-flag check.
    if (item.flagKey && !flags[item.flagKey]) return false
    return true
  }

  const visibleFooter = FOOTER_ITEMS.filter(isVisible)

  return (
    <aside
      className="shell-sidebar flex h-full w-rail flex-shrink-0 flex-col border-r border-sb-border bg-sb-bg text-sb-text"
      data-open={open}
      aria-label="Primary navigation"
    >
      {/* Head — logo lockup (matches .sb-head: 64px tall, bottom border). */}
      <div className="shell-brand flex h-16 flex-shrink-0 items-center gap-[11px] border-b border-sb-border px-[18px]">
        <div className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-[9px] bg-accent text-white shadow-card">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
            <path d={ICON.inv} />
          </svg>
        </div>
        <div className="shell-brand-wordmark text-base font-semibold tracking-[-0.01em] text-white">
          <b className="font-bold">Ora</b>
          <span className="font-medium text-sb-muted">Invoice</span>
        </div>
        {/* In-drawer close button — shown only at ≤860px (when the sidebar is
            an off-canvas drawer); a docked rail >860px has no close affordance.
            Wired to `onClose` (also gives keyboard users a way to dismiss the
            drawer alongside Escape). */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close navigation"
          className="ml-auto hidden h-10 w-10 place-items-center rounded-ctl text-sb-muted hover:bg-sb-hover hover:text-sb-text-strong max-mobile:grid"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-[19px] w-[19px]">
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Scroll — grouped navigation (matches .sb-scroll: flex-1, scrolls). */}
      <nav className="flex-1 overflow-y-auto px-3 pb-[10px] pt-[14px]">
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter(isVisible)
          if (items.length === 0) return null
          return (
            <div key={group.label} className="mb-[14px]">
              <div className="shell-nav-group-heading mono px-3 pb-[7px] text-[10.5px] font-medium uppercase tracking-[0.13em] text-sb-muted">
                {group.label}
              </div>
              {items.map((item) => (
                <NavRow key={item.id} item={item} onClose={onClose} badge={badgeFor(item.id)} />
              ))}
            </div>
          )
        })}

        {/* Footer nav group — Settings + Admin Console (prototype: bottom of
            scroll, margin-top:6px). Hidden entirely if the role gates leave it
            empty (e.g. a salesperson sees neither). */}
        {visibleFooter.length > 0 && (
          <div className="mt-[6px] mb-[14px]">
            {visibleFooter.map((item) => (
              <NavRow key={item.id} item={item} onClose={onClose} />
            ))}
          </div>
        )}
      </nav>

      {/* Foot — org switcher (matches .sb-foot: top border). */}
      <div className="shell-foot flex-shrink-0 border-t border-sb-border p-3">
        <OrgSwitcher />
      </div>
    </aside>
  )
}
