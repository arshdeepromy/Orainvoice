/**
 * Sync manager for POS offline transactions.
 * Detects connectivity changes, syncs pending transactions in chronological order,
 * and handles conflict reports from the server.
 *
 * Validates: Requirement 22.7, 22.8 — POS offline sync and conflict handling
 */

import apiClient from '@/api/client'
import {
  getPendingTransactions,
  markSynced,
  markFailed,
} from './posOfflineStore'
import type { SyncReport } from '@/pages/pos/types'

export type SyncState = 'idle' | 'syncing' | 'error'

type SyncListener = (state: SyncState, pendingCount: number) => void

class POSSyncManager {
  private listeners: Set<SyncListener> = new Set()
  private state: SyncState = 'idle'
  private syncing = false

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('online', () => this.onOnline())
    }
  }

  subscribe(listener: SyncListener): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private notify(pendingCount: number) {
    this.listeners.forEach((fn) => fn(this.state, pendingCount))
  }

  private async onOnline() {
    await this.syncPendingTransactions()
  }

  isOnline(): boolean {
    return typeof navigator !== 'undefined' ? navigator.onLine : true
  }

  async syncPendingTransactions(): Promise<SyncReport | null> {
    if (this.syncing || !this.isOnline()) return null

    this.syncing = true
    this.state = 'syncing'
    this.notify(0)

    try {
      const pending = await getPendingTransactions()
      if (pending.length === 0) {
        this.state = 'idle'
        this.notify(0)
        return null
      }

      // Sort chronologically
      const sorted = [...pending].sort((a, b) => a.timestamp.localeCompare(b.timestamp))

      // Send batch to server
      const payload = sorted.map((tx) => ({
        offline_transaction_id: tx.offlineId,
        timestamp: tx.timestamp,
        line_items: tx.lineItems.map((li) => ({
          product_id: li.productId,
          product_name: li.productName,
          quantity: li.quantity,
          unit_price: li.unitPrice,
          discount_percent: li.discountPercent,
          discount_amount: li.discountAmount,
        })),
        payment_method: tx.paymentMethod,
        subtotal: tx.subtotal,
        tax_amount: tx.taxAmount,
        discount_amount: tx.discountAmount,
        tip_amount: tx.tipAmount,
        total: tx.total,
        cash_tendered: tx.cashTendered,
        change_given: tx.changeGiven,
        customer_id: tx.customerId,
        table_id: tx.tableId,
      }))

      const res = await apiClient.post('/api/v2/pos/transactions/sync', { transactions: payload })
      const report: SyncReport = res.data

      // Mark successes
      for (const success of report.successes) {
        await markSynced(success.offlineId)
      }

      // Mark conflicts as failed
      for (const conflict of report.conflicts) {
        await markFailed(conflict.offlineId, conflict.reason)
      }

      // Mark errors as failed
      for (const error of report.errors) {
        await markFailed(error.offlineId, error.error)
      }

      this.state = 'idle'
      const remaining = await getPendingTransactions()
      this.notify(remaining.length)
      return report
    } catch {
      this.state = 'error'
      const remaining = await getPendingTransactions()
      this.notify(remaining.length)
      return null
    } finally {
      this.syncing = false
    }
  }
}

// Singleton instance
export const posSyncManager = new POSSyncManager()
