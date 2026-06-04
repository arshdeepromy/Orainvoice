/**
 * StockTake — Task 36 port of frontend/src/pages/inventory/StockTake.tsx.
 *
 * Stock take page: enter counted quantities, see variance vs system, commit
 * adjustments. Integrates barcode scanning for product lookup. ALL logic —
 * the module guard, product fetch from /v2/products, counted-quantity entry,
 * variance calculation, barcode scan + matched-row focus, preview POST to
 * /v2/stocktakes and commit PUT /v2/stocktakes/:id/commit — copied VERBATIM.
 * Presentation remapped onto the design tokens (FR-2b); the page is wrapped in
 * a `page page-wide` + `.page-head` so it is reachable standalone.
 *
 * Validates: Requirements 9.5, 9.8
 */

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Spinner, Badge } from '@/components/ui'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { scanBarcodeFromCamera } from '@/utils/barcodeScanner'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Product {
  id: string
  name: string
  sku: string | null
  barcode: string | null
  stock_quantity: string
  unit_of_measure: string
}

interface StocktakeLine {
  product_id: string
  product_name: string
  sku: string | null
  barcode: string | null
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

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_C = 'mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

export default function StockTake() {
  const { isAllowed, isLoading: guardLoading } = useModuleGuard('inventory')
  const productLabel = useTerm('product', 'Product')
  /* useFlag kept for FeatureFlagContext integration per Req 17.2 */
  useFlag('inventory')

  const [, setProducts] = useState<Product[]>([])
  const [lines, setLines] = useState<StocktakeLine[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [result, setResult] = useState<StocktakeResponse | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanFeedback, setScanFeedback] = useState('')

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ products: Product[] }>('/v2/products', { params: { page_size: 1000 } })
      const prods = res.data?.products ?? []
      setProducts(prods)
      setLines(prods.map((p) => ({
        product_id: p.id,
        product_name: p.name,
        sku: p.sku,
        barcode: p.barcode,
        system_quantity: parseFloat(p.stock_quantity),
        counted_quantity: '',
        unit_of_measure: p.unit_of_measure,
      })))
    } catch {
      setError(`Failed to load ${productLabel.toLowerCase()}s.`)
    } finally {
      setLoading(false)
    }
  }, [productLabel])

  useEffect(() => { fetchProducts() }, [fetchProducts])

  const updateCounted = (productId: string, value: string) => {
    setLines((prev) => prev.map((l) =>
      l.product_id === productId ? { ...l, counted_quantity: value } : l,
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
    return variance > 0 ? 'bg-ok-soft/50' : 'bg-danger-soft/50'
  }

  const varianceTextClass = (variance: number | null): string => {
    if (variance === null || variance === 0) return 'text-muted'
    return variance > 0 ? 'text-ok' : 'text-danger'
  }

  /* ---- Barcode scanning ---- */
  const handleScanBarcode = async () => {
    setScanning(true)
    setScanFeedback('')
    try {
      const result = await scanBarcodeFromCamera()
      if (result) {
        const matchedLine = lines.find(
          (l) => l.barcode === result.rawValue || l.sku === result.rawValue,
        )
        if (matchedLine) {
          setScanFeedback(`Found: ${matchedLine.product_name}`)
          // Focus the counted quantity input for the matched product
          const el = document.querySelector<HTMLInputElement>(
            `[data-product-id="${matchedLine.product_id}"]`,
          )
          if (el) {
            el.focus()
            el.scrollIntoView({ behavior: 'smooth', block: 'center' })
          }
        } else {
          setScanFeedback(`Barcode "${result.rawValue}" not found in ${productLabel.toLowerCase()} list.`)
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

  const handlePreview = async () => {
    const filledLines = lines.filter((l) => l.counted_quantity !== '' && !isNaN(parseFloat(l.counted_quantity)))
    if (filledLines.length === 0) { setError(`Enter counted quantities for at least one ${productLabel.toLowerCase()}.`); return }

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

  if (guardLoading) {
    return <div className="py-16"><Spinner label="Loading" /></div>
  }

  if (!isAllowed) return null

  if (loading) {
    return <div className="py-16"><Spinner label={`Loading ${productLabel.toLowerCase()}s for stocktake`} /></div>
  }

  /* ---- Results view ---- */
  if (result) {
    return (
      <div className="page page-wide">
        <div className="page-head">
          <div>
            <div className="eyebrow">Stock</div>
            <h1>Stock Take</h1>
            <p className="sub">Variance report</p>
          </div>
        </div>

        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-text">
            Stocktake {result.status === 'committed' ? 'Complete' : 'Preview'}
          </h2>
          {result.status !== 'committed' && (
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setResult(null)} style={{ minWidth: 44, minHeight: 44 }}>Back to Entry</Button>
              <Button onClick={handleCommit} loading={committing} style={{ minWidth: 44, minHeight: 44 }}>Commit Adjustments</Button>
            </div>
          )}
          {result.status === 'committed' && (
            <div className="flex gap-2 items-center">
              <Badge variant="success">{result.adjustments_applied} adjustments applied</Badge>
              <Button variant="ghost" onClick={() => { setResult(null); fetchProducts() }} style={{ minWidth: 44, minHeight: 44 }}>New Stocktake</Button>
            </div>
          )}
        </div>

        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
          <table className="w-full border-collapse" role="grid">
            <caption className="sr-only">Stocktake variance report</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>{productLabel}</th>
                <th scope="col" className={TH_R}>System Qty</th>
                <th scope="col" className={TH_R}>Counted Qty</th>
                <th scope="col" className={TH_R}>Variance</th>
              </tr>
            </thead>
            <tbody>
              {result.lines.map((l) => {
                const variance = parseFloat(l.variance)
                return (
                  <tr key={l.product_id} className={`border-b border-border last:border-b-0 ${variance > 0 ? 'bg-ok-soft/50' : variance < 0 ? 'bg-danger-soft/50' : ''}`}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-text">{l.product_name}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-right text-muted">{parseFloat(l.system_quantity)}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-right text-text">{parseFloat(l.counted_quantity)}</td>
                    <td className={`mono whitespace-nowrap px-4 py-3 text-sm text-right font-semibold ${variance > 0 ? 'text-ok' : variance < 0 ? 'text-danger' : 'text-muted'}`}>
                      {variance > 0 ? '+' : ''}{variance}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
        </section>
      </div>
    )
  }

  /* ---- Entry view ---- */
  return (
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Stock</div>
          <h1>Stock Take</h1>
          <p className="sub">Count stock and review variances</p>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-[13px] text-muted">
          Enter the counted quantity for each {productLabel.toLowerCase()}. Leave blank to skip. Variances are highlighted.
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={handleScanBarcode} loading={scanning} style={{ minWidth: 44, minHeight: 44 }}>
            📷 Scan Barcode
          </Button>
          <Button onClick={handlePreview} loading={saving} style={{ minWidth: 44, minHeight: 44 }}>Preview Variance</Button>
        </div>
      </div>

      {scanFeedback && (
        <div className="mb-4 rounded-ctl border border-accent/30 bg-accent-soft px-4 py-3 text-[13px] text-accent" role="status">
          {scanFeedback}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">{error}</div>
      )}

      {lines.length === 0 ? (
        <p className="text-[13px] text-muted py-8 text-center">No {productLabel.toLowerCase()}s to count.</p>
      ) : (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
          <table className="w-full border-collapse" role="grid">
            <caption className="sr-only">Stocktake entry</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>{productLabel}</th>
                <th scope="col" className={TH}>SKU</th>
                <th scope="col" className={TH_R}>System Qty</th>
                <th scope="col" className={TH_C}>Counted Qty</th>
                <th scope="col" className={TH_R}>Variance</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const variance = getVariance(l)
                return (
                  <tr key={l.product_id} className={`border-b border-border last:border-b-0 hover:bg-canvas ${varianceClass(variance)}`}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-text">{l.product_name}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{l.sku || '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-right text-muted">{l.system_quantity}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <input
                        type="number"
                        inputMode="numeric"
                        step="any"
                        className="mono w-24 rounded-ctl border border-border bg-card px-2 py-1 text-sm text-right text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                        style={{ minHeight: 44 }}
                        value={l.counted_quantity}
                        onChange={(e) => updateCounted(l.product_id, e.target.value)}
                        aria-label={`Counted quantity for ${l.product_name}`}
                        data-product-id={l.product_id}
                      />
                    </td>
                    <td className={`mono whitespace-nowrap px-4 py-3 text-sm text-right font-semibold ${varianceTextClass(variance)}`}>
                      {variance !== null ? (variance > 0 ? '+' : '') + variance : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
        </section>
      )}
    </div>
  )
}
