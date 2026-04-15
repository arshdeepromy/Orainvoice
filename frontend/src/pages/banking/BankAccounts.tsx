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
  `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

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
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Bank Accounts</h1>
          <p className="text-sm text-gray-500 mt-1">{total} connected accounts</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSync}
            disabled={syncing}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {syncing ? 'Syncing…' : '↻ Sync Now'}
          </button>
          <a
            href="/api/v1/banking/connect"
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
          >
            + Connect Bank
          </a>
        </div>
      </div>

      {syncResult && (
        <div className="mb-4 rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-700">
          {syncResult}
        </div>
      )}

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading accounts" /></div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{error}</div>
      ) : (accounts ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No bank accounts connected. Click "Connect Bank" to get started.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Account</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Bank</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Balance</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">GL Link</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(accounts ?? []).map(acct => (
                <tr key={acct.id}>
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-gray-900">{acct.account_name}</div>
                    <div className="text-xs text-gray-500">{acct.account_number ?? '—'}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-700">{acct.bank_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{acct.account_type ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-right font-mono text-gray-900">
                    {fmt(acct.balance ?? 0)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-700">
                    {acct.linked_gl_account_id ? (
                      <span className="text-green-600">✓ Linked</span>
                    ) : (
                      <span className="text-gray-400">Not linked</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {linkingId === acct.id ? (
                      <div className="flex gap-1 items-center">
                        <select
                          value={selectedGl}
                          onChange={e => setSelectedGl(e.target.value)}
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                        >
                          <option value="">Select GL…</option>
                          {(glAccounts ?? []).map(gl => (
                            <option key={gl.id} value={gl.id}>{gl.code} — {gl.name}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => handleLink(acct.id)}
                          className="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700"
                        >
                          Link
                        </button>
                        <button
                          onClick={() => { setLinkingId(null); setSelectedGl('') }}
                          className="rounded bg-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-300"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setLinkingId(acct.id)}
                        className="text-xs text-blue-600 hover:text-blue-800"
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
