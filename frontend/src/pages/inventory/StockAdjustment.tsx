import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

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

interface AdjustmentForm {
  part_id: string
  quantity_change: string
  reason: string
}

const EMPTY_FORM: AdjustmentForm = { part_id: '', quantity_change: '', reason: '' }

const REASON_OPTIONS = [
  { value: '', label: 'Select a reason…' },
  { value: 'Physical count adjustment', label: 'Physical count adjustment' },
  { value: 'Received from supplier', label: 'Received from supplier' },
  { value: 'Damaged / write-off', label: 'Damaged / write-off' },
  { value: 'Returned to supplier', label: 'Returned to supplier' },
  { value: 'Customer return', label: 'Customer return' },
  { value: 'Other', label: 'Other (specify below)' },
]

/**
 * Stock adjustment form for manually adjusting stock levels with a reason (audit log).
 *
 * Requirements: 62.5
 */
export default function StockAdjustment() {
  const [parts, setParts] = useState<StockLevel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [form, setForm] = useState<AdjustmentForm>(EMPTY_FORM)
  const [customReason, setCustomReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')

  const fetchParts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<StockLevelListResponse>('/inventory/stock')
      setParts(res.data.stock_levels)
    } catch {
      setError('Failed to load parts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchParts() }, [fetchParts])

  const selectedPart = parts.find((p) => p.part_id === form.part_id)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')
    setSuccess('')

    if (!form.part_id) { setFormError('Please select a part.'); return }
    const qty = parseInt(form.quantity_change, 10)
    if (isNaN(qty) || qty === 0) { setFormError('Quantity change must be a non-zero number.'); return }

    const reason = form.reason === 'Other' ? customReason.trim() : form.reason
    if (!reason) { setFormError('Please provide a reason for the adjustment.'); return }

    setSaving(true)
    try {
      await apiClient.put(`/inventory/stock/${form.part_id}`, {
        quantity_change: qty,
        reason,
      })
      setSuccess(`Stock adjusted successfully. ${selectedPart?.part_name}: ${qty > 0 ? '+' : ''}${qty}`)
      setForm(EMPTY_FORM)
      setCustomReason('')
      fetchParts()
    } catch {
      setFormError('Failed to adjust stock. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const partOptions = [
    { value: '', label: 'Select a part…' },
    ...parts.map((p) => ({
      value: p.part_id,
      label: `${p.part_name}${p.part_number ? ` (${p.part_number})` : ''} — Stock: ${p.current_stock}`,
    })),
  ]

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">
        Manually adjust stock levels. All adjustments are recorded in the audit log with the reason provided.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !parts.length && (
        <div className="py-16"><Spinner label="Loading parts" /></div>
      )}

      {!loading && (
        <form onSubmit={handleSubmit} className="max-w-lg space-y-4">
          <Select
            label="Part *"
            options={partOptions}
            value={form.part_id}
            onChange={(e) => setForm((prev) => ({ ...prev, part_id: e.target.value }))}
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
            value={form.quantity_change}
            onChange={(e) => setForm((prev) => ({ ...prev, quantity_change: e.target.value }))}
          />

          {selectedPart && form.quantity_change && !isNaN(parseInt(form.quantity_change, 10)) && (
            <p className="text-sm text-gray-600">
              New stock level will be:{' '}
              <span className="font-medium">
                {selectedPart.current_stock + parseInt(form.quantity_change, 10)}
              </span>
            </p>
          )}

          <Select
            label="Reason *"
            options={REASON_OPTIONS}
            value={form.reason}
            onChange={(e) => setForm((prev) => ({ ...prev, reason: e.target.value }))}
          />

          {form.reason === 'Other' && (
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
              onClick={() => { setForm(EMPTY_FORM); setCustomReason(''); setFormError(''); setSuccess('') }}
            >
              Reset
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}
