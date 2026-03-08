/**
 * Product detail page with tabs: Details, Stock History, Pricing Rules.
 * Supports create (no id) and edit (with id) modes.
 * Integrates barcode scanning for product lookup.
 *
 * Validates: Requirements 9.1, 9.7, 9.8
 */

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Tabs, Spinner, Badge } from '@/components/ui'
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
  category_id: string | null
  description: string | null
  unit_of_measure: string
  sale_price: string
  cost_price: string | null
  tax_applicable: boolean
  tax_rate_override: string | null
  stock_quantity: string
  low_stock_threshold: string | null
  reorder_quantity: string | null
  allow_backorder: boolean
  supplier_id: string | null
  supplier_sku: string | null
  images: string[]
  is_active: boolean
}

interface StockMovement {
  id: string
  movement_type: string
  quantity_change: string
  resulting_quantity: string
  reference_type: string | null
  notes: string | null
  created_at: string
}

interface PricingRule {
  id: string
  rule_type: string
  priority: number
  price_override: string | null
  discount_percent: string | null
  start_date: string | null
  end_date: string | null
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

interface ProductForm {
  name: string
  sku: string
  barcode: string
  category_id: string
  description: string
  unit_of_measure: string
  sale_price: string
  cost_price: string
  tax_applicable: boolean
  low_stock_threshold: string
  reorder_quantity: string
  allow_backorder: boolean
  supplier_id: string
  supplier_sku: string
}

const UOM_OPTIONS = [
  { value: 'each', label: 'Each' },
  { value: 'kg', label: 'Kilogram (kg)' },
  { value: 'litre', label: 'Litre' },
  { value: 'metre', label: 'Metre' },
  { value: 'hour', label: 'Hour' },
  { value: 'box', label: 'Box' },
  { value: 'pack', label: 'Pack' },
]

export default function ProductDetail({ productId }: { productId?: string }) {
  const { isAllowed, isLoading: guardLoading } = useModuleGuard('inventory')
  const productLabel = useTerm('product', 'Product')
  /* useFlag kept for FeatureFlagContext integration per Req 17.2 */
  useFlag('inventory')

  const [product, setProduct] = useState<Product | null>(null)
  const [loading, setLoading] = useState(!!productId)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')

  const [categories, setCategories] = useState<Category[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [movements, setMovements] = useState<StockMovement[]>([])
  const [pricingRules, setPricingRules] = useState<PricingRule[]>([])
  const [scanning, setScanning] = useState(false)

  const [form, setForm] = useState<ProductForm>({
    name: '', sku: '', barcode: '', category_id: '', description: '',
    unit_of_measure: 'each', sale_price: '', cost_price: '',
    tax_applicable: true, low_stock_threshold: '', reorder_quantity: '',
    allow_backorder: false, supplier_id: '', supplier_sku: '',
  })

  const [imageFiles, setImageFiles] = useState<File[]>([])
  const [existingImages, setExistingImages] = useState<string[]>([])

  const fetchProduct = useCallback(async () => {
    if (!productId) return
    setLoading(true)
    try {
      const res = await apiClient.get<Product>(`/v2/products/${productId}`)
      const p = res.data
      setProduct(p)
      setExistingImages(p.images || [])
      setForm({
        name: p.name, sku: p.sku || '', barcode: p.barcode || '',
        category_id: p.category_id || '', description: p.description || '',
        unit_of_measure: p.unit_of_measure, sale_price: p.sale_price,
        cost_price: p.cost_price || '', tax_applicable: p.tax_applicable,
        low_stock_threshold: p.low_stock_threshold || '',
        reorder_quantity: p.reorder_quantity || '',
        allow_backorder: p.allow_backorder, supplier_id: p.supplier_id || '',
        supplier_sku: p.supplier_sku || '',
      })
    } catch {
      setError(`Failed to load ${productLabel.toLowerCase()}.`)
    } finally {
      setLoading(false)
    }
  }, [productId, productLabel])

  const fetchRelated = useCallback(async () => {
    try {
      const [catRes, supRes] = await Promise.all([
        apiClient.get<{ categories: Category[] }>('/v2/product-categories'),
        apiClient.get<{ suppliers: Supplier[] }>('/v2/suppliers'),
      ])
      setCategories(catRes.data.categories)
      setSuppliers(supRes.data.suppliers)
    } catch { /* non-critical */ }
  }, [])

  const fetchMovements = useCallback(async () => {
    if (!productId) return
    try {
      const res = await apiClient.get<{ movements: StockMovement[] }>('/v2/stock-movements', {
        params: { product_id: productId },
      })
      setMovements(res.data.movements)
    } catch { /* non-critical */ }
  }, [productId])

  const fetchPricingRules = useCallback(async () => {
    if (!productId) return
    try {
      const res = await apiClient.get<{ rules: PricingRule[] }>('/v2/pricing-rules', {
        params: { product_id: productId },
      })
      setPricingRules(res.data.rules)
    } catch { /* non-critical */ }
  }, [productId])

  useEffect(() => { fetchProduct() }, [fetchProduct])
  useEffect(() => { fetchRelated() }, [fetchRelated])
  useEffect(() => { fetchMovements() }, [fetchMovements])
  useEffect(() => { fetchPricingRules() }, [fetchPricingRules])

  const updateField = <K extends keyof ProductForm>(key: K, value: ProductForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  /* ---- Barcode scanning to fill barcode field ---- */
  const handleScanBarcode = async () => {
    setScanning(true)
    try {
      const result = await scanBarcodeFromCamera()
      if (result) {
        updateField('barcode', result.rawValue)
      }
    } catch { /* ignore */ }
    finally {
      setScanning(false)
    }
  }

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    const totalImages = existingImages.length + imageFiles.length + files.length
    if (totalImages > 5) {
      setFormError('Maximum 5 images allowed.')
      return
    }
    setImageFiles((prev) => [...prev, ...files])
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')
    setSuccess('')

    if (!form.name.trim()) { setFormError(`${productLabel} name is required.`); return }
    if (!form.sale_price || isNaN(parseFloat(form.sale_price))) { setFormError('Valid sale price is required.'); return }

    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        sale_price: parseFloat(form.sale_price),
        unit_of_measure: form.unit_of_measure,
        tax_applicable: form.tax_applicable,
        allow_backorder: form.allow_backorder,
        images: existingImages,
      }
      if (form.sku.trim()) body.sku = form.sku.trim()
      if (form.barcode.trim()) body.barcode = form.barcode.trim()
      if (form.category_id) body.category_id = form.category_id
      if (form.description.trim()) body.description = form.description.trim()
      if (form.cost_price) body.cost_price = parseFloat(form.cost_price)
      if (form.low_stock_threshold) body.low_stock_threshold = parseFloat(form.low_stock_threshold)
      if (form.reorder_quantity) body.reorder_quantity = parseFloat(form.reorder_quantity)
      if (form.supplier_id) body.supplier_id = form.supplier_id
      if (form.supplier_sku.trim()) body.supplier_sku = form.supplier_sku.trim()

      if (productId) {
        await apiClient.put(`/v2/products/${productId}`, body)
        setSuccess(`${productLabel} updated successfully.`)
        fetchProduct()
      } else {
        const res = await apiClient.post<Product>('/v2/products', body)
        setSuccess(`${productLabel} created successfully.`)
        window.location.assign(`/inventory/products/${res.data.id}`)
      }
    } catch {
      setFormError(`Failed to save ${productLabel.toLowerCase()}.`)
    } finally {
      setSaving(false)
    }
  }

