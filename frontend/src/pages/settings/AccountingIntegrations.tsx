import { useState, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

type Provider = 'xero' | 'myob'

interface AccountingConnection {
  provider: Provider
  connected: boolean
  account_name: string | null
  connected_at: string | null
  last_sync_at: string | null
  sync_status: 'idle' | 'syncing' | 'success' | 'failed'
  error_message: string | null
}

export interface SyncLogEntry {
  id: string
  provider: Provider
  entity_type: 'invoice' | 'payment' | 'credit_note'
  entity_id: string
  entity_ref: string
  status: 'success' | 'failed'
  error_message: string | null
  synced_at: string
  [key: string]: unknown
}

interface AccountingData {
  xero: AccountingConnection
  myob: AccountingConnection
  sync_log: SyncLogEntry[]
}

/* ── Helpers ── */

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function providerLabel(provider: Provider): string {
  return provider === 'xero' ? 'Xero' : 'MYOB'
}

/* ── Connection Card ── */

function ConnectionCard({
  connection,
  onConnect,
  onDisconnect,
  connecting,
}: {
  connection: AccountingConnection
  onConnect: () => void
  onDisconnect: () => void
  connecting: boolean
}) {
  const label = providerLabel(connection.provider)

  const statusBadge = (() => {
    if (!connection.connected) return { variant: 'neutral' as const, text: 'Not connected' }
    switch (connection.sync_status) {
      case 'syncing':
        return { variant: 'info' as const, text: 'Syncing' }
      case 'success':
        return { variant: 'success' as const, text: 'Connected' }
      case 'failed':
        return { variant: 'error' as const, text: 'Sync failed' }
      default:
        return { variant: 'success' as const, text: 'Connected' }
    }
  })()

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900">{label}</h3>
        <Badge variant={statusBadge.variant}>{statusBadge.text}</Badge>
      </div>

      {connection.connected ? (
        <>
          {connection.account_name && (
            <p className="text-sm text-gray-600 mb-1">
              Account: <span className="font-medium text-gray-900">{connection.account_name}</span>
            </p>
          )}
          <p className="text-sm text-gray-600 mb-1">
            Connected: {formatDate(connection.connected_at)}
          </p>
          <p className="text-sm text-gray-600 mb-3">
            Last sync: {formatDate(connection.last_sync_at)}
          </p>

          {connection.sync_status === 'failed' && connection.error_message && (
            <AlertBanner variant="error" title="Sync error" className="mb-3">
              {connection.error_message}
            </AlertBanner>
          )}

          <Button variant="danger" size="sm" onClick={onDisconnect}>
            Disconnect {label}
          </Button>
        </>
      ) : (
        <>
          <p className="text-sm text-gray-600 mb-3">
            Connect your {label} account to automatically sync invoices, payments, and credit notes.
          </p>
          <Button onClick={onConnect} loading={connecting}>
            Connect {label}
          </Button>
        </>
      )}
    </div>
  )
}

/* ── Sync Log Table ── */

function SyncLog({
  entries,
  onRetry,
  retrying,
}: {
  entries: SyncLogEntry[]
  onRetry: (entry: SyncLogEntry) => void
  retrying: string | null
}) {
  const columns: Column<SyncLogEntry>[] = [
    {
      key: 'synced_at',
      header: 'Time',
      sortable: true,
      render: (row) => formatDate(row.synced_at),
    },
    {
      key: 'provider',
      header: 'Provider',
      render: (row) => providerLabel(row.provider),
    },
    {
      key: 'entity_type',
      header: 'Type',
      render: (row) => row.entity_type.replace('_', ' '),
    },
    {
      key: 'entity_ref',
      header: 'Reference',
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <Badge variant={row.status === 'success' ? 'success' : 'error'}>
          {row.status}
        </Badge>
      ),
    },
    {
      key: 'id',
      header: 'Action',
      render: (row) =>
        row.status === 'failed' ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onRetry(row)}
            loading={retrying === row.id}
          >
            Retry
          </Button>
        ) : null,
    },
  ]

  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 mb-3">Recent sync activity</h3>
      {entries.length === 0 ? (
        <p className="text-sm text-gray-500">No sync activity yet. Connect an accounting provider to get started.</p>
      ) : (
        <DataTable columns={columns} data={entries} keyField="id" caption="Accounting sync log" />
      )}
    </div>
  )
}

/* ── Main Page ── */

