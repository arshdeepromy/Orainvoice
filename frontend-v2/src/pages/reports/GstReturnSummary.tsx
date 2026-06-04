import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import { useBranch } from '@/contexts/BranchContext'

interface GstData {
  total_sales: number
  standard_rated_sales: number
  zero_rated_sales: number
  total_gst_collected: number
  net_gst: number
  total_refunds: number
  refund_gst: number
  adjusted_total_sales: number
  adjusted_gst_collected: number
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 2, 1)
  const to = new Date(now.getFullYear(), now.getMonth(), 0)
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'
const fmtNeg = (v: number | undefined) => v != null && v > 0 ? `-$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * GST return summary — total sales, GST collected, standard vs zero-rated,
 * formatted to support manual IRD GST return filing.
 * Requirements: 45.6
 */
export default function GstReturnSummary() {
  const { selectedBranchId } = useBranch()
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<GstData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { start_date: range.from, end_date: range.to }
      if (selectedBranchId) params.branch_id = selectedBranchId
      const res = await apiClient.get<GstData>('/reports/gst-return', { params })
      setData(res.data)
    } catch {
      setError('Failed to load GST return summary.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">
        GST summary formatted for manual IRD GST return filing.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/gst-return" params={{ start_date: range.from, end_date: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading GST return summary" /></div>}

      {!loading && data && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">GST return summary</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Item</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount (NZD)</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border hover:bg-canvas">
                <td className="px-4 py-3 text-sm text-text">Total Sales (incl. GST)</td>
                <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.total_sales)}</td>
              </tr>
              <tr className="border-b border-border hover:bg-canvas">
                <td className="px-4 py-3 text-sm text-muted pl-8">Standard-rated sales (15%)</td>
                <td className="px-4 py-3 text-sm text-muted text-right mono">{fmt(data.standard_rated_sales)}</td>
              </tr>
              <tr className="border-b border-border hover:bg-canvas">
                <td className="px-4 py-3 text-sm text-muted pl-8">Zero-rated sales</td>
                <td className="px-4 py-3 text-sm text-muted text-right mono">{fmt(data.zero_rated_sales)}</td>
              </tr>
              <tr className="border-b border-border hover:bg-canvas bg-accent-soft">
                <td className="px-4 py-3 text-sm font-medium text-text">Total GST Collected</td>
                <td className="px-4 py-3 text-sm font-medium text-text text-right mono">{fmt(data.total_gst_collected)}</td>
              </tr>
              {data.total_refunds > 0 && (
                <>
                  <tr className="border-b border-border hover:bg-canvas bg-danger-soft">
                    <td className="px-4 py-3 text-sm font-medium text-danger">Refunds / Credit Notes</td>
                    <td className="px-4 py-3 text-sm font-medium text-danger text-right mono">{fmtNeg(data.total_refunds)}</td>
                  </tr>
                  <tr className="border-b border-border hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-danger pl-8">GST on refunds</td>
                    <td className="px-4 py-3 text-sm text-danger text-right mono">{fmtNeg(data.refund_gst)}</td>
                  </tr>
                  <tr className="border-b border-border hover:bg-canvas bg-canvas">
                    <td className="px-4 py-3 text-sm font-medium text-text">Adjusted Sales (incl. GST)</td>
                    <td className="px-4 py-3 text-sm font-medium text-text text-right mono">{fmt(data.adjusted_total_sales)}</td>
                  </tr>
                  <tr className="border-b border-border hover:bg-canvas bg-canvas">
                    <td className="px-4 py-3 text-sm font-medium text-text">Adjusted GST Collected</td>
                    <td className="px-4 py-3 text-sm font-medium text-text text-right mono">{fmt(data.adjusted_gst_collected)}</td>
                  </tr>
                </>
              )}
              <tr className="border-b border-border last:border-b-0 hover:bg-canvas bg-ok-soft">
                <td className="px-4 py-3 text-sm font-semibold text-text">Net GST Payable</td>
                <td className="px-4 py-3 text-sm font-semibold text-text text-right mono">{fmt(data.net_gst)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
