import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Input, Select, Badge, Spinner, Pagination } from '../../components/ui'

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

const PAGE_SIZE = 25

/**
 * Filterable stock movement history across all products.
 *
 * Validates: Requirement 9.7
 */
export default function StockMovements() {
  const [movements, setMovements] = useState<StockMovement[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [typeFilter, setTypeFilter] = useState('')
  const [productFilter, setProductFilter] = useState('')
  const [products, setProducts] = useState<Product[]>([])

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
    { value: '', label: 'All products' },
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

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end mb-4">
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
            label="Product"
            options={productOptions}
            value={productFilter}
            onChange={(e) => { setProductFilter(e.target.value); setPage(1) }}
          />
        </div>
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
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Product</th>
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
    </div>
  )
}
