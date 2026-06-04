import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface AgedCustomer {
  customer_id: string
  customer_name: string
  current: number
  '31_60': number
  '61_90': number
  '90_plus': number
  total: number
  invoices: AgedInvoice[]
}

interface AgedInvoice {
  invoice_id: string
  invoice_number: string | null
  due_date: string | null
  balance_due: number
  days_overdue: number
  bucket: string
}

interface AgedOverall {
  current: number
  '31_60': number
  '61_90': number
  '90_plus': number
  total: number
}

interface AgedReceivablesData {
  report_date: string
  customers: AgedCustomer[]
  overall: AgedOverall
}

const fmt = (n: number) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function AgedReceivables() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [reportDate, setReportDate] = useState(new Date().toISOString().slice(0, 10))
  const [data, setData] = useState<AgedReceivablesData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedCustomer, setExpandedCustomer] = useState<string | null>(null)

  const fetchReport = useCallback(async (signal?: AbortSignal) => {
    if (!reportDate) return
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { report_date: reportDate }
      const res = await apiClient.get<AgedReceivablesData>('/reports/aged-receivables', { params, signal })
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
  }, [reportDate])

  useEffect(() => {
    const controller = new AbortController()
    fetchReport(controller.signal)
    return () => controller.abort()
  }, [fetchReport])

  const toggleCustomer = (id: string) => {
    setExpandedCustomer(prev => prev === id ? null : id)
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-text">Aged Receivables</h1>
        <p className="text-sm text-muted mt-1">Outstanding invoices grouped by age</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="block text-xs font-medium text-muted mb-1">Report Date</label>
          <input
            type="date"
            value={reportDate}
            onChange={e => setReportDate(e.target.value)}
            className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading report" /></div>
      ) : error ? (
        <div className="rounded-card border border-danger-soft bg-danger-soft p-6 text-center text-danger">{error}</div>
      ) : !data ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted shadow-card">
          Select a date to generate the report.
        </div>
      ) : (data?.customers ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted shadow-card">
          No outstanding receivables as at {data?.report_date}.
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customer</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Current</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">31–60</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">61–90</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">90+</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
              </tr>
            </thead>
            <tbody>
              {(data?.customers ?? []).map(cust => (
                <tr key={cust.customer_id} className="group">
                  <td colSpan={6} className="p-0">
                    {/* Customer row */}
                    <button
                      onClick={() => toggleCustomer(cust.customer_id)}
                      className="w-full flex items-center hover:bg-canvas px-4 py-3 border-b border-border"
                    >
                      <span className="flex-1 text-left text-sm font-medium text-text">
                        <span className="mr-1 text-muted-2">{expandedCustomer === cust.customer_id ? '▾' : '▸'}</span>
                        {cust.customer_name}
                      </span>
                      <span className="w-24 text-right text-sm text-muted mono">{fmt(cust.current)}</span>
                      <span className="w-24 text-right text-sm text-muted mono">{fmt(cust['31_60'])}</span>
                      <span className="w-24 text-right text-sm text-muted mono">{fmt(cust['61_90'])}</span>
                      <span className="w-24 text-right text-sm text-muted mono">{fmt(cust['90_plus'])}</span>
                      <span className="w-24 text-right text-sm font-semibold text-text mono">{fmt(cust.total)}</span>
                    </button>
                    {/* Expanded invoices */}
                    {expandedCustomer === cust.customer_id && (cust.invoices ?? []).length > 0 && (
                      <div className="bg-canvas px-8 py-2 border-b border-border">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-muted-2">
                              <th className="text-left py-1">Invoice</th>
                              <th className="text-left py-1">Due Date</th>
                              <th className="text-right py-1">Balance</th>
                              <th className="text-right py-1">Days Overdue</th>
                              <th className="text-right py-1">Bucket</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(cust.invoices ?? []).map(inv => (
                              <tr key={inv.invoice_id} className="border-b border-border">
                                <td className="py-1 text-muted mono">{inv.invoice_number ?? '—'}</td>
                                <td className="py-1 text-muted mono">{inv.due_date ?? '—'}</td>
                                <td className="py-1 text-right text-muted mono">{fmt(inv.balance_due)}</td>
                                <td className="py-1 text-right text-muted mono">{inv.days_overdue ?? 0}</td>
                                <td className="py-1 text-right text-muted-2">{inv.bucket}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            {/* Overall totals */}
            {data?.overall && (
              <tfoot className="bg-canvas font-semibold">
                <tr>
                  <td className="px-4 py-3 text-sm text-text">Total</td>
                  <td className="px-4 py-3 text-right text-sm text-text mono">{fmt(data.overall?.current ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-text mono">{fmt(data.overall?.['31_60'] ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-text mono">{fmt(data.overall?.['61_90'] ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-text mono">{fmt(data.overall?.['90_plus'] ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm font-bold text-text mono">{fmt(data.overall?.total ?? 0)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  )
}
