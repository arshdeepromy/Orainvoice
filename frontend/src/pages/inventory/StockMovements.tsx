/**
 * Stock movements history with advanced stock adjustment workflow
 * supporting reasons and batch adjustments.
 *
 * Validates: Requirements 9.5, 9.7
 */

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Badge, Spinner, Pagination, Modal } from '@/components/ui'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useModuleGuard } from '@/hooks/useModuleGuard'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StockMovement {
  id: string
  product_id: string
  movement_type: string
  quantity_change: string
  resulting_quantity: string
  reference_type: string | null
  reference_id: string | null
  notes: string | null
  performed_by: string | null
  created_at: string
}

interface StockMovementListResponse {
  movements: StockMovement[]
  total: number
}

interface Product {
  id: string
  name: string
  stock_quantity: string
}

interface BatchAdjustmentLine {
  product_id: string
  product_name: string
  quantity_change: string
}

const MOVEMENT_TYPES = [
  { value: '', label: 'All types' },
  { value: 'sale', label: 'Sale' },
  { value: 'credit', label: 'Credit' },
  { value: 'receive', label: 'Receive' },
  { value: 'adjustment', label: 'Adjustment' },
  { value: 'transfer', label: 'Transfer' },
  { value: 'return', label: 'Return' },
  { value: 'stocktake', label: 'Stocktake' },
]

const ADJUSTMENT_REASONS = [
  { value: '', label: 'Select a reason…' },
  { value: 'damage', label: 'Damage' },
  { value: 'theft', label: 'Theft' },
  { value: 'expiry', label: 'Expiry' },
  { value: 'count_correction', label: 'Count Correction' },
  { value: 'other', label: 'Other' },
]

const PAGE_SIZE = 25

