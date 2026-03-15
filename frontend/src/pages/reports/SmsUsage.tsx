import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface SmsUsageData {
  total_sent: number
  included_in_plan: number
  package_credits_remaining: number
  effective_quota: number
  overage_count: number
  overage_charge_nzd: number
  per_sms_cost_nzd: number
  reset_at: string | null
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

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * SMS usage report — sent count, included quota, overage, packages, and daily breakdown.
 * Requirements: 7.1, 7.2, 7.3
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

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [usageRes, pkgRes] = await Promise.all([
        apiClient.get<SmsUsageData>('/reports/sms-usage', {
          params: { start_date: range.from, end_date: range.to },
        }),
        apiClient.get<SmsPackage[]>('/org/sms-packages'),
      ])
      setData(usageRes.data)
      setPackages(pkgRes.data)
    } catch {
      setError('Failed to load SMS usage report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  const fetchTiers = useCallback(async () => {
    try {
      const res = await apiClient.get<{ sms_package_pricing?: SmsPackageTier[] }>('/org/sms-usage')
      // Tiers come from the plan; fall back to empty if not present
      if (res.data && Array.isArray((res.data as Record<string, unknown>).sms_package_pricing)) {
        setTiers((res.data as Record<string, unknown>).sms_package_pricing as SmsPackageTier[])
      }
    } catch {
      // Tiers are optional — silently ignore
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => { fetchTiers() }, [fetchTiers])

  const handlePurchase = async () => {
    if (!confirmTier) return
    setPurchasing(true)
    setPurchaseError('')
    try {
      await apiClient.post('/org/sms-packages/purchase', { tier_name: confirmTier.tier_name })
      setConfirmTier(null)
      fetchData()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPurchaseError(msg || 'Purchase failed. Please try again.')
    } finally {
      setPurchasing(false)
    }
  }

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4 no-print">SMS usage, overage charges, and package credits.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/sms-usage" params={{ start_date: range.from, end_date: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading SMS usage report" /></div>}

      {!loading && data && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total SMS Sent</p>
              <p className="text-2xl font-semibold text-gray-900">{data.total_sent}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Included in Plan</p>
              <p className="text-2xl font-semibold text-gray-900">{data.included_in_plan}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Overage Count</p>
              <p className="text-2xl font-semibold text-amber-600">{data.overage_count}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Overage Charge</p>
              <p className="text-2xl font-semibold text-red-600">{fmt(data.overage_charge_nzd)}</p>
            </div>
          </div>

          {/* Daily breakdown bar chart */}
          {data.daily_breakdown && data.daily_breakdown.length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
              <h3 className="text-sm font-medium text-gray-700 mb-3">Daily SMS Sent</h3>
              <SimpleBarChart
                title="Daily SMS sent"
                items={data.daily_breakdown.map((d) => ({
                  label: new Date(d.date).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }),
                  value: d.sms_count,
                }))}
              />
            </div>
          )}

          {/* Active SMS packages */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Active SMS Packages</h3>
            {packages.length === 0 ? (
              <p className="text-sm text-gray-500">No active SMS packages.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-2 pr-4 font-medium text-gray-600">Package</th>
                      <th className="text-right py-2 pr-4 font-medium text-gray-600">Purchased</th>
                      <th className="text-right py-2 pr-4 font-medium text-gray-600">Credits Remaining</th>
                      <th className="text-right py-2 font-medium text-gray-600">Price Paid</th>
                    </tr>
                  </thead>
                  <tbody>
                    {packages.map((pkg) => (
                      <tr key={pkg.id} className="border-b border-gray-100">
                        <td className="py-2 pr-4 text-gray-900">{pkg.tier_name}</td>
                        <td className="py-2 pr-4 text-right text-gray-600">
                          {new Date(pkg.purchased_at).toLocaleDateString('en-NZ')}
                        </td>
                        <td className="py-2 pr-4 text-right text-gray-900">
                          {pkg.credits_remaining} / {pkg.sms_quantity}
                        </td>
                        <td className="py-2 text-right text-gray-600">{fmt(pkg.price_nzd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Purchase SMS packages */}
          {tiers.length > 0 && (
            <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
              <h3 className="text-sm font-medium text-gray-700 mb-3">Purchase SMS Package</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {tiers.map((tier) => (
                  <div
                    key={tier.tier_name}
                    className="rounded-lg border border-gray-200 p-4 flex flex-col items-center gap-2"
                  >
                    <p className="font-medium text-gray-900">{tier.tier_name}</p>
                    <p className="text-sm text-gray-600">{tier.sms_quantity} SMS credits</p>
                    <p className="text-lg font-semibold text-gray-900">{fmt(tier.price_nzd)}</p>
                    <button
                      type="button"
                      className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
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
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Confirm Purchase</h3>
            <p className="text-sm text-gray-600 mb-4">
              Purchase <span className="font-medium">{confirmTier.tier_name}</span> ({confirmTier.sms_quantity} SMS credits) for{' '}
              <span className="font-medium">{fmt(confirmTier.price_nzd)}</span>?
            </p>
            <p className="text-xs text-gray-500 mb-4">
              Your payment method on file will be charged immediately.
            </p>
            {purchaseError && (
              <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {purchaseError}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                onClick={() => { setConfirmTier(null); setPurchaseError('') }}
                disabled={purchasing}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
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
