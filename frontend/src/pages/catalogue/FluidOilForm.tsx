import { useState, useMemo, useEffect, useRef } from 'react'
import { Button, Badge, Modal } from '@/components/ui'

/* ── Types ── */
type FluidType = 'oil' | 'non-oil' | ''
type OilType = 'engine' | 'hydraulic' | 'brake' | 'gear' | 'transmission' | 'power_steering' | ''
type SyntheticType = 'semi_synthetic' | 'full_synthetic' | 'mineral' | ''
type UnitType = 'litre' | 'gallon'
type ContainerType = 'drum' | 'box' | 'bottle' | 'bulk_bag' | ''
type GstMode = 'inclusive' | 'exclusive' | 'exempt' | ''

interface FluidFormData {
  fluid_type: FluidType
  oil_type: OilType
  grade: string
  synthetic_type: SyntheticType
  qty_per_pack: string
  unit_type: UnitType
  container_type: ContainerType
  total_quantity: string
  purchase_price: string
  gst_mode: GstMode
  sell_price_per_unit: string
  brand_name: string
  product_name: string
  description: string
  pack_size: string
}

const EMPTY: FluidFormData = {
  fluid_type: '', oil_type: '', grade: '', synthetic_type: '',
  qty_per_pack: '', unit_type: 'litre', container_type: '', total_quantity: '',
  purchase_price: '', gst_mode: '', sell_price_per_unit: '',
  brand_name: '', product_name: '', description: '', pack_size: '',
}

const OIL_TYPES = [
  { value: 'engine', label: 'Engine Oil' },
  { value: 'hydraulic', label: 'Hydraulic Oil' },
  { value: 'brake', label: 'Brake Oil' },
  { value: 'gear', label: 'Gear Oil' },
  { value: 'transmission', label: 'Transmission Oil' },
  { value: 'power_steering', label: 'Power Steering Oil' },
]

const CONTAINER_TYPES = [
  { value: 'drum', label: 'Drum' },
  { value: 'box', label: 'Box' },
  { value: 'bottle', label: 'Bottle' },
  { value: 'bulk_bag', label: 'Bulk Bag' },
]

function formatNZD(v: number) {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(v)
}

