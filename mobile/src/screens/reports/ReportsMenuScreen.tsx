import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ReportType, ReportDefinition } from '@shared/types/report'
import { ModuleGate } from '@/components/common/ModuleGate'
import { MobileCard } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Report definitions                                                 */
/* ------------------------------------------------------------------ */

const REPORTS: ReportDefinition[] = [
  {
    type: 'revenue',
    name: 'Revenue Report',
    description: 'Revenue breakdown by period, customer, and service',
    moduleSlug: null,
    tradeFamily: null,
  },
  {
    type: 'outstanding_invoices',
    name: 'Outstanding Invoices',
    description: 'All unpaid and overdue invoices',
    moduleSlug: null,
    tradeFamily: null,
  },
  {
    type: 'aged_receivables',
    name: 'Aged Receivables',
    description: 'Receivables aged by 30/60/90+ days',
    moduleSlug: null,
    tradeFamily: null,
  },
  {
    type: 'customer_statement',
    name: 'Customer Statement',
    description: 'Transaction history per customer',
    moduleSlug: null,
    tradeFamily: null,
  },
  {
    type: 'job',
    name: 'Job Report',
    description: 'Job status, time, and profitability',
    moduleSlug: 'jobs',
    tradeFamily: null,
  },
  {
    type: 'inventory',
    name: 'Inventory Report',
    description: 'Stock levels, valuation, and movement',
    moduleSlug: 'inventory',
    tradeFamily: null,
  },
  {
    type: 'fleet',
    name: 'Fleet Report',
    description: 'Vehicle service history and costs',
    moduleSlug: 'vehicles',
    tradeFamily: 'automotive-transport',
  },
  {
    type: 'profit_and_loss',
    name: 'Profit & Loss',
    description: 'Income and expenses for a period',
    moduleSlug: 'accounting',
    tradeFamily: null,
  },
  {
    type: 'balance_sheet',
    name: 'Balance Sheet',
    description: 'Assets, liabilities, and equity snapshot',
    moduleSlug: 'accounting',
    tradeFamily: null,
  },
]

/* ------------------------------------------------------------------ */
/* Icons                                                              */
/* ------------------------------------------------------------------ */

function ReportIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}

/**
 * Reports menu screen — list of report types filtered by ModuleGate.
 * Fleet report only visible for automotive trade family.
 *
 * Requirements: 28.1, 28.2
 */
export default function ReportsMenuScreen() {
  const navigate = useNavigate()

  const handleTap = useCallback(
    (reportType: ReportType) => {
      navigate(`/reports/${reportType}`)
    },
    [navigate],
  )

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Reports
      </h1>

      <div className="flex flex-col gap-2">
        {REPORTS.map((report) => {
          const card = (
            <MobileCard
              key={report.type}
              onTap={() => handleTap(report.type)}
            >
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-blue-50 dark:bg-blue-900/30">
                  <ReportIcon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {report.name}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {report.description}
                  </p>
                </div>
                <svg
                  className="h-5 w-5 flex-shrink-0 text-gray-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden="true"
                >
                  <path d="m9 18 6-6-6-6" />
                </svg>
              </div>
            </MobileCard>
          )

          // Wrap in ModuleGate if module or trade family restriction
          if (report.moduleSlug || report.tradeFamily) {
            return (
              <ModuleGate
                key={report.type}
                moduleSlug={report.moduleSlug ?? '*'}
                tradeFamily={report.tradeFamily ?? undefined}
              >
                {card}
              </ModuleGate>
            )
          }

          return card
        })}
      </div>
    </div>
  )
}
