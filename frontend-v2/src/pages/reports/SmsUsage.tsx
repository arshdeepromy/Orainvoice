import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface SmsUsageData {
  total_sent?: number
  included_in_plan?: number
  package_credits_remaining?: number
  effective_quota?: number
  overage_count?: number
  overage_charge_nzd?: number
  per_sms_cost_nzd?: number
  reset_at?: string | null
  daily_breakdown?: { date: string; sms_count: number }[]
}

interface SmsPackage {
  id: string
  tier_name: string
  sms_quantity: number
  price_nzd: number
  credits_remaining: number
  purchased_at: string
}

interface SmsPackageTier {
  tier_name: string
  sms_quantity: number
  price_nzd: number
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth(), 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) =>
  `$${(v ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

/**
 * SMS usage report — sent count, included quota, overage, packages, and daily breakdown.
 * Tiers are sourced from the org plan via `GET /org/plan-sms-pricing`; the daily chart
 * is sourced from `data.daily_breakdown` returned by `GET /reports/sms-usage`.
 *
 * Requirements: 8.3, 8.4, 9.3, 9.4, 14.1, 14.2, 19.1, 19.3, 21.1
 */
export default function SmsUsage() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<SmsUsageData | null>(null)
  const [packages, setPackages] = useState<SmsPackage[]>([])
  const [tiers, setTiers] = useState<SmsPackageTier[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [purchasing, setPurchasing] = useState(false)
  const [confirmTier, setConfirmTier] = useState<SmsPackageTier | null>(null)
  const [purchaseError, setPurchaseError] = useState('')

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const [usageRes, pkgRes] = await Promise.all([
        apiClient.get<SmsUsageData>('/reports/sms-usage', {
          params: { start_date: range.from, end_date: range.to },
          signal,
        }),
        apiClient.get<SmsPackage[]>('/org/sms-packages', { signal }),
      ])
      setData(usageRes.data ?? null)
      setPackages(pkgRes.data ?? [])
    } catch {
      if (!signal?.aborted) setError('Failed to load SMS usage report.')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [range])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  // Source SMS package tiers from the org plan (GET /org/plan-sms-pricing).
  // Read `sms_package_pricing ?? []` so the purchase section is gated on tier presence.
  useEffect(() => {
    const controller = new AbortController()
    const run = async () => {
      try {
        const res = await apiClient.get<{ sms_package_pricing?: SmsPackageTier[] }>(
          '/org/plan-sms-pricing',
          { signal: controller.signal },
        )
        setTiers(res.data?.sms_package_pricing ?? [])
      } catch {
        // Tiers are optional — silently ignore so the rest of the report renders.
        if (!controller.signal.aborted) setTiers([])
      }
    }
    run()
    return () => controller.abort()
  }, [])

  const handlePurchase = async () => {
    if (!confirmTier) return
    setPurchasing(true)
    setPurchaseError('')
    try {
      await apiClient.post('/org/sms-packages/purchase', { tier_name: confirmTier.tier_name })
      setConfirmTier(null)
      // Refetch usage + packages so the new credits show up
      const controller = new AbortController()
      fetchData(controller.signal)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPurchaseError(msg || 'Purchase failed. Please try again.')
    } finally {
      setPurchasing(false)
    }
  }

  const daily = data?.daily_breakdown ?? []

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">SMS usage, overage charges, and package credits.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/sms-usage" params={{ start_date: range.from, end_date: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading SMS usage report" /></div>}

      {!loading && data && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Total SMS Sent</p>
              <p className="text-2xl font-semibold text-text mono">{data.total_sent ?? 0}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Included in Plan</p>
              <p className="text-2xl font-semibold text-text mono">{data.included_in_plan ?? 0}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Overage Count</p>
              <p className="text-2xl font-semibold text-warn mono">{data.overage_count ?? 0}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Overage Charge</p>
              <p className="text-2xl font-semibold text-danger mono">{fmt(data.overage_charge_nzd)}</p>
            </div>
          </div>

          {/* Daily breakdown bar chart */}
          <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
            <h3 className="text-sm font-medium text-text mb-3">Daily SMS Sent</h3>
            {daily.length > 0 ? (
              <SimpleBarChart
                title="Daily SMS sent"
                items={daily.map((d) => ({
                  label: new Date(d.date).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }),
                  value: d.sms_count ?? 0,
                }))}
              />
            ) : (
              <p className="text-sm text-muted py-8 text-center">No daily SMS data for this period.</p>
            )}
          </div>

          {/* Active SMS packages */}
          <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
            <h3 className="text-sm font-medium text-text mb-3">Active SMS Packages</h3>
            {packages.length === 0 ? (
              <p className="text-sm text-muted">No active SMS packages.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 pr-4 font-medium text-muted">Package</th>
                      <th className="text-right py-2 pr-4 font-medium text-muted">Purchased</th>
                      <th className="text-right py-2 pr-4 font-medium text-muted">Credits Remaining</th>
                      <th className="text-right py-2 font-medium text-muted">Price Paid</th>
                    </tr>
                  </thead>
                  <tbody>
                    {packages.map((pkg) => (
                      <tr key={pkg.id} className="border-b border-border">
                        <td className="py-2 pr-4 text-text">{pkg.tier_name}</td>
                        <td className="py-2 pr-4 text-right text-muted mono">
                          {new Date(pkg.purchased_at).toLocaleDateString('en-NZ')}
                        </td>
                        <td className="py-2 pr-4 text-right text-text mono">
                          {pkg.credits_remaining ?? 0} / {pkg.sms_quantity ?? 0}
                        </td>
                        <td className="py-2 text-right text-muted mono">{fmt(pkg.price_nzd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Purchase SMS packages — gated on tier presence (≥1) */}
          {tiers.length > 0 && (
            <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
              <h3 className="text-sm font-medium text-text mb-3">Purchase SMS Package</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {tiers.map((tier) => (
                  <div
                    key={tier.tier_name}
                    className="rounded-card border border-border p-4 flex flex-col items-center gap-2"
                  >
                    <p className="font-medium text-text">{tier.tier_name}</p>
                    <p className="text-sm text-muted">{tier.sms_quantity ?? 0} SMS credits</p>
                    <p className="text-lg font-semibold text-text mono">{fmt(tier.price_nzd)}</p>
                    <button
                      type="button"
                      className="mt-2 rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
                      onClick={() => setConfirmTier(tier)}
                    >
                      Purchase
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Purchase confirmation dialog */}
      {confirmTier && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true">
          <div className="bg-card rounded-card shadow-pop p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-text mb-2">Confirm Purchase</h3>
            <p className="text-sm text-muted mb-4">
              Purchase <span className="font-medium">{confirmTier.tier_name}</span> ({confirmTier.sms_quantity} SMS credits) for{' '}
              <span className="font-medium">{fmt(confirmTier.price_nzd)}</span>?
            </p>
            <p className="text-xs text-muted-2 mb-4">
              Your payment method on file will be charged immediately.
            </p>
            {purchaseError && (
              <div className="mb-3 rounded-ctl border border-danger-soft bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
                {purchaseError}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                className="rounded-ctl border border-border px-4 py-2 text-sm font-medium text-muted hover:bg-canvas"
                onClick={() => { setConfirmTier(null); setPurchaseError('') }}
                disabled={purchasing}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50"
                onClick={handlePurchase}
                disabled={purchasing}
              >
                {purchasing ? 'Processing…' : 'Confirm Purchase'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
