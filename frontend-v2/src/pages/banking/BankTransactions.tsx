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
    unmatched: 'bg-warn-soft text-warn',
    matched: 'bg-ok-soft text-ok',
    excluded: 'bg-[#EEF0F4] text-muted',
    manual: 'bg-accent-soft text-accent',
  }
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? 'bg-[#EEF0F4] text-muted'}`}>
      {status}
    </span>
  )
}

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

const FILTER =
  'rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

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
        <h1 className="text-2xl font-semibold text-text">Bank Transactions</h1>
        <p className="mt-1 text-sm text-muted">{total} transactions</p>
      </div>

      {/* Filters */}
      <div className="mb-4 flex items-end gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted">Status</label>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className={FILTER}
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
        <div className="mb-4 rounded-ctl border border-border bg-accent-soft p-3 text-sm text-accent">
          {actionMsg}
        </div>
      )}

      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading transactions" /></div>
      ) : error ? (
        <div className="rounded-card border border-danger-soft bg-danger-soft p-6 text-center text-danger">{error}</div>
      ) : (transactions ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No transactions found. Sync your bank accounts to import transactions.
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Date</th>
                <th className={TH}>Description</th>
                <th className={TH}>Merchant</th>
                <th className={TH_RIGHT}>Amount</th>
                <th className={TH}>Status</th>
                <th className={TH}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(transactions ?? []).map(txn => (
                <tr key={txn.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono px-4 py-3 text-sm text-text">{txn.date}</td>
                  <td className="max-w-xs truncate px-4 py-3 text-sm text-text">{txn.description}</td>
                  <td className="px-4 py-3 text-sm text-text">{txn.merchant_name ?? '—'}</td>
                  <td className={`mono px-4 py-3 text-right text-sm ${(txn.amount ?? 0) >= 0 ? 'text-ok' : 'text-danger'}`}>
                    {(txn.amount ?? 0) >= 0 ? '+' : ''}{fmt(txn.amount ?? 0)}
                  </td>
                  <td className="px-4 py-3">{statusBadge(txn.reconciliation_status)}</td>
                  <td className="px-4 py-3">
                    {txn.reconciliation_status === 'unmatched' && (
                      <div className="flex gap-1">
                        <button
                          onClick={() => handleExclude(txn.id)}
                          className="text-xs text-muted hover:text-text"
                        >
                          Exclude
                        </button>
                        {(txn.amount ?? 0) < 0 && (
                          <button
                            onClick={() => handleCreateExpense(txn.id)}
                            className="text-xs text-accent hover:text-accent-press"
                          >
                            Create Expense
                          </button>
                        )}
                      </div>
                    )}
                    {txn.reconciliation_status === 'manual' && (
                      <span className="text-xs text-accent">Review needed</span>
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
