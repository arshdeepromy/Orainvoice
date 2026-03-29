import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type AdjustmentType = 'parts' | 'fluids'

interface StockLevel {
  part_id: string
  part_name: string
  part_number: string | null
  current_stock: number
  min_threshold: number
  reorder_quantity: number
  is_below_threshold: boolean
}

interface StockLevelListResponse {
  stock_levels: StockLevel[]
  total: number
}

interface FluidStockLevel {
  product_id: string
  display_name: string
  brand_name: string | null
  fluid_type: string
  oil_type: string | null
  grade: string | null
  unit_type: string
  current_stock_volume: number
  min_stock_volume: number
  reorder_volume: number
  is_below_threshold: boolean
}

interface FluidStockListResponse {
  fluid_stock_levels: FluidStockLevel[]
  total: number
}

interface PartForm {
  part_id: string
  quantity_change: string
  reason: string
}

interface FluidForm {
  product_id: string
  volume_change: string
  reason: string
}

const EMPTY_PART_FORM: PartForm = { part_id: '', quantity_change: '', reason: '' }
const EMPTY_FLUID_FORM: FluidForm = { product_id: '', volume_change: '', reason: '' }

const REASON_OPTIONS = [
  { value: '', label: 'Select a reason…' },
  { value: 'Physical count adjustment', label: 'Physical count adjustment' },
  { value: 'Received from supplier', label: 'Received from supplier' },
  { value: 'Damaged / write-off', label: 'Damaged / write-off' },
  { value: 'Returned to supplier', label: 'Returned to supplier' },
  { value: 'Customer return', label: 'Customer return' },
  { value: 'Other', label: 'Other (specify below)' },
]

const UNIT_ABBREV: Record<string, string> = { litre: 'L', gallon: 'gal' }

/**
 * Stock adjustment form for manually adjusting stock levels with a reason (audit log).
 * Supports both Parts (integer qty) and Fluids/Oils (decimal volume).
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
 */
