/**
 * Pricing Rules management page with create/edit forms, priority ordering,
 * and overlap validation warning.
 *
 * Validates: Requirements 9.1, 9.2, 9.3, 9.4
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Badge, Spinner, Modal } from '@/components/ui'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { detectPricingRuleOverlap } from '@/utils/inventoryCalcs'
import type { PricingRuleForOverlap } from '@/utils/inventoryCalcs'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PricingRule {
  id: string
  product_id: string | null
  rule_type: string
  priority: number
  customer_id: string | null
  customer_tag: string | null
  min_quantity: string | null
  max_quantity: string | null
  start_date: string | null
  end_date: string | null
  price_override: string | null
  discount_percent: string | null
  is_active: boolean
}

interface Product {
  id: string
  name: string
}

interface RuleForm {
  product_id: string
  rule_type: string
  priority: string
  customer_tag: string
  min_quantity: string
  max_quantity: string
  start_date: string
  end_date: string
  price_override: string
  discount_percent: string
  is_active: boolean
}

const EMPTY_FORM: RuleForm = {
  product_id: '', rule_type: 'customer_specific', priority: '0',
  customer_tag: '', min_quantity: '', max_quantity: '',
  start_date: '', end_date: '', price_override: '', discount_percent: '',
  is_active: true,
}

const RULE_TYPES = [
  { value: 'customer_specific', label: 'Customer-Specific' },
  { value: 'volume', label: 'Volume / Tiered' },
  { value: 'date_based', label: 'Date-Based / Promotional' },
  { value: 'trade_category', label: 'Trade Category' },
]

export default function PricingRules() {
  const { isAllowed, isLoading: guardLoading } = useModuleGuard('inventory')
  const productLabel = useTerm('product', 'Product')
  /* useFlag kept for FeatureFlagContext integration per Req 17.2 */
  useFlag('pricing_rules')

  const [rules, setRules] = useState<PricingRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [products, setProducts] = useState<Product[]>([])

  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<RuleForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [overlapWarning, setOverlapWarning] = useState('')

  const fetchRules = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ rules: PricingRule[] }>('/v2/pricing-rules')
      setRules(res.data.rules.sort((a, b) => a.priority - b.priority))
    } catch {
      setError('Failed to load pricing rules.')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchProducts = useCallback(async () => {
    try {
      const res = await apiClient.get<{ products: Product[] }>('/v2/products', { params: { page_size: 500 } })
      setProducts(res.data?.products ?? [])
    } catch { /* non-critical */ }
  }, [])

  useEffect(() => { fetchRules() }, [fetchRules])
  useEffect(() => { fetchProducts() }, [fetchProducts])

  const productMap = useMemo(() => new Map(products.map((p) => [p.id, p.name])), [products])

  /* ---- Overlap detection ---- */
  const checkOverlap = useCallback((currentForm: RuleForm) => {
    if (!currentForm.product_id || !currentForm.start_date || !currentForm.end_date) {
      setOverlapWarning('')
      return
    }

    const candidate: PricingRuleForOverlap = {
      product_id: currentForm.product_id,
      start_date: currentForm.start_date,
      end_date: currentForm.end_date,
    }

    // Build list of existing rules (excluding the one being edited) that have date ranges
    const existingDateRules: PricingRuleForOverlap[] = rules
      .filter((r) => r.id !== editingId && r.product_id && r.start_date && r.end_date)
      .map((r) => ({
        product_id: r.product_id!,
        start_date: r.start_date!,
        end_date: r.end_date!,
      }))

    const allRules = [...existingDateRules, candidate]
    const overlaps = detectPricingRuleOverlap(allRules)

    // Check if the candidate (last index) is involved in any overlap
    const candidateIdx = allRules.length - 1
    const conflicting = overlaps.filter(
      (o) => o.index1 === candidateIdx || o.index2 === candidateIdx,
    )

    if (conflicting.length > 0) {
      const conflictIndices = conflicting.map((o) =>
        o.index1 === candidateIdx ? o.index2 : o.index1,
      )
      const conflictNames = conflictIndices.map((idx) => {
        const r = existingDateRules[idx]
        const pName = productMap.get(r.product_id) || 'Unknown'
        return `${pName} (${r.start_date} – ${r.end_date})`
      })
      setOverlapWarning(`Overlapping rules detected for the same ${productLabel.toLowerCase()}: ${conflictNames.join(', ')}`)
    } else {
      setOverlapWarning('')
    }
  }, [rules, editingId, productMap, productLabel])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setOverlapWarning('')
    setModalOpen(true)
  }

  const openEdit = (rule: PricingRule) => {
    setEditingId(rule.id)
    const newForm: RuleForm = {
      product_id: rule.product_id || '',
      rule_type: rule.rule_type,
      priority: String(rule.priority),
      customer_tag: rule.customer_tag || '',
      min_quantity: rule.min_quantity || '',
      max_quantity: rule.max_quantity || '',
      start_date: rule.start_date || '',
      end_date: rule.end_date || '',
      price_override: rule.price_override || '',
      discount_percent: rule.discount_percent || '',
      is_active: rule.is_active,
    }
    setForm(newForm)
    setFormError('')
    setOverlapWarning('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.rule_type) { setFormError('Rule type is required.'); return }
    if (!form.price_override && !form.discount_percent) {
      setFormError('Either price override or discount percent is required.')
      return
    }

    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = {
        rule_type: form.rule_type,
        priority: parseInt(form.priority, 10) || 0,
        is_active: form.is_active,
      }
      if (form.product_id) body.product_id = form.product_id
      if (form.customer_tag.trim()) body.customer_tag = form.customer_tag.trim()
      if (form.min_quantity) body.min_quantity = parseFloat(form.min_quantity)
      if (form.max_quantity) body.max_quantity = parseFloat(form.max_quantity)
      if (form.start_date) body.start_date = form.start_date
      if (form.end_date) body.end_date = form.end_date
      if (form.price_override) body.price_override = parseFloat(form.price_override)
      if (form.discount_percent) body.discount_percent = parseFloat(form.discount_percent)

      if (editingId) {
        await apiClient.put(`/api/v2/pricing-rules/${editingId}`, body)
      } else {
        await apiClient.post('/api/v2/pricing-rules', body)
      }
      setModalOpen(false)
      fetchRules()
    } catch {
      setFormError('Failed to save pricing rule.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this pricing rule?')) return
    try {
      await apiClient.delete(`/api/v2/pricing-rules/${id}`)
      fetchRules()
    } catch {
      setError('Failed to delete pricing rule.')
    }
  }

  const handleToggle = async (rule: PricingRule) => {
    try {
      await apiClient.put(`/api/v2/pricing-rules/${rule.id}`, { is_active: !rule.is_active })
      fetchRules()
    } catch {
      setError('Failed to toggle rule.')
    }
  }

  const updateField = <K extends keyof RuleForm>(key: K, value: RuleForm[K]) => {
    const updated = { ...form, [key]: value }
    setForm(updated)
    // Re-check overlap when product or dates change
    if (key === 'product_id' || key === 'start_date' || key === 'end_date') {
      checkOverlap(updated)
    }
  }

  const productOptions = [
    { value: '', label: `All ${productLabel.toLowerCase()}s` },
    ...products.map((p) => ({ value: p.id, label: p.name })),
  ]

  if (guardLoading) {
    return <div className="py-16"><Spinner label="Loading" /></div>
  }

  if (!isAllowed) return null

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">
          Pricing rules are evaluated in priority order. Lower numbers = higher priority.
        </p>
        <Button onClick={openCreate} style={{ minWidth: 44, minHeight: 44 }}>+ New Rule</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && (
        <div className="py-16"><Spinner label="Loading pricing rules" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Pricing rules</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Priority</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">{productLabel}</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price / Discount</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Conditions</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {rules.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-500">
                    No pricing rules yet. Create rules to automate pricing.
                  </td>
                </tr>
              ) : (
                rules.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-semibold text-gray-900">{r.priority}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <Badge variant="info">{r.rule_type.replace('_', ' ')}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {r.product_id ? (productMap.get(r.product_id) || 'Unknown') : 'All'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">
                      {r.price_override ? `${parseFloat(r.price_override).toFixed(2)}` : ''}
                      {r.discount_percent ? `${r.discount_percent}% off` : ''}
                      {!r.price_override && !r.discount_percent ? '—' : ''}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 max-w-xs">
                      {r.customer_tag && <span className="mr-2">Tag: {r.customer_tag}</span>}
                      {(r.min_quantity || r.max_quantity) && <span className="mr-2">Qty: {r.min_quantity || '0'}–{r.max_quantity || '∞'}</span>}
                      {(r.start_date || r.end_date) && <span>{r.start_date || '…'} – {r.end_date || '…'}</span>}
                      {!r.customer_tag && !r.min_quantity && !r.max_quantity && !r.start_date && !r.end_date && '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <button
                        onClick={() => handleToggle(r)}
                        aria-label={`Toggle rule ${r.is_active ? 'off' : 'on'}`}
                        style={{ minWidth: 44, minHeight: 44 }}
                        className="inline-flex items-center justify-center"
                      >
                        <Badge variant={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <button onClick={() => openEdit(r)} className="text-blue-600 hover:text-blue-800 mr-2 inline-flex items-center justify-center" style={{ minWidth: 44, minHeight: 44 }} aria-label="Edit rule">Edit</button>
                      <button onClick={() => handleDelete(r.id)} className="text-red-600 hover:text-red-800 inline-flex items-center justify-center" style={{ minWidth: 44, minHeight: 44 }} aria-label="Delete rule">Delete</button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create/Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Pricing Rule' : 'New Pricing Rule'}>
        <div className="space-y-3">
          <Select label="Rule type *" options={RULE_TYPES} value={form.rule_type} onChange={(e) => updateField('rule_type', e.target.value)} />
          <Select label={productLabel} options={productOptions} value={form.product_id} onChange={(e) => updateField('product_id', e.target.value)} />
          <Input label="Priority" type="number" value={form.priority} onChange={(e) => updateField('priority', e.target.value)} placeholder="0 = highest" />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Price override ($)" inputMode="numeric" type="number" step="0.01" value={form.price_override} onChange={(e) => updateField('price_override', e.target.value)} />
            <Input label="Discount (%)" inputMode="numeric" type="number" step="0.01" value={form.discount_percent} onChange={(e) => updateField('discount_percent', e.target.value)} />
          </div>
          {form.rule_type === 'customer_specific' && (
            <Input label="Customer tag" value={form.customer_tag} onChange={(e) => updateField('customer_tag', e.target.value)} />
          )}
          {form.rule_type === 'volume' && (
            <div className="grid grid-cols-2 gap-3">
              <Input label="Min quantity" inputMode="numeric" type="number" value={form.min_quantity} onChange={(e) => updateField('min_quantity', e.target.value)} />
              <Input label="Max quantity" inputMode="numeric" type="number" value={form.max_quantity} onChange={(e) => updateField('max_quantity', e.target.value)} />
            </div>
          )}
          {(form.rule_type === 'date_based' || form.start_date || form.end_date) && (
            <div className="grid grid-cols-2 gap-3">
              <Input label="Start date" type="date" value={form.start_date} onChange={(e) => updateField('start_date', e.target.value)} />
              <Input label="End date" type="date" value={form.end_date} onChange={(e) => updateField('end_date', e.target.value)} />
            </div>
          )}
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.is_active} onChange={(e) => updateField('is_active', e.target.checked)} className="rounded border-gray-300" />
            Active
          </label>
        </div>

        {/* Overlap warning */}
        {overlapWarning && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="alert" data-testid="overlap-warning">
            ⚠️ {overlapWarning}
          </div>
        )}

        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)} style={{ minWidth: 44, minHeight: 44 }}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving} style={{ minWidth: 44, minHeight: 44 }}>{editingId ? 'Save' : 'Create'}</Button>
        </div>
      </Modal>
    </div>
  )
}
