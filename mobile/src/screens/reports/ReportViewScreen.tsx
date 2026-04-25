import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import type { ReportData } from '@shared/types/report'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileButton, MobileSpinner } from '@/components/ui'
import { DateRangePicker } from '@/components/common/DateRangePicker'
import type { DateRange } from '@/components/common/DateRangePicker'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function getDefaultDateRange(): DateRange {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  return {
    start: start.toISOString().split('T')[0],
    end: now.toISOString().split('T')[0],
  }
}

/**
 * Report view screen — mobile-optimised report display with summary cards,
 * scrollable data tables, date range filter, pull-to-refresh.
 *
 * Requirements: 28.3, 28.4, 28.5
 */
export default function ReportViewScreen() {
  const { type } = useParams<{ type: string }>()
  const navigate = useNavigate()
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange)

  const { data: report, isLoading, error, refetch } = useApiDetail<ReportData>({
    endpoint: `/api/v1/reports/${type}?start=${dateRange.start}&end=${dateRange.end}`,
    enabled: !!type,
  })

  const handleDateChange = useCallback(
    (range: DateRange) => {
      setDateRange(range)
      // Refetch will happen via endpoint change in useApiDetail
    },
    [],
  )

  // Force refetch when date range changes
  const handleApply = useCallback(async () => {
    await refetch()
  }, [refetch])

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'Report not available'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const summaryEntries = Object.entries(report.summary ?? {})
  const rows = report.rows ?? []
  const columns = rows.length > 0 ? Object.keys(rows[0]) : []

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        {report.title ?? 'Report'}
      </h1>

      {/* Date range filter */}
      <DateRangePicker
        value={dateRange}
        onChange={handleDateChange}
        label="Date Range"
      />
      <MobileButton variant="secondary" size="sm" onClick={handleApply}>
        Apply
      </MobileButton>

      {/* Summary cards */}
      {summaryEntries.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {summaryEntries.map(([key, value]) => (
            <MobileCard key={key} padding="p-3">
              <div className="flex flex-col">
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                </span>
                <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
                  {typeof value === 'number' ? formatCurrency(value) : String(value ?? '')}
                </span>
              </div>
            </MobileCard>
          ))}
        </div>
      )}

      {/* Data table */}
      {rows.length > 0 && (
        <MobileCard padding="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  {columns.map((col) => (
                    <th
                      key={col}
                      className="whitespace-nowrap px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400"
                    >
                      {col.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr
                    key={idx}
                    className="border-b border-gray-100 last:border-b-0 dark:border-gray-700"
                  >
                    {columns.map((col) => {
                      const val = row[col]
                      return (
                        <td
                          key={col}
                          className="whitespace-nowrap px-3 py-2 text-gray-900 dark:text-gray-100"
                        >
                          {typeof val === 'number'
                            ? formatCurrency(val)
                            : String(val ?? '')}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </MobileCard>
      )}

      {rows.length === 0 && summaryEntries.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
          No data for the selected period
        </p>
      )}
    </div>
  )
}
