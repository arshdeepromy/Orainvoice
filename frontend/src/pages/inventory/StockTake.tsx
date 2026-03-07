import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Spinner, Badge } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Product {
  id: string
  name: string
  sku: string | null
  stock_quantity: string
  unit_of_measure: string
}

interface StocktakeLine {
  product_id: string
  product_name: string
  sku: string | null
  system_quantity: number
  counted_quantity: string
  unit_of_measure: string
}

interface StocktakeVarianceLine {
  product_id: string
  product_name: string
  system_quantity: string
  counted_quantity: string
  variance: string
}

interface StocktakeResponse {
  id: string
  lines: StocktakeVarianceLine[]
  status: string
  adjustments_applied: number
}

/**
 * Stock take page: enter counted quantities, see variance vs system, commit adjustments.
 *
 * Validates: Requirement 9.8
 */
export default function StockTake() {
  const [products, setProducts] = useState<Product[]>([])
  const [lines, setLines] = useState<StocktakeLine[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [result, setResult] = useState<StocktakeResponse | null>(null)

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ products: Product[] }>('/v2/products', { params: { page_size: 1000 } })
      const prods = res.data.products
      setProducts(prods)
      setLines(prods.map((p) => ({
        product_id: p.id,
        product_name: p.name,
        sku: p.sku,
        system_quantity: parseFloat(p.stock_quantity),
        counted_quantity: '',
        unit_of_measure: p.unit_of_measure,
      })))
    } catch {
      setError('Failed to load products.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchProducts() }, [fetchProducts])

  const updateCounted = (productId: string, value: string) => {
    setLines((prev) => prev.map((l) =>
      l.product_id === productId ? { ...l, counted_quantity: value } : l
    ))
  }

  const getVariance = (line: StocktakeLine): number | null => {
    if (line.counted_quantity === '') return null
    const counted = parseFloat(line.counted_quantity)
    if (isNaN(counted)) return null
    return counted - line.system_quantity
  }

  const varianceClass = (variance: number | null): string => {
    if (variance === null || variance === 0) return ''
    return variance > 0 ? 'bg-green-50' : 'bg-red-50'
  }

  const varianceTextClass = (variance: number | null): string => {
    if (variance === null || variance === 0) return 'text-gray-500'
    return variance > 0 ? 'text-green-700' : 'text-red-700'
  }

  const handlePreview = async () => {
    const filledLines = lines.filter((l) => l.counted_quantity !== '' && !isNaN(parseFloat(l.counted_quantity)))
    if (filledLines.length === 0) { setError('Enter counted quantities for at least one product.'); return }

    setSaving(true)
    setError('')
    try {
      const res = await apiClient.post<StocktakeResponse>('/v2/stocktakes', {
        lines: filledLines.map((l) => ({
          product_id: l.product_id,
          counted_quantity: parseFloat(l.counted_quantity),
        })),
      })
      setResult(res.data)
    } catch {
      setError('Failed to create stocktake.')
    } finally {
      setSaving(false)
    }
  }

  const handleCommit = async () => {
    if (!result) return
    setCommitting(true)
    setError('')
    try {
      const res = await apiClient.put<StocktakeResponse>(`/v2/stocktakes/${result.id}/commit`)
      setResult(res.data)
    } catch {
      setError('Failed to commit stocktake adjustments.')
    } finally {
      setCommitting(false)
    }
  }

  if (loading) {
    return <div className="py-16"><Spinner label="Loading products for stocktake" /></div>
  }

  /* ---- Results view ---- */
  if (result) {
    return (
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Stocktake {result.status === 'committed' ? 'Complete' : 'Preview'}
          </h2>
          {result.status !== 'committed' && (
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setResult(null)}>Back to Entry</Button>
              <Button onClick={handleCommit} loading={committing}>Commit Adjustments</Button>
            </div>
          )}
          {result.status === 'committed' && (
            <div className="flex gap-2 items-center">
              <Badge variant="success">{result.adjustments_applied} adjustments applied</Badge>
              <Button variant="secondary" onClick={() => { setResult(null); fetchProducts() }}>New Stocktake</Button>
            </div>
          )}
        </div>

        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Stocktake variance report</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Product</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">System Qty</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Counted Qty</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Variance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {result.lines.map((l) => {
                const variance = parseFloat(l.variance)
                return (
                  <tr key={l.product_id} className={variance > 0 ? 'bg-green-50' : variance < 0 ? 'bg-red-50' : ''}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{l.product_name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{parseFloat(l.system_quantity)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">{parseFloat(l.counted_quantity)}</td>
                    <td className={`whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-semibold ${variance > 0 ? 'text-green-700' : variance < 0 ? 'text-red-700' : 'text-gray-500'}`}>
                      {variance > 0 ? '+' : ''}{variance}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  /* ---- Entry view ---- */
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">
          Enter the counted quantity for each product. Leave blank to skip. Variances are highlighted.
        </p>
        <Button onClick={handlePreview} loading={saving}>Preview Variance</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {lines.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">No products to count.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Stocktake entry</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Product</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">SKU</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">System Qty</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Counted Qty</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Variance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {lines.map((l) => {
                const variance = getVariance(l)
                return (
                  <tr key={l.product_id} className={varianceClass(variance)}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{l.product_name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{l.sku || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{l.system_quantity}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <input
                        type="number"
                        step="any"
                        className="w-24 rounded-md border border-gray-300 px-2 py-1 text-sm text-right tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                        value={l.counted_quantity}
                        onChange={(e) => updateCounted(l.product_id, e.target.value)}
                        aria-label={`Counted quantity for ${l.product_name}`}
                      />
                    </td>
                    <td className={`whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-semibold ${varianceTextClass(variance)}`}>
                      {variance !== null ? (variance > 0 ? '+' : '') + variance : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
