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
  `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

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
      <div className="flex items-center justify-center h-64">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Tax Savings Wallets</h1>
      <p className="text-gray-600">
        Virtual set-aside wallets for GST and income tax obligations.
      </p>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      {/* Wallet cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(wallets ?? []).map((w) => (
          <div
            key={w.id}
            className={`bg-white rounded-lg shadow p-5 border-2 cursor-pointer transition ${
              selectedWallet === w.wallet_type
                ? 'border-blue-500'
                : 'border-transparent hover:border-gray-200'
            }`}
            onClick={() => setSelectedWallet(w.wallet_type)}
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-500">
                {WALLET_LABELS[w.wallet_type] ?? w.wallet_type}
              </h3>
            </div>
            <p className="text-2xl font-bold text-gray-900">{fmt(w.balance ?? 0)}</p>
            <div className="mt-3 flex gap-2">
              <button
                className="text-xs px-3 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200"
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
                className="text-xs px-3 py-1 bg-orange-100 text-orange-700 rounded hover:bg-orange-200"
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
        <div className="bg-white rounded-lg shadow p-5 border">
          <h3 className="text-lg font-semibold mb-3">
            {actionType === 'deposit' ? 'Deposit to' : 'Withdraw from'}{' '}
            {WALLET_LABELS[actionWallet] ?? actionWallet} Wallet
          </h3>
          {actionError && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded mb-3 text-sm">
              {actionError}
            </div>
          )}
          {actionSuccess && (
            <div className="bg-green-50 border border-green-200 text-green-700 px-3 py-2 rounded mb-3 text-sm">
              {actionSuccess}
            </div>
          )}
          <div className="flex gap-3 items-end">
            <div>
              <label className="block text-sm text-gray-600 mb-1">Amount ($)</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className="border rounded px-3 py-2 w-40"
                value={actionAmount}
                onChange={(e) => setActionAmount(e.target.value)}
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm text-gray-600 mb-1">Description</label>
              <input
                type="text"
                className="border rounded px-3 py-2 w-full"
                value={actionDesc}
                onChange={(e) => setActionDesc(e.target.value)}
                placeholder="Optional description"
              />
            </div>
            <button
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              disabled={actionLoading || !actionAmount}
              onClick={handleAction}
            >
              {actionLoading ? 'Processing...' : 'Confirm'}
            </button>
            <button
              className="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
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
        <div className="bg-white rounded-lg shadow">
          <div className="px-5 py-4 border-b">
            <h3 className="text-lg font-semibold">
              {WALLET_LABELS[selectedWallet] ?? selectedWallet} — Transaction History
            </h3>
          </div>
          {txLoading ? (
            <div className="flex items-center justify-center h-32">
              <Spinner />
            </div>
          ) : (transactions ?? []).length === 0 ? (
            <div className="px-5 py-8 text-center text-gray-500">
              No transactions yet
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-5 py-3 text-left text-gray-600">Date</th>
                  <th className="px-5 py-3 text-left text-gray-600">Type</th>
                  <th className="px-5 py-3 text-left text-gray-600">Description</th>
                  <th className="px-5 py-3 text-right text-gray-600">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {(transactions ?? []).map((tx) => (
                  <tr key={tx.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3 text-gray-700">
                      {new Date(tx.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        tx.transaction_type === 'auto_sweep'
                          ? 'bg-blue-100 text-blue-700'
                          : tx.transaction_type === 'manual_deposit'
                          ? 'bg-green-100 text-green-700'
                          : tx.transaction_type === 'manual_withdrawal'
                          ? 'bg-orange-100 text-orange-700'
                          : 'bg-gray-100 text-gray-700'
                      }`}>
                        {TX_TYPE_LABELS[tx.transaction_type] ?? tx.transaction_type}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-gray-600">{tx.description ?? '—'}</td>
                    <td className={`px-5 py-3 text-right font-medium ${
                      (tx.amount ?? 0) >= 0 ? 'text-green-700' : 'text-red-700'
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