export function AccountingIntegrations() {
  const [data, setData] = useState<AccountingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [connecting, setConnecting] = useState<Provider | null>(null)
  const [retrying, setRetrying] = useState<string | null>(null)
  const { toasts, addToast, dismissToast } = useToast()
  const oauthCheckedRef = useRef(false)

  // Show success/error toast if redirected from OAuth callback (run once)
  useEffect(() => {
    if (oauthCheckedRef.current) return
    const params = new URLSearchParams(window.location.search)
    const connected = params.get('connected')
    const error = params.get('error')
    if (connected) {
      oauthCheckedRef.current = true
      addToast('success', `${providerLabel(connected as Provider)} connected successfully`)
      window.history.replaceState({}, '', window.location.pathname)
    }
    if (error) {
      oauthCheckedRef.current = true
      addToast('error', `Connection failed: ${error}`)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [addToast])

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<AccountingData>('/org/accounting/')
      console.log('Accounting data response:', res.data)
      setData(res.data)
    } catch (err) {
      console.error('Accounting fetch error:', err)
      addToast('error', 'Failed to load accounting integration settings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const handleConnect = async (provider: Provider) => {
    setConnecting(provider)
    try {
      const { data: oauthData } = await apiClient.post<{ authorization_url: string }>(
        `/org/accounting/connect/${provider}`,
      )
      window.location.href = oauthData.authorization_url
    } catch {
      addToast('error', `Failed to start ${providerLabel(provider)} connection`)
      setConnecting(null)
    }
  }

  const handleDisconnect = async (provider: Provider) => {
    try {
      await apiClient.post(`/org/accounting/disconnect/${provider}`)
      addToast('success', `${providerLabel(provider)} disconnected`)
      fetchData()
    } catch {
      addToast('error', `Failed to disconnect ${providerLabel(provider)}`)
    }
  }

  const handleRetry = async (entry: SyncLogEntry) => {
    setRetrying(entry.id)
    try {
      await apiClient.post(`/org/accounting/sync/${entry.id}/retry`)
      addToast('success', `Retry queued for ${entry.entity_ref}`)
      fetchData()
    } catch {
      addToast('error', `Failed to retry sync for ${entry.entity_ref}`)
    } finally {
      setRetrying(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading accounting integrations" />
      </div>
    )
  }

  if (!data) {
    return (
      <AlertBanner variant="error" title="Something went wrong">
        We couldn't load your accounting integration settings. Please refresh the page or try again later.
      </AlertBanner>
    )
  }

  const hasFailedSyncs = data.sync_log.some((e) => e.status === 'failed')

  const handleRetryAll = async (provider: Provider) => {
    setRetrying('all')
    try {
      const res = await apiClient.post<{ synced: number; failed: number; message: string }>(
        `/org/accounting/sync/${provider}`,
      )
      const result = res.data
      if ((result?.synced ?? 0) > 0) {
        addToast('success', result?.message ?? 'Retry complete')
      } else {
        addToast('info', result?.message ?? 'No failed syncs to retry')
      }
      fetchData()
    } catch {
      addToast('error', `Failed to retry syncs for ${providerLabel(provider)}`)
    } finally {
      setRetrying(null)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Accounting integrations</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-6 max-w-3xl">
        {hasFailedSyncs && (
          <AlertBanner variant="warning" title="Sync failures detected">
            Some records failed to sync. Check the activity log below and retry failed items.
          </AlertBanner>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ConnectionCard
            connection={data.xero}
            onConnect={() => handleConnect('xero')}
            onDisconnect={() => handleDisconnect('xero')}
            connecting={connecting === 'xero'}
          />
          <ConnectionCard
            connection={data.myob}
            onConnect={() => handleConnect('myob')}
            onDisconnect={() => handleDisconnect('myob')}
            connecting={connecting === 'myob'}
          />
        </div>

        <SyncLog entries={data.sync_log} onRetry={handleRetry} retrying={retrying} />

        {hasFailedSyncs && (
          <div className="flex gap-3">
            {data.xero.connected && (
              <Button
                variant="secondary"
                size="sm"
                loading={retrying === 'all'}
                onClick={() => handleRetryAll('xero')}
              >
                Retry all failed (Xero)
              </Button>
            )}
            {data.myob.connected && (
              <Button
                variant="secondary"
                size="sm"
                loading={retrying === 'all'}
                onClick={() => handleRetryAll('myob')}
              >
                Retry all failed (MYOB)
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
