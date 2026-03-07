/**
 * Purchase order detail page with PO form, line items,
 * receive goods interface with quantity inputs per line,
 * and PDF download button.
 *
 * Validates: Requirement 16 — Purchase Order Module
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface POLine {
  id: string
  product_id: string
  description: string | null
  quantity_ordered: string
  quantity_received: string
  unit_cost: string
  line_total: string
}

interface PurchaseOrder {
  id: string
  org_id: string
  po_number: string
  supplier_id: string
  job_id: string | null
  project_id: string | null
  status: string
  expected_delivery: string | null
  total_amount: string
  notes: string | null
  lines: POLine[]
  created_at: string
  updated_at: string
}

interface ReceiveQuantity {
  line_id: string
  quantity: string
}

interface PODetailProps {
  poId?: string
}

export default function PODetail({ poId }: PODetailProps) {
  const [po, setPo] = useState<PurchaseOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [showReceiveForm, setShowReceiveForm] = useState(false)
  const [receiveQuantities, setReceiveQuantities] = useState<ReceiveQuantity[]>([])
  const [receiving, setReceiving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPO = useCallback(async () => {
    if (!poId) return
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v2/purchase-orders/${poId}`)
      setPo(res.data)
    } catch {
      setPo(null)
    } finally {
      setLoading(false)
    }
  }, [poId])

  useEffect(() => { fetchPO() }, [fetchPO])

  const handleReceiveGoods = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!po) return
    setReceiving(true)
    setError(null)
    try {
      const lines = receiveQuantities
        .filter(rq => parseFloat(rq.quantity) > 0)
        .map(rq => ({ line_id: rq.line_id, quantity: parseFloat(rq.quantity) }))

      if (lines.length === 0) {
        setError('Enter at least one quantity to receive')
        setReceiving(false)
        return
      }

      const res = await apiClient.post(`/api/v2/purchase-orders/${po.id}/receive`, { lines })
      setPo(res.data)
      setShowReceiveForm(false)
      setReceiveQuantities([])
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to receive goods')
    } finally {
      setReceiving(false)
    }
  }

  const handleSendPO = async () => {
    if (!po) return
    try {
      const res = await apiClient.put(`/api/v2/purchase-orders/${po.id}/send`)
      setPo(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to send PO')
    }
  }

  const handleDownloadPDF = async () => {
    if (!po) return
    try {
      await apiClient.get(`/api/v2/purchase-orders/${po.id}/pdf`)
    } catch {
      // PDF download failed
    }
  }

  const openReceiveForm = () => {
    if (!po) return
    setReceiveQuantities(
      po.lines.map(line => ({
        line_id: line.id,
        quantity: '0',
      })),
    )
    setShowReceiveForm(true)
  }

  if (loading) {
    return <div role="status" aria-label="Loading purchase order">Loading purchase order…</div>
  }

  if (!po) {
    return <p>Purchase order not found.</p>
  }

  const canReceive = ['sent', 'partial'].includes(po.status)
  const canSend = po.status === 'draft'

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>{po.po_number}</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {canSend && (
            <button onClick={handleSendPO} aria-label="Send to supplier">Send to Supplier</button>
          )}
          {canReceive && (
            <button onClick={openReceiveForm} aria-label="Receive goods">Receive Goods</button>
          )}
          <button onClick={handleDownloadPDF} aria-label="Download PDF">Download PDF</button>
        </div>
      </div>

      {error && <div role="alert" style={{ color: 'red', marginBottom: '1rem' }}>{error}</div>}

      {/* PO details */}
      <div style={{ marginBottom: '1rem' }}>
        <p><strong>Status:</strong> <span data-testid="po-status">{po.status}</span></p>
        <p><strong>Supplier:</strong> {po.supplier_id}</p>
        {po.expected_delivery && <p><strong>Expected Delivery:</strong> {po.expected_delivery}</p>}
        <p><strong>Total:</strong> ${Number(po.total_amount).toFixed(2)}</p>
        {po.notes && <p><strong>Notes:</strong> {po.notes}</p>}
      </div>

      {/* Line items table */}
      <h2>Line Items</h2>
      <table role="grid" aria-label="PO line items">
        <thead>
          <tr>
            <th>Product</th>
            <th>Description</th>
            <th>Qty Ordered</th>
            <th>Qty Received</th>
            <th>Outstanding</th>
            <th>Unit Cost</th>
            <th>Line Total</th>
          </tr>
        </thead>
        <tbody>
          {po.lines.map(line => {
            const outstanding = Number(line.quantity_ordered) - Number(line.quantity_received)
            return (
              <tr key={line.id} role="row">
                <td>{line.product_id}</td>
                <td>{line.description || '—'}</td>
                <td>{line.quantity_ordered}</td>
                <td>{line.quantity_received}</td>
                <td>{outstanding > 0 ? outstanding : 0}</td>
                <td>${Number(line.unit_cost).toFixed(2)}</td>
                <td>${Number(line.line_total).toFixed(2)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* Receive goods form */}
      {showReceiveForm && (
        <form onSubmit={handleReceiveGoods} aria-label="Receive goods">
          <h3>Receive Goods</h3>
          <table role="grid" aria-label="Receive quantities">
            <thead>
              <tr>
                <th>Product</th>
                <th>Ordered</th>
                <th>Already Received</th>
                <th>Outstanding</th>
                <th>Receive Qty</th>
              </tr>
            </thead>
            <tbody>
              {po.lines.map((line, idx) => {
                const outstanding = Number(line.quantity_ordered) - Number(line.quantity_received)
                return (
                  <tr key={line.id}>
                    <td>{line.product_id}</td>
                    <td>{line.quantity_ordered}</td>
                    <td>{line.quantity_received}</td>
                    <td>{outstanding}</td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        max={outstanding}
                        step="any"
                        aria-label={`Receive quantity for line ${idx + 1}`}
                        value={receiveQuantities[idx]?.quantity || '0'}
                        onChange={e => {
                          const updated = [...receiveQuantities]
                          updated[idx] = { ...updated[idx], quantity: e.target.value }
                          setReceiveQuantities(updated)
                        }}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button type="submit" disabled={receiving}>
              {receiving ? 'Receiving…' : 'Confirm Receive'}
            </button>
            <button type="button" onClick={() => setShowReceiveForm(false)}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  )
}
