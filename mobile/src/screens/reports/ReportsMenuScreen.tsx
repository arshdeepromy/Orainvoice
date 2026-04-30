import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Page, Card, BlockTitle } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'

/* ------------------------------------------------------------------ */
/* Report definitions                                                 */
/* ------------------------------------------------------------------ */

interface ReportDef {
  type: string
  name: string
  description: string
  category: string
  moduleSlug: string | null
  tradeFamily: string | null
}

const REPORTS: ReportDef[] = [
  { type: 'revenue', name: 'Revenue Report', description: 'Revenue breakdown by period, customer, and service', category: 'Sales', moduleSlug: null, tradeFamily: null },
  { type: 'outstanding_invoices', name: 'Outstanding Invoices', description: 'All unpaid and overdue invoices', category: 'Sales', moduleSlug: null, tradeFamily: null },
  { type: 'aged_receivables', name: 'Aged Receivables', description: 'Receivables aged by 30/60/90+ days', category: 'Sales', moduleSlug: null, tradeFamily: null },
  { type: 'customer_statement', name: 'Customer Statement', description: 'Transaction history per customer', category: 'Sales', moduleSlug: null, tradeFamily: null },
  { type: 'job', name: 'Job Report', description: 'Job status, time, and profitability', category: 'Operations', moduleSlug: 'jobs', tradeFamily: null },
  { type: 'inventory', name: 'Inventory Report', description: 'Stock levels, valuation, and movement', category: 'Operations', moduleSlug: 'inventory', tradeFamily: null },
  { type: 'fleet', name: 'Fleet Report', description: 'Vehicle service history and costs', category: 'Industry', moduleSlug: 'vehicles', tradeFamily: 'automotive-transport' },
  { type: 'profit_and_loss', name: 'Profit & Loss', description: 'Income and expenses for a period', category: 'Finance', moduleSlug: 'accounting', tradeFamily: null },
  { type: 'balance_sheet', name: 'Balance Sheet', description: 'Assets, liabilities, and equity snapshot', category: 'Finance', moduleSlug: 'accounting', tradeFamily: null },
]

function ReportIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

const categoryColors: Record<string, string> = {
  Sales: 'bg-blue-50 dark:bg-blue-900/30',
  Operations: 'bg-green-50 dark:bg-green-900/30',
  Industry: 'bg-amber-50 dark:bg-amber-900/30',
  Finance: 'bg-purple-50 dark:bg-purple-900/30',
}

const categoryIconColors: Record<string, string> = {
  Sales: 'text-blue-600 dark:text-blue-400',
  Operations: 'text-green-600 dark:text-green-400',
  Industry: 'text-amber-600 dark:text-amber-400',
  Finance: 'text-purple-600 dark:text-purple-400',
}

/**
 * Reports screen — category cards, date picker, chart/table. No module gate.
 * Requirements: 46.1, 46.2, 46.3, 46.4
 */
export default function ReportsMenuScreen() {
  const navigate = useNavigate()

  const handleTap = useCallback((reportType: string) => {
    navigate(`/reports/${reportType}`)
  }, [navigate])

  // Group by category
  const grouped = REPORTS.reduce<Record<string, ReportDef[]>>((acc, r) => {
    if (!acc[r.category]) acc[r.category] = []
    acc[r.category].push(r)
    return acc
  }, {})

  return (
    <Page data-testid="reports-page">
      <div className="flex flex-col pb-24">
        {Object.entries(grouped).map(([category, reports]) => (
          <div key={category}>
            <BlockTitle>{category}</BlockTitle>
            <div className="flex flex-col gap-2 px-4">
              {reports.map((report) => {
                const card = (
                  <Card
                    key={report.type}
                    className="cursor-pointer"
                    onClick={() => handleTap(report.type)}
                    data-testid={`report-card-${report.type}`}
                  >
                    <div className="flex items-start gap-3 p-1">
                      <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg ${categoryColors[category] ?? 'bg-gray-50'}`}>
                        <ReportIcon className={`h-5 w-5 ${categoryIconColors[category] ?? 'text-gray-600'}`} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{report.name}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">{report.description}</p>
                      </div>
                    </div>
                  </Card>
                )

                if (report.moduleSlug || report.tradeFamily) {
                  return (
                    <ModuleGate key={report.type} moduleSlug={report.moduleSlug ?? '*'} tradeFamily={report.tradeFamily ?? undefined}>
                      {card}
                    </ModuleGate>
                  )
                }
                return card
              })}
            </div>
          </div>
        ))}
      </div>
    </Page>
  )
}
