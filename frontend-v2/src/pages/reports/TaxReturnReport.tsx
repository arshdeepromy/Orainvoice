import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Select, PrintButton } from '@/components/ui'
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
    <table className="min-w-full" role="grid">
      <caption className="sr-only">GST Return (NZ)</caption>
      <thead>
        <tr>
          <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Item</th>
          <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Total Sales (incl. GST)</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.total_sales_incl)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text pl-8">Total Sales (excl. GST)</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.total_sales_excl)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">GST Collected</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.gst_collected)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">GST on Purchases</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.gst_on_purchases)}</td></tr>
        <tr className="border-b border-border last:border-b-0 hover:bg-canvas bg-ok-soft"><td className="px-4 py-3 text-sm font-semibold text-text">Net GST Payable</td><td className="px-4 py-3 text-sm font-semibold text-text text-right mono">{fmt(data.net_gst)}</td></tr>
      </tbody>
    </table>
  )

  const renderBAS = () => (
    <table className="min-w-full" role="grid">
      <caption className="sr-only">BAS Return (AU)</caption>
      <thead>
        <tr>
          <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Item</th>
          <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Total Sales</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.total_sales)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">GST on Sales</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.gst_on_sales)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">GST on Purchases</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.gst_on_purchases)}</td></tr>
        <tr className="border-b border-border last:border-b-0 hover:bg-canvas bg-ok-soft"><td className="px-4 py-3 text-sm font-semibold text-text">Net GST</td><td className="px-4 py-3 text-sm font-semibold text-text text-right mono">{fmt(data.net_gst)}</td></tr>
      </tbody>
    </table>
  )

  const renderVAT = () => (
    <table className="min-w-full" role="grid">
      <caption className="sr-only">VAT Return (UK)</caption>
      <thead>
        <tr>
          <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Box</th>
          <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Box 1: VAT due on sales</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.box1_vat_due_sales)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Box 2: VAT due on acquisitions</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.box2_vat_due_acquisitions)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Box 3: Total VAT due</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.box3_total_vat_due)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Box 4: VAT reclaimed</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.box4_vat_reclaimed)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas bg-ok-soft"><td className="px-4 py-3 text-sm font-semibold text-text">Box 5: Net VAT</td><td className="px-4 py-3 text-sm font-semibold text-text text-right mono">{fmt(data.box5_net_vat)}</td></tr>
        <tr className="border-b border-border hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Box 6: Total sales excl. VAT</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.box6_total_sales_excl)}</td></tr>
        <tr className="border-b border-border last:border-b-0 hover:bg-canvas"><td className="px-4 py-3 text-sm text-text">Box 7: Total purchases excl. VAT</td><td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.box7_total_purchases_excl)}</td></tr>
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

      {error && <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading tax return report" /></div>}

      {!loading && data && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          {taxType === 'gst_return' && renderGST()}
          {taxType === 'bas_return' && renderBAS()}
          {taxType === 'vat_return' && renderVAT()}
        </div>
      )}
    </div>
  )
}