export default function StockAdjustment() {
  const [adjustmentType, setAdjustmentType] = useState<AdjustmentType>('parts')

  /* Parts state */
  const [parts, setParts] = useState<StockLevel[]>([])
  const [partsLoading, setPartsLoading] = useState(true)
  const [partForm, setPartForm] = useState<PartForm>(EMPTY_PART_FORM)

  /* Fluids state */
  const [fluids, setFluids] = useState<FluidStockLevel[]>([])
  const [fluidsLoading, setFluidsLoading] = useState(false)
  const [fluidForm, setFluidForm] = useState<FluidForm>(EMPTY_FLUID_FORM)

  /* Shared state */
  const [error, setError] = useState('')
  const [customReason, setCustomReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')

  /* ---- Data fetching ---- */

  const fetchParts = useCallback(async () => {
    setPartsLoading(true)
    setError('')
    try {
      const res = await apiClient.get<StockLevelListResponse>('/inventory/stock')
      setParts(res.data?.stock_levels ?? [])
    } catch {
      setError('Failed to load parts.')
    } finally {
      setPartsLoading(false)
    }
  }, [])

  const fetchFluids = useCallback(async () => {
    setFluidsLoading(true)
    setError('')
    try {
      const res = await apiClient.get<FluidStockListResponse>('/inventory/fluid-stock')
      setFluids(res.data?.fluid_stock_levels ?? [])
    } catch {
      setError('Failed to load fluids/oils.')
    } finally {
      setFluidsLoading(false)
    }
  }, [])

  useEffect(() => { fetchParts() }, [fetchParts])

  useEffect(() => {
    if (adjustmentType === 'fluids' && fluids.length === 0) {
      fetchFluids()
    }
  }, [adjustmentType, fluids.length, fetchFluids])

  /* ---- Reset on type change ---- */

  const handleTypeChange = (type: AdjustmentType) => {
    setAdjustmentType(type)
    setPartForm(EMPTY_PART_FORM)
    setFluidForm(EMPTY_FLUID_FORM)
    setCustomReason('')
    setFormError('')
    setSuccess('')
  }

  /* ---- Derived values ---- */

  const selectedPart = parts.find((p) => p.part_id === partForm.part_id)
  const selectedFluid = fluids.find((f) => f.product_id === fluidForm.product_id)
  const unitLabel = selectedFluid ? (UNIT_ABBREV[selectedFluid.unit_type] || selectedFluid.unit_type) : 'L'

  /* ---- Submit handlers ---- */

  const handlePartSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')
    setSuccess('')

    if (!partForm.part_id) { setFormError('Please select a part.'); return }
    const qty = parseInt(partForm.quantity_change, 10)
    if (isNaN(qty) || qty === 0) { setFormError('Quantity change must be a non-zero number.'); return }

    const reason = partForm.reason === 'Other' ? customReason.trim() : partForm.reason
    if (!reason) { setFormError('Please provide a reason for the adjustment.'); return }

    setSaving(true)
    try {
      await apiClient.put(`/inventory/stock/${partForm.part_id}`, { quantity_change: qty, reason })
      setSuccess(`Stock adjusted successfully. ${selectedPart?.part_name}: ${qty > 0 ? '+' : ''}${qty}`)
      setPartForm(EMPTY_PART_FORM)
      setCustomReason('')
      fetchParts()
    } catch {
      setFormError('Failed to adjust stock. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleFluidSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')
    setSuccess('')

    if (!fluidForm.product_id) { setFormError('Please select a fluid/oil product.'); return }
    const vol = parseFloat(fluidForm.volume_change)
    if (isNaN(vol) || vol === 0) { setFormError('Volume change must be a non-zero number.'); return }

    const reason = fluidForm.reason === 'Other' ? customReason.trim() : fluidForm.reason
    if (!reason) { setFormError('Please provide a reason for the adjustment.'); return }

    setSaving(true)
    try {
      await apiClient.put(`/inventory/fluid-stock/${fluidForm.product_id}`, { volume_change: vol, reason })
      setSuccess(`Stock adjusted successfully. ${selectedFluid?.display_name}: ${vol > 0 ? '+' : ''}${vol} ${unitLabel}`)
      setFluidForm(EMPTY_FLUID_FORM)
      setCustomReason('')
      fetchFluids()
    } catch {
      setFormError('Failed to adjust stock. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  /* ---- Dropdown options ---- */

  const partOptions = [
    { value: '', label: 'Select a part…' },
    ...parts.map((p) => ({
      value: p.part_id,
      label: `${p.part_name}${p.part_number ? ` (${p.part_number})` : ''} — Stock: ${p.current_stock}`,
    })),
  ]

  const fluidOptions = [
    { value: '', label: 'Select a fluid/oil…' },
    ...fluids.map((f) => ({
      value: f.product_id,
      label: `${f.display_name}${f.brand_name ? ` (${f.brand_name})` : ''} — Volume: ${f.current_stock_volume} ${UNIT_ABBREV[f.unit_type] || f.unit_type}`,
    })),
  ]

  const isLoading = adjustmentType === 'parts' ? partsLoading : fluidsLoading

  /* ---- Render ---- */

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">
        Manually adjust stock levels. All adjustments are recorded in the audit log with the reason provided.
      </p>

      {/* Type selector toggle */}
      <div className="flex gap-2 mb-6" role="group" aria-label="Adjustment type">
        <Button
          type="button"
          variant={adjustmentType === 'parts' ? 'primary' : 'secondary'}
          size="sm"
          onClick={() => handleTypeChange('parts')}
        >
          Parts
        </Button>
        <Button
          type="button"
          variant={adjustmentType === 'fluids' ? 'primary' : 'secondary'}
          size="sm"
          onClick={() => handleTypeChange('fluids')}
        >
          Fluids / Oils
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {isLoading && (
        <div className="py-16"><Spinner label={adjustmentType === 'parts' ? 'Loading parts' : 'Loading fluids'} /></div>
      )}

      {/* ---- Parts form ---- */}
      {!isLoading && adjustmentType === 'parts' && (
        <form onSubmit={handlePartSubmit} className="max-w-lg space-y-4">
          <Select
            label="Part *"
            options={partOptions}
            value={partForm.part_id}
            onChange={(e) => setPartForm((prev) => ({ ...prev, part_id: e.target.value }))}
          />

          {selectedPart && (
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <span className="text-gray-500">Current stock:</span>{' '}
                  <span className="font-medium">{selectedPart.current_stock}</span>
                </div>
                <div>
                  <span className="text-gray-500">Min threshold:</span>{' '}
                  <span className="font-medium">{selectedPart.min_threshold}</span>
                </div>
                <div>
                  <span className="text-gray-500">Reorder qty:</span>{' '}
                  <span className="font-medium">{selectedPart.reorder_quantity}</span>
                </div>
              </div>
            </div>
          )}

          <Input
            label="Quantity change *"
            type="number"
            placeholder="e.g. 10 to add, -5 to remove"
            value={partForm.quantity_change}
            onChange={(e) => setPartForm((prev) => ({ ...prev, quantity_change: e.target.value }))}
          />

          {selectedPart && partForm.quantity_change && !isNaN(parseInt(partForm.quantity_change, 10)) && (
            <p className="text-sm text-gray-600">
              New stock level will be:{' '}
              <span className="font-medium">
                {selectedPart.current_stock + parseInt(partForm.quantity_change, 10)}
              </span>
            </p>
          )}

          <Select
            label="Reason *"
            options={REASON_OPTIONS}
            value={partForm.reason}
            onChange={(e) => setPartForm((prev) => ({ ...prev, reason: e.target.value }))}
          />

          {partForm.reason === 'Other' && (
            <Input
              label="Custom reason *"
              placeholder="Describe the reason for this adjustment"
              value={customReason}
              onChange={(e) => setCustomReason(e.target.value)}
            />
          )}

          {formError && <p className="text-sm text-red-600" role="alert">{formError}</p>}
          {success && (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700" role="status">{success}</div>
          )}

          <div className="flex gap-2">
            <Button type="submit" loading={saving}>Adjust Stock</Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => { setPartForm(EMPTY_PART_FORM); setCustomReason(''); setFormError(''); setSuccess('') }}
            >
              Reset
            </Button>
          </div>
        </form>
      )}

      {/* ---- Fluids form ---- */}
      {!isLoading && adjustmentType === 'fluids' && (
        <form onSubmit={handleFluidSubmit} className="max-w-lg space-y-4">
          <Select
            label="Fluid / Oil Product *"
            options={fluidOptions}
            value={fluidForm.product_id}
            onChange={(e) => setFluidForm((prev) => ({ ...prev, product_id: e.target.value }))}
          />

          {selectedFluid && (
            <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-gray-500">Current volume:</span>{' '}
                  <span className="font-medium">{selectedFluid.current_stock_volume} {unitLabel}</span>
                </div>
                <div>
                  <span className="text-gray-500">Unit:</span>{' '}
                  <span className="font-medium">{selectedFluid.unit_type}</span>
                </div>
                <div>
                  <span className="text-gray-500">Min threshold:</span>{' '}
                  <span className="font-medium">{selectedFluid.min_stock_volume} {unitLabel}</span>
                </div>
                <div>
                  <span className="text-gray-500">Reorder volume:</span>{' '}
                  <span className="font-medium">{selectedFluid.reorder_volume} {unitLabel}</span>
                </div>
              </div>
            </div>
          )}

          <Input
            label="Volume change *"
            type="number"
            step="0.1"
            placeholder="e.g. 5.5 to add, -2.0 to remove"
            value={fluidForm.volume_change}
            onChange={(e) => setFluidForm((prev) => ({ ...prev, volume_change: e.target.value }))}
          />

          {selectedFluid && fluidForm.volume_change && !isNaN(parseFloat(fluidForm.volume_change)) && (
            <p className="text-sm text-gray-600">
              New volume will be:{' '}
              <span className="font-medium">
                {(selectedFluid.current_stock_volume + parseFloat(fluidForm.volume_change)).toFixed(1)} {unitLabel}
              </span>
            </p>
          )}

          <Select
            label="Reason *"
            options={REASON_OPTIONS}
            value={fluidForm.reason}
            onChange={(e) => setFluidForm((prev) => ({ ...prev, reason: e.target.value }))}
          />

          {fluidForm.reason === 'Other' && (
            <Input
              label="Custom reason *"
              placeholder="Describe the reason for this adjustment"
              value={customReason}
              onChange={(e) => setCustomReason(e.target.value)}
            />
          )}

          {formError && <p className="text-sm text-red-600" role="alert">{formError}</p>}
          {success && (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700" role="status">{success}</div>
          )}

          <div className="flex gap-2">
            <Button type="submit" loading={saving}>Adjust Stock</Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => { setFluidForm(EMPTY_FLUID_FORM); setCustomReason(''); setFormError(''); setSuccess('') }}
            >
              Reset
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}
