import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface TaxWallet {
  id: string
  wallet_type: string
  balance: number
  target_balance: number | null
  created_at: string
  updated_at: string
}

interface WalletTransaction {
  id: string
  wallet_id: string
  amount: number
  transaction_type: string
  source_payment_id: string | null
  description: string | null
  created_by: string | null
  created_at: string
}

const fmt = (n: number) =>
  `${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const WALLET_LABELS: Record<string, string> = {
  gst: 'GST',
  income_tax: 'Income Tax',
  provisional_tax: 'Provisional Tax',
}

const TX_TYPE_LABELS: Record<string, string> = {
  auto_sweep: 'Auto Sweep',
  manual_deposit: 'Manual Deposit',
  manual_withdrawal: 'Manual Withdrawal',
  tax_payment: 'Tax Payment',
}

export default function TaxWallets() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [wallets, setWallets] = useState<TaxWallet[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedWallet, setSelectedWallet] = useState<string | null>(null)
  const [transactions, setTransactions] = useState<WalletTransaction[]>([])
  const [txLoading, setTxLoading] = useState(false)

  // Deposit/withdraw form state
  const [actionType, setActionType] = useState<'deposit' | 'withdraw' | null>(null)
  const [actionWallet, setActionWallet] = useState<string>('')
  const [actionAmount, setActionAmount] = useState('')
  const [actionDesc, setActionDesc] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState('')
  const [actionSuccess, setActionSuccess] = useState('')

  const fetchWallets = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ items: TaxWallet[]; total: number }>(
        '/tax-wallets',
        { signal },
      )
      setWallets(res.data?.items ?? [])
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setError('Failed to load tax wallets')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchTransactions = useCallback(async (walletType: string, signal?: AbortSignal) => {
    setTxLoading(true)
    try {
      const res = await apiClient.get<{ items: WalletTransaction[]; total: number }>(
        `/tax-wallets/${walletType}/transactions`,
        { signal },
      )
      setTransactions(res.data?.items ?? [])
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setTransactions([])
      }
    } finally {
      setTxLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchWallets(controller.signal)
    return () => controller.abort()
  }, [fetchWallets])

  useEffect(() => {
    if (!selectedWallet) return
    const controller = new AbortController()
    fetchTransactions(selectedWallet, controller.signal)
    return () => controller.abort()
  }, [selectedWallet, fetchTransactions])

  const handleAction = async () => {
    if (!actionWallet || !actionAmount || !actionType) return
    setActionLoading(true)
    setActionError('')
    setActionSuccess('')
    try {
      const endpoint = actionType === 'deposit'
        ? `/tax-wallets/${actionWallet}/deposit`
        : `/tax-wallets/${actionWallet}/withdraw`
      await apiClient.post(endpoint, {
        amount: actionAmount,
        description: actionDesc || undefined,
      })
      setActionSuccess(`${actionType === 'deposit' ? 'Deposit' : 'Withdrawal'} successful`)
      setActionAmount('')
      setActionDesc('')
      setActionType(null)
      fetchWallets()
      if (selectedWallet === actionWallet) {
        fetchTransactions(actionWallet)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: { message?: string } | string } } })
        ?.response?.data?.detail
      if (typeof msg === 'object' && msg?.message) {
        setActionError(msg.message)
      } else if (typeof msg === 'string') {
        setActionError(msg)
      } else {
        setActionError('Operation failed')
      }
    } finally {
      setActionLoading(false)
    }
  }

  if (loading && wallets.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <h1 className="text-2xl font-bold text-text">Tax Savings Wallets</h1>
      <p className="text-muted">
        Virtual set-aside wallets for GST and income tax obligations.
      </p>

      {error && (
        <div className="rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-danger">
          {error}
        </div>
      )}

      {/* Wallet cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {(wallets ?? []).map((w) => (
          <div
            key={w.id}
            className={`cursor-pointer rounded-card border-2 bg-card p-5 shadow-card transition ${
              selectedWallet === w.wallet_type
                ? 'border-accent'
                : 'border-transparent hover:border-border'
            }`}
            onClick={() => setSelectedWallet(w.wallet_type)}
          >
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-medium text-muted">
                {WALLET_LABELS[w.wallet_type] ?? w.wallet_type}
              </h3>
            </div>
            <p className="mono text-2xl font-bold text-text">{fmt(w.balance ?? 0)}</p>
            <div className="mt-3 flex gap-2">
              <button
                className="rounded-ctl bg-ok-soft px-3 py-1 text-xs text-ok hover:brightness-95"
                onClick={(e) => {
                  e.stopPropagation()
                  setActionType('deposit')
                  setActionWallet(w.wallet_type)
                  setActionError('')
                  setActionSuccess('')
                }}
              >
                Deposit
              </button>
              <button
                className="rounded-ctl bg-warn-soft px-3 py-1 text-xs text-warn hover:brightness-95"
                onClick={(e) => {
                  e.stopPropagation()
                  setActionType('withdraw')
                  setActionWallet(w.wallet_type)
                  setActionError('')
                  setActionSuccess('')
                }}
              >
                Withdraw
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Deposit/Withdraw modal */}
      {actionType && (
        <div className="rounded-card border border-border bg-card p-5 shadow-card">
          <h3 className="mb-3 text-lg font-semibold text-text">
            {actionType === 'deposit' ? 'Deposit to' : 'Withdraw from'}{' '}
            {WALLET_LABELS[actionWallet] ?? actionWallet} Wallet
          </h3>
          {actionError && (
            <div className="mb-3 rounded-ctl border border-danger-soft bg-danger-soft px-3 py-2 text-sm text-danger">
              {actionError}
            </div>
          )}
          {actionSuccess && (
            <div className="mb-3 rounded-ctl border border-ok-soft bg-ok-soft px-3 py-2 text-sm text-ok">
              {actionSuccess}
            </div>
          )}
          <div className="flex items-end gap-3">
            <div>
              <label className="mb-1 block text-sm text-muted">Amount ($)</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className="w-40 rounded-ctl border border-border bg-card px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                value={actionAmount}
                onChange={(e) => setActionAmount(e.target.value)}
              />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-sm text-muted">Description</label>
              <input
                type="text"
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                value={actionDesc}
                onChange={(e) => setActionDesc(e.target.value)}
                placeholder="Optional description"
              />
            </div>
            <button
              className="rounded-ctl bg-accent px-4 py-2 text-white hover:bg-accent-press disabled:opacity-50"
              disabled={actionLoading || !actionAmount}
              onClick={handleAction}
            >
              {actionLoading ? 'Processing...' : 'Confirm'}
            </button>
            <button
              className="rounded-ctl bg-canvas px-4 py-2 text-text hover:bg-border"
              onClick={() => {
                setActionType(null)
                setActionError('')
                setActionSuccess('')
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Transaction history */}
      {selectedWallet && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="border-b border-border px-5 py-4">
            <h3 className="text-lg font-semibold text-text">
              {WALLET_LABELS[selectedWallet] ?? selectedWallet} — Transaction History
            </h3>
          </div>
          {txLoading ? (
            <div className="flex h-32 items-center justify-center">
              <Spinner />
            </div>
          ) : (transactions ?? []).length === 0 ? (
            <div className="px-5 py-8 text-center text-muted">
              No transactions yet
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="mono border-b border-border px-5 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Date</th>
                  <th className="mono border-b border-border px-5 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Type</th>
                  <th className="mono border-b border-border px-5 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Description</th>
                  <th className="mono border-b border-border px-5 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Amount</th>
                </tr>
              </thead>
              <tbody>
                {(transactions ?? []).map((tx) => (
                  <tr key={tx.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono px-5 py-3 text-text">
                      {new Date(tx.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3">
                      <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                        tx.transaction_type === 'auto_sweep'
                          ? 'bg-accent-soft text-accent'
                          : tx.transaction_type === 'manual_deposit'
                          ? 'bg-ok-soft text-ok'
                          : tx.transaction_type === 'manual_withdrawal'
                          ? 'bg-warn-soft text-warn'
                          : 'bg-[#EEF0F4] text-muted'
                      }`}>
                        {TX_TYPE_LABELS[tx.transaction_type] ?? tx.transaction_type}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-muted">{tx.description ?? '—'}</td>
                    <td className={`mono px-5 py-3 text-right font-medium ${
                      (tx.amount ?? 0) >= 0 ? 'text-ok' : 'text-danger'
                    }`}>
                      {fmt(tx.amount ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
