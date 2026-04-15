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
        <h1 className="text-2xl font-semibold text-gray-900">Aged Receivables</h1>
        <p className="text-sm text-gray-500 mt-1">Outstanding invoices grouped by age</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Report Date</label>
          <input
            type="date"
            value={reportDate}
            onChange={e => setReportDate(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading report" /></div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{error}</div>
      ) : !data ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          Select a date to generate the report.
        </div>
      ) : (data?.customers ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No outstanding receivables as at {data?.report_date}.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customer</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Current</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">31–60</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">61–90</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">90+</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(data?.customers ?? []).map(cust => (
                <tr key={cust.customer_id} className="group">
                  <td colSpan={6} className="p-0">
                    {/* Customer row */}
                    <button
                      onClick={() => toggleCustomer(cust.customer_id)}
                      className="w-full flex items-center hover:bg-gray-50 px-4 py-3"
                    >
                      <span className="flex-1 text-left text-sm font-medium text-gray-900">
                        <span className="mr-1 text-gray-400">{expandedCustomer === cust.customer_id ? '▾' : '▸'}</span>
                        {cust.customer_name}
                      </span>
                      <span className="w-24 text-right text-sm text-gray-700">{fmt(cust.current)}</span>
                      <span className="w-24 text-right text-sm text-gray-700">{fmt(cust['31_60'])}</span>
                      <span className="w-24 text-right text-sm text-gray-700">{fmt(cust['61_90'])}</span>
                      <span className="w-24 text-right text-sm text-gray-700">{fmt(cust['90_plus'])}</span>
                      <span className="w-24 text-right text-sm font-semibold text-gray-900">{fmt(cust.total)}</span>
                    </button>
                    {/* Expanded invoices */}
                    {expandedCustomer === cust.customer_id && (cust.invoices ?? []).length > 0 && (
                      <div className="bg-gray-50 px-8 py-2 border-t border-gray-100">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-gray-500">
                              <th className="text-left py-1">Invoice</th>
                              <th className="text-left py-1">Due Date</th>
                              <th className="text-right py-1">Balance</th>
                              <th className="text-right py-1">Days Overdue</th>
                              <th className="text-right py-1">Bucket</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(cust.invoices ?? []).map(inv => (
                              <tr key={inv.invoice_id} className="border-b border-gray-100">
                                <td className="py-1 text-gray-700">{inv.invoice_number ?? '—'}</td>
                                <td className="py-1 text-gray-700">{inv.due_date ?? '—'}</td>
                                <td className="py-1 text-right text-gray-700">{fmt(inv.balance_due)}</td>
                                <td className="py-1 text-right text-gray-700">{inv.days_overdue ?? 0}</td>
                                <td className="py-1 text-right text-gray-500">{inv.bucket}</td>
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
              <tfoot className="bg-gray-100 font-semibold">
                <tr>
                  <td className="px-4 py-3 text-sm text-gray-900">Total</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-900">{fmt(data.overall?.current ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-900">{fmt(data.overall?.['31_60'] ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-900">{fmt(data.overall?.['61_90'] ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm text-gray-900">{fmt(data.overall?.['90_plus'] ?? 0)}</td>
                  <td className="px-4 py-3 text-right text-sm font-bold text-gray-900">{fmt(data.overall?.total ?? 0)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  )
}
