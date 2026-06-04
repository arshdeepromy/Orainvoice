import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal, Input, Select } from '@/components/ui'
import { useBranch } from '@/contexts/BranchContext'

interface Supplier { id: string; name: string; contact_name?: string | null; email?: string | null; phone?: string | null; address?: string | null }
interface CataloguePart {
  id: string; name: string; part_number: string | null; brand: string | null
  default_price: string; part_type: string; current_stock?: number
}

// Unified item for the product search (covers both products and catalogue parts)
interface SearchItem {
  id: string; name: string; sku: string | null; cost_price: number
  source: 'product' | 'catalogue'; stock?: number
}

interface POLine {
  id: string
  product_id: string | null
  catalogue_item_id?: string | null
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
  lines: POLine[]
  branch_id?: string | null
}

interface NewLine {
  product_id: string | null
  catalogue_item_id: string | null
  description: string
  quantity: number
  unit_cost: number
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'partial', label: 'Partially Received' },
  { value: 'received', label: 'Received' },
  { value: 'cancelled', label: 'Cancelled' },
]

function statusBadge(status: string) {
  const map: Record<string, 'info' | 'warn' | 'success' | 'danger' | 'neutral'> = {
    draft: 'neutral', sent: 'info', partial: 'warn', received: 'success', cancelled: 'danger',
  }
  const labels: Record<string, string> = {
    draft: 'Draft', sent: 'Sent', partial: 'Partial', received: 'Received', cancelled: 'Cancelled',
  }
  return <Badge variant={map[status] || 'neutral'}>{labels[status] || status}</Badge>
}

