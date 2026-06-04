/**
 * WooCommerce Setup page — connection form and sync log.
 *
 * Validates: Requirement — Ecommerce Module, Task 39.13
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'

interface SyncLogEntry {
  id: string
  direction: string
  entity_type: string
  entity_id: string | null
  status: string
  error_details: string | null
  retry_count: number
  created_at: string
}

interface ConnectionForm {
  store_url: string
  consumer_key: string
  consumer_secret: string
  sync_frequency_minutes: number
  auto_create_invoices: boolean
}

const headerCell =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const inputClass =
  'min-h-[44px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent'
const labelClass = 'mb-1 block text-sm font-medium text-text'

export default function WooCommerceSetup() {
  const [form, setForm] = useState<ConnectionForm>({
    store_url: '',
    consumer_key: '',
    consumer_secret: '',
    sync_frequency_minutes: 15,
    auto_create_invoices: true,
  })
  const [connected, setConnected] = useState(false)
  const [syncLogs, setSyncLogs] = useState<SyncLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)

  const fetchSyncLog = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/ecommerce/sync-log')
      setSyncLogs(res.data?.logs ?? [])
    } catch {
      // ignore — sync log may be empty
    }
  }, [])

  useEffect(() => {
    setLoading(false)
    fetchSyncLog()
  }, [fetchSyncLog])

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await apiClient.post('/api/v2/ecommerce/woocommerce/connect', form)
      setConnected(true)
      fetchSyncLog()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to connect')
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      await apiClient.post('/api/v2/ecommerce/woocommerce/sync')
      fetchSyncLog()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  if (loading) {
    return <div role="status" aria-label="Loading WooCommerce setup" className="py-12 text-center text-sm text-muted">Loading…</div>
  }

  return (
    <div className="space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-text">WooCommerce Setup</h1>

      {error && <div role="alert" className="rounded-ctl bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {!connected ? (
        <form onSubmit={handleConnect} aria-label="Connect WooCommerce store" className="max-w-lg space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <div>
            <label htmlFor="store_url" className={labelClass}>Store URL</label>
            <input
              id="store_url"
              type="url"
              required
              value={form.store_url}
              onChange={(e) => setForm({ ...form, store_url: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="consumer_key" className={labelClass}>Consumer Key</label>
            <input
              id="consumer_key"
              type="text"
              required
              value={form.consumer_key}
              onChange={(e) => setForm({ ...form, consumer_key: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="consumer_secret" className={labelClass}>Consumer Secret</label>
            <input
              id="consumer_secret"
              type="password"
              required
              value={form.consumer_secret}
              onChange={(e) => setForm({ ...form, consumer_secret: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="sync_frequency" className={labelClass}>Sync Frequency (minutes)</label>
            <input
              id="sync_frequency"
              type="number"
              min={15}
              value={form.sync_frequency_minutes}
              onChange={(e) => setForm({ ...form, sync_frequency_minutes: Number(e.target.value) })}
              className={inputClass}
            />
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={form.auto_create_invoices}
                onChange={(e) => setForm({ ...form, auto_create_invoices: e.target.checked })}
              />
              Auto-create invoices from orders
            </label>
          </div>
          <Button type="submit">Connect Store</Button>
        </form>
      ) : (
        <div className="space-y-3 rounded-card border border-border bg-card p-4 shadow-card">
          <p className="text-sm text-text">Connected to WooCommerce store</p>
          <Button onClick={handleSync} disabled={syncing} loading={syncing}>
            {syncing ? 'Syncing…' : 'Trigger Sync'}
          </Button>
        </div>
      )}

      <h2 className="text-base font-semibold text-text">Sync Log</h2>
      {syncLogs.length === 0 ? (
        <p className="text-sm text-muted">No sync activity yet</p>
      ) : (
        <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table role="grid" aria-label="Sync log" className="w-full text-sm">
            <thead>
              <tr>
                <th className={headerCell}>Direction</th>
                <th className={headerCell}>Type</th>
                <th className={headerCell}>Status</th>
                <th className={headerCell}>Retries</th>
                <th className={headerCell}>Date</th>
                <th className={headerCell}>Error</th>
              </tr>
            </thead>
            <tbody>
              {syncLogs.map((log) => (
                <tr key={log.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3 text-text">{log.direction}</td>
                  <td className="px-4 py-3 text-text">{log.entity_type}</td>
                  <td className="px-4 py-3 text-text">{log.status}</td>
                  <td className="mono px-4 py-3 text-text">{log.retry_count}</td>
                  <td className="mono px-4 py-3 text-text">{new Date(log.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-text">{log.error_details ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
