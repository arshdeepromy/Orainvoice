/**
 * WooCommerce Setup page — connection form and sync log.
 *
 * Validates: Requirement — Ecommerce Module, Task 39.13
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

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
    return <div role="status" aria-label="Loading WooCommerce setup">Loading…</div>
  }

  return (
    <div>
      <h1>WooCommerce Setup</h1>

      {error && <div role="alert">{error}</div>}

      {!connected ? (
        <form onSubmit={handleConnect} aria-label="Connect WooCommerce store">
          <div>
            <label htmlFor="store_url">Store URL</label>
            <input
              id="store_url"
              type="url"
              required
              value={form.store_url}
              onChange={(e) => setForm({ ...form, store_url: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="consumer_key">Consumer Key</label>
            <input
              id="consumer_key"
              type="text"
              required
              value={form.consumer_key}
              onChange={(e) => setForm({ ...form, consumer_key: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="consumer_secret">Consumer Secret</label>
            <input
              id="consumer_secret"
              type="password"
              required
              value={form.consumer_secret}
              onChange={(e) => setForm({ ...form, consumer_secret: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="sync_frequency">Sync Frequency (minutes)</label>
            <input
              id="sync_frequency"
              type="number"
              min={15}
              value={form.sync_frequency_minutes}
              onChange={(e) => setForm({ ...form, sync_frequency_minutes: Number(e.target.value) })}
            />
          </div>
          <div>
            <label>
              <input
                type="checkbox"
                checked={form.auto_create_invoices}
                onChange={(e) => setForm({ ...form, auto_create_invoices: e.target.checked })}
              />
              Auto-create invoices from orders
            </label>
          </div>
          <button type="submit">Connect Store</button>
        </form>
      ) : (
        <div>
          <p>Connected to WooCommerce store</p>
          <button onClick={handleSync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Trigger Sync'}
          </button>
        </div>
      )}

      <h2>Sync Log</h2>
      {syncLogs.length === 0 ? (
        <p>No sync activity yet</p>
      ) : (
        <table role="grid" aria-label="Sync log">
          <thead>
            <tr>
              <th>Direction</th>
              <th>Type</th>
              <th>Status</th>
              <th>Retries</th>
              <th>Date</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {syncLogs.map((log) => (
              <tr key={log.id}>
                <td>{log.direction}</td>
                <td>{log.entity_type}</td>
                <td>{log.status}</td>
                <td>{log.retry_count}</td>
                <td>{new Date(log.created_at).toLocaleString()}</td>
                <td>{log.error_details ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
