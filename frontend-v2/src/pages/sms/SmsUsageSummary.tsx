import { useState, useEffect } from 'react'
import { Spinner, AlertBanner } from '@/components/ui'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface UsageSummary {
  total_sent: number
  total_cost: string
  included_quota: number
  package_credits_remaining: number
  overage_count: number
  overage_charge: string
  warning: boolean
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  return `${(num || 0).toFixed(2)} NZD`
}

/* ------------------------------------------------------------------ */
/*  Cost Trend Bar Chart (CSS-only)                                    */
/* ------------------------------------------------------------------ */

/** Simple bar chart showing the current month's cost as a single bar.
 *  If historical data were available from the API we'd show 6 months;
 *  for now we render the current month's stats.                       */
function CostTrendChart({ totalCost }: { totalCost: string }) {
  const cost = parseFloat(totalCost) || 0
  const label = new Date().toLocaleString('default', { month: 'short' })

  // When there's no cost yet, show a minimal bar
  const barHeight = cost > 0 ? 100 : 4

  return (
    <div className="mt-4">
      <h4 className="text-sm font-medium text-text mb-2">Monthly Cost Trend</h4>
      <div className="flex items-end gap-2 h-28 border-b border-border pb-1">
        <div className="flex flex-col items-center flex-1 max-w-[80px]">
          <span className="mono text-xs text-muted mb-1">{formatNZD(cost)}</span>
          <div
            className="w-full rounded-t bg-accent transition-all duration-300"
            style={{ height: `${barHeight}%` }}
            role="img"
            aria-label={`${label}: ${formatNZD(cost)}`}
          />
          <span className="text-xs text-muted-2 mt-1">{label}</span>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export function SmsUsageSummary() {
  const [data, setData] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchUsage() {
      try {
        setLoading(true)
        setError(null)
        const res = await apiClient.get('/api/v2/org/sms/usage-summary')
        if (!cancelled) setData(res.data)
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to load SMS usage'
          setError(msg)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchUsage()
    return () => { cancelled = true }
  }, [])

  /* Loading state */
  if (loading) {
    return (
      <div className="rounded-card border border-border bg-card p-6">
        <Spinner label="Loading SMS usage" />
      </div>
    )
  }

  /* Error state */
  if (error) {
    return (
      <div className="rounded-card border border-border bg-card p-6">
        <AlertBanner variant="error" title="SMS Usage Error">
          {error}
        </AlertBanner>
      </div>
    )
  }

  if (!data) return null

  const effectiveQuota = (data.included_quota ?? 0) + (data.package_credits_remaining ?? 0)
  const quotaUsedPct = effectiveQuota > 0 ? Math.round(((data.total_sent ?? 0) / effectiveQuota) * 100) : 0

  return (
    <div className="rounded-card border border-border bg-card p-6 space-y-4">
      <h3 className="text-lg font-semibold text-text">SMS Usage Summary</h3>

      {/* 80% quota warning */}
      {data.warning && (
        <AlertBanner variant="warning" title="Quota Warning">
          SMS usage has exceeded 80% of your effective quota ({data.total_sent} / {effectiveQuota}).
          Consider purchasing an SMS package to avoid overage charges.
        </AlertBanner>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-ctl bg-canvas p-3">
          <p className="text-xs text-muted">Total Sent</p>
          <p className="mono text-xl font-bold text-text">{data.total_sent ?? 0}</p>
        </div>

        <div className="rounded-ctl bg-canvas p-3">
          <p className="text-xs text-muted">Total Cost</p>
          <p className="mono text-xl font-bold text-text">{formatNZD(data.total_cost)}</p>
        </div>

        <div className="rounded-ctl bg-canvas p-3">
          <p className="text-xs text-muted">Quota Remaining</p>
          <p className="mono text-xl font-bold text-text">
            {effectiveQuota - (data.total_sent ?? 0) > 0 ? effectiveQuota - (data.total_sent ?? 0) : 0}
          </p>
          <p className="text-xs text-muted-2">{quotaUsedPct}% used</p>
        </div>

        <div className="rounded-ctl bg-canvas p-3">
          <p className="text-xs text-muted">Overage</p>
          <p className={`mono text-xl font-bold ${(data.overage_count ?? 0) > 0 ? 'text-danger' : 'text-text'}`}>
            {data.overage_count ?? 0}
          </p>
          {(data.overage_count ?? 0) > 0 && (
            <p className="mono text-xs text-danger">{formatNZD(data.overage_charge)}</p>
          )}
        </div>
      </div>

      {/* Quota progress bar */}
      <div>
        <div className="flex justify-between text-xs text-muted mb-1">
          <span>{data.total_sent ?? 0} sent</span>
          <span>{effectiveQuota} quota</span>
        </div>
        <div className="h-2 w-full rounded-full bg-canvas overflow-hidden" role="progressbar" aria-valuenow={quotaUsedPct} aria-valuemin={0} aria-valuemax={100}>
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              quotaUsedPct >= 100 ? 'bg-danger' : quotaUsedPct >= 80 ? 'bg-warn' : 'bg-accent'
            }`}
            style={{ width: `${Math.min(quotaUsedPct, 100)}%` }}
          />
        </div>
      </div>

      {/* Monthly cost trend chart */}
      <CostTrendChart totalCost={data.total_cost} />
    </div>
  )
}

export default SmsUsageSummary
