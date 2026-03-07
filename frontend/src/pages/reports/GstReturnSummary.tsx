import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

interface GstData {
  total_sales: number
  standard_rated_sales: number
  zero_rated_sales: number
  total_gst_collected: number
  net_gst: number
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 2, 1)
  const to = new Date(now.getFullYear(), now.getMonth(), 0)
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) }
}

const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

/**
 * GST return summary — total sales, GST collected, standard vs zero-rated,
 * formatted to support manual IRD GST return filing.
 * Requirements: 45.6
 */
export default function GstReturnSummary() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<GstData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<GstData>('/reports/gst-return', {
        params: { from: range.from, to: range.to },
      })
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
      <p className="text-sm text-gray-500 mb-4">
        GST summary formatted for manual IRD GST return filing.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/gst-return" params={{ from: range.from, to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading GST return summary" /></div>}

      {!loading && data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">GST return summary</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Item</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount (NZD)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              <tr className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm text-gray-900">Total Sales (incl. GST)</td>
                <td className="px-4 py-3 text-sm text-gray-900 text-right">{fmt(data.total_sales)}</td>
              </tr>
              <tr className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm text-gray-700 pl-8">Standard-rated sales (15%)</td>
                <td className="px-4 py-3 text-sm text-gray-700 text-right">{fmt(data.standard_rated_sales)}</td>
              </tr>
              <tr className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm text-gray-700 pl-8">Zero-rated sales</td>
                <td className="px-4 py-3 text-sm text-gray-700 text-right">{fmt(data.zero_rated_sales)}</td>
              </tr>
              <tr className="hover:bg-gray-50 bg-blue-50">
                <td className="px-4 py-3 text-sm font-medium text-gray-900">Total GST Collected</td>
                <td className="px-4 py-3 text-sm font-medium text-gray-900 text-right">{fmt(data.total_gst_collected)}</td>
              </tr>
              <tr className="hover:bg-gray-50 bg-green-50">
                <td className="px-4 py-3 text-sm font-semibold text-gray-900">Net GST Payable</td>
                <td className="px-4 py-3 text-sm font-semibold text-gray-900 text-right">{fmt(data.net_gst)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