function formatNZD(amount: number) {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

export default function POList() {
  const navigate = useNavigate()
  const { branches: branchList, selectedBranchId } = useBranch()
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const pageSize = 20

  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [searchItems, setSearchItems] = useState<SearchItem[]>([])
  const [supplierMap, setSupplierMap] = useState<Record<string, string>>({})

  // Create modal
  const [showCreate, setShowCreate] = useState(false)
  const [createSupplierId, setCreateSupplierId] = useState('')
  const [createSupplierName, setCreateSupplierName] = useState('')
  const [createExpectedDelivery, setCreateExpectedDelivery] = useState('')
  const [createNotes, setCreateNotes] = useState('')
  const [createLines, setCreateLines] = useState<NewLine[]>([])
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState('')

  // Supplier search state
  const [supplierQuery, setSupplierQuery] = useState('')
  const [supplierDropdownOpen, setSupplierDropdownOpen] = useState(false)
  const supplierRef = useRef<HTMLDivElement>(null)

  // Product/part search state
  const [productQuery, setProductQuery] = useState('')
  const [productDropdownOpen, setProductDropdownOpen] = useState(false)
  const [selectedItem, setSelectedItem] = useState<SearchItem | null>(null)
  const productRef = useRef<HTMLDivElement>(null)
  const [addQty, setAddQty] = useState('')
  const [addCost, setAddCost] = useState('')

  // Add supplier modal
  const [showAddSupplier, setShowAddSupplier] = useState(false)
  const [newSupplier, setNewSupplier] = useState({ name: '', contact_name: '', email: '', phone: '', address: '' })
  const [addSupplierSaving, setAddSupplierSaving] = useState(false)
  const [addSupplierError, setAddSupplierError] = useState('')

  // Add part modal
  const [showAddPart, setShowAddPart] = useState(false)
  const [newPart, setNewPart] = useState({ name: '', part_number: '', brand: '', default_price: '', description: '' })
  const [addPartSaving, setAddPartSaving] = useState(false)
  const [addPartError, setAddPartError] = useState('')

  const fetchOrders = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), page_size: String(pageSize) }
      if (statusFilter) params.status = statusFilter
      const res = await apiClient.get('/api/v2/purchase-orders', { params })
      const data = res.data as { purchase_orders?: PurchaseOrder[]; total?: number }
      setOrders(data?.purchase_orders ?? [])
      setTotal(data?.total ?? 0)
    } catch { setOrders([]) }
    finally { setLoading(false) }
  }, [page, statusFilter, selectedBranchId])

  const fetchMeta = useCallback(async () => {
    try {
      const [suppRes, partsRes] = await Promise.all([
        apiClient.get('/api/v2/suppliers'),
        apiClient.get('/catalogue/parts', { params: { limit: 500 } }),
      ])
      const supps: Supplier[] = suppRes.data.suppliers || suppRes.data || []
      setSuppliers(supps)
      const map: Record<string, string> = {}
      supps.forEach(s => { map[s.id] = s.name })
      setSupplierMap(map)

      // Build unified search items from catalogue parts
      const parts: CataloguePart[] = partsRes.data.parts || []
      const items: SearchItem[] = parts.map(p => ({
        id: p.id,
        name: p.name,
        sku: p.part_number,
        cost_price: Number(p.default_price) || 0,
        source: 'catalogue' as const,
      }))
      setSearchItems(items)
    } catch {
      // Fallback for suppliers
      try {
        const suppRes = await apiClient.get('/inventory/suppliers')
        const supps: Supplier[] = suppRes.data.suppliers || []
        setSuppliers(supps)
        const map: Record<string, string> = {}
        supps.forEach(s => { map[s.id] = s.name })
        setSupplierMap(map)
      } catch { /* non-blocking */ }
    }
  }, [])

  useEffect(() => { fetchOrders() }, [fetchOrders])
  useEffect(() => { fetchMeta() }, [fetchMeta])

  // Close supplier dropdown on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (supplierRef.current && !supplierRef.current.contains(e.target as Node)) {
        setSupplierDropdownOpen(false)
      }
      if (productRef.current && !productRef.current.contains(e.target as Node)) {
        setProductDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const totalPages = Math.ceil(total / pageSize)

  const openCreate = () => {
    setCreateSupplierId('')
    setCreateSupplierName('')
    setSupplierQuery('')
    setCreateExpectedDelivery('')
    setCreateNotes('')
    setCreateLines([])
    setCreateError('')
    setSelectedItem(null)
    setProductQuery('')
    setAddQty('')
    setAddCost('')
    setShowCreate(true)
  }

  // Supplier search helpers — show all when query empty, filter when typing
  const filteredSuppliers = supplierQuery.trim() === ''
    ? suppliers
    : suppliers.filter(s => s.name.toLowerCase().includes(supplierQuery.toLowerCase()))

  const selectSupplier = (s: Supplier) => {
    setCreateSupplierId(s.id)
    setCreateSupplierName(s.name)
    setSupplierQuery(s.name)
    setSupplierDropdownOpen(false)
  }

  const clearSupplier = () => {
    setCreateSupplierId('')
    setCreateSupplierName('')
    setSupplierQuery('')
  }

  const openAddSupplier = () => {
    setNewSupplier({ name: supplierQuery.trim(), contact_name: '', email: '', phone: '', address: '' })
    setAddSupplierError('')
    setShowAddSupplier(true)
  }

  const handleAddSupplier = async () => {
    if (!newSupplier.name.trim()) { setAddSupplierError('Supplier name is required.'); return }
    setAddSupplierSaving(true)
    setAddSupplierError('')
    try {
      const body: Record<string, string> = { name: newSupplier.name.trim() }
      if (newSupplier.contact_name.trim()) body.contact_name = newSupplier.contact_name.trim()
      if (newSupplier.email.trim()) body.email = newSupplier.email.trim()
      if (newSupplier.phone.trim()) body.phone = newSupplier.phone.trim()
      if (newSupplier.address.trim()) body.address = newSupplier.address.trim()
      const res = await apiClient.post('/inventory/suppliers', body)
      const created: Supplier = res.data.supplier || res.data
      // Add to local list and select it
      setSuppliers(prev => [...prev, created])
      setSupplierMap(prev => ({ ...prev, [created.id]: created.name }))
      selectSupplier(created)
      setShowAddSupplier(false)
    } catch (err) {
      setAddSupplierError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create supplier.')
    } finally { setAddSupplierSaving(false) }
  }

  const addLine = () => {
    if (!selectedItem) return
    const qty = parseFloat(addQty)
    const cost = parseFloat(addCost)
    if (isNaN(qty) || qty <= 0 || isNaN(cost) || cost < 0) return
    setCreateLines(prev => [...prev, {
      product_id: selectedItem.source === 'product' ? selectedItem.id : null,
      catalogue_item_id: selectedItem.source === 'catalogue' ? selectedItem.id : null,
      description: selectedItem.name,
      quantity: qty,
      unit_cost: cost,
    }])
    setSelectedItem(null)
    setProductQuery('')
    setAddQty('')
    setAddCost('')
  }

  const removeLine = (idx: number) => {
    setCreateLines(prev => prev.filter((_, i) => i !== idx))
  }

  const handleCreate = async () => {
    if (!createSupplierId) { setCreateError('Select a supplier.'); return }
    if (createLines.length === 0) { setCreateError('Add at least one line item.'); return }
    setCreateSaving(true)
    setCreateError('')
    try {
      await apiClient.post('/api/v2/purchase-orders', {
        supplier_id: createSupplierId,
        branch_id: selectedBranchId || undefined,
        expected_delivery: createExpectedDelivery || null,
        notes: createNotes.trim() || null,
        lines: createLines.map(l => ({
          product_id: l.product_id || null,
          catalogue_item_id: l.catalogue_item_id || null,
          description: l.description,
          quantity_ordered: l.quantity,
          unit_cost: l.unit_cost,
        })),
      })
      setShowCreate(false)
      fetchOrders()
    } catch (err) {
      setCreateError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create purchase order.')
    } finally { setCreateSaving(false) }
  }

  // Product/part search helpers
  const filteredItems = productQuery.trim() === ''
    ? searchItems
    : searchItems.filter(i =>
        i.name.toLowerCase().includes(productQuery.toLowerCase()) ||
        (i.sku && i.sku.toLowerCase().includes(productQuery.toLowerCase()))
      )

  const selectItem = (item: SearchItem) => {
    setSelectedItem(item)
    setProductQuery(item.name)
    setProductDropdownOpen(false)
    if (item.cost_price) setAddCost(String(item.cost_price))
  }

  const clearItem = () => {
    setSelectedItem(null)
    setProductQuery('')
    setAddCost('')
  }

  const openAddPart = () => {
    setNewPart({ name: productQuery.trim(), part_number: '', brand: '', default_price: '', description: '' })
    setAddPartError('')
    setShowAddPart(true)
  }

  const handleAddPart = async () => {
    if (!newPart.name.trim()) { setAddPartError('Part name is required.'); return }
    setAddPartSaving(true)
    setAddPartError('')
    try {
      const res = await apiClient.post('/catalogue/parts', {
        name: newPart.name.trim(),
        part_number: newPart.part_number.trim() || null,
        brand: newPart.brand.trim() || null,
        default_price: newPart.default_price ? Number(newPart.default_price) : 0,
        description: newPart.description.trim() || null,
        part_type: 'part',
      })
      const created = res.data.part || res.data
      const newItem: SearchItem = {
        id: created.id,
        name: created.name,
        sku: created.part_number || null,
        cost_price: Number(created.default_price) || 0,
        source: 'catalogue',
      }
      setSearchItems(prev => [...prev, newItem])
      selectItem(newItem)
      setShowAddPart(false)
    } catch (err) {
      setAddPartError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create part.')
    } finally { setAddPartSaving(false) }
  }

  const lineTotal = createLines.reduce((sum, l) => sum + l.quantity * l.unit_cost, 0)

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-text">Purchase Orders</h1>
        <Button onClick={openCreate}>+ New Purchase Order</Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <div className="w-48">
          <Select label="Status" options={STATUS_OPTIONS} value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }} />
        </div>
      </div>

      {loading ? (
        <div className="py-16 text-center"><Spinner label="Loading purchase orders" /></div>
      ) : orders.length === 0 ? (
        <div className="rounded-card border border-border bg-card p-12 text-center shadow-card">
          <p className="text-muted">No purchase orders found.</p>
          <Button className="mt-4" onClick={openCreate}>Create your first PO</Button>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full">
              <thead>
                <tr>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">PO Number</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Supplier</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Branch</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Expected Delivery</th>
                  <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
                  <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {orders.map(po => (
                  <tr key={po.id} className="border-b border-border last:border-b-0 hover:bg-canvas cursor-pointer" onClick={() => navigate(`/purchase-orders/${po.id}`)}>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm font-medium text-accent">{po.po_number}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{supplierMap[po.supplier_id] || po.supplier_id.slice(0, 8)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                      {po.branch_id ? ((branchList ?? []).find(b => b.id === po.branch_id)?.name ?? '—') : '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">{statusBadge(po.status)}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">{po.expected_delivery || '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-right font-medium text-text">{formatNZD(Number(po.total_amount))}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">{new Date(po.created_at).toLocaleDateString('en-NZ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted">{total} purchase order{total !== 1 ? 's' : ''}</p>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                <span className="flex items-center text-sm text-muted">Page {page} of {totalPages}</span>
                <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Create PO Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="New Purchase Order">
        <div className="space-y-4">
          {/* Supplier live search */}
          <div>
            <label className="block text-sm font-medium text-text mb-1">Supplier *</label>
            {createSupplierId ? (
              <div className="flex items-center gap-2 rounded-ctl border border-border bg-canvas px-3 py-2">
                <span className="flex-1 text-sm text-text">{createSupplierName}</span>
                <button type="button" onClick={clearSupplier} className="rounded p-1 text-muted-2 hover:text-text text-xs" aria-label="Change supplier">✕</button>
              </div>
            ) : (
              <div ref={supplierRef} className="relative">
                <input
                  type="text"
                  value={supplierQuery}
                  onChange={e => { setSupplierQuery(e.target.value); setSupplierDropdownOpen(true) }}
                  onFocus={() => setSupplierDropdownOpen(true)}
                  placeholder="Search or type supplier name…"
                  className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text placeholder:text-muted-2 focus:outline-none focus:ring-2 focus:ring-accent"
                  autoComplete="off"
                />
                {supplierDropdownOpen && (
                  <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-ctl border border-border bg-card shadow-pop">
                    {filteredSuppliers.length > 0 && filteredSuppliers.slice(0, 10).map(s => (
                      <button key={s.id} type="button" onClick={() => selectSupplier(s)}
                        className="w-full px-3 py-2 text-left text-sm hover:bg-canvas">
                        <span className="font-medium text-text">{s.name}</span>
                        {s.contact_name && <span className="ml-2 text-xs text-muted">{s.contact_name}</span>}
                      </button>
                    ))}
                    {filteredSuppliers.length === 0 && supplierQuery.length > 0 && (
                      <div className="px-3 py-2 text-sm text-muted">No suppliers match "{supplierQuery}"</div>
                    )}
                    {filteredSuppliers.length === 0 && supplierQuery.length === 0 && suppliers.length === 0 && (
                      <div className="px-3 py-2 text-sm text-muted">No suppliers yet</div>
                    )}
                    <button type="button" onClick={openAddSupplier}
                      className="w-full border-t border-border px-3 py-2 text-left text-sm font-medium text-accent hover:bg-accent-soft">
                      + Add New Supplier{supplierQuery.trim() ? ` "${supplierQuery.trim()}"` : ''}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          <Input label="Expected Delivery" type="date" value={createExpectedDelivery}
            onChange={e => setCreateExpectedDelivery(e.target.value)} />

          {/* Line items */}
          <div>
            <label className="block text-sm font-medium text-text mb-2">Line Items</label>
            <div className="flex gap-2 mb-2 items-end">
              {/* Product/part live search */}
              <div className="flex-1">
                <label className="block text-xs font-medium text-muted mb-1">Part / Product</label>
                {selectedItem ? (
                  <div className="flex items-center gap-2 rounded-ctl border border-border bg-canvas px-3 py-2 h-10">
                    <span className="flex-1 text-sm text-text truncate">{selectedItem.name}</span>
                    <button type="button" onClick={clearItem} className="text-muted-2 hover:text-text text-xs shrink-0">✕</button>
                  </div>
                ) : (
                  <div ref={productRef} className="relative">
                    <input
                      type="text"
                      value={productQuery}
                      onChange={e => { setProductQuery(e.target.value); setProductDropdownOpen(true) }}
                      onFocus={() => setProductDropdownOpen(true)}
                      placeholder="Search parts…"
                      className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm h-10 text-text placeholder:text-muted-2 focus:outline-none focus:ring-2 focus:ring-accent"
                      autoComplete="off"
                    />
                    {productDropdownOpen && (
                      <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-ctl border border-border bg-card shadow-pop">
                        {filteredItems.slice(0, 10).map(item => (
                          <button key={item.id} type="button" onClick={() => selectItem(item)}
                            className="w-full px-3 py-2 text-left text-sm hover:bg-canvas">
                            <div className="flex items-center justify-between">
                              <span className="font-medium text-text">{item.name}</span>
                              <span className="mono text-xs text-muted ml-2">{formatNZD(item.cost_price)}</span>
                            </div>
                            {item.sku && <div className="mono text-xs text-muted-2">{item.sku}</div>}
                          </button>
                        ))}
                        {filteredItems.length === 0 && productQuery.length > 0 && (
                          <div className="px-3 py-2 text-sm text-muted">No parts match "{productQuery}"</div>
                        )}
                        {filteredItems.length === 0 && productQuery.length === 0 && searchItems.length === 0 && (
                          <div className="px-3 py-2 text-sm text-muted">No parts in catalogue yet</div>
                        )}
                        <button type="button" onClick={openAddPart}
                          className="w-full border-t border-border px-3 py-2 text-left text-sm font-medium text-accent hover:bg-accent-soft">
                          + Add New Part{productQuery.trim() ? ` "${productQuery.trim()}"` : ''}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div className="w-20">
                <Input label="Qty" type="number" min="1" value={addQty}
                  onChange={e => setAddQty(e.target.value)} />
              </div>
              <div className="w-28">
                <Input label="Unit Cost" type="number" min="0" step="0.01" value={addCost}
                  onChange={e => setAddCost(e.target.value)} />
              </div>
              <div className="flex items-end">
                <Button size="sm" variant="ghost" onClick={addLine} disabled={!selectedItem || !addQty || !addCost}>Add</Button>
              </div>
            </div>

            {createLines.length > 0 && (
              <div className="rounded-ctl border border-border overflow-hidden">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr>
                      <th className="mono border-b border-border px-3 py-2 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Product</th>
                      <th className="mono border-b border-border px-3 py-2 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Qty</th>
                      <th className="mono border-b border-border px-3 py-2 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Unit Cost</th>
                      <th className="mono border-b border-border px-3 py-2 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
                      <th className="border-b border-border px-3 py-2 w-10"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {createLines.map((l, i) => (
                      <tr key={i} className="border-b border-border last:border-b-0">
                        <td className="px-3 py-2 text-text">{l.description}</td>
                        <td className="mono px-3 py-2 text-right">{l.quantity}</td>
                        <td className="mono px-3 py-2 text-right">{formatNZD(l.unit_cost)}</td>
                        <td className="mono px-3 py-2 text-right font-medium">{formatNZD(l.quantity * l.unit_cost)}</td>
                        <td className="px-3 py-2">
                          <button type="button" onClick={() => removeLine(i)} className="text-danger hover:brightness-90 text-xs">✕</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-canvas">
                    <tr>
                      <td colSpan={3} className="px-3 py-2 text-right text-sm font-medium text-muted">Total:</td>
                      <td className="mono px-3 py-2 text-right text-sm font-semibold text-text">{formatNZD(lineTotal)}</td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
            {createLines.length === 0 && <p className="text-sm text-muted-2 italic">No items added yet.</p>}
          </div>

          <div>
            <label className="block text-sm font-medium text-text mb-1">Notes</label>
            <textarea value={createNotes} onChange={e => setCreateNotes(e.target.value)} rows={2}
              placeholder="Optional notes…"
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent" />
          </div>

          {createError && <p className="text-sm text-danger">{createError}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} loading={createSaving}>Create Purchase Order</Button>
          </div>
        </div>
      </Modal>

      {/* Add Supplier Modal */}
      <Modal open={showAddSupplier} onClose={() => setShowAddSupplier(false)} title="New Supplier">
        <div className="space-y-3">
          <Input label="Supplier name *" value={newSupplier.name}
            onChange={e => setNewSupplier(prev => ({ ...prev, name: e.target.value }))} />
          <Input label="Contact person" value={newSupplier.contact_name}
            onChange={e => setNewSupplier(prev => ({ ...prev, contact_name: e.target.value }))} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Email" type="email" value={newSupplier.email}
              onChange={e => setNewSupplier(prev => ({ ...prev, email: e.target.value }))} />
            <Input label="Phone" value={newSupplier.phone}
              onChange={e => setNewSupplier(prev => ({ ...prev, phone: e.target.value }))} />
          </div>
          <Input label="Address" value={newSupplier.address}
            onChange={e => setNewSupplier(prev => ({ ...prev, address: e.target.value }))} />
          {addSupplierError && <p className="text-sm text-danger">{addSupplierError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowAddSupplier(false)}>Cancel</Button>
            <Button onClick={handleAddSupplier} loading={addSupplierSaving}>Create Supplier</Button>
          </div>
        </div>
      </Modal>

      {/* Add Part Modal */}
      <Modal open={showAddPart} onClose={() => setShowAddPart(false)} title="New Part">
        <div className="space-y-3">
          <Input label="Part name *" value={newPart.name}
            onChange={e => setNewPart(prev => ({ ...prev, name: e.target.value }))} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Part number / SKU" value={newPart.part_number}
              onChange={e => setNewPart(prev => ({ ...prev, part_number: e.target.value }))} />
            <Input label="Brand" value={newPart.brand}
              onChange={e => setNewPart(prev => ({ ...prev, brand: e.target.value }))} />
          </div>
          <Input label="Default price (ex-GST)" type="number" min="0" step="0.01" value={newPart.default_price}
            onChange={e => setNewPart(prev => ({ ...prev, default_price: e.target.value }))} />
          <div>
            <label className="block text-sm font-medium text-text mb-1">Description</label>
            <textarea value={newPart.description} onChange={e => setNewPart(prev => ({ ...prev, description: e.target.value }))}
              rows={2} placeholder="Optional description…"
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent" />
          </div>
          {addPartError && <p className="text-sm text-danger">{addPartError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowAddPart(false)}>Cancel</Button>
            <Button onClick={handleAddPart} loading={addPartSaving}>Create Part</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
