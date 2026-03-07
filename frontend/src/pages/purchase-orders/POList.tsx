/**
 * Purchase order list page with paginated table, status filter,
 * supplier filter, and create button.
 *
 * Validates: Requirement 16 — Purchase Order Module
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface PurchaseOrderSummary {
  id: string
  po_number: string
  supplier_id: string
  status: string
  expected_delivery: string | null
  total_amount: string
  notes: string | null
  created_at: string
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'partial', label: 'Partially Received' },
  { value: 'received', label: 'Received' },
  { value: 'cancelled', label: 'Cancelled' },
]

export default function POList() {
  const [orders, setOrders] = useState<PurchaseOrderSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const pageSize = 20

  const fetchOrders = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (statusFilter) params.set('status', statusFilter)
      if (supplierFilter) params.set('supplier_id', supplierFilter)

      const res = await apiClient.get(`/api/v2/purchase-orders?${params}`)
      setOrders(res.data.purchase_orders)
      setTotal(res.data.total)
    } catch {
      setOrders([])
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter, supplierFilter])

  useEffect(() => { fetchOrders() }, [fetchOrders])

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return <div role="status" aria-label="Loading purchase orders">Loading purchase orders…</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Purchase Orders</h1>
        <a href="/purchase-orders/new" role="link" aria-label="Create purchase order">
          <button>+ New Purchase Order</button>
        </a>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <label htmlFor="status-filter">Status</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
          >
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="supplier-filter">Supplier ID</label>
          <input
            id="supplier-filter"
            type="text"
            placeholder="Filter by supplier"
            value={supplierFilter}
            onChange={e => { setSupplierFilter(e.target.value); setPage(1) }}
          />
        </div>
      </div>

      {/* PO table */}
      {orders.length === 0 ? (
        <p>No purchase orders found. Create your first purchase order to get started.</p>
      ) : (
        <>
          <table role="grid" aria-label="Purchase orders list">
            <thead>
              <tr>
                <th>PO Number</th>
                <th>Status</th>
                <th>Supplier</th>
                <th>Expected Delivery</th>
                <th>Total</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {orders.map(po => (
                <tr key={po.id} role="row">
                  <td><a href={`/purchase-orders/${po.id}`}>{po.po_number}</a></td>
                  <td>{po.status}</td>
                  <td>{po.supplier_id}</td>
                  <td>{po.expected_delivery || '—'}</td>
                  <td>${Number(po.total_amount).toFixed(2)}</td>
                  <td>{new Date(po.created_at).toLocaleDateString()}</td>
                  <td>
                    <a href={`/purchase-orders/${po.id}`}>View</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <nav aria-label="Pagination">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
              <span>Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
