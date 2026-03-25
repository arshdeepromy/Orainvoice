import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal, Input } from '@/components/ui'

interface POLine {
  id: string
  product_id: string
  description: string | null
  quantity_ordered: number
  quantity_received: number
  unit_cost: number
  line_total: number
}

interface PurchaseOrder {
  id: string
  po_number: string
  supplier_id: string
  status: string
  expected_delivery: string | null
  total_amount: number
  notes: string | null
  created_at: string
  updated_at: string
  lines: POLine[]
}

interface Supplier { id: string; name: string; email?: string; phone?: string }

function formatNZD(amount: number) {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

function statusBadge(status: string) {
  const map: Record<string, 'info' | 'warning' | 'success' | 'error' | 'neutral'> = {
    draft: 'neutral', sent: 'info', partial: 'warning', received: 'success', cancelled: 'error',
  }
  const labels: Record<string, string> = {
    draft: 'Draft', sent: 'Sent', partial: 'Partially Received', received: 'Received', cancelled: 'Cancelled',
  }
  return <Badge variant={map[status] || 'neutral'}>{labels[status] || status}</Badge>
}

export default function PODetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [po, setPo] = useState<PurchaseOrder | null>(null)
  const [supplier, setSupplier] = useState<Supplier | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [actionErr, setActionErr] = useState('')
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  // Receive modal
  const [showReceive, setShowReceive] = useState(false)
  const [receiveQtys, setReceiveQtys] = useState<Record<string, string>>({})
  const [receiving, setReceiving] = useState(false)
  const [receiveError, setReceiveError] = useState('')

  const fetchPO = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v2/purchase-orders/${id}`)
      setPo(res.data)
      // Fetch supplier name
      try {
        const suppRes = await apiClient.get(`/api/v2/suppliers/${res.data.supplier_id}`)
        setSupplier(suppRes.data)
      } catch { /* non-blocking */ }
    } catch {
      setError('Purchase order not found.')
    } finally { setLoading(false) }
  }, [id])

  useEffect(() => { fetchPO() }, [fetchPO])

  const handleSend = async () => {
    if (!po) return
    setSending(true)
    setActionErr('')
    try {
      const res = await apiClient.put(`/api/v2/purchase-orders/${po.id}/send`)
      setPo(res.data)
      setActionMsg('Purchase order marked as sent.')
    } catch (err: any) {
      setActionErr(err?.response?.data?.detail || 'Failed to send.')
    } finally { setSending(false) }
  }

  const handleCancel = async () => {
    if (!po) return
    setCancelling(true)
    setActionErr('')
    try {
      await apiClient.put(`/api/v2/purchase-orders/${po.id}`, { status: 'cancelled' })
      setPo(prev => prev ? { ...prev, status: 'cancelled' } : prev)
      setActionMsg('Purchase order cancelled.')
    } catch (err: any) {
      setActionErr(err?.response?.data?.detail || 'Failed to cancel.')
    } finally { setCancelling(false) }
  }

  const openReceive = () => {
    if (!po) return
    const qtys: Record<string, string> = {}
    po.lines.forEach(l => {
      const outstanding = Number(l.quantity_ordered) - Number(l.quantity_received)
      if (outstanding > 0) qtys[l.id] = String(outstanding)
    })
    setReceiveQtys(qtys)
    setReceiveError('')
    setShowReceive(true)
  }

  const handleReceive = async () => {
    if (!po) return
    const lines = Object.entries(receiveQtys)
      .filter(([, qty]) => Number(qty) > 0)
      .map(([lineId, qty]) => ({ line_id: lineId, quantity: Number(qty) }))
    if (lines.length === 0) { setReceiveError('Enter quantities to receive.'); return }
    setReceiving(true)
    setReceiveError('')
    try {
      const res = await apiClient.post(`/api/v2/purchase-orders/${po.id}/receive`, { lines })
      setPo(res.data)
      setShowReceive(false)
      setActionMsg('Goods received and stock updated.')
    } catch (err: any) {
      setReceiveError(err?.response?.data?.detail || 'Failed to receive goods.')
    } finally { setReceiving(false) }
  }

  if (loading) return <div className="px-4 py-16 text-center"><Spinner label="Loading purchase order" /></div>
  if (error || !po) return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{error || 'Not found.'}</div>
      <Button variant="secondary" className="mt-4" onClick={() => navigate('/purchase-orders')}>← Back</Button>
    </div>
  )

  const canSend = po.status === 'draft'
  const canReceive = po.status === 'sent' || po.status === 'partial'
  const canCancel = po.status === 'draft' || po.status === 'sent'

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/purchase-orders')}
            className="rounded p-1 text-gray-400 hover:text-gray-600" aria-label="Back">←</button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{po.po_number}</h1>
            <p className="text-sm text-gray-500">{supplier?.name || 'Unknown Supplier'}</p>
          </div>
          <div className="ml-2">{statusBadge(po.status)}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canSend && <Button size="sm" onClick={handleSend} loading={sending}>Mark as Sent</Button>}
          {canReceive && <Button size="sm" variant="primary" onClick={openReceive}>Receive Goods</Button>}
          {canCancel && <Button size="sm" variant="danger" onClick={handleCancel} loading={cancelling}>Cancel PO</Button>}
        </div>
      </div>

      {actionMsg && <div className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">{actionMsg}</div>}
      {actionErr && <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{actionErr}</div>}

      {/* Info cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium uppercase text-gray-500">Supplier</p>
          <p className="mt-1 text-sm font-medium text-gray-900">{supplier?.name || '—'}</p>
          {supplier?.email && <p className="text-xs text-gray-500">{supplier.email}</p>}
          {supplier?.phone && <p className="text-xs text-gray-500">{supplier.phone}</p>}
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium uppercase text-gray-500">Expected Delivery</p>
          <p className="mt-1 text-sm font-medium text-gray-900">{po.expected_delivery || 'Not set'}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium uppercase text-gray-500">Total Amount</p>
          <p className="mt-1 text-lg font-semibold text-gray-900">{formatNZD(Number(po.total_amount))}</p>
        </div>
      </div>

      {po.notes && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium uppercase text-gray-500 mb-1">Notes</p>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{po.notes}</p>
        </div>
      )}

      {/* Line items table */}
      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Ordered</th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Received</th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Outstanding</th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Unit Cost</th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Line Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {po.lines.map(line => {
              const outstanding = Number(line.quantity_ordered) - Number(line.quantity_received)
              return (
                <tr key={line.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">{line.description || line.product_id.slice(0, 8)}</td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums">{Number(line.quantity_ordered)}</td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums">{Number(line.quantity_received)}</td>
                  <td className={`px-4 py-3 text-sm text-right tabular-nums font-medium ${outstanding > 0 ? 'text-amber-600' : 'text-green-600'}`}>
                    {outstanding}
                  </td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums">{formatNZD(Number(line.unit_cost))}</td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums font-medium">{formatNZD(Number(line.line_total))}</td>
                </tr>
              )
            })}
          </tbody>
          <tfoot className="bg-gray-50">
            <tr>
              <td colSpan={5} className="px-4 py-3 text-right text-sm font-medium text-gray-700">Total:</td>
              <td className="px-4 py-3 text-right text-sm font-semibold text-gray-900 tabular-nums">{formatNZD(Number(po.total_amount))}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-400">
        Created: {new Date(po.created_at).toLocaleString('en-NZ')} · Updated: {new Date(po.updated_at).toLocaleString('en-NZ')}
      </div>

      {/* Receive Goods Modal */}
      <Modal open={showReceive} onClose={() => setShowReceive(false)} title="Receive Goods">
        <div className="space-y-4">
          <p className="text-sm text-gray-600">Enter the quantity received for each line item.</p>
          <div className="space-y-3">
            {po.lines.filter(l => Number(l.quantity_ordered) - Number(l.quantity_received) > 0).map(line => {
              const outstanding = Number(line.quantity_ordered) - Number(line.quantity_received)
              return (
                <div key={line.id} className="flex items-center gap-3">
                  <div className="flex-1">
                    <p className="text-sm font-medium text-gray-900">{line.description || line.product_id.slice(0, 8)}</p>
                    <p className="text-xs text-gray-500">Outstanding: {outstanding}</p>
                  </div>
                  <div className="w-24">
                    <Input label="Qty" type="number" min="0" max={outstanding} value={receiveQtys[line.id] || ''}
                      onChange={e => setReceiveQtys(prev => ({ ...prev, [line.id]: e.target.value }))} />
                  </div>
                </div>
              )
            })}
          </div>
          {receiveError && <p className="text-sm text-red-600">{receiveError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowReceive(false)}>Cancel</Button>
            <Button onClick={handleReceive} loading={receiving}>Confirm Receipt</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
