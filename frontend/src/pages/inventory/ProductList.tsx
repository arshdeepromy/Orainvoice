/**
 * Product list with search, category filter, barcode scanning,
 * low-stock dashboard, and supplier catalogue integration view.
 *
 * Validates: Requirements 9.1, 9.6, 9.7, 9.8
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Badge, Spinner, Pagination } from '@/components/ui'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { scanBarcodeFromCamera } from '@/utils/barcodeScanner'
import { filterLowStockProducts } from '@/utils/inventoryCalcs'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Product {
  id: string
  name: string
  sku: string | null
  barcode: string | null
  category_id: string | null
  sale_price: string
  stock_quantity: string
  low_stock_threshold: string | null
  reorder_quantity: string | null
  supplier_id: string | null
  is_active: boolean
}

interface Category {
  id: string
  name: string
}

interface Supplier {
  id: string
  name: string
}

interface ProductListResponse {
  products: Product[]
  total: number
  page: number
  page_size: number
}

type ViewMode = 'products' | 'low-stock' | 'supplier-catalogue'

const PAGE_SIZE = 20

export default function ProductList() {
  const { isAllowed, isLoading: guardLoading } = useModuleGuard('inventory')
  const productLabel = useTerm('product', 'Product')
  /* useFlag kept for FeatureFlagContext integration per Req 17.2 */
  useFlag('inventory')

  const [products, setProducts] = useState<Product[]>([])
  const [allProducts, setAllProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [categories, setCategories] = useState<Category[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [viewMode, setViewMode] = useState<ViewMode>('products')
  const [scanning, setScanning] = useState(false)
  const [scanFeedback, setScanFeedback] = useState('')
  const [creatingPO, setCreatingPO] = useState<string | null>(null)

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { page, page_size: PAGE_SIZE }
      if (search.trim()) params.search = search.trim()
      if (categoryFilter) params.category_id = categoryFilter
      const res = await apiClient.get<ProductListResponse>('/v2/products', { params })
      setProducts(res.data?.products ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setError(`Failed to load ${productLabel.toLowerCase()}s.`)
    } finally {
      setLoading(false)
    }
  }, [page, search, categoryFilter, productLabel])

  const fetchAllProducts = useCallback(async () => {
    try {
      const res = await apiClient.get<ProductListResponse>('/v2/products', { params: { page_size: 1000 } })
      setAllProducts(res.data?.products ?? [])
    } catch { /* non-critical */ }
  }, [])

  const fetchCategories = useCallback(async () => {
    try {
      const res = await apiClient.get<{ categories: Category[] }>('/v2/product-categories')
      setCategories(res.data?.categories ?? [])
    } catch { /* non-critical */ }
  }, [])

  const fetchSuppliers = useCallback(async () => {
    try {
      const res = await apiClient.get<{ suppliers: Supplier[] }>('/v2/suppliers')
      setSuppliers(res.data?.suppliers ?? [])
    } catch { /* non-critical */ }
  }, [])

  useEffect(() => { fetchCategories() }, [fetchCategories])
  useEffect(() => { fetchSuppliers() }, [fetchSuppliers])
  useEffect(() => { fetchProducts() }, [fetchProducts])
  useEffect(() => { fetchAllProducts() }, [fetchAllProducts])

  const supplierMap = useMemo(() => new Map(suppliers.map((s) => [s.id, s.name])), [suppliers])
  const categoryMap = useMemo(() => new Map(categories.map((c) => [c.id, c.name])), [categories])

  /* ---- Low stock products ---- */
  const lowStockProducts = useMemo(() => {
    return filterLowStockProducts(
      allProducts
        .filter((p) => p.low_stock_threshold !== null)
        .map((p) => ({
          ...p,
          id: p.id,
          stock_level: parseFloat(p.stock_quantity),
          reorder_point: parseFloat(p.low_stock_threshold || '0'),
        })),
    )
  }, [allProducts])

  /* ---- Supplier catalogue ---- */
  const supplierCatalogue = useMemo(() => {
    const grouped = new Map<string, Product[]>()
    for (const p of allProducts) {
      if (!p.supplier_id) continue
      const existing = grouped.get(p.supplier_id) || []
      existing.push(p)
      grouped.set(p.supplier_id, existing)
    }
    return grouped
  }, [allProducts])

  const handleSearch = (value: string) => {
    setSearch(value)
    setPage(1)
  }

  const handleCategoryChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setCategoryFilter(e.target.value)
    setPage(1)
  }

  /* ---- Barcode scanning ---- */
  const handleScanBarcode = async () => {
    setScanning(true)
    setScanFeedback('')
    try {
      const result = await scanBarcodeFromCamera()
      if (result) {
        const matched = allProducts.find(
          (p) => p.barcode === result.rawValue || p.sku === result.rawValue,
        )
        if (matched) {
          setScanFeedback(`Found: ${matched.name}`)
          window.location.assign(`/inventory/products/${matched.id}`)
        } else {
          setScanFeedback(`Barcode "${result.rawValue}" not found.`)
        }
      } else {
        setScanFeedback('No barcode detected. Try again.')
      }
    } catch {
      setScanFeedback('Camera access failed.')
    } finally {
      setScanning(false)
    }
  }

  /* ---- Create Purchase Order from low stock ---- */
  const handleCreatePO = async (product: Product) => {
    setCreatingPO(product.id)
    try {
      await apiClient.post('/v2/purchase-orders', {
        supplier_id: product.supplier_id,
        lines: [{
          product_id: product.id,
          quantity: parseFloat(product.reorder_quantity || '1'),
          unit_price: parseFloat(product.sale_price),
        }],
        notes: `Auto-generated from low stock alert for ${product.name}`,
      })
      setScanFeedback(`Purchase order created for ${product.name}`)
    } catch {
      setError(`Failed to create purchase order for ${product.name}.`)
    } finally {
      setCreatingPO(null)
    }
  }

  const categoryOptions = [
    { value: '', label: 'All categories' },
    ...categories.map((c) => ({ value: c.id, label: c.name })),
  ]

  const formatPrice = (v: string) => {
    const n = parseFloat(v)
    return isNaN(n) ? v : `${n.toFixed(2)}`
  }

  if (guardLoading) {
    return <div className="py-16"><Spinner label="Loading" /></div>
  }

  if (!isAllowed) return null

  return (
    <div>
      {/* View mode tabs */}
      <div className="flex gap-2 mb-4 border-b border-gray-200 pb-2">
        {(['products', 'low-stock', 'supplier-catalogue'] as ViewMode[]).map((mode) => (
          <button
            key={mode}
            onClick={() => setViewMode(mode)}
            className={`px-4 py-2 text-sm font-medium rounded-t-md inline-flex items-center justify-center ${
              viewMode === mode
                ? 'bg-white border border-b-white border-gray-200 text-blue-600 -mb-px'
                : 'text-gray-500 hover:text-gray-700'
            }`}
            style={{ minWidth: 44, minHeight: 44 }}
          >
            {mode === 'products' && `${productLabel}s`}
            {mode === 'low-stock' && `Low Stock${lowStockProducts.length > 0 ? ` (${lowStockProducts.length})` : ''}`}
            {mode === 'supplier-catalogue' && 'Supplier Catalogue'}
          </button>
        ))}
      </div>

      {scanFeedback && (
        <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700" role="status">
          {scanFeedback}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {/* ---- Products view ---- */}
      {viewMode === 'products' && (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="w-64">
                <Input
                  label={`Search ${productLabel.toLowerCase()}s`}
                  placeholder="Name, SKU, or barcode…"
                  value={search}
                  onChange={(e) => handleSearch(e.target.value)}
                  aria-label={`Search ${productLabel.toLowerCase()}s`}
                />
              </div>
              <div className="w-48">
                <Select label="Category" options={categoryOptions} value={categoryFilter} onChange={handleCategoryChange} />
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={handleScanBarcode} loading={scanning} style={{ minWidth: 44, minHeight: 44 }} aria-label="Scan barcode">
                📷 Scan Barcode
              </Button>
              <Button onClick={() => window.location.assign('/inventory/products/new')} style={{ minWidth: 44, minHeight: 44 }}>
                + New {productLabel}
              </Button>
            </div>
          </div>

          {loading && products.length === 0 && (
            <div className="py-16"><Spinner label={`Loading ${productLabel.toLowerCase()}s`} /></div>
          )}

          {!loading && (
            <>
              <div className="overflow-x-auto rounded-lg border border-gray-200">
                <table className="min-w-full divide-y divide-gray-200" role="grid">
                  <caption className="sr-only">{productLabel} list</caption>
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                      <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">SKU</th>
                      <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                      <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price</th>
                      <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Stock Qty</th>
                      <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {products.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                          {search || categoryFilter ? `No ${productLabel.toLowerCase()}s match your filters.` : `No ${productLabel.toLowerCase()}s yet. Add your first ${productLabel.toLowerCase()} to get started.`}
                        </td>
                      </tr>
                    ) : (
                      products.map((p) => (
                        <tr key={p.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => window.location.assign(`/inventory/products/${p.id}`)}>
                          <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{p.name}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{p.sku || '—'}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{categoryMap.get(p.category_id || '') || '—'}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">{formatPrice(p.sale_price)}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-gray-900">{parseFloat(p.stock_quantity)}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                            <Badge variant={p.is_active ? 'success' : 'neutral'}>
                              {p.is_active ? 'Active' : 'Inactive'}
                            </Badge>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} className="mt-4" />
            </>
          )}
        </>
      )}

      {/* ---- Low Stock Dashboard ---- */}
      {viewMode === 'low-stock' && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            {productLabel}s at or below their configured reorder point. Click "Create PO" to generate a purchase order.
          </p>
          {lowStockProducts.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-500">
              All {productLabel.toLowerCase()}s are above their reorder points. 🎉
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200" role="grid">
                <caption className="sr-only">Low stock {productLabel.toLowerCase()}s</caption>
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">SKU</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Current Stock</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reorder Point</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reorder Qty</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Supplier</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {lowStockProducts.map((p) => (
                    <tr key={p.id} className="bg-amber-50/50 hover:bg-amber-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{p.name}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{p.sku || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-semibold text-red-700">{p.stock_level}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{p.reorder_point}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{p.reorder_quantity || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{supplierMap.get(p.supplier_id || '') || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <Button
                          size="sm"
                          onClick={() => handleCreatePO(p)}
                          loading={creatingPO === p.id}
                          disabled={!p.supplier_id}
                          style={{ minWidth: 44, minHeight: 44 }}
                          aria-label={`Create purchase order for ${p.name}`}
                        >
                          Create PO
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ---- Supplier Catalogue View ---- */}
      {viewMode === 'supplier-catalogue' && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            {productLabel}s grouped by preferred supplier with pricing and stock status.
          </p>
          {supplierCatalogue.size === 0 ? (
            <div className="py-12 text-center text-sm text-gray-500">
              No {productLabel.toLowerCase()}s have suppliers assigned yet.
            </div>
          ) : (
            <div className="space-y-6">
              {Array.from(supplierCatalogue.entries()).map(([supplierId, prods]) => (
                <div key={supplierId} className="rounded-lg border border-gray-200">
                  <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
                    <h3 className="text-sm font-semibold text-gray-900">
                      {supplierMap.get(supplierId) || 'Unknown Supplier'}
                    </h3>
                    <p className="text-xs text-gray-500">{prods.length} {productLabel.toLowerCase()}(s)</p>
                  </div>
                  <table className="min-w-full divide-y divide-gray-200" role="grid">
                    <thead className="bg-gray-50/50">
                      <tr>
                        <th scope="col" className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                        <th scope="col" className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">SKU</th>
                        <th scope="col" className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price</th>
                        <th scope="col" className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Stock</th>
                        <th scope="col" className="px-4 py-2 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {prods.map((p) => {
                        const stock = parseFloat(p.stock_quantity)
                        const threshold = parseFloat(p.low_stock_threshold || '0')
                        const isLow = p.low_stock_threshold !== null && stock <= threshold
                        return (
                          <tr key={p.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => window.location.assign(`/inventory/products/${p.id}`)}>
                            <td className="whitespace-nowrap px-4 py-2 text-sm font-medium text-gray-900">{p.name}</td>
                            <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-700">{p.sku || '—'}</td>
                            <td className="whitespace-nowrap px-4 py-2 text-sm text-right tabular-nums text-gray-900">{formatPrice(p.sale_price)}</td>
                            <td className="whitespace-nowrap px-4 py-2 text-sm text-right tabular-nums font-medium text-gray-900">{stock}</td>
                            <td className="whitespace-nowrap px-4 py-2 text-sm text-center">
                              <Badge variant={isLow ? 'warning' : 'success'}>{isLow ? 'Low Stock' : 'OK'}</Badge>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
