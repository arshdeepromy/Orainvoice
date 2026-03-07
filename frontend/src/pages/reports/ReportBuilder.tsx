import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Select, Spinner } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'

interface ReportTypeOption {
  value: string
  label: string
  category: string
}

const REPORT_TYPES: ReportTypeOption[] = [
  // Inventory
  { value: 'stock_valuation', label: 'Stock Valuation', category: 'Inventory' },
  { value: 'stock_movement_summary', label: 'Stock Movement Summary', category: 'Inventory' },
  { value: 'low_stock', label: 'Low Stock Alert', category: 'Inventory' },
  { value: 'dead_stock', label: 'Dead Stock', category: 'Inventory' },
  // Jobs
  { value: 'job_profitability', label: 'Job Profitability', category: 'Jobs' },
  { value: 'jobs_by_status', label: 'Jobs by Status', category: 'Jobs' },
  { value: 'avg_completion_time', label: 'Avg Completion Time', category: 'Jobs' },
  { value: 'staff_utilisation', label: 'Staff Utilisation', category: 'Jobs' },
  // Projects
  { value: 'project_profitability', label: 'Project Profitability', category: 'Projects' },
  { value: 'progress_claim_summary', label: 'Progress Claim Summary', category: 'Projects' },
  { value: 'variation_register', label: 'Variation Register', category: 'Projects' },
  { value: 'retention_summary', label: 'Retention Summary', category: 'Projects' },
  // POS
  { value: 'daily_sales_summary', label: 'Daily Sales Summary', category: 'POS' },
  { value: 'session_reconciliation', label: 'Session Reconciliation', category: 'POS' },
  { value: 'hourly_sales_heatmap', label: 'Hourly Sales Heatmap', category: 'POS' },
  // Hospitality
  { value: 'table_turnover', label: 'Table Turnover', category: 'Hospitality' },
  { value: 'avg_order_value', label: 'Average Order Value', category: 'Hospitality' },
  { value: 'kitchen_prep_times', label: 'Kitchen Prep Times', category: 'Hospitality' },
  { value: 'tip_summary', label: 'Tip Summary', category: 'Hospitality' },
  // Tax
  { value: 'gst_return', label: 'GST Return (NZ)', category: 'Tax' },
  { value: 'bas_return', label: 'BAS Return (AU)', category: 'Tax' },
  { value: 'vat_return', label: 'VAT Return (UK)', category: 'Tax' },
]

const CURRENCIES = ['NZD', 'AUD', 'USD', 'GBP', 'EUR']

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now)
  from.setMonth(from.getMonth() - 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

/**
 * Universal report builder with type selector, date range, location filter,
 * currency selector, and export buttons (PDF, CSV, Excel).
 *
 * Requirements: Task 54.17
 */
export default function ReportBuilder() {
  const [reportType, setReportType] = useState(REPORT_TYPES[0].value)
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [locationId, setLocationId] = useState('')
  const [currency, setCurrency] = useState('NZD')
  const [data, setData] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState<string | null>(null)

  const fetchReport = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {
        date_from: range.from,
        date_to: range.to,
        currency,
      }
      if (locationId) params.location_id = locationId
      const res = await apiClient.get(`/reports/${reportType}`, { params })
      setData(res.data)
    } catch {
      setError('Failed to generate report.')
    } finally {
      setLoading(false)
    }
  }, [reportType, range, locationId, currency])

  const handleExport = async (format: string) => {
    setExporting(format)
    try {
      const params: Record<string, string> = {
        date_from: range.from,
        date_to: range.to,
        currency,
        format,
      }
      if (locationId) params.location_id = locationId
      const res = await apiClient.get(`/reports/${reportType}`, {
        params,
        responseType: 'blob',
      })
      const blob = new Blob([res.data])
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${reportType}.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // silent
    } finally {
      setExporting(null)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Report Builder</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div>
          <Select
            label="Report Type"
            value={reportType}
            onChange={(e) => setReportType(e.target.value)}
            options={REPORT_TYPES.map((rt) => ({
              value: rt.value,
              label: `${rt.category}: ${rt.label}`,
            }))}
          />
        </div>

        <div>
          <DateRangeFilter value={range} onChange={setRange} />
        </div>

        <div>
          <label htmlFor="location-filter" className="block text-sm font-medium text-gray-700 mb-1">
            Location
          </label>
          <input
            id="location-filter"
            type="text"
            placeholder="All locations"
            value={locationId}
            onChange={(e) => setLocationId(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <Select
            label="Currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            options={CURRENCIES.map((c) => ({ value: c, label: c }))}
          />
        </div>
      </div>

      <div className="flex items-center gap-3 mb-6">
        <Button onClick={fetchReport} loading={loading}>
          Generate Report
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={exporting === 'pdf'}
          onClick={() => handleExport('pdf')}
          aria-label="Export as PDF"
        >
          PDF
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={exporting === 'csv'}
          onClick={() => handleExport('csv')}
          aria-label="Export as CSV"
        >
          CSV
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={exporting === 'xlsx'}
          onClick={() => handleExport('xlsx')}
          aria-label="Export as Excel"
        >
          Excel
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Generating report" /></div>}

      {!loading && data && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <pre className="text-sm text-gray-700 whitespace-pre-wrap overflow-x-auto">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
