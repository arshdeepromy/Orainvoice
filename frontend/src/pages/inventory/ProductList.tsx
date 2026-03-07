import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Badge, Spinner, Pagination } from '../../components/ui'

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
  is_active: boolean
}

interface Category {
  id: string
  name: string
}

interface ProductListResponse {
  products: Product[]
  total: number
  page: number
  page_size: number
}

interface CategoryListResponse {
  categories: Category[]
  total: number
}

const PAGE_SIZE = 20

/**
 * Paginated product list with search, category filter, and barcode scan button.
 *
 * Validates: Requirement 9.1, 9.10
 */
export default function ProductList() {
  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [categories, setCategories] = useState<Category[]>([])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { page, page_size: PAGE_SIZE }
      if (search.trim()) params.search = search.trim()
      if (categoryFilter) params.category_id = categoryFilter
      const res = await apiClient.get<ProductListResponse>('/v2/products', { params })
      setProducts(res.data.products)
      setTotal(res.data.total)
    } catch {
      setError('Failed to load products.')
    } finally {
      setLoading(false)
    }
  }, [page, search, categoryFilter])

  const fetchCategories = useCallback(async () => {
    try {
      const res = await apiClient.get<CategoryListResponse>('/v2/product-categories')
      setCategories(res.data.categories)
    } catch {
      /* categories are optional filter, ignore errors */
    }
  }, [])

  useEffect(() => { fetchCategories() }, [fetchCategories])
  useEffect(() => { fetchProducts() }, [fetchProducts])

  const handleSearch = (value: string) => {
    setSearch(value)
    setPage(1)
  }

  const handleCategoryChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setCategoryFilter(e.target.value)
    setPage(1)
  }

  const handleScanBarcode = () => {
    // Placeholder — wired up in task 17.8
    alert('Barcode scanner will open here')
  }

  const categoryOptions = [
    { value: '', label: 'All categories' },
    ...categories.map((c) => ({ value: c.id, label: c.name })),
  ]

  const formatPrice = (v: string) => {
    const n = parseFloat(v)
    return isNaN(n) ? v : `$${n.toFixed(2)}`
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="w-64">
            <Input
              label="Search products"
              placeholder="Name, SKU, or barcode…"
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
              aria-label="Search products"
            />
          </div>
          <div className="w-48">
            <Select
              label="Category"
              options={categoryOptions}
              value={categoryFilter}
              onChange={handleCategoryChange}
            />
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={handleScanBarcode} aria-label="Scan barcode">
            📷 Scan Barcode
          </Button>
          <Button onClick={() => window.location.assign('/inventory/products/new')}>
            + New Product
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && products.length === 0 && (
        <div className="py-16"><Spinner label="Loading products" /></div>
      )}

      {!loading && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Product list</caption>
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
                      {search || categoryFilter ? 'No products match your filters.' : 'No products yet. Add your first product to get started.'}
                    </td>
                  </tr>
                ) : (
                  products.map((p) => {
                    const cat = categories.find((c) => c.id === p.category_id)
                    return (
                      <tr key={p.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => window.location.assign(`/inventory/products/${p.id}`)}>
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{p.name}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{p.sku || '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{cat?.name || '—'}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">{formatPrice(p.sale_price)}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-gray-900">{parseFloat(p.stock_quantity)}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                          <Badge variant={p.is_active ? 'success' : 'neutral'}>
                            {p.is_active ? 'Active' : 'Inactive'}
                          </Badge>
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
