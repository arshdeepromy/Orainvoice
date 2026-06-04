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
      <div className="bg-card rounded-card shadow-pop w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-text">Sync Status</h2>
          <button onClick={onClose} className="text-muted hover:text-text" aria-label="Close sync status">✕</button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-3 px-6 py-4">
          <div className="text-center p-3 bg-warn-soft rounded-ctl">
            <p className="mono text-2xl font-bold text-warn" data-testid="pending-count">{pendingCount}</p>
            <p className="text-xs text-warn">Pending</p>
          </div>
          <div className="text-center p-3 bg-ok-soft rounded-ctl">
            <p className="mono text-2xl font-bold text-ok" data-testid="synced-count">{syncedCount}</p>
            <p className="text-xs text-ok">Synced</p>
          </div>
          <div className="text-center p-3 bg-danger-soft rounded-ctl">
            <p className="mono text-2xl font-bold text-danger" data-testid="failed-count">{failedCount}</p>
            <p className="text-xs text-danger">Failed</p>
          </div>
        </div>

        {/* Force sync button */}
        <div className="px-6 pb-3">
          <button
            onClick={handleForceSync}
            disabled={syncing || pendingCount === 0}
            className="w-full py-2 rounded-ctl bg-accent text-white font-medium hover:bg-accent-press disabled:opacity-50"
            aria-label="Force sync"
          >
            {syncing ? 'Syncing…' : `Sync ${pendingCount} Pending`}
          </button>
        </div>

        {/* Transaction list */}
        <div className="flex-1 overflow-y-auto px-6 pb-4">
          {loading && <p className="text-muted text-sm" role="status" aria-label="Loading transactions">Loading…</p>}
          {!loading && transactions.length === 0 && (
            <p className="text-muted-2 text-sm text-center py-4">No offline transactions.</p>
          )}
          {!loading && transactions.length > 0 && (
            <table className="w-full text-sm" role="grid" aria-label="Transaction list">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="py-2">Time</th>
                  <th className="py-2">Total</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr key={tx.offlineId} className="border-b border-border">
                    <td className="py-2 text-text">{new Date(tx.timestamp).toLocaleString()}</td>
                    <td className="mono py-2 text-text">${tx.total.toFixed(2)}</td>
                    <td className="py-2">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                        tx.syncStatus === 'synced' ? 'bg-ok-soft text-ok' :
                        tx.syncStatus === 'failed' ? 'bg-danger-soft text-danger' :
                        'bg-warn-soft text-warn'
                      }`}>
                        {tx.syncStatus}
                      </span>
                      {tx.syncError && (
                        <p className="text-xs text-danger mt-0.5">{tx.syncError}</p>
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
