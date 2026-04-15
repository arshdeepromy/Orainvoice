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
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p className={`mt-1 text-3xl font-semibold ${color}`}>
        {(value ?? 0).toLocaleString()}
      </p>
    </div>
  )

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Reconciliation</h1>
          <p className="text-sm text-gray-500 mt-1">
            Bank transaction matching overview
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/banking/accounts"
            className="rounded-md bg-white border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Bank Accounts
          </Link>
          <Link
            to="/banking/transactions"
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            View Transactions
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading summary" /></div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{error}</div>
      ) : !summary ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No reconciliation data available. Connect a bank account to get started.
        </div>
      ) : (
        <>
          {/* Status cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            {statCard('Total', summary?.total ?? 0, 'text-gray-900')}
            {statCard('Matched', summary?.matched ?? 0, 'text-green-700')}
            {statCard('Unmatched', summary?.unmatched ?? 0, 'text-yellow-700')}
            {statCard('Manual Review', summary?.manual ?? 0, 'text-blue-700')}
            {statCard('Excluded', summary?.excluded ?? 0, 'text-gray-500')}
          </div>

          {/* Last sync info */}
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">Sync Status</h2>
            <p className="text-sm text-gray-600">
              Last sync:{' '}
              {summary?.last_sync_at
                ? new Date(summary.last_sync_at).toLocaleString()
                : 'Never'}
            </p>
            {(summary?.unmatched ?? 0) > 0 && (
              <p className="mt-2 text-sm text-yellow-700">
                {summary?.unmatched ?? 0} transactions need attention.{' '}
                <Link to="/banking/transactions?status=unmatched" className="underline">
                  Review now →
                </Link>
              </p>
            )}
            {(summary?.manual ?? 0) > 0 && (
              <p className="mt-1 text-sm text-blue-700">
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