export default function StockMovements() {
  const { isAllowed, isLoading: guardLoading } = useModuleGuard('inventory')
  const productLabel = useTerm('product', 'Product')
  /* useFlag kept for FeatureFlagContext integration per Req 17.2 */
  useFlag('inventory')

  const [movements, setMovements] = useState<StockMovement[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [typeFilter, setTypeFilter] = useState('')
  const [productFilter, setProductFilter] = useState('')
  const [products, setProducts] = useState<Product[]>([])

  /* ---- Batch adjustment state ---- */
  const [adjustModalOpen, setAdjustModalOpen] = useState(false)
  const [adjustReason, setAdjustReason] = useState('')
  const [adjustCustomReason, setAdjustCustomReason] = useState('')
  const [adjustNotes, setAdjustNotes] = useState('')
  const [batchLines, setBatchLines] = useState<BatchAdjustmentLine[]>([])
  const [adjustSaving, setAdjustSaving] = useState(false)
  const [adjustError, setAdjustError] = useState('')
  const [adjustSuccess, setAdjustSuccess] = useState('')

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const fetchMovements = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { page, page_size: PAGE_SIZE }
      if (typeFilter) params.movement_type = typeFilter
      if (productFilter) params.product_id = productFilter
      const res = await apiClient.get<StockMovementListResponse>('/v2/stock-movements', { params })
      setMovements(res.data.movements)
      setTotal(res.data.total)
    } catch {
      setError('Failed to load stock movements.')
    } finally {
      setLoading(false)
    }
  }, [page, typeFilter, productFilter])

  const fetchProducts = useCallback(async () => {
    try {
      const res = await apiClient.get<{ products: Product[] }>('/v2/products', { params: { page_size: 500 } })
      setProducts(res.data.products)
    } catch { /* non-critical */ }
  }, [])

  useEffect(() => { fetchProducts() }, [fetchProducts])
  useEffect(() => { fetchMovements() }, [fetchMovements])

  const productOptions = [
    { value: '', label: `All ${productLabel.toLowerCase()}s` },
    ...products.map((p) => ({ value: p.id, label: p.name })),
  ]

  const productMap = new Map(products.map((p) => [p.id, p.name]))

  const movementBadgeVariant = (type: string) => {
    switch (type) {
      case 'sale': return 'error' as const
      case 'credit': case 'receive': case 'return': return 'success' as const
      case 'adjustment': case 'stocktake': return 'warning' as const
      default: return 'neutral' as const
    }
  }

  /* ---- Batch adjustment handlers ---- */
  const openAdjustModal = () => {
    setAdjustReason('')
    setAdjustCustomReason('')
    setAdjustNotes('')
    setBatchLines([{ product_id: '', product_name: '', quantity_change: '' }])
    setAdjustError('')
    setAdjustSuccess('')
    setAdjustModalOpen(true)
  }

  const addBatchLine = () => {
    setBatchLines((prev) => [...prev, { product_id: '', product_name: '', quantity_change: '' }])
  }

  const removeBatchLine = (idx: number) => {
    setBatchLines((prev) => prev.filter((_, i) => i !== idx))
  }

  const updateBatchLine = (idx: number, field: keyof BatchAdjustmentLine, value: string) => {
    setBatchLines((prev) => prev.map((line, i) => {
      if (i !== idx) return line
      if (field === 'product_id') {
        const prod = products.find((p) => p.id === value)
        return { ...line, product_id: value, product_name: prod?.name || '' }
      }
      return { ...line, [field]: value }
    }))
  }

  const handleBatchAdjust = async () => {
    const reason = adjustReason === 'other' ? adjustCustomReason.trim() : adjustReason
    if (!reason) { setAdjustError('Please select a reason.'); return }

    const validLines = batchLines.filter(
      (l) => l.product_id && l.quantity_change && !isNaN(parseFloat(l.quantity_change)) && parseFloat(l.quantity_change) !== 0,
    )
    if (validLines.length === 0) {
      setAdjustError(`Select at least one ${productLabel.toLowerCase()} with a non-zero quantity.`)
      return
    }

    setAdjustSaving(true)
    setAdjustError('')
    try {
      await apiClient.post('/v2/stock-movements/batch', {
        reason,
        notes: adjustNotes.trim() || undefined,
        adjustments: validLines.map((l) => ({
          product_id: l.product_id,
          quantity_change: parseFloat(l.quantity_change),
        })),
      })
      setAdjustSuccess(`${validLines.length} adjustment(s) applied successfully.`)
      fetchMovements()
      fetchProducts()
      setTimeout(() => setAdjustModalOpen(false), 1500)
    } catch {
      setAdjustError('Failed to apply batch adjustment.')
    } finally {
      setAdjustSaving(false)
    }
  }

  if (guardLoading) {
    return <div className="py-16"><Spinner label="Loading" /></div>
  }

  if (!isAllowed) return null

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="w-48">
            <Select
              label="Movement type"
              options={MOVEMENT_TYPES}
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value); setPage(1) }}
            />
          </div>
          <div className="w-64">
            <Select
              label={productLabel}
              options={productOptions}
              value={productFilter}
              onChange={(e) => { setProductFilter(e.target.value); setPage(1) }}
            />
          </div>
        </div>
        <Button onClick={openAdjustModal} style={{ minWidth: 44, minHeight: 44 }}>
          + Batch Adjustment
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && movements.length === 0 && (
        <div className="py-16"><Spinner label="Loading stock movements" /></div>
      )}

      {!loading && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Stock movements</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">{productLabel}</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Change</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Resulting</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reference</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {movements.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-500">
                      No stock movements found.
                    </td>
                  </tr>
                ) : (
                  movements.map((m) => {
                    const change = parseFloat(m.quantity_change)
                    return (
                      <tr key={m.id} className="hover:bg-gray-50">
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                          {new Date(m.created_at).toLocaleDateString('en-NZ')}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">
                          {productMap.get(m.product_id) || m.product_id.slice(0, 8)}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant={movementBadgeVariant(m.movement_type)}>{m.movement_type}</Badge>
                        </td>
                        <td className={`whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium ${change > 0 ? 'text-green-700' : 'text-red-700'}`}>
                          {change > 0 ? '+' : ''}{change}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">
                          {parseFloat(m.resulting_quantity)}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                          {m.reference_type || '—'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">
                          {m.notes || '—'}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={setPage}
            className="mt-4"
          />
        </>
      )}

      {/* Batch Adjustment Modal */}
      <Modal open={adjustModalOpen} onClose={() => setAdjustModalOpen(false)} title="Batch Stock Adjustment">
        <div className="space-y-3">
          <Select
            label="Adjustment reason *"
            options={ADJUSTMENT_REASONS}
            value={adjustReason}
            onChange={(e) => setAdjustReason(e.target.value)}
          />
          {adjustReason === 'other' && (
            <Input
              label="Custom reason *"
              value={adjustCustomReason}
              onChange={(e) => setAdjustCustomReason(e.target.value)}
              placeholder="Describe the reason"
            />
          )}
          <Input
            label="Reference notes"
            value={adjustNotes}
            onChange={(e) => setAdjustNotes(e.target.value)}
            placeholder="Optional reference or notes"
          />

          <div className="border-t border-gray-200 pt-3">
            <p className="text-sm font-medium text-gray-700 mb-2">{productLabel}s to adjust</p>
            {batchLines.map((line, idx) => (
              <div key={idx} className="flex gap-2 mb-2 items-end">
                <div className="flex-1">
                  <Select
                    label={idx === 0 ? productLabel : ''}
                    options={[{ value: '', label: `Select ${productLabel.toLowerCase()}…` }, ...products.map((p) => ({ value: p.id, label: p.name }))]}
                    value={line.product_id}
                    onChange={(e) => updateBatchLine(idx, 'product_id', e.target.value)}
                  />
                </div>
                <div className="w-32">
                  <Input
                    label={idx === 0 ? 'Qty change' : ''}
                    type="number"
                    inputMode="numeric"
                    placeholder="+10 or -5"
                    value={line.quantity_change}
                    onChange={(e) => updateBatchLine(idx, 'quantity_change', e.target.value)}
                  />
                </div>
                {batchLines.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeBatchLine(idx)}
                    className="text-red-500 hover:text-red-700 inline-flex items-center justify-center"
                    style={{ minWidth: 44, minHeight: 44 }}
                    aria-label={`Remove line ${idx + 1}`}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <Button variant="secondary" size="sm" onClick={addBatchLine} style={{ minWidth: 44, minHeight: 44 }}>
              + Add {productLabel}
            </Button>
          </div>
        </div>

        {adjustError && <p className="mt-2 text-sm text-red-600" role="alert">{adjustError}</p>}
        {adjustSuccess && <div className="mt-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700" role="status">{adjustSuccess}</div>}

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setAdjustModalOpen(false)} style={{ minWidth: 44, minHeight: 44 }}>Cancel</Button>
          <Button size="sm" onClick={handleBatchAdjust} loading={adjustSaving} style={{ minWidth: 44, minHeight: 44 }}>Apply Adjustments</Button>
        </div>
      </Modal>
    </div>
  )
}
