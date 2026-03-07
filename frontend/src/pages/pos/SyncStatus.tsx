/**
 * Sync status dashboard showing pending/synced/failed transactions
 * with a force sync button.
 *
 * Validates: Requirement 22.7, 22.8 — POS sync status and conflict reporting
 */

import { useEffect, useState, useCallback } from 'react'
import { getAllTransactions } from '@/utils/posOfflineStore'
import { posSyncManager } from '@/utils/posSyncManager'
import type { OfflineTransaction } from './types'

interface SyncStatusProps {
  onClose: () => void
}

export default function SyncStatus({ onClose }: SyncStatusProps) {
  const [transactions, setTransactions] = useState<OfflineTransaction[]>([])
  const [syncing, setSyncing] = useState(false)
  const [loading, setLoading] = useState(true)

  const loadTransactions = useCallback(async () => {
    setLoading(true)
    try {
      const all = await getAllTransactions()
      setTransactions(all.sort((a, b) => b.timestamp.localeCompare(a.timestamp)))
    } catch {
      setTransactions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadTransactions() }, [loadTransactions])

  const pendingCount = transactions.filter((t) => t.syncStatus === 'pending').length
  const syncedCount = transactions.filter((t) => t.syncStatus === 'synced').length
  const failedCount = transactions.filter((t) => t.syncStatus === 'failed').length

  const handleForceSync = async () => {
    setSyncing(true)
    await posSyncManager.syncPendingTransactions()
    await loadTransactions()
    setSyncing(false)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="dialog" aria-label="Sync Status">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">Sync Status</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close sync status">✕</button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-3 px-6 py-4">
          <div className="text-center p-3 bg-yellow-50 rounded-lg">
            <p className="text-2xl font-bold text-yellow-600" data-testid="pending-count">{pendingCount}</p>
            <p className="text-xs text-yellow-700">Pending</p>
          </div>
          <div className="text-center p-3 bg-green-50 rounded-lg">
            <p className="text-2xl font-bold text-green-600" data-testid="synced-count">{syncedCount}</p>
            <p className="text-xs text-green-700">Synced</p>
          </div>
          <div className="text-center p-3 bg-red-50 rounded-lg">
            <p className="text-2xl font-bold text-red-600" data-testid="failed-count">{failedCount}</p>
            <p className="text-xs text-red-700">Failed</p>
          </div>
        </div>

        {/* Force sync button */}
        <div className="px-6 pb-3">
          <button
            onClick={handleForceSync}
            disabled={syncing || pendingCount === 0}
            className="w-full py-2 rounded-md bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50"
            aria-label="Force sync"
          >
            {syncing ? 'Syncing…' : `Sync ${pendingCount} Pending`}
          </button>
        </div>

        {/* Transaction list */}
        <div className="flex-1 overflow-y-auto px-6 pb-4">
          {loading && <p className="text-gray-500 text-sm" role="status" aria-label="Loading transactions">Loading…</p>}
          {!loading && transactions.length === 0 && (
            <p className="text-gray-400 text-sm text-center py-4">No offline transactions.</p>
          )}
          {!loading && transactions.length > 0 && (
            <table className="w-full text-sm" role="grid" aria-label="Transaction list">
              <thead>
                <tr className="text-left text-gray-500 border-b">
                  <th className="py-2">Time</th>
                  <th className="py-2">Total</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr key={tx.offlineId} className="border-b border-gray-100">
                    <td className="py-2">{new Date(tx.timestamp).toLocaleString()}</td>
                    <td className="py-2">${tx.total.toFixed(2)}</td>
                    <td className="py-2">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                        tx.syncStatus === 'synced' ? 'bg-green-100 text-green-700' :
                        tx.syncStatus === 'failed' ? 'bg-red-100 text-red-700' :
                        'bg-yellow-100 text-yellow-700'
                      }`}>
                        {tx.syncStatus}
                      </span>
                      {tx.syncError && (
                        <p className="text-xs text-red-500 mt-0.5">{tx.syncError}</p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
