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
 *   - Typed client only (`@/api/payslips`).
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
          <h1 className="text-2xl font-semibold text-text">
            Wage variance
          </h1>
          <p className="mt-1 text-sm text-muted">
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
          <span className="block text-xs font-medium uppercase tracking-wide text-muted">
            Pay period (reference)
          </span>
          <select
            value={selectedPeriodId ?? ''}
            onChange={(e) => setSelectedPeriodId(e.target.value || null)}
            disabled={periodsLoading || (periods ?? []).length === 0}
            data-testid="wage-variance-period-selector"
            className="mt-1 block min-h-[44px] min-w-[280px] rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)] disabled:opacity-50"
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
          <span className="block text-xs font-medium uppercase tracking-wide text-muted">
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
            className="mt-1 block min-h-[44px] w-32 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]"
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
          variant="ghost"
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
          className="mb-3 text-sm text-muted"
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
          className="rounded-card border border-dashed border-border px-4 py-12 text-center text-sm text-muted"
          data-testid="wage-variance-empty"
        >
          No variance data available. The report needs at least two
          finalised pay periods to compare.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table
            className="min-w-full text-sm"
            data-testid="wage-variance-table"
          >
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Staff
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Previous gross
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Current gross
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Δ
                </th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                  Δ %
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const flagged = !!r?.above_threshold
                const deltaN = Number(r?.delta ?? 0)
                const deltaClass = !Number.isFinite(deltaN)
                  ? 'text-muted'
                  : deltaN > 0
                    ? 'text-ok'
                    : deltaN < 0
                      ? 'text-danger'
                      : 'text-muted'
                return (
                  <tr
                    key={r?.staff_id ?? Math.random().toString(36)}
                    data-testid={`wage-variance-row-${r?.staff_id ?? ''}`}
                    data-above-threshold={flagged ? 'true' : 'false'}
                    className={
                      `border-b border-border last:border-b-0 hover:bg-canvas ${
                        flagged ? 'bg-warn-soft' : ''
                      }`
                    }
                  >
                    <td className="px-4 py-2 text-text mono text-xs">
                      {r?.staff_id ?? '—'}
                    </td>
                    <td className="px-4 py-2 text-right mono text-muted">
                      {formatMoney(r?.previous_gross)}
                    </td>
                    <td className="px-4 py-2 text-right mono text-text">
                      {formatMoney(r?.current_gross)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right mono font-medium ${deltaClass}`}
                    >
                      {formatMoney(r?.delta)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right mono font-medium ${deltaClass}`}
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
