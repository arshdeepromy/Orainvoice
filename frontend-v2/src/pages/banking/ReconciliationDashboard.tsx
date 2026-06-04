import { useState, useEffect, useCallback } from 'react'
import { Navigate, Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface ReconciliationSummary {
  unmatched: number
  matched: number
  excluded: number
  manual: number
  total: number
  last_sync_at: string | null
}

export default function ReconciliationDashboard() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [summary, setSummary] = useState<ReconciliationSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchSummary = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<ReconciliationSummary>(
        '/banking/reconciliation-summary',
        { signal },
      )
      setSummary(res.data ?? null)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setError('Failed to load reconciliation summary')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchSummary(controller.signal)
    return () => controller.abort()
  }, [fetchSummary])

  const statCard = (label: string, value: number, color: string) => (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <p className="text-sm font-medium text-muted">{label}</p>
      <p className={`mt-1 text-3xl font-semibold ${color}`}>
        {(value ?? 0).toLocaleString()}
      </p>
    </div>
  )

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Reconciliation</h1>
          <p className="mt-1 text-sm text-muted">
            Bank transaction matching overview
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/banking/accounts"
            className="rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas"
          >
            Bank Accounts
          </Link>
          <Link
            to="/banking/transactions"
            className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press"
          >
            View Transactions
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading summary" /></div>
      ) : error ? (
        <div className="rounded-card border border-danger-soft bg-danger-soft p-6 text-center text-danger">{error}</div>
      ) : !summary ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No reconciliation data available. Connect a bank account to get started.
        </div>
      ) : (
        <>
          {/* Status cards */}
          <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
            {statCard('Total', summary?.total ?? 0, 'text-text')}
            {statCard('Matched', summary?.matched ?? 0, 'text-ok')}
            {statCard('Unmatched', summary?.unmatched ?? 0, 'text-warn')}
            {statCard('Manual Review', summary?.manual ?? 0, 'text-accent')}
            {statCard('Excluded', summary?.excluded ?? 0, 'text-muted')}
          </div>

          {/* Last sync info */}
          <div className="rounded-card border border-border bg-card p-5 shadow-card">
            <h2 className="mb-2 text-sm font-semibold text-text">Sync Status</h2>
            <p className="text-sm text-muted">
              Last sync:{' '}
              {summary?.last_sync_at
                ? new Date(summary.last_sync_at).toLocaleString()
                : 'Never'}
            </p>
            {(summary?.unmatched ?? 0) > 0 && (
              <p className="mt-2 text-sm text-warn">
                {summary?.unmatched ?? 0} transactions need attention.{' '}
                <Link to="/banking/transactions?status=unmatched" className="underline">
                  Review now →
                </Link>
              </p>
            )}
            {(summary?.manual ?? 0) > 0 && (
              <p className="mt-1 text-sm text-accent">
                {summary?.manual ?? 0} transactions flagged for manual review.{' '}
                <Link to="/banking/transactions?status=manual" className="underline">
                  Review now →
                </Link>
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
