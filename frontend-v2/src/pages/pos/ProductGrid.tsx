/**
 * Product grid for POS with category tabs, search bar, and product tiles.
 *
 * Validates: Requirement 22.1 — POS product grid panel
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'
import type { POSProduct, POSCategory } from './types'

interface ProductGridProps {
  onSelectProduct: (product: POSProduct) => void
}

export default function ProductGrid({ onSelectProduct }: ProductGridProps) {
  const [products, setProducts] = useState<POSProduct[]>([])
  const [categories, setCategories] = useState<POSCategory[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page_size: '100' })
      if (search) params.set('search', search)
      if (selectedCategory) params.set('category_id', selectedCategory)
      const res = await apiClient.get(`/api/v2/products?${params}`)
      setProducts(res.data?.products ?? [])
    } catch {
      setProducts([])
    } finally {
      setLoading(false)
    }
  }, [search, selectedCategory])

  const fetchCategories = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/product-categories')
      setCategories(res.data?.categories ?? [])
    } catch {
      setCategories([])
    }
  }, [])

  useEffect(() => { fetchCategories() }, [fetchCategories])
  useEffect(() => { fetchProducts() }, [fetchProducts])

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <div className="p-3 border-b border-border">
        <label htmlFor="pos-search" className="sr-only">Search products</label>
        <input
          id="pos-search"
          type="search"
          placeholder="Search products…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          aria-label="Search products"
        />
      </div>

      {/* Category tabs */}
      <div className="flex gap-1 px-3 py-2 border-b border-border overflow-x-auto" role="tablist" aria-label="Product categories">
        <button
          role="tab"
          aria-selected={selectedCategory === ''}
          onClick={() => setSelectedCategory('')}
          className={`px-3 py-1.5 rounded-ctl text-sm font-medium whitespace-nowrap ${
            selectedCategory === '' ? 'bg-accent text-white' : 'bg-canvas text-text hover:bg-border'
          }`}
        >
          All
        </button>
        {categories.map((cat) => (
          <button
            key={cat.id}
            role="tab"
            aria-selected={selectedCategory === cat.id}
            onClick={() => setSelectedCategory(cat.id)}
            className={`px-3 py-1.5 rounded-ctl text-sm font-medium whitespace-nowrap ${
              selectedCategory === cat.id ? 'bg-accent text-white' : 'bg-canvas text-text hover:bg-border'
            }`}
          >
            {cat.name}
          </button>
        ))}
      </div>

      {/* Product tiles */}
      <div className="flex-1 overflow-y-auto p-3" role="tabpanel">
        {loading && (
          <p className="text-muted text-center py-8" role="status" aria-label="Loading products">Loading products…</p>
        )}
        {!loading && products.length === 0 && (
          <p className="text-muted text-center py-8">No products found.</p>
        )}
        {!loading && products.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3" role="list" aria-label="Product list">
            {products.map((product) => (
              <button
                key={product.id}
                role="listitem"
                onClick={() => onSelectProduct(product)}
                className="flex flex-col items-center p-3 min-h-[44px] rounded-ctl border border-border hover:border-accent hover:shadow-card transition-all bg-card text-left"
                aria-label={`Add ${product.name} — ${product.sale_price.toFixed(2)}`}
              >
                {product.images.length > 0 ? (
                  <img
                    src={product.images[0]}
                    alt={product.name}
                    className="w-16 h-16 object-cover rounded-ctl mb-2"
                  />
                ) : (
                  <div className="w-16 h-16 bg-canvas rounded-ctl mb-2 flex items-center justify-center text-muted-2 text-xs">
                    No img
                  </div>
                )}
                <span className="text-sm font-medium text-text text-center line-clamp-2">{product.name}</span>
                <span className="mono text-sm font-semibold text-accent mt-1">${product.sale_price.toFixed(2)}</span>
                {product.stock_quantity <= 0 && (
                  <span className="text-xs text-danger mt-0.5">Out of stock</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