  const categoryOptions = [
    { value: '', label: 'No category' },
    ...categories.map((c) => ({ value: c.id, label: c.name })),
  ]

  const supplierOptions = [
    { value: '', label: 'No supplier' },
    ...suppliers.map((s) => ({ value: s.id, label: s.name })),
  ]

  if (guardLoading) {
    return <div className="py-16"><Spinner label="Loading" /></div>
  }

  if (!isAllowed) return null

  if (loading) {
    return <div className="py-16"><Spinner label={`Loading ${productLabel.toLowerCase()}`} /></div>
  }

  if (error) {
    return <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
  }

  /* ---- Details Tab ---- */
  const detailsTab = (
    <form onSubmit={handleSave} className="max-w-2xl space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input label={`${productLabel} name *`} value={form.name} onChange={(e) => updateField('name', e.target.value)} />
        <Input label="SKU" value={form.sku} onChange={(e) => updateField('sku', e.target.value)} placeholder="Auto-generated if blank" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <Input label="Barcode" value={form.barcode} onChange={(e) => updateField('barcode', e.target.value)} />
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={handleScanBarcode}
            loading={scanning}
            style={{ minWidth: 44, minHeight: 44 }}
            aria-label="Scan barcode"
          >
            📷
          </Button>
        </div>
        <Select label="Category" options={categoryOptions} value={form.category_id} onChange={(e) => updateField('category_id', e.target.value)} />
      </div>
      <div>
        <label htmlFor="description" className="text-sm font-medium text-gray-700">Description</label>
        <textarea
          id="description"
          className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          rows={3}
          value={form.description}
          onChange={(e) => updateField('description', e.target.value)}
        />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Input label="Sale price *" inputMode="numeric" type="number" step="0.01" value={form.sale_price} onChange={(e) => updateField('sale_price', e.target.value)} />
        <Input label="Cost price" inputMode="numeric" type="number" step="0.01" value={form.cost_price} onChange={(e) => updateField('cost_price', e.target.value)} />
        <Select label="Unit of measure" options={UOM_OPTIONS} value={form.unit_of_measure} onChange={(e) => updateField('unit_of_measure', e.target.value)} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Select label="Supplier" options={supplierOptions} value={form.supplier_id} onChange={(e) => updateField('supplier_id', e.target.value)} />
        <Input label="Supplier SKU" value={form.supplier_sku} onChange={(e) => updateField('supplier_sku', e.target.value)} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input label="Low stock threshold" inputMode="numeric" type="number" step="1" value={form.low_stock_threshold} onChange={(e) => updateField('low_stock_threshold', e.target.value)} />
        <Input label="Reorder quantity" inputMode="numeric" type="number" step="1" value={form.reorder_quantity} onChange={(e) => updateField('reorder_quantity', e.target.value)} />
      </div>
      <div className="flex gap-6">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.tax_applicable} onChange={(e) => updateField('tax_applicable', e.target.checked)} className="rounded border-gray-300" />
          Tax applicable
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.allow_backorder} onChange={(e) => updateField('allow_backorder', e.target.checked)} className="rounded border-gray-300" />
          Allow backorder
        </label>
      </div>

      {/* Image upload */}
      <div>
        <label className="text-sm font-medium text-gray-700">{productLabel} images (max 5)</label>
        <div className="mt-1 flex flex-wrap gap-2">
          {existingImages.map((url, i) => (
            <div key={i} className="relative w-20 h-20 rounded border border-gray-200 overflow-hidden">
              <img src={url} alt={`${productLabel} image ${i + 1}`} className="w-full h-full object-cover" />
              <button
                type="button"
                onClick={() => setExistingImages((prev) => prev.filter((_, idx) => idx !== i))}
                className="absolute top-0 right-0 bg-red-500 text-white text-xs px-1 rounded-bl"
                style={{ minWidth: 44, minHeight: 44 }}
                aria-label={`Remove image ${i + 1}`}
              >×</button>
            </div>
          ))}
          {imageFiles.map((f, i) => (
            <div key={`new-${i}`} className="w-20 h-20 rounded border border-blue-200 bg-blue-50 flex items-center justify-center text-xs text-blue-700 overflow-hidden">
              {f.name.slice(0, 10)}
            </div>
          ))}
        </div>
        {existingImages.length + imageFiles.length < 5 && (
          <input type="file" accept="image/*" multiple onChange={handleImageUpload} className="mt-2 text-sm" aria-label={`Upload ${productLabel.toLowerCase()} images`} />
        )}
      </div>

      {formError && <p className="text-sm text-red-600" role="alert">{formError}</p>}
      {success && <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700" role="status">{success}</div>}

      <div className="flex gap-2">
        <Button type="submit" loading={saving} style={{ minWidth: 44, minHeight: 44 }}>{productId ? 'Save Changes' : `Create ${productLabel}`}</Button>
        <Button type="button" variant="secondary" onClick={() => window.history.back()} style={{ minWidth: 44, minHeight: 44 }}>Cancel</Button>
      </div>
    </form>
  )

  /* ---- Stock History Tab ---- */
  const stockHistoryTab = (
    <div>
      {product && (
        <div className="mb-4 rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
          Current stock: <span className="font-semibold">{parseFloat(product.stock_quantity)}</span> {product.unit_of_measure}
        </div>
      )}
      {movements.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">No stock movements recorded yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Stock movement history</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Change</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Resulting</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {movements.map((m) => {
                const change = parseFloat(m.quantity_change)
                return (
                  <tr key={m.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{new Date(m.created_at).toLocaleDateString('en-NZ')}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <Badge variant={change > 0 ? 'success' : change < 0 ? 'error' : 'neutral'}>{m.movement_type}</Badge>
                    </td>
                    <td className={`whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium ${change > 0 ? 'text-green-700' : 'text-red-700'}`}>
                      {change > 0 ? '+' : ''}{change}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">{parseFloat(m.resulting_quantity)}</td>
                    <td className="px-4 py-3 text-sm text-gray-700">{m.notes || m.reference_type || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  /* ---- Pricing Rules Tab ---- */
  const pricingRulesTab = (
    <div>
      {pricingRules.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">No pricing rules configured for this {productLabel.toLowerCase()}.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Pricing rules</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Priority</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price / Discount</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date Range</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {pricingRules.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{r.priority}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{r.rule_type}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">
                    {r.price_override ? `${parseFloat(r.price_override).toFixed(2)}` : r.discount_percent ? `${r.discount_percent}% off` : '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                    {r.start_date || r.end_date ? `${r.start_date || '…'} – ${r.end_date || '…'}` : 'Always'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                    <Badge variant={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  const tabs = [
    { id: 'details', label: 'Details', content: detailsTab },
    ...(productId ? [
      { id: 'stock-history', label: 'Stock History', content: stockHistoryTab },
      { id: 'pricing-rules', label: 'Pricing Rules', content: pricingRulesTab },
    ] : []),
  ]

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">
        {productId ? (product?.name || productLabel) : `New ${productLabel}`}
      </h1>
      <Tabs tabs={tabs} defaultTab="details" />
    </div>
  )
}
