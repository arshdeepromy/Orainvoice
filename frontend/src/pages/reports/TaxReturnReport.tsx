import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Select, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type TaxType = 'gst_return' | 'bas_return' | 'vat_return'

const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 2, 1)
  const to = new Date(now.getFullYear(), now.getMonth(), 0)
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) }
}

/**
 * Tax return reports: GST (NZ), BAS (AU), VAT (UK).
 * Requirements: Task 54.18
 */
export default function TaxReturnReport() {
  const [taxType, setTaxType] = useState<TaxType>('gst_return')
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/reports/${taxType}`, {
        params: { date_from: range.from, date_to: range.to },
      })
      setData(res.data?.data ?? res.data)
    } catch {
      setError('Failed to load tax return report.')
    } finally {
      setLoading(false)
    }
  }, [taxType, range])

  useEffect(() => { fetchData() }, [fetchData])

  const renderGST = () => (
    <table className="min-w-full divide-y divide-gray-200" role="grid">
      <caption className="sr-only">GST Return (NZ)</caption>
      <thead className="bg-gray-50">
        <tr>
          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Item</th>
          <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Amount</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-200 bg-white">
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Total Sales (incl. GST)</td><td className="px-4 py-3 text-sm text-right">{fmt(data.total_sales_incl)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm pl-8">Total Sales (excl. GST)</td><td className="px-4 py-3 text-sm text-right">{fmt(data.total_sales_excl)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">GST Collected</td><td className="px-4 py-3 text-sm text-right">{fmt(data.gst_collected)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">GST on Purchases</td><td className="px-4 py-3 text-sm text-right">{fmt(data.gst_on_purchases)}</td></tr>
        <tr className="hover:bg-gray-50 bg-green-50"><td className="px-4 py-3 text-sm font-semibold">Net GST Payable</td><td className="px-4 py-3 text-sm font-semibold text-right">{fmt(data.net_gst)}</td></tr>
      </tbody>
    </table>
  )

  const renderBAS = () => (
    <table className="min-w-full divide-y divide-gray-200" role="grid">
      <caption className="sr-only">BAS Return (AU)</caption>
      <thead className="bg-gray-50">
        <tr>
          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Item</th>
          <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Amount</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-200 bg-white">
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Total Sales</td><td className="px-4 py-3 text-sm text-right">{fmt(data.total_sales)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">GST on Sales</td><td className="px-4 py-3 text-sm text-right">{fmt(data.gst_on_sales)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">GST on Purchases</td><td className="px-4 py-3 text-sm text-right">{fmt(data.gst_on_purchases)}</td></tr>
        <tr className="hover:bg-gray-50 bg-green-50"><td className="px-4 py-3 text-sm font-semibold">Net GST</td><td className="px-4 py-3 text-sm font-semibold text-right">{fmt(data.net_gst)}</td></tr>
      </tbody>
    </table>
  )

  const renderVAT = () => (
    <table className="min-w-full divide-y divide-gray-200" role="grid">
      <caption className="sr-only">VAT Return (UK)</caption>
      <thead className="bg-gray-50">
        <tr>
          <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Box</th>
          <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Amount</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-200 bg-white">
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Box 1: VAT due on sales</td><td className="px-4 py-3 text-sm text-right">{fmt(data.box1_vat_due_sales)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Box 2: VAT due on acquisitions</td><td className="px-4 py-3 text-sm text-right">{fmt(data.box2_vat_due_acquisitions)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Box 3: Total VAT due</td><td className="px-4 py-3 text-sm text-right">{fmt(data.box3_total_vat_due)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Box 4: VAT reclaimed</td><td className="px-4 py-3 text-sm text-right">{fmt(data.box4_vat_reclaimed)}</td></tr>
        <tr className="hover:bg-gray-50 bg-green-50"><td className="px-4 py-3 text-sm font-semibold">Box 5: Net VAT</td><td className="px-4 py-3 text-sm font-semibold text-right">{fmt(data.box5_net_vat)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Box 6: Total sales excl. VAT</td><td className="px-4 py-3 text-sm text-right">{fmt(data.box6_total_sales_excl)}</td></tr>
        <tr className="hover:bg-gray-50"><td className="px-4 py-3 text-sm">Box 7: Total purchases excl. VAT</td><td className="px-4 py-3 text-sm text-right">{fmt(data.box7_total_purchases_excl)}</td></tr>
      </tbody>
    </table>
  )

  return (
    <div data-print-content>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <div className="flex gap-3 items-end">
          <Select
            label="Tax Type"
            value={taxType}
            onChange={(e) => setTaxType(e.target.value as TaxType)}
            options={[
              { value: 'gst_return', label: 'GST Return (NZ)' },
              { value: 'bas_return', label: 'BAS Return (AU)' },
              { value: 'vat_return', label: 'VAT Return (UK)' },
            ]}
          />
          <DateRangeFilter value={range} onChange={setRange} />
        </div>
        <div className="flex items-center gap-2">
          <ExportButtons endpoint={`/reports/${taxType}`} params={{ date_from: range.from, date_to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading tax return report" /></div>}

      {!loading && data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          {taxType === 'gst_return' && renderGST()}
          {taxType === 'bas_return' && renderBAS()}
          {taxType === 'vat_return' && renderVAT()}
        </div>
      )}
    </div>
  )
}
