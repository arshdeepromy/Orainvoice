/**
 * WageVariancePage — Reports → Wage Variance (Phase 4 task D6).
 *
 * Per design.md §6.6 + R12:
 *   - Report table: staff name, this-period gross, last-period gross,
 *     delta, % change.
 *   - Filter by % threshold (numeric input; default 10).
 *   - Period selector (uses listPayPeriods({ limit: 100 })).
 *   - Calls getWageVarianceReport({ threshold_pct }).
 *   - Highlight rows where above_threshold === true.
 *
 * Conventions:
 *   - Typed client only (`frontend/src/api/payslips.ts`).
 *   - All API responses consumed with `?.` + `?? []` / `?? null`.
 *   - Decimal values arrive as strings; coerced via Number(s).
 *   - Every effect uses an AbortController.
 *
 * **Validates: Staff Management Phase 4 task D6, R12**
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Spinner, AlertBanner } from '@/components/ui'
import {
  getWageVarianceReport,
  listPayPeriods,
} from '@/api/payslips'
import type {
  PayPeriod,
  WageVarianceReport,
  WageVarianceRow,
} from '@/api/payslips'

const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

const DEFAULT_THRESHOLD_PCT = 10

function formatMoney(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) return NZD.format(0)
  return NZD.format(n)
}

function formatPct(value: string | number | null | undefined): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0)
  if (!Number.isFinite(n)) return '0.00%'
  return `${n.toFixed(2)}%`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function formatPeriodRange(period: PayPeriod | null | undefined): string {
  if (!period) return '—'
  return `${formatDate(period.start_date)} – ${formatDate(period.end_date)}`
}

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

function readErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  if (err instanceof Error) return err.message
  return 'Failed to load report'
}

export default function WageVariancePage() {
  // Period catalogue (used to render the selector + look up the period
  // labels by id surfaced in the report response).
  const [periods, setPeriods] = useState<PayPeriod[]>([])
  const [periodsLoading, setPeriodsLoading] = useState<boolean>(true)
  const [periodsError, setPeriodsError] = useState<string | null>(null)
  const [selectedPeriodId, setSelectedPeriodId] = useState<string | null>(null)

  const [thresholdInput, setThresholdInput] = useState<string>(
    String(DEFAULT_THRESHOLD_PCT),
  )
  const [activeThreshold, setActiveThreshold] = useState<number>(
    DEFAULT_THRESHOLD_PCT,
  )

  const [report, setReport] = useState<WageVarianceReport | null>(null)
  const [reportLoading, setReportLoading] = useState<boolean>(false)
  const [reportError, setReportError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState<number>(0)

  // ── Load pay periods (for the selector) ──
  useEffect(() => {
    const controller = new AbortController()
    setPeriodsLoading(true)
    setPeriodsError(null)
    ;(async () => {
      try {
        const res = await listPayPeriods({ limit: 100 }, controller.signal)
        if (controller.signal.aborted) return
        const items = res.items ?? []
        setPeriods(items)
        // Default to the first non-open finalised period when one
        // exists; otherwise the first row.
        setSelectedPeriodId((prev) => {
          if (prev && items.some((p) => p?.id === prev)) return prev
          const finalised = items.find((p) => p?.status === 'finalised')
          return finalised?.id ?? items[0]?.id ?? null
        })
      } catch (err) {
        if (isAbortError(err)) return
        setPeriodsError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setPeriodsLoading(false)
      }
    })()
    return () => controller.abort()
  }, [])

  // ── Load the wage-variance report ──
  useEffect(() => {
    const controller = new AbortController()
    setReportLoading(true)
    setReportError(null)
    ;(async () => {
      try {
        const res = await getWageVarianceReport(
          { threshold_pct: activeThreshold },
          controller.signal,
        )
        if (controller.signal.aborted) return
        setReport(res)
      } catch (err) {
        if (isAbortError(err)) return
        setReportError(readErrorMessage(err))
      } finally {
        if (!controller.signal.aborted) setReportLoading(false)
      }
    })()
    return () => controller.abort()
  }, [activeThreshold, refreshTick])

  // Quick-lookup of staff names by staff_id when the server didn't
  // include them. Only the staff_id is guaranteed in WageVarianceRow.
  // The period label is sourced from the report's current_period_id +
  // previous_period_id and the periods catalogue.
  const periodById = useMemo(() => {
    const map = new Map<string, PayPeriod>()
    for (const p of (periods ?? [])) {
      if (p?.id) map.set(p.id, p)
    }
    return map
  }, [periods])

  const currentPeriod =
    (report?.current_period_id && periodById.get(report.current_period_id)) ||
    null
  const previousPeriod =
    (report?.previous_period_id && periodById.get(report.previous_period_id)) ||
    null

  const rows: WageVarianceRow[] = report?.items ?? []

  const applyThreshold = useCallback(() => {
    const parsed = Number(thresholdInput)
    if (!Number.isFinite(parsed) || parsed < 0) return
    setActiveThreshold(parsed)
  }, [thresholdInput])

  const handleThresholdKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') applyThreshold()
    },
    [applyThreshold],
  )

  return (
    <div
      className="mx-auto w-full max-w-6xl px-4 py-6"
      data-testid="wage-variance-page"
    >
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
            Wage variance
          </h1>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            Compares each staff member's gross pay between the latest two
            finalised pay periods. Rows above the threshold are highlighted
            for review.
          </p>
        </div>
      </header>

      {periodsError && (
        <AlertBanner variant="error" className="mb-4">
          {periodsError}
        </AlertBanner>
      )}

      <section className="mb-4 flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="block text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">
            Pay period (reference)
          </span>
          <select
            value={selectedPeriodId ?? ''}
            onChange={(e) => setSelectedPeriodId(e.target.value || null)}
            disabled={periodsLoading || (periods ?? []).length === 0}
            data-testid="wage-variance-period-selector"
            className="mt-1 block min-h-[44px] min-w-[280px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          >
            {(periods ?? []).length === 0 && (
              <option value="">No pay periods available</option>
            )}
            {(periods ?? []).map((p) => (
              <option key={p?.id ?? ''} value={p?.id ?? ''}>
                {formatPeriodRange(p)} · {p?.status ?? '—'}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="block text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">
            Threshold (%)
          </span>
          <input
            type="number"
            min="0"
            step="0.5"
            value={thresholdInput}
            onChange={(e) => setThresholdInput(e.target.value)}
            onKeyDown={handleThresholdKeyDown}
            data-testid="wage-variance-threshold-input"
            className="mt-1 block min-h-[44px] w-32 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          />
        </label>

        <Button
          variant="primary"
          onClick={applyThreshold}
          disabled={reportLoading}
          loading={reportLoading}
          data-testid="wage-variance-apply"
        >
          Apply
        </Button>
        <Button
          variant="secondary"
          onClick={() => setRefreshTick((t) => t + 1)}
          disabled={reportLoading}
          data-testid="wage-variance-refresh"
        >
          Refresh
        </Button>
      </section>

      {reportError && (
        <AlertBanner variant="error" className="mb-4">
          {reportError}
        </AlertBanner>
      )}

      {report && (currentPeriod || previousPeriod) && (
        <p
          className="mb-3 text-sm text-gray-600 dark:text-gray-400"
          data-testid="wage-variance-period-summary"
        >
          {previousPeriod && (
            <>
              <span className="font-medium">Previous:</span>{' '}
              {formatPeriodRange(previousPeriod)}
            </>
          )}
          {currentPeriod && previousPeriod && <span> · </span>}
          {currentPeriod && (
            <>
              <span className="font-medium">Current:</span>{' '}
              {formatPeriodRange(currentPeriod)}
            </>
          )}
        </p>
      )}

      {reportLoading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" label="Loading report" />
        </div>
      ) : rows.length === 0 ? (
        <div
          className="rounded-md border border-dashed border-gray-300 px-4 py-12 text-center text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400"
          data-testid="wage-variance-empty"
        >
          No variance data available. The report needs at least two
          finalised pay periods to compare.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-gray-200 dark:border-gray-700">
          <table
            className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700"
            data-testid="wage-variance-table"
          >
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                  Staff
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Previous gross
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Current gross
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Δ
                </th>
                <th className="px-4 py-2 text-right font-medium text-gray-600 dark:text-gray-300">
                  Δ %
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
              {rows.map((r) => {
                const flagged = !!r?.above_threshold
                const deltaN = Number(r?.delta ?? 0)
                const deltaClass = !Number.isFinite(deltaN)
                  ? 'text-gray-700 dark:text-gray-300'
                  : deltaN > 0
                    ? 'text-emerald-700 dark:text-emerald-300'
                    : deltaN < 0
                      ? 'text-red-700 dark:text-red-300'
                      : 'text-gray-700 dark:text-gray-300'
                return (
                  <tr
                    key={r?.staff_id ?? Math.random().toString(36)}
                    data-testid={`wage-variance-row-${r?.staff_id ?? ''}`}
                    data-above-threshold={flagged ? 'true' : 'false'}
                    className={
                      flagged
                        ? 'bg-amber-50 dark:bg-amber-900/20'
                        : ''
                    }
                  >
                    <td className="px-4 py-2 text-gray-900 dark:text-gray-100 font-mono text-xs">
                      {r?.staff_id ?? '—'}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                      {formatMoney(r?.previous_gross)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">
                      {formatMoney(r?.current_gross)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right tabular-nums font-medium ${deltaClass}`}
                    >
                      {formatMoney(r?.delta)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right tabular-nums font-medium ${deltaClass}`}
                    >
                      {formatPct(r?.delta_pct)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
