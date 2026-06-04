import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface BankAccount {
  id: string
  akahu_account_id: string
  account_name: string
  account_number: string | null
  bank_name: string | null
  account_type: string | null
  balance: number
  currency: string
  is_active: boolean
  last_refreshed_at: string | null
  linked_gl_account_id: string | null
}

interface GLAccount {
  id: string
  code: string
  name: string
}

const fmt = (n: number) =>
  `${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

export default function BankAccounts() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [accounts, setAccounts] = useState<BankAccount[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState('')
  const [glAccounts, setGlAccounts] = useState<GLAccount[]>([])
  const [linkingId, setLinkingId] = useState<string | null>(null)
  const [selectedGl, setSelectedGl] = useState('')

  const fetchAccounts = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ items: BankAccount[]; total: number }>(
        '/banking/accounts',
        { signal },
      )
      setAccounts(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setError('Failed to load bank accounts')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchGlAccounts = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<{ items: GLAccount[]; total: number }>(
        '/ledger/accounts',
        { params: { account_type: 'asset', is_active: true }, signal },
      )
      setGlAccounts(res.data?.items ?? [])
    } catch {
      // Non-critical
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchAccounts(controller.signal)
    fetchGlAccounts(controller.signal)
    return () => controller.abort()
  }, [fetchAccounts, fetchGlAccounts])

  const handleSync = async () => {
    setSyncing(true)
    setSyncResult('')
    try {
      const res = await apiClient.post<{
        accounts_synced: number
        transactions_synced: number
        auto_matched: number
      }>('/banking/sync')
      setSyncResult(
        `Synced ${res.data?.accounts_synced ?? 0} accounts, ` +
        `${res.data?.transactions_synced ?? 0} transactions, ` +
        `${res.data?.auto_matched ?? 0} auto-matched`,
      )
      fetchAccounts()
    } catch {
      setSyncResult('Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const handleLink = async (accountId: string) => {
    if (!selectedGl) return
    try {
      await apiClient.post(`/banking/accounts/${accountId}/link`, {
        linked_gl_account_id: selectedGl,
      })
      setLinkingId(null)
      setSelectedGl('')
      fetchAccounts()
    } catch {
      setError('Failed to link account')
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Bank Accounts</h1>
          <p className="mt-1 text-sm text-muted">{total} connected accounts</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSync}
            disabled={syncing}
            className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50"
          >
            {syncing ? 'Syncing…' : '↻ Sync Now'}
          </button>
          <a
            href="/api/v1/banking/connect"
            className="rounded-ctl bg-ok px-4 py-2 text-sm font-medium text-white hover:brightness-95"
          >
            + Connect Bank
          </a>
        </div>
      </div>

      {syncResult && (
        <div className="mb-4 rounded-ctl border border-border bg-accent-soft p-3 text-sm text-accent">
          {syncResult}
        </div>
      )}

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading accounts" /></div>
      ) : error ? (
        <div className="rounded-card border border-danger-soft bg-danger-soft p-6 text-center text-danger">{error}</div>
      ) : (accounts ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No bank accounts connected. Click "Connect Bank" to get started.
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Account</th>
                <th className={TH}>Bank</th>
                <th className={TH}>Type</th>
                <th className={TH_RIGHT}>Balance</th>
                <th className={TH}>GL Link</th>
                <th className={TH}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(accounts ?? []).map(acct => (
                <tr key={acct.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-text">{acct.account_name}</div>
                    <div className="mono text-xs text-muted">{acct.account_number ?? '—'}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-text">{acct.bank_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-text">{acct.account_type ?? '—'}</td>
                  <td className="mono px-4 py-3 text-right text-sm text-text">
                    {fmt(acct.balance ?? 0)}
                  </td>
                  <td className="px-4 py-3 text-sm text-text">
                    {acct.linked_gl_account_id ? (
                      <span className="text-ok">✓ Linked</span>
                    ) : (
                      <span className="text-muted-2">Not linked</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {linkingId === acct.id ? (
                      <div className="flex items-center gap-1">
                        <select
                          value={selectedGl}
                          onChange={e => setSelectedGl(e.target.value)}
                          className="rounded-ctl border border-border bg-card px-2 py-1 text-xs text-text focus:border-accent focus:outline-none"
                        >
                          <option value="">Select GL…</option>
                          {(glAccounts ?? []).map(gl => (
                            <option key={gl.id} value={gl.id}>{gl.code} — {gl.name}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => handleLink(acct.id)}
                          className="rounded-ctl bg-accent px-2 py-1 text-xs text-white hover:bg-accent-press"
                        >
                          Link
                        </button>
                        <button
                          onClick={() => { setLinkingId(null); setSelectedGl('') }}
                          className="rounded-ctl bg-canvas px-2 py-1 text-xs text-text hover:bg-border"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setLinkingId(acct.id)}
                        className="text-xs text-accent hover:underline"
                      >
                        Link to GL
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
