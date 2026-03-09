import { useState, useCallback } from 'react'
import apiClient from '../../api/client'
import { Input, Button, Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'

interface StatementLine {
  date: string
  description: string
  amount: number
  balance: number
}

interface StatementData {
  customer_name: string
  lines: StatementLine[]
  outstanding_balance: number
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now)
  from.setMonth(from.getMonth() - 3)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Customer statement — select a customer, view all invoices and payments
 * in a date range with outstanding balance. Printable/emailable PDF.
 * Requirements: 45.7
 */
export default function CustomerStatement() {
  const [customerId, setCustomerId] = useState('')
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<StatementData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)

  const fetchStatement = useCallback(async () => {
    if (!customerId.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<StatementData>(`/reports/customer-statement/${customerId}`, {
        params: { from: range.from, to: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load customer statement.')
    } finally {
      setLoading(false)
    }
  }, [customerId, range])

  const handleExportPdf = async () => {
    if (!customerId.trim()) return
    setExporting(true)
    try {
      const res = await apiClient.get(`/reports/customer-statement/${customerId}`, {
        params: { from: range.from, to: range.to, format: 'pdf' },
        responseType: 'blob',
      })
      const blob = new Blob([res.data])
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'customer-statement.pdf'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // Silently fail
    } finally {
      setExporting(false)
    }
  }

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4">
        Generate a printable statement for a specific customer showing invoices, payments, and outstanding balance.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end mb-6 no-print">
        <div className="w-64">
          <Input
            label="Customer ID"
            placeholder="Enter customer ID…"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
          />
        </div>
        <DateRangeFilter value={range} onChange={setRange} />
        <Button onClick={fetchStatement} disabled={!customerId.trim()} loading={loading}>
          Generate
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading customer statement" /></div>}

      {!loading && data && (
        <>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-medium text-gray-900">{data.customer_name}</h3>
              <p className="text-sm text-gray-500">
                Outstanding balance: <span className="font-semibold text-red-600">{fmt(data.outstanding_balance)}</span>
              </p>
            </div>
            <Button variant="secondary" size="sm" loading={exporting} onClick={handleExportPdf} aria-label="Export statement as PDF">
              Export PDF
            </Button>
            <PrintButton label="Print Statement" />
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Customer statement</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {!data.lines || data.lines.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-500">
                      No transactions for this period.
                    </td>
                  </tr>
                ) : (
                  data.lines.map((line, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {new Date(line.date).toLocaleDateString('en-NZ')}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">{line.description}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right">{fmt(line.amount)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right">{fmt(line.balance)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
