import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface BankTransaction {
  id: string
  bank_account_id: string
  akahu_transaction_id: string
  date: string
  description: string
  amount: number
  balance: number | null
  merchant_name: string | null
  category: string | null
  reconciliation_status: string
  matched_invoice_id: string | null
  matched_expense_id: string | null
  matched_journal_id: string | null
}

const fmt = (n: number) =>
  `${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const statusBadge = (status: string) => {
  const colors: Record<string, string> = {
    unmatched: 'bg-yellow-100 text-yellow-800',
    matched: 'bg-green-100 text-green-800',
    excluded: 'bg-gray-100 text-gray-600',
    manual: 'bg-blue-100 text-blue-800',
  }
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  )
}

export default function BankTransactions() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [transactions, setTransactions] = useState<BankTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [actionMsg, setActionMsg] = useState('')

  const fetchTransactions = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = {}
      if (statusFilter) params.status = statusFilter
      const res = await apiClient.get<{ items: BankTransaction[]; total: number }>(
        '/banking/transactions',
        { params, signal },
      )
      setTransactions(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setError('Failed to load transactions')
      }
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    const controller = new AbortController()
    fetchTransactions(controller.signal)
    return () => controller.abort()
  }, [fetchTransactions])

  const handleExclude = async (txnId: string) => {
    try {
      await apiClient.post(`/banking/transactions/${txnId}/exclude`)
      setActionMsg('Transaction excluded')
      fetchTransactions()
    } catch {
      setActionMsg('Failed to exclude')
    }
  }

  const handleCreateExpense = async (txnId: string) => {
    try {
      await apiClient.post(`/banking/transactions/${txnId}/create-expense`)
      setActionMsg('Expense created and linked')
      fetchTransactions()
    } catch {
      setActionMsg('Failed to create expense')
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Bank Transactions</h1>
        <p className="text-sm text-gray-500 mt-1">{total} transactions</p>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Status</label>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="unmatched">Unmatched</option>
            <option value="matched">Matched</option>
            <option value="manual">Manual Review</option>
            <option value="excluded">Excluded</option>
          </select>
        </div>
      </div>

      {actionMsg && (
        <div className="mb-4 rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-700">
          {actionMsg}
        </div>
      )}

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading transactions" /></div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{error}</div>
      ) : (transactions ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No transactions found. Sync your bank accounts to import transactions.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Merchant</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(transactions ?? []).map(txn => (
                <tr key={txn.id}>
                  <td className="px-4 py-3 text-sm text-gray-700">{txn.date}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">{txn.description}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{txn.merchant_name ?? '—'}</td>
                  <td className={`px-4 py-3 text-sm text-right font-mono ${(txn.amount ?? 0) >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                    {(txn.amount ?? 0) >= 0 ? '+' : ''}{fmt(txn.amount ?? 0)}
                  </td>
                  <td className="px-4 py-3">{statusBadge(txn.reconciliation_status)}</td>
                  <td className="px-4 py-3">
                    {txn.reconciliation_status === 'unmatched' && (
                      <div className="flex gap-1">
                        <button
                          onClick={() => handleExclude(txn.id)}
                          className="text-xs text-gray-600 hover:text-gray-800"
                        >
                          Exclude
                        </button>
                        {(txn.amount ?? 0) < 0 && (
                          <button
                            onClick={() => handleCreateExpense(txn.id)}
                            className="text-xs text-blue-600 hover:text-blue-800"
                          >
                            Create Expense
                          </button>
                        )}
                      </div>
                    )}
                    {txn.reconciliation_status === 'manual' && (
                      <span className="text-xs text-blue-600">Review needed</span>
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
