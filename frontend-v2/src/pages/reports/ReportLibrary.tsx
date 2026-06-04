import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useTenant } from '@/contexts/TenantContext'

/* ============================================================
   ReportLibrary — grouped, module-gated report cards.
   ------------------------------------------------------------
   Design source: §"E2 — ReportLibrary", §"E3 — Surface financial reports"

   Six groups:
     1. Financial — Revenue, Invoice Status, Outstanding,
        Top Services, P&L, Balance Sheet, Aged Receivables,
        Customer Statement
     2. Sales & operations — Job Report, Inventory, POS,
        Hospitality, Projects, Fleet
     3. Tax & compliance — GST Return, Income Tax (Tax Return),
        Customer Statement (read-only re-link)
     4. Payroll & people — Wage Variance
     5. Usage & system — Carjam Usage, SMS Usage, Storage
     6. Automation — Scheduled Reports, Report Builder

   Each card gates with the existing `ModuleGate`/`useModules`
   hook (and an optional trade-family check via `useTenant`)
   so a card only shows when its module is enabled — matching
   the gating already enforced on the routes in `App.tsx`.

   E3: P&L / Balance Sheet / Aged Receivables / Income Tax are
   surfaced in the Financial + Tax groups (each gated by the
   `accounting` module) so the financial reports show up in the
   library rather than being routed-but-orphaned.

   Tokens: card uses `rounded-card border border-border bg-card
   shadow-card`, title `text-text`, description `text-muted`,
   group heading `text-lg font-semibold text-text`. Hover lifts
   the border colour and adds a subtle shadow, matching the
   design tokens used by the rest of the v2 reports surface.

   Requirements: 16.1, 16.2, 16.3, 16.4, 17.1, 17.2, 17.3, 21.1
   ============================================================ */

/** A single card in the report library. */
interface ReportCard {
  /** Card title (the report name). */
  title: string
  /** Short one-line description shown beneath the title. */
  desc: string
  /** Route to navigate to when the card is activated. */
  to: string
  /**
   * Module slug that gates the card. When omitted, the card is
   * always visible. The gate uses `useModules().isEnabled(slug)`
   * so it stays in sync with the org's enabled modules.
   */
  module?: string
  /**
   * Optional trade-family slug. When set, the card is hidden
   * when the org's `tradeFamily` does not match (or is null).
   * Currently unused but kept in the contract so trade-only
   * reports (e.g. automotive-only Carjam) can be gated without
   * widening the public type later.
   */
  tradeFamily?: string
}

interface ReportGroup {
  /** Group heading shown above the card grid. */
  label: string
  /** Cards within the group; rendered in declaration order. */
  cards: ReportCard[]
}

/**
 * The grouped report library — single source of truth for both
 * the rendered groups and the test that asserts every card is
 * present. Routes here MUST exist in `App.tsx` (Task 20.1 wires
 * the in-hub tab routes alongside the 12 orphan routes already
 * mounted by Tasks 46–48).
 */
