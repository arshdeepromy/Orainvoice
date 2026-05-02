import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate } from './portalFormatters'

interface LoyaltyTier {
  name: string
  threshold_points: number
  discount_percent: number
}

interface LoyaltyTransaction {
  transaction_type: string
  points: number
  balance_after: number
  reference_type: string | null
  created_at: string
}

interface LoyaltyData {
  programme_configured: boolean
  total_points: number
  current_tier: LoyaltyTier | null
  next_tier: LoyaltyTier | null
  points_to_next_tier: number | null
  transactions: LoyaltyTransaction[]
}

interface LoyaltyBalanceProps {
  token: string
}

export function LoyaltyBalance({ token }: LoyaltyBalanceProps) {
  const locale = usePortalLocale()
  const [data, setData] = useState<LoyaltyData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchLoyalty = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/portal/${token}/loyalty`)
      setData(res.data)
    } catch {
      setError('Failed to load loyalty information.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { fetchLoyalty() }, [fetchLoyalty])

  if (loading) return <div className="py-8"><Spinner label="Loading loyalty" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (!data) return null

  // Req 61.1: No loyalty programme configured for this org
  if (!data.programme_configured) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-gray-500">This business does not have a loyalty programme.</p>
      </div>
    )
  }

  // Req 61.2: Programme exists but customer has zero balance
  if ((data.total_points ?? 0) === 0 && (data.transactions ?? []).length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-lg font-semibold text-gray-900">You have 0 points</p>
        <p className="mt-2 text-sm text-gray-500">
          Earn points by paying invoices and using services. Points are awarded automatically when invoices are paid.
        </p>
      </div>
    )
  }

  const progressPercent = data.next_tier && data.points_to_next_tier != null
    ? Math.min(100, ((data.total_points / data.next_tier.threshold_points) * 100))
    : 100

  return (
    <div>
      {/* Points summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 mb-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Points Balance</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 tabular-nums">
            {(data.total_points ?? 0).toLocaleString()}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Current Tier</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">
            {data.current_tier?.name ?? 'None'}
          </p>
          {data.current_tier && data.current_tier.discount_percent > 0 && (
            <p className="text-xs text-green-600 mt-1">
              {data.current_tier.discount_percent}% discount
            </p>
          )}
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Next Tier</p>
          {data.next_tier ? (
            <>
              <p className="mt-1 text-xl font-semibold text-gray-900">{data.next_tier.name}</p>
              <p className="text-xs text-gray-400 mt-1">
                {data.points_to_next_tier?.toLocaleString()} points to go
              </p>
            </>
          ) : (
            <p className="mt-1 text-sm text-gray-400">You're at the top!</p>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {data.next_tier && (
        <div className="mb-6">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>{data.current_tier?.name ?? 'Start'}</span>
            <span>{data.next_tier.name}</span>
          </div>
          <div className="h-2 rounded-full bg-gray-200">
            <div
              className="h-2 rounded-full transition-all"
              style={{ width: `${progressPercent}%`, backgroundColor: 'var(--portal-accent, #3b82f6)' }}
            />
          </div>
        </div>
      )}

      {/* Transaction history */}
      {data.transactions.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Transaction History</h4>
          <div className="space-y-2">
            {data.transactions.map((tx, i) => (
              <div key={i} className="flex items-center justify-between rounded border border-gray-100 bg-white px-4 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge variant={tx.points > 0 ? 'success' : 'warning'}>
                    {tx.transaction_type}
                  </Badge>
                  {tx.reference_type && (
                    <span className="text-gray-400 text-xs">{tx.reference_type}</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className={`font-medium tabular-nums ${tx.points > 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {tx.points > 0 ? '+' : ''}{tx.points}
                  </span>
                  <span className="text-xs text-gray-400">{formatDate(tx.created_at, locale)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
