import { useState, useMemo } from 'react'
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
  const [resultJson, setResultJson] = useState('')

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
      if (!f.purchase_price || Number(f.purchase_price) <= 0) e.purchase_price = 'Required'
      if (!f.gst_mode) e.gst_mode = 'Select GST type'
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

  const handleSubmit = () => {
    if (!validate()) return
    const json = JSON.stringify(f, null, 2)
    setResultJson(json)
    setShowResult(true)
    console.log('FluidOilForm submit:', f)
    onSubmit?.(f)
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

      {/* Non-Oil: simple form */}
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
          <Field label="Pack Size">
            <input type="text" value={f.pack_size} onChange={e => set('pack_size', e.target.value)} placeholder="e.g. 5L, 20L"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </Field>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Purchase Price" required error={errors.purchase_price}>
              <div className="flex">
                <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">NZD $</span>
                <input type="number" min="0" step="0.01" value={f.purchase_price} onChange={e => set('purchase_price', e.target.value)}
                  className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </Field>
            <Field label="Sell Price">
              <div className="flex">
                <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">NZD $</span>
                <input type="number" min="0" step="0.01" value={f.sell_price_per_unit} onChange={e => set('sell_price_per_unit', e.target.value)}
                  className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </Field>
          </div>
          <SegmentedToggle label="GST" required
            options={[{ value: 'inclusive' as GstMode, label: 'GST Inclusive' }, { value: 'exclusive' as GstMode, label: 'GST Exclusive' }, { value: 'exempt' as GstMode, label: 'GST Exempt' }]}
            value={f.gst_mode as GstMode} onChange={v => set('gst_mode', v)} />
          {errors.gst_mode && <p className="text-xs text-red-600">{errors.gst_mode}</p>}
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

      {/* Step 6: Optional Fields */}
      <Section show={showOptional}>
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
      </Section>

      {/* Step 7: Summary Card */}
      <Section show={(isOil && !!f.oil_type && totalVolume > 0) || (isNonOil && !!f.product_name)}>
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
                  {f.pack_size && <p className="text-xs text-gray-500">{f.pack_size}</p>}
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Price</p>
                  <p className="font-medium text-gray-900">{f.purchase_price ? formatNZD(Number(f.purchase_price)) : '—'}</p>
                  {f.gst_mode && <Badge variant={f.gst_mode === 'exempt' ? 'neutral' : 'info'}>{f.gst_mode === 'inclusive' ? 'GST Inc.' : f.gst_mode === 'exclusive' ? 'GST Excl.' : 'GST Exempt'}</Badge>}
                </div>
              </>
            )}
          </div>
        </div>
      </Section>

      {/* Actions */}
      <div className="flex justify-end gap-3 pt-2 border-t border-gray-200">
        {onClose && <Button variant="secondary" onClick={onClose}>Cancel</Button>}
        <Button onClick={handleSubmit}>Add Product</Button>
      </div>

      {/* Result modal */}
      <Modal open={showResult} onClose={() => setShowResult(false)} title="Product Data (JSON)">
        <pre className="bg-gray-900 text-green-400 rounded-md p-4 text-xs overflow-auto max-h-80 font-mono">{resultJson}</pre>
        <div className="mt-3 flex justify-end">
          <Button variant="secondary" onClick={() => setShowResult(false)}>Close</Button>
        </div>
      </Modal>
    </div>
  )
}
