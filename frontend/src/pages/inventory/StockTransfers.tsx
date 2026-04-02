/**
 * Branch-based stock transfers page.
 * Lists transfers, provides create form, and action buttons per status.
 *
 * Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 17.6
 */
import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { ToastContainer, useToast } from '@/components/ui/Toast'

interface TransferRow {
  id: string
  from_branch_name: string
  to_branch_name: string
  stock_item_name: string
  quantity: number
  status: string
  requested_by_name: string
  created_at: string
}

interface BranchOption {
  id: string
  name: string
}

const STATUS_VARIANT: Record<string, 'neutral' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'warning',
  approved: 'info',
  shipped: 'info',
  received: 'success',
  cancelled: 'error',
}

export default function StockTransfers() {
  const { branches } = useBranch()
  const { toasts, addToast, dismissToast } = useToast()
  const [transfers, setTransfers] = useState<TransferRow[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Form state
  const [fromBranch, setFromBranch] = useState('')
  const [toBranch, setToBranch] = useState('')
  const [productId, setProductId] = useState('')
  const [quantity, setQuantity] = useState('')

  const branchOptions: BranchOption[] = (branches ?? []).map((b) => ({ id: b.id, name: b.name }))

  const fetchTransfers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ transfers: TransferRow[] }>('/inventory/transfers')
      setTransfers(res.data?.transfers ?? [])
    } catch {
      addToast('error', 'Failed to load transfers')
    } finally {
      setLoading(false)
    }
  }, [addToast])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      try {
        const res = await apiClient.get<{ transfers: TransferRow[] }>(
          '/inventory/transfers',
          { signal: controller.signal },
        )
        setTransfers(res.data?.transfers ?? [])
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          addToast('error', 'Failed to load transfers')
        }
      } finally {
        setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [addToast])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (fromBranch === toBranch) {
      addToast('error', 'Source and destination branches must be different')
      return
    }
    setSubmitting(true)
    try {
      await apiClient.post('/inventory/transfers', {
        from_branch_id: fromBranch,
        to_branch_id: toBranch,
        stock_item_id: productId,
        quantity: parseFloat(quantity),
      })
      addToast('success', 'Transfer created')
      setShowForm(false)
      setFromBranch('')
      setToBranch('')
      setProductId('')
      setQuantity('')
      fetchTransfers()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create transfer'
      addToast('error', msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleAction = async (transferId: string, action: string) => {
    try {
      await apiClient.post(`/inventory/transfers/${transferId}/${action}`)
      addToast('success', `Transfer ${action} successful`)
      fetchTransfers()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `Failed to ${action} transfer`
      addToast('error', msg)
    }
  }

  if (loading && transfers.length === 0) {
    return <div className="py-16"><Spinner label="Loading stock transfers" /></div>
  }

  return (
    <div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">Manage inter-branch stock transfers.</p>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : 'New Transfer'}
        </Button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 rounded-lg border border-gray-200 bg-white p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="tf-from" className="block text-sm font-medium text-gray-700 mb-1">Source Branch</label>
              <select id="tf-from" value={fromBranch} onChange={(e) => setFromBranch(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
                <option value="">Select source</option>
                {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="tf-to" className="block text-sm font-medium text-gray-700 mb-1">Destination Branch</label>
              <select id="tf-to" value={toBranch} onChange={(e) => setToBranch(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
                <option value="">Select destination</option>
                {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="tf-product" className="block text-sm font-medium text-gray-700 mb-1">Stock Item ID</label>
              <input id="tf-product" type="text" value={productId} onChange={(e) => setProductId(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" placeholder="Stock item UUID" />
            </div>
            <div>
              <label htmlFor="tf-qty" className="block text-sm font-medium text-gray-700 mb-1">Quantity</label>
              <input id="tf-qty" type="number" step="0.001" min="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button size="sm" type="submit" loading={submitting} disabled={submitting}>Create Transfer</Button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200" role="grid">
          <caption className="sr-only">Stock transfers</caption>
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">From</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">To</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Product</th>
              <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Qty</th>
              <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Requested By</th>
              <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white">
            {transfers.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-500">No stock transfers found.</td></tr>
            ) : (
              transfers.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{new Date(t.created_at).toLocaleDateString('en-NZ')}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{t.from_branch_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{t.to_branch_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{t.stock_item_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">{t.quantity ?? 0}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                    <Badge variant={STATUS_VARIANT[t.status] ?? 'neutral'}>
                      {(t.status ?? 'unknown').charAt(0).toUpperCase() + (t.status ?? 'unknown').slice(1)}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{t.requested_by_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                    <div className="flex justify-center gap-1">
                      {t.status === 'pending' && (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => handleAction(t.id, 'approve')}>Approve</Button>
                          <Button size="sm" variant="danger" onClick={() => handleAction(t.id, 'cancel')}>Cancel</Button>
                        </>
                      )}
                      {t.status === 'approved' && (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => handleAction(t.id, 'ship')}>Ship</Button>
                          <Button size="sm" variant="danger" onClick={() => handleAction(t.id, 'cancel')}>Cancel</Button>
                        </>
                      )}
                      {t.status === 'shipped' && (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => handleAction(t.id, 'receive')}>Receive</Button>
                          <Button size="sm" variant="danger" onClick={() => handleAction(t.id, 'cancel')}>Cancel</Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
