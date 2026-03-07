import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Badge, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type RuleType = 'visit_count' | 'spend_threshold' | 'customer_tag'
type DiscountType = 'percentage' | 'fixed'
type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface DiscountRule {
  id: string
  name: string
  rule_type: RuleType
  threshold_value: string | null
  discount_type: DiscountType
  discount_value: string
  is_active: boolean
  created_at: string
}

interface DiscountRuleForm {
  name: string
  rule_type: RuleType
  threshold_value: string
  discount_type: DiscountType
  discount_value: string
  is_active: boolean
}

const EMPTY_FORM: DiscountRuleForm = {
  name: '',
  rule_type: 'visit_count',
  threshold_value: '',
  discount_type: 'percentage',
  discount_value: '',
  is_active: true,
}

const RULE_TYPE_OPTIONS = [
  { value: 'visit_count', label: 'Visit Count' },
  { value: 'spend_threshold', label: 'Spend Threshold' },
  { value: 'customer_tag', label: 'Customer Tag' },
]

const DISCOUNT_TYPE_OPTIONS = [
  { value: 'percentage', label: 'Percentage (%)' },
  { value: 'fixed', label: 'Fixed Amount ($)' },
]

function ruleTypeLabel(type: RuleType): string {
  switch (type) {
    case 'visit_count': return 'Visit Count'
    case 'spend_threshold': return 'Spend Threshold'
    case 'customer_tag': return 'Customer Tag'
    default: return type
  }
}

function ruleTypeBadgeVariant(type: RuleType): BadgeVariant {
  switch (type) {
    case 'visit_count': return 'info'
    case 'spend_threshold': return 'warning'
    case 'customer_tag': return 'neutral'
    default: return 'neutral'
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function DiscountRules() {
  const [rules, setRules] = useState<DiscountRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create / Edit modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<DiscountRuleForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  /* Delete confirmation */
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchRules = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ discount_rules: DiscountRule[]; total: number }>('/customers/discount-rules')
      setRules(res.data.discount_rules)
    } catch {
      setError('Failed to load discount rules.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchRules() }, [fetchRules])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (rule: DiscountRule) => {
    setEditingId(rule.id)
    setForm({
      name: rule.name,
      rule_type: rule.rule_type,
      threshold_value: rule.threshold_value || '',
      discount_type: rule.discount_type,
      discount_value: rule.discount_value,
      is_active: rule.is_active,
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Rule name is required.')
      return
    }
    if (!form.discount_value.trim() || isNaN(Number(form.discount_value))) {
      setFormError('Valid discount value is required.')
      return
    }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        rule_type: form.rule_type,
        discount_type: form.discount_type,
        discount_value: form.discount_value.trim(),
        is_active: form.is_active,
      }
      if (form.threshold_value.trim()) body.threshold_value = form.threshold_value.trim()

      if (editingId) {
        await apiClient.put(`/customers/discount-rules/${editingId}`, body)
      } else {
        await apiClient.post('/customers/discount-rules', body)
      }
      setModalOpen(false)
      fetchRules()
    } catch {
      setFormError(editingId ? 'Failed to update discount rule.' : 'Failed to create discount rule.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      await apiClient.delete(`/customers/discount-rules/${deleteId}`)
      setDeleteId(null)
      fetchRules()
    } catch {
      setError('Failed to delete discount rule.')
    } finally {
      setDeleting(false)
    }
  }

  const handleToggleActive = async (rule: DiscountRule) => {
    try {
      await apiClient.put(`/customers/discount-rules/${rule.id}`, { is_active: !rule.is_active })
      fetchRules()
    } catch {
      setError('Failed to update rule status.')
    }
  }

  const updateField = <K extends keyof DiscountRuleForm>(field: K, value: DiscountRuleForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Discount Rules</h1>
          <p className="text-sm text-gray-500 mt-1">Manage loyalty discounts based on visit count, spend, or customer tags</p>
        </div>
        <Button onClick={openCreate}>+ New Rule</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !rules.length && (
        <div className="py-16"><Spinner label="Loading discount rules" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Discount rules</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Threshold</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Discount</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {rules.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                    No discount rules yet. Create one to offer loyalty discounts.
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <tr key={rule.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{rule.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <Badge variant={ruleTypeBadgeVariant(rule.rule_type)}>{ruleTypeLabel(rule.rule_type)}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                      {rule.threshold_value || '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">
                      {rule.discount_type === 'percentage' ? `${rule.discount_value}%` : `$${rule.discount_value}`}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <button
                        onClick={() => handleToggleActive(rule)}
                        className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                        aria-label={`Toggle ${rule.name} ${rule.is_active ? 'off' : 'on'}`}
                      >
                        <Badge variant={rule.is_active ? 'success' : 'neutral'}>
                          {rule.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="secondary" onClick={() => openEdit(rule)}>Edit</Button>
                        <Button size="sm" variant="danger" onClick={() => setDeleteId(rule.id)}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Discount Rule' : 'New Discount Rule'}>
        <div className="space-y-3">
          <Input label="Rule name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <Select
            label="Rule type"
            options={RULE_TYPE_OPTIONS}
            value={form.rule_type}
            onChange={(e) => updateField('rule_type', e.target.value as RuleType)}
          />
          {form.rule_type !== 'customer_tag' && (
            <Input
              label={form.rule_type === 'visit_count' ? 'Minimum visits' : 'Minimum spend ($)'}
              type="number"
              value={form.threshold_value}
              onChange={(e) => updateField('threshold_value', e.target.value)}
              placeholder={form.rule_type === 'visit_count' ? 'e.g. 5' : 'e.g. 500.00'}
            />
          )}
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Discount type"
              options={DISCOUNT_TYPE_OPTIONS}
              value={form.discount_type}
              onChange={(e) => updateField('discount_type', e.target.value as DiscountType)}
            />
            <Input
              label={form.discount_type === 'percentage' ? 'Discount (%)' : 'Discount ($)'}
              type="number"
              value={form.discount_value}
              onChange={(e) => updateField('discount_value', e.target.value)}
              placeholder={form.discount_type === 'percentage' ? 'e.g. 10' : 'e.g. 25.00'}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => updateField('is_active', e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Active
          </label>
        </div>
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Rule'}</Button>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Discount Rule">
        <p className="text-sm text-gray-600 mb-4">
          Are you sure you want to delete this discount rule? Customers currently qualifying for this discount will no longer receive it.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