const GROUPS: ReportGroup[] = [
  {
    label: 'Financial',
    cards: [
      { title: 'Profit & Loss', desc: 'Income vs expenses', to: '/reports/profit-loss', module: 'accounting' },
      { title: 'Balance sheet', desc: 'Assets & liabilities', to: '/reports/balance-sheet', module: 'accounting' },
      { title: 'Revenue summary', desc: 'By month & category', to: '/reports/revenue' },
      { title: 'Aged receivables', desc: 'Who owes you what', to: '/reports/aged-receivables', module: 'accounting' },
      { title: 'Outstanding invoices', desc: 'Unpaid & overdue', to: '/reports/outstanding' },
      { title: 'Customer statement', desc: 'Per-account activity', to: '/reports/customer-statement' },
    ],
  },
  {
    label: 'Sales & operations',
    cards: [
      { title: 'Invoice status', desc: 'Pipeline by status', to: '/reports/invoice-status' },
      { title: 'Top services', desc: 'Best-sellers by revenue', to: '/reports/top-services' },
      { title: 'Job report', desc: 'Completed jobs & recovery', to: '/reports/jobs', module: 'jobs' },
      { title: 'Fleet report', desc: 'Fleet account servicing', to: '/reports/fleet', module: 'vehicles' },
      { title: 'POS report', desc: 'Register sales & tenders', to: '/reports/pos', module: 'pos' },
      { title: 'Hospitality', desc: 'Covers & daypart sales', to: '/reports/hospitality', module: 'kitchen_display' },
      { title: 'Project report', desc: 'Budget vs actual', to: '/reports/projects', module: 'projects' },
      { title: 'Inventory valuation', desc: 'Stock on hand value', to: '/reports/inventory', module: 'inventory' },
    ],
  },
  {
    label: 'Tax & compliance',
    cards: [
      { title: 'GST return', desc: 'Period summary for IRD', to: '/reports/gst-return' },
      { title: 'Income tax summary', desc: 'Provisional tax', to: '/reports/tax-return', module: 'accounting' },
    ],
  },
  {
    label: 'Payroll & people',
    cards: [
      { title: 'Wage variance', desc: 'Rostered vs actual', to: '/reports/wage-variance', module: 'payroll' },
    ],
  },
  {
    label: 'Usage & system',
    cards: [
      { title: 'CARJAM usage', desc: 'Vehicle data lookups', to: '/reports/carjam-usage', module: 'vehicles' },
      { title: 'SMS usage', desc: 'Messages & spend', to: '/reports/sms-usage' },
      { title: 'Storage usage', desc: 'Files by type', to: '/reports/storage' },
    ],
  },
  {
    label: 'Automation',
    cards: [
      { title: 'Scheduled reports', desc: 'Automated delivery', to: '/reports/scheduled' },
      { title: 'Report builder', desc: 'Custom report from any data', to: '/reports/builder' },
    ],
  },
]

/** Single library card — a navigation tile with title + description. */
function ReportCardLink({ card }: { card: ReportCard }) {
  return (
    <Link
      to={card.to}
      className="group flex h-full flex-col rounded-card border border-border bg-card p-5 shadow-card transition-all hover:border-accent hover:shadow-pop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <h3 className="text-[15px] font-semibold text-text group-hover:text-accent">
        {card.title}
      </h3>
      <p className="mt-1 text-sm text-muted">{card.desc}</p>
    </Link>
  )
}

/**
 * Grouped, module-gated report library — renders six labelled
 * groups of cards. A card whose `module` is disabled (or whose
 * `tradeFamily` does not match the org) is hidden; an entire
 * group is hidden when all its cards are filtered out.
 *
 * Requirements: 16.1, 16.2, 16.3, 16.4, 17.1, 17.2, 17.3, 21.1
 * Design: §"E2 — ReportLibrary", §"E3 — Surface financial reports"
 */
export default function ReportLibrary() {
  const { isEnabled } = useModules()
  const { tradeFamily } = useTenant()

  // Filter cards down to those visible to this org/user. Group
  // headings hide when every card in the group is filtered out
  // so empty sections never render.
  const visibleGroups = useMemo(() => {
    return GROUPS.map((group) => ({
      ...group,
      cards: group.cards.filter((card) => {
        if (card.module && !isEnabled(card.module)) return false
        if (card.tradeFamily && card.tradeFamily !== tradeFamily) return false
        return true
      }),
    })).filter((group) => group.cards.length > 0)
  }, [isEnabled, tradeFamily])

  if (visibleGroups.length === 0) {
    return (
      <section className="rounded-card border border-border bg-card p-8 text-center text-sm text-muted shadow-card">
        No reports are available — enable a module to see reports.
      </section>
    )
  }

  return (
    <div className="space-y-8" data-testid="report-library">
      {visibleGroups.map((group) => (
        <section key={group.label} aria-labelledby={`report-group-${slugify(group.label)}`}>
          <h2
            id={`report-group-${slugify(group.label)}`}
            className="mb-3 text-lg font-semibold text-text"
          >
            {group.label}
          </h2>
          <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {group.cards.map((card) => (
              <ReportCardLink key={card.to} card={card} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

/** Lightweight slugifier — used only for stable aria-labelledby hooks. */
function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}
