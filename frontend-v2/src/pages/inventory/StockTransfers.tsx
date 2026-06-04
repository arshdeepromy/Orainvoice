/**
 * StockTransfers — Task 36 port of frontend/src/pages/inventory/StockTransfers.tsx.
 *
 * Branch-based stock transfers page. Lists transfers, provides a create form,
 * and per-status action buttons. ALL logic — the `branch_management` module
 * gate, the branch options from BranchContext, the dual fetch (callback +
 * AbortController effect), create POST /inventory/transfers, and the
 * approve/ship/receive/cancel actions POST /inventory/transfers/:id/:action —
 * copied VERBATIM. Presentation remapped onto the design tokens (FR-2b) using
 * the StockTransfers.html prototype language (page-head eyebrow "Multi-site",
 * card-wrapped table). `Button` `secondary`→`ghost`.
 *
 * Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 17.6
 */
import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import { Button, Badge, Spinner, ToastContainer, useToast } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

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

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  pending: 'warn',
  approved: 'info',
  shipped: 'info',
  received: 'success',
  cancelled: 'danger',
}

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_C = 'mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

export default function StockTransfers() {
  const { isEnabled } = useModules()
  if (!isEnabled('branch_management')) return <Navigate to="/dashboard" replace />

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
    <div className="page page-wide">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="page-head">
        <div>
          <div className="eyebrow">Multi-site</div>
          <h1>Stock transfers</h1>
          <p className="sub">Inter-branch stock movements</p>
        </div>
        <div className="head-actions">
          <Button size="sm" onClick={() => setShowForm(!showForm)}>
            {showForm ? 'Cancel' : 'New Transfer'}
          </Button>
        </div>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 rounded-card border border-border bg-card p-4 shadow-card space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="tf-from" className="block text-[12.5px] font-medium text-text mb-1">Source Branch</label>
              <select id="tf-from" value={fromBranch} onChange={(e) => setFromBranch(e.target.value)} required
                className="h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
                <option value="">Select source</option>
                {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="tf-to" className="block text-[12.5px] font-medium text-text mb-1">Destination Branch</label>
              <select id="tf-to" value={toBranch} onChange={(e) => setToBranch(e.target.value)} required
                className="h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
                <option value="">Select destination</option>
                {branchOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="tf-product" className="block text-[12.5px] font-medium text-text mb-1">Stock Item ID</label>
              <input id="tf-product" type="text" value={productId} onChange={(e) => setProductId(e.target.value)} required
                className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" placeholder="Stock item UUID" />
            </div>
            <div>
              <label htmlFor="tf-qty" className="block text-[12.5px] font-medium text-text mb-1">Quantity</label>
              <input id="tf-qty" type="number" step="0.001" min="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)} required
                className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" type="button" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button size="sm" type="submit" loading={submitting} disabled={submitting}>Create Transfer</Button>
          </div>
        </form>
      )}

      <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
        <div className="overflow-x-auto">
        <table className="w-full border-collapse" role="grid">
          <caption className="sr-only">Stock transfers</caption>
          <thead>
            <tr>
              <th scope="col" className={TH}>Date</th>
              <th scope="col" className={TH}>From</th>
              <th scope="col" className={TH}>To</th>
              <th scope="col" className={TH}>Product</th>
              <th scope="col" className={TH_R}>Qty</th>
              <th scope="col" className={TH_C}>Status</th>
              <th scope="col" className={TH}>Requested By</th>
              <th scope="col" className={TH_C}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {transfers.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-[13px] text-muted">No stock transfers found.</td></tr>
            ) : (
              transfers.map((t) => (
                <tr key={t.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{new Date(t.created_at).toLocaleDateString('en-NZ')}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">{t.from_branch_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-text">{t.to_branch_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{t.stock_item_name ?? '—'}</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-text">{t.quantity ?? 0}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                    <Badge variant={STATUS_VARIANT[t.status] ?? 'neutral'}>
                      {(t.status ?? 'unknown').charAt(0).toUpperCase() + (t.status ?? 'unknown').slice(1)}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{t.requested_by_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                    <div className="flex justify-center gap-1">
                      {t.status === 'pending' && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => handleAction(t.id, 'approve')}>Approve</Button>
                          <Button size="sm" variant="danger" onClick={() => handleAction(t.id, 'cancel')}>Cancel</Button>
                        </>
                      )}
                      {t.status === 'approved' && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => handleAction(t.id, 'ship')}>Ship</Button>
                          <Button size="sm" variant="danger" onClick={() => handleAction(t.id, 'cancel')}>Cancel</Button>
                        </>
                      )}
                      {t.status === 'shipped' && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => handleAction(t.id, 'receive')}>Receive</Button>
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
      </section>
    </div>
  )
}