/* ── Segmented toggle ── */
function SegmentedToggle<T extends string>({ options, value, onChange, label, required }: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  label: string
  required?: boolean
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}{required && ' *'}</label>
      <div className="inline-flex rounded-md border border-gray-300 overflow-hidden w-full">
        {options.map((opt, i) => (
          <button key={opt.value} type="button" onClick={() => onChange(opt.value)}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors ${i > 0 ? 'border-l border-gray-300' : ''} ${
              value === opt.value ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
            }`}>
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/* ── Section wrapper with animation ── */
function Section({ show, children }: { show: boolean; children: React.ReactNode }) {
  if (!show) return null
  return <div className="animate-in fade-in slide-in-from-top-2 duration-300">{children}</div>
}

/* ── Field row ── */
function Field({ label, required, children, error }: { label: string; required?: boolean; children: React.ReactNode; error?: string }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}{required && ' *'}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

/* ── Main Component ── */
export default function FluidOilForm({ onClose, onSubmit }: { onClose?: () => void; onSubmit?: (data: FluidFormData) => void }) {
  const [f, setF] = useState<FluidFormData>({ ...EMPTY })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [showResult, setShowResult] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [editProduct, setEditProduct] = useState<any | null>(null)
  const [editSaving, setEditSaving] = useState(false)

  // List of saved products
  const [products, setProducts] = useState<any[]>([])

  // Suppliers
  const [suppliers, setSuppliers] = useState<{id: string; name: string}[]>([])
  const [supplierSearch, setSupplierSearch] = useState('')
  const [supplierDropOpen, setSupplierDropOpen] = useState(false)
  const [selectedSupplierId, setSelectedSupplierId] = useState('')
  const [selectedSupplierName, setSelectedSupplierName] = useState('')
  const [showAddSupplier, setShowAddSupplier] = useState(false)
  const [newSupplier, setNewSupplier] = useState({ name: '', contact_name: '', email: '', phone: '', address: '' })
  const [addSupplierSaving, setAddSupplierSaving] = useState(false)
  const [addSupplierError, setAddSupplierError] = useState('')
  const supplierDropRef = useRef<HTMLDivElement>(null)
  const fetchProducts = async () => {
    try {
      const { default: apiClient } = await import('@/api/client')
      const res = await apiClient.get('/catalogue/fluids')
      setProducts(res.data.products || [])
    } catch { /* non-blocking */ }
  }

  useEffect(() => { fetchProducts() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch suppliers
  useEffect(() => {
    (async () => {
      try {
        const { default: apiClient } = await import('@/api/client')
        const res = await apiClient.get('/inventory/suppliers')
        setSuppliers((res.data.suppliers || []).map((s: any) => ({ id: s.id, name: s.name })))
      } catch { /* non-blocking */ }
    })()
  }, [])

  // Click outside supplier dropdown
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (supplierDropRef.current && !supplierDropRef.current.contains(e.target as Node)) setSupplierDropOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const set = <K extends keyof FluidFormData>(key: K, val: FluidFormData[K]) => {
    setF(prev => ({ ...prev, [key]: val }))
    if (errors[key]) setErrors(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  // Reset downstream fields when fluid_type changes
  const setFluidType = (v: FluidType) => {
    setF({ ...EMPTY, fluid_type: v })
    setErrors({})
  }

  const setOilType = (v: OilType) => {
    setF(prev => ({ ...prev, oil_type: v, grade: '', synthetic_type: '' }))
  }

  // Computed values
  const unitLabel = f.unit_type === 'gallon' ? 'Gallon' : 'Litre'
  const unitLabelLower = f.unit_type === 'gallon' ? 'gallon' : 'litre'

  const totalVolume = useMemo(() => {
    const qpp = parseFloat(f.qty_per_pack) || 0
    const tq = parseFloat(f.total_quantity) || 0
    return qpp * tq
  }, [f.qty_per_pack, f.total_quantity])

  const costPerUnit = useMemo(() => {
    const pp = parseFloat(f.purchase_price) || 0
    return totalVolume > 0 ? pp / totalVolume : 0
  }, [f.purchase_price, totalVolume])

  const sellPerUnit = parseFloat(f.sell_price_per_unit) || 0
  const margin = sellPerUnit - costPerUnit
  const marginPct = costPerUnit > 0 ? (margin / costPerUnit) * 100 : 0

  const isOil = f.fluid_type === 'oil'
  const isNonOil = f.fluid_type === 'non-oil'
  const isEngineOil = isOil && f.oil_type === 'engine'
  const showOilType = isOil
  const showGrade = isEngineOil
  const showPack = isOil && !!f.oil_type
  const showPricing = isOil && !!f.oil_type && !!f.container_type
  const showOptional = isOil && !!f.oil_type

  const containerLabel = CONTAINER_TYPES.find(c => c.value === f.container_type)?.label || ''
  const oilTypeLabel = OIL_TYPES.find(o => o.value === f.oil_type)?.label || ''

  // Validation
  const validate = (): boolean => {
    const e: Record<string, string> = {}
    if (!f.fluid_type) e.fluid_type = 'Select a fluid type'

    if (isNonOil) {
      if (!f.brand_name.trim()) e.brand_name = 'Required'
      if (!f.product_name.trim()) e.product_name = 'Required'
      if (!f.qty_per_pack || Number(f.qty_per_pack) <= 0) e.qty_per_pack = 'Required'
      if (!f.container_type) e.container_type = 'Select container type'
      if (!f.total_quantity || Number(f.total_quantity) <= 0) e.total_quantity = 'Required'
      if (!f.purchase_price || Number(f.purchase_price) <= 0) e.purchase_price = 'Required'
      if (!f.gst_mode) e.gst_mode = 'Select GST type'
      if (!f.sell_price_per_unit || Number(f.sell_price_per_unit) <= 0) e.sell_price_per_unit = 'Required'
    }

    if (isOil) {
      if (!f.oil_type) e.oil_type = 'Select an oil type'
      if (isEngineOil && !f.grade.trim()) e.grade = 'Enter a grade'
      if (!f.qty_per_pack || Number(f.qty_per_pack) <= 0) e.qty_per_pack = 'Required'
      if (!f.container_type) e.container_type = 'Select container type'
      if (!f.total_quantity || Number(f.total_quantity) <= 0) e.total_quantity = 'Required'
      if (!f.purchase_price || Number(f.purchase_price) <= 0) e.purchase_price = 'Required'
      if (!f.gst_mode) e.gst_mode = 'Select GST type'
      if (!f.sell_price_per_unit || Number(f.sell_price_per_unit) <= 0) e.sell_price_per_unit = 'Required'
    }

    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setSaving(true)
    setSaveError('')
    try {
      const { default: apiClient } = await import('@/api/client')
      const payload = {
        fluid_type: f.fluid_type === 'non-oil' ? 'non-oil' : 'oil',
        oil_type: f.oil_type || null,
        grade: f.grade || null,
        synthetic_type: f.synthetic_type || null,
        product_name: f.product_name || null,
        brand_name: f.brand_name || null,
        description: f.description || null,
        pack_size: f.pack_size || null,
        qty_per_pack: f.qty_per_pack ? Number(f.qty_per_pack) : null,
        unit_type: f.unit_type,
        container_type: f.container_type || null,
        total_quantity: f.total_quantity ? Number(f.total_quantity) : null,
        purchase_price: f.purchase_price ? Number(f.purchase_price) : null,
        gst_mode: f.gst_mode || null,
        sell_price_per_unit: f.sell_price_per_unit ? Number(f.sell_price_per_unit) : null,
        supplier_id: selectedSupplierId || null,
      }
      await apiClient.post('/catalogue/fluids', payload)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
      setF({ ...EMPTY })
      fetchProducts()
      onSubmit?.(f)
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail || 'Failed to save product.')
    } finally { setSaving(false) }
  }

  const handleToggleActive = async (productId: string) => {
    try {
      const { default: apiClient } = await import('@/api/client')
      await apiClient.put(`/catalogue/fluids/${productId}/toggle-active`)
      fetchProducts()
    } catch { /* non-blocking */ }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      const { default: apiClient } = await import('@/api/client')
      await apiClient.delete(`/catalogue/fluids/${deleteId}`)
      setDeleteId(null)
      fetchProducts()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail || 'Failed to delete product.')
      setDeleteId(null)
    } finally { setDeleting(false) }
  }

  const handleEditSave = async () => {
    if (!editProduct) return
    setEditSaving(true)
    try {
      const { default: apiClient } = await import('@/api/client')
      await apiClient.put(`/catalogue/fluids/${editProduct.id}`, editProduct)
      setEditProduct(null)
      fetchProducts()
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail || 'Failed to update product.')
    } finally { setEditSaving(false) }
  }

  const handleAddSupplierFluid = async () => {
    if (!newSupplier.name.trim()) { setAddSupplierError('Supplier name is required.'); return }
    setAddSupplierSaving(true)
    setAddSupplierError('')
    try {
      const { default: apiClient } = await import('@/api/client')
      const body: Record<string, string> = { name: newSupplier.name.trim() }
      if (newSupplier.contact_name.trim()) body.contact_name = newSupplier.contact_name.trim()
      if (newSupplier.email.trim()) body.email = newSupplier.email.trim()
      if (newSupplier.phone.trim()) body.phone = newSupplier.phone.trim()
      if (newSupplier.address.trim()) body.address = newSupplier.address.trim()
      const res = await apiClient.post('/inventory/suppliers', body)
      const created = res.data.supplier || res.data
      setSuppliers(prev => [...prev, { id: created.id, name: created.name }])
      setSelectedSupplierId(created.id)
      setSelectedSupplierName(created.name)
      setShowAddSupplier(false)
      setNewSupplier({ name: '', contact_name: '', email: '', phone: '', address: '' })
    } catch (err: any) {
      setAddSupplierError(err?.response?.data?.detail || 'Failed to create supplier.')
    } finally { setAddSupplierSaving(false) }
  }

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-semibold text-gray-900">Add Fluid / Oil Product</h2>

      {/* Step 1: Fluid Type */}
      <SegmentedToggle
        label="Fluid Type"
        required
        options={[{ value: 'oil' as FluidType, label: 'Oil' }, { value: 'non-oil' as FluidType, label: 'Non-Oil' }]}
        value={f.fluid_type as FluidType}
        onChange={setFluidType}
      />
      {errors.fluid_type && <p className="text-xs text-red-600">{errors.fluid_type}</p>}

      {/* Non-Oil: full form with pack/pricing like oils */}
      <Section show={isNonOil}>
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Brand Name" required error={errors.brand_name}>
              <input type="text" value={f.brand_name} onChange={e => set('brand_name', e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </Field>
            <Field label="Product Name" required error={errors.product_name}>
              <input type="text" value={f.product_name} onChange={e => set('product_name', e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </Field>
          </div>

          {/* Pack / Purchase Format */}
          <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 space-y-3">
            <p className="text-sm font-medium text-gray-900">How is this product purchased?</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Field label="Qty per pack" required error={errors.qty_per_pack}>
                <input type="number" min="1" step="0.1" value={f.qty_per_pack} onChange={e => set('qty_per_pack', e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. 5" />
              </Field>
              <Field label="Unit">
                <div className="inline-flex rounded-md border border-gray-300 overflow-hidden w-full">
                  {(['litre', 'gallon'] as UnitType[]).map((u, i) => (
                    <button key={u} type="button" onClick={() => set('unit_type', u)}
                      className={`flex-1 py-2 text-sm font-medium transition-colors ${i > 0 ? 'border-l border-gray-300' : ''} ${
                        f.unit_type === u ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                      }`}>
                      {u === 'litre' ? 'Litre' : 'Gallon'}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Container" required error={errors.container_type}>
                <select value={f.container_type} onChange={e => set('container_type', e.target.value as ContainerType)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">Select…</option>
                  {CONTAINER_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </Field>
              <Field label="Total packs" required error={errors.total_quantity}>
                <input type="number" min="1" step="1" value={f.total_quantity} onChange={e => set('total_quantity', e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. 6" />
              </Field>
            </div>
            {totalVolume > 0 && (
              <div className="flex items-center gap-2 rounded-md bg-white border border-gray-200 px-3 py-2">
                <span className="text-sm text-gray-500">Total Volume:</span>
                <span className="text-sm font-semibold text-gray-900">{totalVolume.toLocaleString()} {unitLabel}s</span>
              </div>
            )}
          </div>

          {/* Pricing */}
          <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 space-y-3">
            <p className="text-sm font-medium text-gray-900">Pricing</p>
            <Field label="Purchase Price (total cost)" required error={errors.purchase_price}>
              <div className="flex">
                <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">NZD $</span>
                <input type="number" min="0" step="0.01" value={f.purchase_price} onChange={e => set('purchase_price', e.target.value)}
                  className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
              </div>
            </Field>
            <SegmentedToggle label="GST" required
              options={[{ value: 'inclusive' as GstMode, label: 'GST Inclusive' }, { value: 'exclusive' as GstMode, label: 'GST Exclusive' }, { value: 'exempt' as GstMode, label: 'GST Exempt' }]}
              value={f.gst_mode as GstMode} onChange={v => set('gst_mode', v)} />
            {errors.gst_mode && <p className="text-xs text-red-600">{errors.gst_mode}</p>}
            {costPerUnit > 0 && (
              <div className="rounded-md bg-white border border-gray-200 px-3 py-2 flex items-center justify-between">
                <span className="text-sm text-gray-500">Cost per {unitLabel}:</span>
                <span className="text-sm font-semibold text-gray-900">{formatNZD(costPerUnit)}</span>
              </div>
            )}
            <Field label={`Sell Price per ${unitLabel}`} required error={errors.sell_price_per_unit}>
              <div className="flex">
                <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">NZD $</span>
                <input type="number" min="0" step="0.01" value={f.sell_price_per_unit} onChange={e => set('sell_price_per_unit', e.target.value)}
                  className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
              </div>
            </Field>
            {sellPerUnit > 0 && costPerUnit > 0 && (
              <div className={`rounded-md border px-3 py-2 flex items-center justify-between ${margin >= 0 ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
                <span className="text-sm text-gray-600">Margin:</span>
                <span className={`text-sm font-semibold ${margin >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                  {formatNZD(margin)} ({marginPct.toFixed(1)}%)
                </span>
              </div>
            )}
          </div>

          <Field label="Description">
            <textarea value={f.description} onChange={e => set('description', e.target.value)} rows={2} placeholder="Optional"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </Field>
        </div>
      </Section>

      {/* Step 2: Oil Type */}
      <Section show={showOilType}>
        <Field label="Oil Type" required error={errors.oil_type}>
          <select value={f.oil_type} onChange={e => setOilType(e.target.value as OilType)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">Select oil type…</option>
            {OIL_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
      </Section>

      {/* Step 3: Grade (Engine Oil only) */}
      <Section show={showGrade}>
        <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-4 space-y-3">
          <p className="text-xs font-medium text-blue-700 uppercase tracking-wider">Engine Oil Grade</p>
          <Field label="Grade" required error={errors.grade}>
            <input type="text" value={f.grade} onChange={e => set('grade', e.target.value)} placeholder="e.g. 5W-30, 10W-40"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </Field>
          <SegmentedToggle label="Synthetic Type"
            options={[
              { value: 'semi_synthetic' as SyntheticType, label: 'Semi Synthetic' },
              { value: 'full_synthetic' as SyntheticType, label: 'Full Synthetic' },
              { value: 'mineral' as SyntheticType, label: 'Mineral' },
            ]}
            value={f.synthetic_type as SyntheticType} onChange={v => set('synthetic_type', v)} />
        </div>
      </Section>

      {/* Step 4: Pack / Purchase Format */}
      <Section show={showPack}>
        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <p className="text-sm font-medium text-gray-900">How is this product purchased?</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Field label="Qty per pack" required error={errors.qty_per_pack}>
              <input type="number" min="1" step="1" value={f.qty_per_pack} onChange={e => set('qty_per_pack', e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. 205" />
            </Field>
            <Field label="Unit">
              <div className="inline-flex rounded-md border border-gray-300 overflow-hidden w-full">
                {(['litre', 'gallon'] as UnitType[]).map((u, i) => (
                  <button key={u} type="button" onClick={() => set('unit_type', u)}
                    className={`flex-1 py-2 text-sm font-medium transition-colors ${i > 0 ? 'border-l border-gray-300' : ''} ${
                      f.unit_type === u ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                    }`}>
                    {u === 'litre' ? 'Litre' : 'Gallon'}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Container" required error={errors.container_type}>
              <select value={f.container_type} onChange={e => set('container_type', e.target.value as ContainerType)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">Select…</option>
                {CONTAINER_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </Field>
            <Field label="Total packs" required error={errors.total_quantity}>
              <input type="number" min="1" step="1" value={f.total_quantity} onChange={e => set('total_quantity', e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. 3" />
            </Field>
          </div>
          {totalVolume > 0 && (
            <div className="flex items-center gap-2 rounded-md bg-gray-50 border border-gray-200 px-3 py-2">
              <span className="text-sm text-gray-500">Total Volume:</span>
              <span className="text-sm font-semibold text-gray-900">{totalVolume.toLocaleString()} {unitLabel}s</span>
              {f.container_type && f.total_quantity && (
                <span className="text-xs text-gray-400 ml-auto">
                  {f.total_quantity} × {f.qty_per_pack}{f.unit_type === 'litre' ? 'L' : 'gal'} {containerLabel}
                </span>
              )}
            </div>
          )}
        </div>
      </Section>

      {/* Step 5: Pricing */}
      <Section show={showPricing}>
        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <p className="text-sm font-medium text-gray-900">Pricing</p>
          <Field label="Purchase Price (total cost)" required error={errors.purchase_price}>
            <div className="flex">
              <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">NZD $</span>
              <input type="number" min="0" step="0.01" value={f.purchase_price} onChange={e => set('purchase_price', e.target.value)}
                className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
            </div>
          </Field>
          <SegmentedToggle label="GST" required
            options={[{ value: 'inclusive' as GstMode, label: 'GST Inclusive' }, { value: 'exclusive' as GstMode, label: 'GST Exclusive' }, { value: 'exempt' as GstMode, label: 'GST Exempt' }]}
            value={f.gst_mode as GstMode} onChange={v => set('gst_mode', v)} />
          {errors.gst_mode && <p className="text-xs text-red-600">{errors.gst_mode}</p>}

          {costPerUnit > 0 && (
            <div className="rounded-md bg-gray-50 border border-gray-200 px-3 py-2 flex items-center justify-between">
              <span className="text-sm text-gray-500">Cost per {unitLabel}:</span>
              <span className="text-sm font-semibold text-gray-900">{formatNZD(costPerUnit)}</span>
            </div>
          )}

          <Field label={`Sell Price per ${unitLabel}`} required error={errors.sell_price_per_unit}>
            <div className="flex">
              <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">NZD $</span>
              <input type="number" min="0" step="0.01" value={f.sell_price_per_unit} onChange={e => set('sell_price_per_unit', e.target.value)}
                className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
            </div>
          </Field>

          {sellPerUnit > 0 && costPerUnit > 0 && (
            <div className="rounded-md border px-3 py-2 flex items-center justify-between
              ${margin >= 0 ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}">
              <span className="text-sm text-gray-600">Margin:</span>
              <div className="text-right">
                <span className={`text-sm font-semibold ${margin >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                  {formatNZD(margin)} ({marginPct.toFixed(1)}%)
                </span>
              </div>
            </div>
          )}
        </div>
      </Section>

      {/* Step 6: Optional Fields + Supplier */}
      <Section show={showOptional || isNonOil}>
        <div className="space-y-3">
          {/* Supplier searchable dropdown */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">Supplier</label>
              <button type="button" onClick={() => { setNewSupplier({ name: '', contact_name: '', email: '', phone: '', address: '' }); setAddSupplierError(''); setShowAddSupplier(true) }}
                className="text-xs text-blue-600 hover:underline font-medium">+ Add Supplier</button>
            </div>
            {selectedSupplierId ? (
              <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2">
                <span className="flex-1 text-sm text-gray-900">{selectedSupplierName}</span>
                <button type="button" onClick={() => { setSelectedSupplierId(''); setSelectedSupplierName('') }} className="text-gray-400 hover:text-gray-600 text-xs">✕</button>
              </div>
            ) : (
              <div ref={supplierDropRef} className="relative">
                <input type="text" value={supplierSearch}
                  onChange={e => { setSupplierSearch(e.target.value); setSupplierDropOpen(true) }}
                  onFocus={() => setSupplierDropOpen(true)}
                  placeholder="Search suppliers…"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" autoComplete="off" />
                {supplierDropOpen && (
                  <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
                    {suppliers.filter(s => !supplierSearch.trim() || s.name.toLowerCase().includes(supplierSearch.toLowerCase())).slice(0, 15).map(s => (
                      <button key={s.id} type="button" onClick={() => { setSelectedSupplierId(s.id); setSelectedSupplierName(s.name); setSupplierSearch(''); setSupplierDropOpen(false) }}
                        className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 text-gray-900">{s.name}</button>
                    ))}
                    {suppliers.filter(s => !supplierSearch.trim() || s.name.toLowerCase().includes(supplierSearch.toLowerCase())).length === 0 && (
                      <div className="px-3 py-2 text-sm text-gray-500">No suppliers match</div>
                    )}
                    <button type="button" onClick={() => { setNewSupplier({ name: supplierSearch.trim(), contact_name: '', email: '', phone: '', address: '' }); setAddSupplierError(''); setShowAddSupplier(true); setSupplierDropOpen(false) }}
                      className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm font-medium text-blue-600 hover:bg-blue-50">
                      + Add New Supplier{supplierSearch.trim() ? ` "${supplierSearch.trim()}"` : ''}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          {showOptional && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label="Brand Name">
                <input type="text" value={f.brand_name} onChange={e => set('brand_name', e.target.value)} placeholder="e.g. Castrol, Penrite"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </Field>
              <Field label="Description">
                <textarea value={f.description} onChange={e => set('description', e.target.value)} rows={2} placeholder="Optional notes"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
              </Field>
            </div>
          )}
        </div>
      </Section>

      {/* Step 7: Summary Card */}
      <Section show={(isOil && !!f.oil_type && totalVolume > 0) || (isNonOil && !!f.product_name && totalVolume > 0)}>
        <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4">
          <p className="text-xs font-semibold text-blue-700 uppercase tracking-wider mb-2">Summary</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            {isOil && (
              <>
                <div>
                  <p className="text-gray-500 text-xs">Product</p>
                  <p className="font-medium text-gray-900">{oilTypeLabel}{f.grade ? ` ${f.grade}` : ''}</p>
                  {f.synthetic_type && <p className="text-xs text-gray-500 capitalize">{f.synthetic_type.replace('_', ' ')}</p>}
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Container</p>
                  <p className="font-medium text-gray-900">
                    {f.total_quantity || '?'} × {f.qty_per_pack || '?'}{f.unit_type === 'litre' ? 'L' : 'gal'} {containerLabel}
                  </p>
                  <p className="text-xs text-gray-500">{totalVolume > 0 ? `${totalVolume.toLocaleString()} ${unitLabel}s total` : ''}</p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Pricing</p>
                  <p className="font-medium text-gray-900">{f.purchase_price ? formatNZD(Number(f.purchase_price)) : '—'}</p>
                  <p className="text-xs text-gray-500">
                    {costPerUnit > 0 ? `${formatNZD(costPerUnit)}/${unitLabelLower}` : ''}
                    {sellPerUnit > 0 ? ` → ${formatNZD(sellPerUnit)}/${unitLabelLower}` : ''}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Margin</p>
                  {margin !== 0 ? (
                    <p className={`font-medium ${margin >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                      {formatNZD(margin)} ({marginPct.toFixed(1)}%)
                    </p>
                  ) : <p className="text-gray-400">—</p>}
                  {f.gst_mode && <Badge variant={f.gst_mode === 'exempt' ? 'neutral' : 'info'}>{f.gst_mode === 'inclusive' ? 'GST Inc.' : f.gst_mode === 'exclusive' ? 'GST Excl.' : 'GST Exempt'}</Badge>}
                </div>
              </>
            )}
            {isNonOil && (
              <>
                <div>
                  <p className="text-gray-500 text-xs">Product</p>
                  <p className="font-medium text-gray-900">{f.brand_name} {f.product_name}</p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Container</p>
                  <p className="font-medium text-gray-900">
                    {f.total_quantity || '?'} × {f.qty_per_pack || '?'}{f.unit_type === 'litre' ? 'L' : 'gal'} {containerLabel}
                  </p>
                  <p className="text-xs text-gray-500">{totalVolume > 0 ? `${totalVolume.toLocaleString()} ${unitLabel}s total` : ''}</p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Pricing</p>
                  <p className="font-medium text-gray-900">{f.purchase_price ? formatNZD(Number(f.purchase_price)) : '—'}</p>
                  <p className="text-xs text-gray-500">
                    {costPerUnit > 0 ? `${formatNZD(costPerUnit)}/${unitLabelLower}` : ''}
                    {sellPerUnit > 0 ? ` → ${formatNZD(sellPerUnit)}/${unitLabelLower}` : ''}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Margin</p>
                  {margin !== 0 ? (
                    <p className={`font-medium ${margin >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                      {formatNZD(margin)} ({marginPct.toFixed(1)}%)
                    </p>
                  ) : <p className="text-gray-400">—</p>}
                  {f.gst_mode && <Badge variant={f.gst_mode === 'exempt' ? 'neutral' : 'info'}>{f.gst_mode === 'inclusive' ? 'GST Inc.' : f.gst_mode === 'exclusive' ? 'GST Excl.' : 'GST Exempt'}</Badge>}
                </div>
              </>
            )}
          </div>
        </div>
      </Section>

      {/* Actions */}
      {saveError && <p className="text-sm text-red-600">{saveError}</p>}
      {saveSuccess && <p className="text-sm text-green-600">✓ Product saved successfully.</p>}
      <div className="flex justify-end gap-3 pt-2 border-t border-gray-200">
        {onClose && <Button variant="secondary" onClick={onClose}>Cancel</Button>}
        <Button onClick={handleSubmit} loading={saving}>Add Product</Button>
      </div>

      {/* Saved products list */}
      {products.length > 0 && (
        <div className="mt-6">
          <h3 className="text-lg font-medium text-gray-900 mb-3">Saved Fluid / Oil Products</h3>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Product</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Type</th>
                  <th className="px-4 py-2 text-right text-xs font-medium uppercase text-gray-500">Volume</th>
                  <th className="px-4 py-2 text-right text-xs font-medium uppercase text-gray-500">Cost/Unit</th>
                  <th className="px-4 py-2 text-right text-xs font-medium uppercase text-gray-500">Sell/Unit</th>
                  <th className="px-4 py-2 text-right text-xs font-medium uppercase text-gray-500">Margin</th>
                  <th className="px-4 py-2 text-center text-xs font-medium uppercase text-gray-500">Status</th>
                  <th className="px-4 py-2 text-right text-xs font-medium uppercase text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {products.map((p: any) => (
                  <tr key={p.id} className={`hover:bg-gray-50 ${!p.is_active ? 'opacity-60' : ''}`}>
                    <td className="px-4 py-2 font-medium text-gray-900">
                      {p.brand_name ? `${p.brand_name} ` : ''}{p.product_name || p.oil_type || p.fluid_type}
                      {p.grade && <span className="ml-1 text-gray-500">{p.grade}</span>}
                    </td>
                    <td className="px-4 py-2 text-gray-700 capitalize">{p.fluid_type}{p.oil_type ? ` / ${p.oil_type.replace('_', ' ')}` : ''}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{p.total_volume ? `${Number(p.total_volume).toLocaleString()} ${p.unit_type === 'gallon' ? 'gal' : 'L'}` : '—'}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{p.cost_per_unit ? formatNZD(Number(p.cost_per_unit)) : '—'}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{p.sell_price_per_unit ? formatNZD(Number(p.sell_price_per_unit)) : '—'}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{p.margin_pct != null ? `${Number(p.margin_pct).toFixed(1)}%` : '—'}</td>
                    <td className="px-4 py-2 text-center">
                      <Badge variant={p.is_active ? 'success' : 'neutral'}>{p.is_active ? 'Active' : 'Inactive'}</Badge>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="secondary" onClick={() => setEditProduct({...p})}>Edit</Button>
                        <Button size="sm" variant="secondary" onClick={() => handleToggleActive(p.id)}>
                          {p.is_active ? 'Deactivate' : 'Activate'}
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => setDeleteId(p.id)}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Edit modal — full fields */}
      <Modal open={!!editProduct} onClose={() => setEditProduct(null)} title="Edit Fluid / Oil Product">
        {editProduct && (() => {
          const ep = editProduct
          const upd = (k: string, v: any) => setEditProduct((p: any) => ({ ...p, [k]: v }))
          const eQpp = parseFloat(ep.qty_per_pack) || 0
          const eTq = parseFloat(ep.total_quantity) || 0
          const eTotalVol = eQpp * eTq
          const ePp = parseFloat(ep.purchase_price) || 0
          const eCpu = eTotalVol > 0 ? ePp / eTotalVol : 0
          const eSpu = parseFloat(ep.sell_price_per_unit) || 0
          const eMargin = eSpu - eCpu
          const eMarginPct = eCpu > 0 ? (eMargin / eCpu) * 100 : 0
          const eUnitLabel = ep.unit_type === 'gallon' ? 'Gallon' : 'Litre'
          return (
          <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Brand Name">
                <input type="text" value={ep.brand_name || ''} onChange={e => upd('brand_name', e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </Field>
              {ep.fluid_type === 'non-oil' ? (
                <Field label="Product Name">
                  <input type="text" value={ep.product_name || ''} onChange={e => upd('product_name', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </Field>
              ) : (
                <Field label="Oil Type">
                  <select value={ep.oil_type || ''} onChange={e => upd('oil_type', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    {OIL_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </Field>
              )}
            </div>
            {ep.oil_type === 'engine' && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Grade">
                  <input type="text" value={ep.grade || ''} onChange={e => upd('grade', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </Field>
                <Field label="Synthetic Type">
                  <select value={ep.synthetic_type || ''} onChange={e => upd('synthetic_type', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="">—</option>
                    <option value="semi_synthetic">Semi Synthetic</option>
                    <option value="full_synthetic">Full Synthetic</option>
                    <option value="mineral">Mineral</option>
                  </select>
                </Field>
              </div>
            )}
            {/* Pack format */}
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 space-y-2">
              <p className="text-xs font-medium text-gray-500 uppercase">Pack Format</p>
              <div className="grid grid-cols-4 gap-2">
                <Field label="Qty/pack">
                  <input type="number" min="1" step="0.1" value={ep.qty_per_pack || ''} onChange={e => upd('qty_per_pack', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </Field>
                <Field label="Unit">
                  <select value={ep.unit_type || 'litre'} onChange={e => upd('unit_type', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="litre">Litre</option>
                    <option value="gallon">Gallon</option>
                  </select>
                </Field>
                <Field label="Container">
                  <select value={ep.container_type || ''} onChange={e => upd('container_type', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="">—</option>
                    {CONTAINER_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </Field>
                <Field label="Total packs">
                  <input type="number" min="1" step="1" value={ep.total_quantity || ''} onChange={e => upd('total_quantity', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </Field>
              </div>
              {eTotalVol > 0 && (
                <p className="text-xs text-gray-500">Total Volume: <span className="font-semibold text-gray-900">{eTotalVol.toLocaleString()} {eUnitLabel}s</span></p>
              )}
            </div>
            {/* Pricing */}
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 space-y-2">
              <p className="text-xs font-medium text-gray-500 uppercase">Pricing</p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Purchase Price">
                  <input type="number" min="0" step="0.01" value={ep.purchase_price || ''} onChange={e => upd('purchase_price', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </Field>
                <Field label={`Sell Price per ${eUnitLabel}`}>
                  <input type="number" min="0" step="0.01" value={ep.sell_price_per_unit || ''} onChange={e => upd('sell_price_per_unit', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </Field>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">GST</label>
                <div className="inline-flex rounded-md border border-gray-300 overflow-hidden w-full">
                  {(['inclusive', 'exclusive', 'exempt'] as const).map((mode, i) => (
                    <button key={mode} type="button" onClick={() => upd('gst_mode', mode)}
                      className={`flex-1 py-1.5 text-xs font-medium transition-colors ${i > 0 ? 'border-l border-gray-300' : ''} ${
                        ep.gst_mode === mode ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                      }`}>
                      {mode === 'inclusive' ? 'GST Inc.' : mode === 'exclusive' ? 'GST Excl.' : 'Exempt'}
                    </button>
                  ))}
                </div>
              </div>
              {eCpu > 0 && (
                <div className="flex justify-between text-xs text-gray-500">
                  <span>Cost/{eUnitLabel}: <span className="font-semibold text-gray-900">{formatNZD(eCpu)}</span></span>
                  {eMargin !== 0 && (
                    <span>Margin: <span className={`font-semibold ${eMargin >= 0 ? 'text-green-700' : 'text-red-700'}`}>{formatNZD(eMargin)} ({eMarginPct.toFixed(1)}%)</span></span>
                  )}
                </div>
              )}
            </div>
            <Field label="Description">
              <textarea value={ep.description || ''} onChange={e => upd('description', e.target.value)} rows={2}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={() => setEditProduct(null)}>Cancel</Button>
              <Button onClick={handleEditSave} loading={editSaving}>Save Changes</Button>
            </div>
          </div>
          )
        })()}
      </Modal>

      {/* Add Supplier Modal */}
      <Modal open={showAddSupplier} onClose={() => setShowAddSupplier(false)} title="New Supplier">
        <div className="space-y-3">
          <Field label="Supplier name *">
            <input type="text" value={newSupplier.name} onChange={e => setNewSupplier(p => ({ ...p, name: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </Field>
          <Field label="Contact person">
            <input type="text" value={newSupplier.contact_name} onChange={e => setNewSupplier(p => ({ ...p, contact_name: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Email">
              <input type="email" value={newSupplier.email} onChange={e => setNewSupplier(p => ({ ...p, email: e.target.value }))}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </Field>
            <Field label="Phone">
              <input type="text" value={newSupplier.phone} onChange={e => setNewSupplier(p => ({ ...p, phone: e.target.value }))}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </Field>
          </div>
          <Field label="Address">
            <input type="text" value={newSupplier.address} onChange={e => setNewSupplier(p => ({ ...p, address: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </Field>
          {addSupplierError && <p className="text-sm text-red-600">{addSupplierError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowAddSupplier(false)}>Cancel</Button>
            <Button onClick={handleAddSupplierFluid} loading={addSupplierSaving}>Create Supplier</Button>
          </div>
        </div>
      </Modal>

      {/* Delete confirm modal */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Product">
        <p className="text-sm text-gray-600 mb-4">This will permanently delete this fluid/oil product. This cannot be undone.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="danger" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>

      {/* Result modal */}
      <Modal open={showResult} onClose={() => setShowResult(false)} title="Product Saved">
        <p className="text-sm text-gray-600">Product has been saved to the database.</p>
        <div className="mt-3 flex justify-end">
          <Button variant="secondary" onClick={() => setShowResult(false)}>Close</Button>
        </div>
      </Modal>
    </div>
  )
}
