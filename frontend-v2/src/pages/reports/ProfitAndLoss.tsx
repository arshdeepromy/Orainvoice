import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'
import { useBranch } from '@/contexts/BranchContext'

interface LineItem {
  account_id: string
  account_code: string
  account_name: string
  amount: number
}

interface ProfitLossData {
  currency: string
  revenue_items: LineItem[]
  total_revenue: number
  cogs_items: LineItem[]
  total_cogs: number
  gross_profit: number
  gross_margin_pct: number
  expense_items: LineItem[]
  total_expenses: number
  net_profit: number
  net_margin_pct: number
  period_start: string
  period_end: string
  basis: string
}

function defaultDates() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const end = new Date(now.getFullYear(), now.getMonth(), 0)
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  }
}

const fmt = (n: number) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function ProfitAndLoss() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const { branches, selectedBranchId } = useBranch()
  const defaults = defaultDates()

  const [periodStart, setPeriodStart] = useState(defaults.start)
  const [periodEnd, setPeriodEnd] = useState(defaults.end)
  const [basis, setBasis] = useState<'accrual' | 'cash'>('accrual')
  const [branchId, setBranchId] = useState<string>(selectedBranchId ?? '')
  const [data, setData] = useState<ProfitLossData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchReport = useCallback(async (signal?: AbortSignal) => {
    if (!periodStart || !periodEnd) return
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {
        period_start: periodStart,
        period_end: periodEnd,
        basis,
      }
      if (branchId) params.branch_id = branchId
      const res = await apiClient.get<ProfitLossData>('/reports/profit-loss', { params, signal })
      setData(res.data ?? null)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'Failed to load report')
        setData(null)
      }
    } finally {
      setLoading(false)
    }
  }, [periodStart, periodEnd, basis, branchId])

  useEffect(() => {
    const controller = new AbortController()
    fetchReport(controller.signal)
    return () => controller.abort()
  }, [fetchReport])

  const renderSection = (title: string, items: LineItem[], total: number, totalLabel: string) => (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-text uppercase tracking-wider mb-2">{title}</h3>
      {(items ?? []).length === 0 ? (
        <p className="text-sm text-muted-2 italic">No items</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {(items ?? []).map(item => (
              <tr key={item.account_id} className="border-b border-border">
                <td className="py-1.5 mono text-muted w-20">{item.account_code}</td>
                <td className="py-1.5 text-text">{item.account_name}</td>
                <td className="py-1.5 text-right text-text mono">{fmt(item.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-border-strong font-semibold">
              <td colSpan={2} className="py-2 text-text">{totalLabel}</td>
              <td className="py-2 text-right text-text mono">{fmt(total)}</td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  )

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-text">Profit & Loss</h1>
        <p className="text-sm text-muted mt-1">Revenue, costs, and net profit for a period</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Start Date</label>
          <input
            type="date"
            value={periodStart}
            onChange={e => setPeriodStart(e.target.value)}
            className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted mb-1">End Date</label>
          <input
            type="date"
            value={periodEnd}
            onChange={e => setPeriodEnd(e.target.value)}
            className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Basis</label>
          <select
            value={basis}
            onChange={e => setBasis(e.target.value as 'accrual' | 'cash')}
            className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            <option value="accrual">Accrual</option>
            <option value="cash">Cash</option>
          </select>
        </div>
        {(branches ?? []).length > 1 && (
          <div>
            <label className="block text-xs font-medium text-muted mb-1">Branch</label>
            <select
              value={branchId}
              onChange={e => setBranchId(e.target.value)}
              className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            >
              <option value="">All Branches</option>
              {(branches ?? []).map(b => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading report" /></div>
      ) : error ? (
        <div className="rounded-card border border-danger-soft bg-danger-soft p-6 text-center text-danger">{error}</div>
      ) : !data ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted shadow-card">
          Select a date range to generate the report.
        </div>
      ) : (
        <div className="rounded-card border border-border bg-card p-6 shadow-card">
          <div className="flex items-center justify-between mb-6 text-xs text-muted">
            <span className="mono">{data?.period_start} to {data?.period_end}</span>
            <span className="uppercase">{data?.basis ?? 'accrual'} basis · {data?.currency ?? 'NZD'}</span>
          </div>

          {renderSection('Revenue', data?.revenue_items ?? [], data?.total_revenue ?? 0, 'Total Revenue')}
          {renderSection('Cost of Goods Sold', data?.cogs_items ?? [], data?.total_cogs ?? 0, 'Total COGS')}

          {/* Gross Profit */}
          <div className="border-t-2 border-border-strong py-3 mb-6 flex justify-between font-semibold text-text">
            <span>Gross Profit</span>
            <span className="mono">{fmt(data?.gross_profit ?? 0)} <span className="text-xs font-normal text-muted">({(data?.gross_margin_pct ?? 0).toFixed(1)}%)</span></span>
          </div>

          {renderSection('Expenses', data?.expense_items ?? [], data?.total_expenses ?? 0, 'Total Expenses')}

          {/* Net Profit */}
          <div className={`border-t-2 border-text py-3 flex justify-between font-bold text-lg ${(data?.net_profit ?? 0) >= 0 ? 'text-ok' : 'text-danger'}`}>
            <span>Net Profit</span>
            <span className="mono">{fmt(data?.net_profit ?? 0)} <span className="text-sm font-normal text-muted">({(data?.net_margin_pct ?? 0).toFixed(1)}%)</span></span>
          </div>
        </div>
      )}
    </div>
  )
}
