import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface WalletLight {
  wallet_type: string
  balance: number
  obligation: number
  shortfall: number
  traffic_light: string
  next_due: string | null
}

interface TaxPositionData {
  currency: string
  gst_owing: number
  next_gst_due: string | null
  income_tax_estimate: number
  next_income_tax_due: string | null
  provisional_tax_amount: number
  gst_wallet_balance: number
  gst_shortfall: number
  gst_traffic_light: string
  income_tax_wallet_balance: number
  income_tax_shortfall: number
  income_tax_traffic_light: string
}

interface WalletSummaryData {
  currency: string
  wallets: WalletLight[]
  gst_wallet_balance: number
  gst_owing: number
  gst_shortfall: number
  income_tax_wallet_balance: number
  income_tax_estimate: number
  income_tax_shortfall: number
  next_gst_due: string | null
  next_income_tax_due: string | null
}

const fmt = (n: number) =>
  `${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const LIGHT_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  green: { bg: 'bg-ok-soft', text: 'text-ok', dot: 'bg-ok' },
  amber: { bg: 'bg-warn-soft', text: 'text-warn', dot: 'bg-warn' },
  red: { bg: 'bg-danger-soft', text: 'text-danger', dot: 'bg-danger' },
}

export default function TaxPosition() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [position, setPosition] = useState<TaxPositionData | null>(null)
  const [summary, setSummary] = useState<WalletSummaryData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const [posRes, sumRes] = await Promise.all([
        apiClient.get<TaxPositionData>('/reports/tax-position', { signal }),
        apiClient.get<WalletSummaryData>('/tax-wallets/summary', { signal }),
      ])
      setPosition(posRes.data ?? null)
      setSummary(sumRes.data ?? null)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setError('Failed to load tax position data')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  if (loading && !position) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    )
  }

  const renderLight = (light: string) => {
    const colors = LIGHT_COLORS[light] ?? LIGHT_COLORS.red
    return (
      <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${colors.bg} ${colors.text}`}>
        <span className={`h-2 w-2 rounded-full ${colors.dot}`} />
        {light.charAt(0).toUpperCase() + light.slice(1)}
      </span>
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <h1 className="text-2xl font-bold text-text">Tax Position Dashboard</h1>
      <p className="text-muted">
        Combined view of GST and income tax obligations with wallet coverage.
      </p>

      {error && (
        <div className="rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-danger">
          {error}
        </div>
      )}

      {position && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* GST Card */}
          <div className="rounded-card border border-border bg-card p-6 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-text">GST</h2>
              {renderLight(position?.gst_traffic_light ?? 'red')}
            </div>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-muted">GST Owing</span>
                <span className="mono font-medium text-text">{fmt(position?.gst_owing ?? 0)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Wallet Balance</span>
                <span className="mono font-medium text-ok">
                  {fmt(position?.gst_wallet_balance ?? 0)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Shortfall</span>
                <span className={`mono font-medium ${(position?.gst_shortfall ?? 0) > 0 ? 'text-danger' : 'text-ok'}`}>
                  {fmt(position?.gst_shortfall ?? 0)}
                </span>
              </div>
              {position?.next_gst_due && (
                <div className="flex justify-between border-t border-border pt-2">
                  <span className="text-muted">Next Due</span>
                  <span className="mono font-medium text-text">{position.next_gst_due}</span>
                </div>
              )}
            </div>
          </div>

          {/* Income Tax Card */}
          <div className="rounded-card border border-border bg-card p-6 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-text">Income Tax</h2>
              {renderLight(position?.income_tax_traffic_light ?? 'red')}
            </div>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-muted">Estimated Tax</span>
                <span className="mono font-medium text-text">{fmt(position?.income_tax_estimate ?? 0)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Wallet Balance</span>
                <span className="mono font-medium text-ok">
                  {fmt(position?.income_tax_wallet_balance ?? 0)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Shortfall</span>
                <span className={`mono font-medium ${(position?.income_tax_shortfall ?? 0) > 0 ? 'text-danger' : 'text-ok'}`}>
                  {fmt(position?.income_tax_shortfall ?? 0)}
                </span>
              </div>
              {position?.next_income_tax_due && (
                <div className="flex justify-between border-t border-border pt-2">
                  <span className="text-muted">Next Due</span>
                  <span className="mono font-medium text-text">{position.next_income_tax_due}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Wallet summary traffic lights */}
      {summary && (summary?.wallets ?? []).length > 0 && (
        <div className="rounded-card border border-border bg-card p-6 shadow-card">
          <h2 className="mb-4 text-lg font-semibold text-text">Wallet Coverage</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {(summary?.wallets ?? []).map((w) => {
              const pct = (w.obligation ?? 0) > 0
                ? Math.round(((w.balance ?? 0) / (w.obligation ?? 1)) * 100)
                : 100
              return (
                <div key={w.wallet_type} className="flex items-center gap-4 rounded-card border border-border p-3">
                  {renderLight(w.traffic_light ?? 'red')}
                  <div className="flex-1">
                    <div className="font-medium text-text">
                      {w.wallet_type === 'gst' ? 'GST' : 'Income Tax'}
                    </div>
                    <div className="mono text-sm text-muted">
                      {fmt(w.balance ?? 0)} of {fmt(w.obligation ?? 0)} ({pct}%)
                    </div>
                  </div>
                  {(w.shortfall ?? 0) > 0 && (
                    <div className="mono text-sm font-medium text-danger">
                      -{fmt(w.shortfall ?? 0)} shortfall
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
