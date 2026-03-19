import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { validateDiscountValue } from './coupon-utils'

/* ── Types ── */

export interface StorageTier {
  tier_name: string
  size_gb: number
  price_nzd_per_month: number
}

export interface SmsPackageTier {
  tier_name: string
  sms_quantity: number
  price_nzd: number
}

export interface Plan {
  id: string
  name: string
  monthly_price_nzd: number
  user_seats: number
  storage_quota_gb: number
  carjam_lookups_included: number
  per_carjam_lookup_cost_nzd: number
  enabled_modules: string[]
  is_public: boolean
  is_archived: boolean
  storage_tier_pricing: StorageTier[]
  trial_duration: number
  trial_duration_unit: 'days' | 'weeks' | 'months'
  sms_included: boolean
  per_sms_cost_nzd: number
  sms_included_quota: number
  sms_package_pricing: SmsPackageTier[]
  created_at: string
  updated_at: string
}

export interface Coupon {
  id: string
  code: string
  description: string | null
  discount_type: 'percentage' | 'fixed_amount' | 'trial_extension'
  discount_value: number
  duration_months: number | null
  usage_limit: number | null
  times_redeemed: number
  is_active: boolean
  starts_at: string | null
  expires_at: string | null
  created_at: string
  updated_at: string
}

export interface ModuleInfo {
  slug: string
  display_name: string
  description: string
  category: string
  is_core: boolean
  dependencies: string[] | null
}

export interface StoragePricingConfig {
  increment_gb: number
  price_per_gb_nzd: number
}

export interface StoragePackage {
  id: string
  name: string
  storage_gb: number
  price_nzd_per_month: number
  description: string | null
  is_active: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

/* ── Helpers ── */

function formatCurrency(n: number) { return `$${n.toFixed(2)}` }
function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
}

const MODULE_CATEGORIES: Record<string, string> = {
  core: 'Core',
  sales: 'Sales & Quoting',
  operations: 'Operations',
  inventory: 'Inventory & Stock',
  pos: 'Point of Sale',
  hospitality: 'Hospitality',
  staff: 'Staff & Scheduling',
  construction: 'Construction',
  compliance: 'Compliance',
  finance: 'Finance',
  engagement: 'Customer Engagement',
  enterprise: 'Enterprise',
  ecommerce: 'Ecommerce',
  admin: 'Admin',
  other: 'Other',
}

/* ── Storage Tier Row ── */

function StorageTierRow({ tier, onChange, onRemove }: {
  tier: StorageTier
  onChange: (t: StorageTier) => void
  onRemove: () => void
}) {
  return (
    <div className="flex items-end gap-2">
      <Input
        label="Tier name"
        value={tier.tier_name}
        onChange={e => onChange({ ...tier, tier_name: e.target.value })}
        className="flex-1"
      />
      <Input
        label="Size (GB)"
        type="number"
        value={String(tier.size_gb)}
        onChange={e => onChange({ ...tier, size_gb: Number(e.target.value) })}
        className="w-24"
      />
      <Input
        label="Price/mo (NZD)"
        type="number"
        step="0.01"
        value={String(tier.price_nzd_per_month)}
        onChange={e => onChange({ ...tier, price_nzd_per_month: Number(e.target.value) })}
        className="w-32"
      />
      <Button type="button" variant="danger" size="sm" onClick={onRemove}>Remove</Button>
    </div>
  )
}

/* ── SMS Package Tier Row ── */

function SmsPackageTierRow({ tier, onChange, onRemove }: {
  tier: SmsPackageTier
  onChange: (t: SmsPackageTier) => void
  onRemove: () => void
}) {
  return (
    <div className="flex items-end gap-2">
      <Input
        label="Tier name"
        value={tier.tier_name}
        onChange={e => onChange({ ...tier, tier_name: e.target.value })}
        className="flex-1"
      />
      <Input
        label="SMS quantity"
        type="number"
        min="1"
        value={String(tier.sms_quantity)}
        onChange={e => onChange({ ...tier, sms_quantity: Number(e.target.value) })}
        className="w-28"
      />
      <Input
        label="Price (NZD)"
        type="number"
        step="0.01"
        min="0"
        value={String(tier.price_nzd)}
        onChange={e => onChange({ ...tier, price_nzd: Number(e.target.value) })}
        className="w-28"
      />
      <Button type="button" variant="danger" size="sm" onClick={onRemove}>Remove</Button>
    </div>
  )
}

/* ── Module Picker ── */

function ModulePicker({ modules, selected, onChange }: {
  modules: ModuleInfo[]
  selected: string[]
  onChange: (slugs: string[]) => void
}) {
  // Group by category
  const grouped = modules.reduce<Record<string, ModuleInfo[]>>((acc, m) => {
    const cat = m.category || 'other'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(m)
    return acc
  }, {})

  const toggle = (slug: string, isCore: boolean) => {
    if (isCore) return // core modules can't be toggled
    if (selected.includes(slug)) {
      onChange(selected.filter(s => s !== slug))
    } else {
      onChange([...selected, slug])
    }
  }

  const selectAll = () => onChange(modules.map(m => m.slug))
  const selectNone = () => onChange(modules.filter(m => m.is_core).map(m => m.slug))

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-gray-700">Enabled modules</label>
        <div className="flex gap-2">
          <button type="button" className="text-xs text-blue-600 hover:underline" onClick={selectAll}>Select all</button>
          <button type="button" className="text-xs text-blue-600 hover:underline" onClick={selectNone}>Core only</button>
        </div>
      </div>
      <div className="max-h-64 overflow-y-auto rounded-md border border-gray-200 p-3 space-y-4" role="group" aria-label="Module selection">
        {Object.entries(grouped).map(([cat, mods]) => (
          <div key={cat}>
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              {MODULE_CATEGORIES[cat] ?? cat}
            </p>
            <div className="space-y-1">
              {mods.map(m => (
                <label key={m.slug} className="flex items-start gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.includes(m.slug)}
                    disabled={m.is_core}
                    onChange={() => toggle(m.slug, m.is_core)}
                    className="mt-0.5"
                  />
                  <span className="flex-1">
                    <span className="font-medium text-gray-800">{m.display_name}</span>
                    {m.is_core && <Badge variant="neutral" className="ml-1 text-[10px]">Core</Badge>}
                    {Array.isArray(m.dependencies) && m.dependencies.length > 0 && (
                      <span className="text-xs text-gray-400 ml-1">
                        (requires {m.dependencies.join(', ')})
                      </span>
                    )}
                    <br />
                    <span className="text-xs text-gray-500">{m.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-gray-500">{selected.length} module{selected.length !== 1 ? 's' : ''} selected</p>
    </div>
  )
}

/* ── Plan Form Modal ── */

interface PlanFormData {
  name: string
  monthly_price_nzd: number
  user_seats: number
  storage_quota_gb: number
  carjam_lookups_included: number
  per_carjam_lookup_cost_nzd: number
  enabled_modules: string[]
  is_public: boolean
  storage_tier_pricing: StorageTier[]
  trial_duration: number
  trial_duration_unit: 'days' | 'weeks' | 'months'
  sms_included: boolean
  per_sms_cost_nzd: number
  sms_included_quota: number
  sms_package_pricing: SmsPackageTier[]
}

const EMPTY_FORM: PlanFormData = {
  name: '',
  monthly_price_nzd: 0,
  user_seats: 1,
  storage_quota_gb: 5,
  carjam_lookups_included: 0,
  per_carjam_lookup_cost_nzd: 0,
  enabled_modules: [],
  is_public: true,
  storage_tier_pricing: [],
  trial_duration: 0,
  trial_duration_unit: 'days',
  sms_included: false,
  per_sms_cost_nzd: 0,
  sms_included_quota: 0,
  sms_package_pricing: [],
}

function PlanFormModal({ open, onClose, onSave, saving, editPlan, modules }: {
  open: boolean
  onClose: () => void
  onSave: (data: PlanFormData) => void
  saving: boolean
  editPlan: Plan | null
  modules: ModuleInfo[]
}) {
  const [form, setForm] = useState<PlanFormData>(EMPTY_FORM)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [activeTab, setActiveTab] = useState<'general' | 'modules' | 'storage'>('general')

  useEffect(() => {
    if (open) {
      if (editPlan) {
        setForm({
          name: editPlan.name,
          monthly_price_nzd: editPlan.monthly_price_nzd,
          user_seats: editPlan.user_seats,
          storage_quota_gb: editPlan.storage_quota_gb,
          carjam_lookups_included: editPlan.carjam_lookups_included,
          per_carjam_lookup_cost_nzd: editPlan.per_carjam_lookup_cost_nzd ?? 0,
          enabled_modules: editPlan.enabled_modules,
          is_public: editPlan.is_public,
          storage_tier_pricing: editPlan.storage_tier_pricing ?? [],
          trial_duration: editPlan.trial_duration ?? 0,
          trial_duration_unit: editPlan.trial_duration_unit ?? 'days',
          sms_included: editPlan.sms_included ?? false,
          per_sms_cost_nzd: editPlan.per_sms_cost_nzd ?? 0,
          sms_included_quota: editPlan.sms_included_quota ?? 0,
          sms_package_pricing: editPlan.sms_package_pricing ?? [],
        })
      } else {
        // Default: include all core modules
        const coreModules = modules.filter(m => m.is_core).map(m => m.slug)
        setForm({ ...EMPTY_FORM, enabled_modules: coreModules })
      }
      setErrors({})
      setActiveTab('general')
    }
  }, [open, editPlan, modules])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: Record<string, string> = {}
    if (!form.name.trim()) errs.name = 'Plan name is required'
    if (form.monthly_price_nzd < 0) errs.monthly_price_nzd = 'Must be >= 0'
    if (form.user_seats < 1) errs.user_seats = 'Must be >= 1'
    if (form.storage_quota_gb < 1) errs.storage_quota_gb = 'Must be >= 1'
    if (Object.keys(errs).length) { setErrors(errs); setActiveTab('general'); return }
    onSave(form)
  }

  const set = <K extends keyof PlanFormData>(k: K, v: PlanFormData[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const addStorageTier = () => {
    set('storage_tier_pricing', [
      ...form.storage_tier_pricing,
      { tier_name: `${form.storage_tier_pricing.length + 1} GB Add-on`, size_gb: 1, price_nzd_per_month: 0.50 },
    ])
  }

  const updateStorageTier = (idx: number, tier: StorageTier) => {
    const updated = [...form.storage_tier_pricing]
    updated[idx] = tier
    set('storage_tier_pricing', updated)
  }

  const removeStorageTier = (idx: number) => {
    set('storage_tier_pricing', form.storage_tier_pricing.filter((_, i) => i !== idx))
  }

  const addSmsPackageTier = () => {
    set('sms_package_pricing', [
      ...form.sms_package_pricing,
      { tier_name: `SMS Pack ${form.sms_package_pricing.length + 1}`, sms_quantity: 100, price_nzd: 10 },
    ])
  }

  const updateSmsPackageTier = (idx: number, tier: SmsPackageTier) => {
    const updated = [...form.sms_package_pricing]
    updated[idx] = tier
    set('sms_package_pricing', updated)
  }

  const removeSmsPackageTier = (idx: number) => {
    set('sms_package_pricing', form.sms_package_pricing.filter((_, i) => i !== idx))
  }

  const tabs = [
    { key: 'general' as const, label: 'General' },
    { key: 'modules' as const, label: 'Modules' },
    { key: 'storage' as const, label: 'Storage' },
  ]

  return (
    <Modal open={open} onClose={onClose} title={editPlan ? 'Edit plan' : 'Create plan'} className="max-w-2xl">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Tabs */}
        <div className="flex border-b border-gray-200 -mx-6 px-6" role="tablist" aria-label="Plan form tabs">
          {tabs.map(t => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={activeTab === t.key}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === t.key
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* General tab */}
        {activeTab === 'general' && (
          <div className="space-y-4" role="tabpanel" aria-label="General settings">
              <Input label="Plan name" value={form.name} onChange={e => set('name', e.target.value)} error={errors.name} />
              <div className="grid grid-cols-2 gap-3">
              <Input label="Monthly price (NZD)" type="number" step="0.01" value={String(form.monthly_price_nzd)} onChange={e => set('monthly_price_nzd', Number(e.target.value))} error={errors.monthly_price_nzd} />
              <Input label="User seats" type="number" value={String(form.user_seats)} onChange={e => set('user_seats', Number(e.target.value))} error={errors.user_seats} />
              <Input label="Included storage (GB)" type="number" value={String(form.storage_quota_gb)} onChange={e => set('storage_quota_gb', Number(e.target.value))} error={errors.storage_quota_gb} helperText="Default storage included with this plan" />
            </div>

            {/* Carjam lookups — only relevant for automotive trades */}
            <fieldset className="rounded-md border border-gray-200 p-3 space-y-2">
              <legend className="text-sm font-medium text-gray-700 px-1">Carjam vehicle lookups</legend>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.carjam_lookups_included > 0}
                  onChange={e => set('carjam_lookups_included', e.target.checked ? 100 : 0)}
                />
                <span>
                  <span className="font-medium">Include Carjam lookups</span>
                  <br />
                  <span className="text-xs text-gray-500">Only needed for automotive trades (workshops, mechanics, fleet). Leave off for other industries.</span>
                </span>
              </label>
              {form.carjam_lookups_included > 0 && (
                <div className="ml-6 space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      label="Included lookup quota"
                      type="number"
                      min="0"
                      value={String(form.carjam_lookups_included)}
                      onChange={e => set('carjam_lookups_included', Math.max(0, Number(e.target.value)))}
                      helperText="Carjam API lookups included per month"
                    />
                    <Input
                      label="Per-lookup cost (NZD)"
                      type="number"
                      step="0.01"
                      min="0"
                      value={String(form.per_carjam_lookup_cost_nzd)}
                      onChange={e => set('per_carjam_lookup_cost_nzd', Math.max(0, Number(e.target.value)))}
                      helperText="Overage cost per lookup beyond quota"
                    />
                  </div>
                </div>
              )}
            </fieldset>

            {/* SMS service */}
            <fieldset className="rounded-md border border-gray-200 p-3 space-y-2">
              <legend className="text-sm font-medium text-gray-700 px-1">SMS service</legend>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.sms_included}
                  onChange={e => set('sms_included', e.target.checked)}
                />
                <span>
                  <span className="font-medium">Include SMS notifications</span>
                  <br />
                  <span className="text-xs text-gray-500">Enable SMS reminders, appointment confirmations and overdue notices for this plan. MFA verification codes are always available regardless of this setting.</span>
                </span>
              </label>
              {form.sms_included && (
                <div className="ml-6 space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      label="Included SMS quota"
                      type="number"
                      min="0"
                      value={String(form.sms_included_quota)}
                      onChange={e => set('sms_included_quota', Math.max(0, Number(e.target.value)))}
                      helperText="Business SMS messages included per month"
                    />
                    <Input
                      label="Per-SMS cost (NZD)"
                      type="number"
                      step="0.0001"
                      min="0"
                      value={String(form.per_sms_cost_nzd)}
                      onChange={e => set('per_sms_cost_nzd', Math.max(0, Number(e.target.value)))}
                      helperText="Overage cost per SMS beyond quota"
                    />
                  </div>
                  <div className="space-y-2">
                    <h4 className="text-sm font-medium text-gray-700">SMS package tiers</h4>
                    <p className="text-xs text-gray-500">Bulk SMS packages organisations can purchase as add-ons.</p>
                    {form.sms_package_pricing.length === 0 && (
                      <p className="text-sm text-gray-500">No SMS package tiers configured.</p>
                    )}
                    {form.sms_package_pricing.map((tier, idx) => (
                      <SmsPackageTierRow
                        key={idx}
                        tier={tier}
                        onChange={t => updateSmsPackageTier(idx, t)}
                        onRemove={() => removeSmsPackageTier(idx)}
                      />
                    ))}
                    <Button type="button" variant="secondary" size="sm" onClick={addSmsPackageTier}>
                      Add SMS package tier
                    </Button>
                  </div>
                </div>
              )}
            </fieldset>

            {/* Visibility */}
            <fieldset className="rounded-md border border-gray-200 p-3 space-y-2">
              <legend className="text-sm font-medium text-gray-700 px-1">Plan visibility</legend>
              <label className="flex items-start gap-2 text-sm cursor-pointer">
                <input type="radio" name="visibility" checked={form.is_public} onChange={() => set('is_public', true)} className="mt-0.5" />
                <span>
                  <span className="font-medium">Public</span>
                  <br />
                  <span className="text-xs text-gray-500">Visible on the public signup page. Organisations can self-select this plan.</span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm cursor-pointer">
                <input type="radio" name="visibility" checked={!form.is_public} onChange={() => set('is_public', false)} className="mt-0.5" />
                <span>
                  <span className="font-medium">Private</span>
                  <br />
                  <span className="text-xs text-gray-500">Hidden from signup. Can only be manually assigned to organisations or used for custom pricing.</span>
                </span>
              </label>
            </fieldset>

            {/* Trial period */}
            <fieldset className="rounded-md border border-gray-200 p-3 space-y-2">
              <legend className="text-sm font-medium text-gray-700 px-1">Trial period</legend>
              <p className="text-xs text-gray-500">Set to 0 for no trial. New signups on this plan will get a free trial for the specified duration.</p>
              <div className="flex items-end gap-3">
                <Input
                  label="Duration"
                  type="number"
                  min="0"
                  value={String(form.trial_duration)}
                  onChange={e => set('trial_duration', Math.max(0, Number(e.target.value)))}
                  className="w-24"
                />
                <div className="flex-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Unit</label>
                  <select
                    value={form.trial_duration_unit}
                    onChange={e => set('trial_duration_unit', e.target.value as 'days' | 'weeks' | 'months')}
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-blue-500"
                    aria-label="Trial duration unit"
                  >
                    <option value="days">Days</option>
                    <option value="weeks">Weeks</option>
                    <option value="months">Months</option>
                  </select>
                </div>
              </div>
              {form.trial_duration > 0 && (
                <p className="text-xs text-blue-600">
                  New signups will get a {form.trial_duration} {form.trial_duration_unit} free trial.
                </p>
              )}
              {form.trial_duration === 0 && (
                <p className="text-xs text-gray-500">
                  No trial — new signups will start with an active subscription immediately.
                </p>
              )}
            </fieldset>
          </div>
        )}

        {/* Modules tab */}
        {activeTab === 'modules' && (
          <div role="tabpanel" aria-label="Module selection">
            <ModulePicker
              modules={modules}
              selected={form.enabled_modules}
              onChange={slugs => set('enabled_modules', slugs)}
            />
          </div>
        )}

        {/* Storage tab */}
        {activeTab === 'storage' && (
          <div className="space-y-4" role="tabpanel" aria-label="Storage configuration">
            <div className="rounded-md bg-blue-50 border border-blue-200 p-3">
              <p className="text-sm text-blue-800">
                This plan includes <span className="font-semibold">{form.storage_quota_gb} GB</span> of storage.
                Add storage tiers below for organisations that need more.
              </p>
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">Add-on storage tiers</h3>
              {form.storage_tier_pricing.length === 0 && (
                <p className="text-sm text-gray-500">No add-on storage tiers configured. Organisations will only have the included storage.</p>
              )}
              {form.storage_tier_pricing.map((tier, idx) => (
                <StorageTierRow
                  key={idx}
                  tier={tier}
                  onChange={t => updateStorageTier(idx, t)}
                  onRemove={() => removeStorageTier(idx)}
                />
              ))}
              <Button type="button" variant="secondary" size="sm" onClick={addStorageTier}>
                Add storage tier
              </Button>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>{editPlan ? 'Update plan' : 'Create plan'}</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Global Storage Pricing Section ── */

function GlobalStoragePricing({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [incrementGb, setIncrementGb] = useState('')
  const [pricePerGb, setPricePerGb] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const fetchPricing = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<Record<string, any>>('/admin/settings')
      const sp = res.data.storage_pricing ?? {}
      setIncrementGb(String(sp.increment_gb ?? 1))
      setPricePerGb(String(sp.price_per_gb_nzd ?? 0.50))
    } catch {
      // non-blocking
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPricing() }, [fetchPricing])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await apiClient.put('/admin/settings', {
        storage_pricing: {
          increment_gb: parseInt(incrementGb, 10),
          price_per_gb_nzd: parseFloat(pricePerGb),
        },
      })
      onToast('success', 'Global storage pricing updated')
    } catch {
      onToast('error', 'Failed to update storage pricing')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner label="Loading storage pricing" />

  return (
    <form onSubmit={handleSave} className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <h2 className="text-base font-semibold text-gray-900">Global Storage Pricing</h2>
      <p className="text-xs text-gray-500">Default add-on storage pricing applied when plans don't define their own tiers.</p>
      <div className="grid grid-cols-2 gap-3 max-w-md">
        <Input
          label="Increment (GB)"
          type="number"
          value={incrementGb}
          onChange={e => setIncrementGb(e.target.value)}
          helperText="Block size for add-on storage"
          required
        />
        <Input
          label="Price per GB (NZD)"
          type="number"
          step="0.01"
          value={pricePerGb}
          onChange={e => setPricePerGb(e.target.value)}
          helperText="Monthly cost per GB"
          required
        />
      </div>
      <Button type="submit" size="sm" loading={saving}>Save pricing</Button>
    </form>
  )
}

/* ── Storage Package Form Modal ── */

interface StoragePackageFormData {
  name: string
  storage_gb: number
  price_nzd_per_month: number
  description: string
  sort_order: number
}

const EMPTY_STORAGE_FORM: StoragePackageFormData = {
  name: '',
  storage_gb: 1,
  price_nzd_per_month: 0,
  description: '',
  sort_order: 0,
}

function StoragePackageFormModal({ open, onClose, onSave, saving, editPackage }: {
  open: boolean
  onClose: () => void
  onSave: (data: StoragePackageFormData) => void
  saving: boolean
  editPackage: StoragePackage | null
}) {
  const [form, setForm] = useState<StoragePackageFormData>(EMPTY_STORAGE_FORM)
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (open) {
      if (editPackage) {
        setForm({
          name: editPackage.name,
          storage_gb: editPackage.storage_gb,
          price_nzd_per_month: editPackage.price_nzd_per_month,
          description: editPackage.description ?? '',
          sort_order: editPackage.sort_order,
        })
      } else {
        setForm(EMPTY_STORAGE_FORM)
      }
      setErrors({})
    }
  }, [open, editPackage])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: Record<string, string> = {}
    if (!form.name.trim()) errs.name = 'Name is required'
    if (form.storage_gb <= 0) errs.storage_gb = 'Must be greater than 0'
    if (form.price_nzd_per_month < 0) errs.price_nzd_per_month = 'Must be >= 0'
    if (Object.keys(errs).length) { setErrors(errs); return }
    onSave(form)
  }

  const set = <K extends keyof StoragePackageFormData>(k: K, v: StoragePackageFormData[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  return (
    <Modal open={open} onClose={onClose} title={editPackage ? 'Edit storage package' : 'Create storage package'} className="max-w-lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Package name"
          value={form.name}
          onChange={e => set('name', e.target.value)}
          error={errors.name}
        />
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Storage (GB)"
            type="number"
            min="1"
            value={String(form.storage_gb)}
            onChange={e => set('storage_gb', Number(e.target.value))}
            error={errors.storage_gb}
          />
          <Input
            label="Price/month (NZD)"
            type="number"
            step="0.01"
            min="0"
            value={String(form.price_nzd_per_month)}
            onChange={e => set('price_nzd_per_month', Number(e.target.value))}
            error={errors.price_nzd_per_month}
          />
        </div>
        <Input
          label="Description"
          value={form.description}
          onChange={e => set('description', e.target.value)}
        />
        <Input
          label="Sort order"
          type="number"
          value={String(form.sort_order)}
          onChange={e => set('sort_order', Number(e.target.value))}
          helperText="Lower numbers appear first"
        />
        <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>{editPackage ? 'Update package' : 'Create package'}</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Storage Packages Content ── */

function StoragePackagesContent({ onToast }: { onToast: (v: 'success' | 'error', msg: string) => void }) {
  const [packages, setPackages] = useState<StoragePackage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [showDeactivated, setShowDeactivated] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [editPackage, setEditPackage] = useState<StoragePackage | null>(null)
  const [saving, setSaving] = useState(false)

  const fetchPackages = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get('/admin/storage-packages', {
        params: { include_inactive: showDeactivated },
      })
      setPackages(res.data.packages ?? [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [showDeactivated])

  useEffect(() => { fetchPackages() }, [fetchPackages])

  const handleSave = async (data: StoragePackageFormData) => {
    setSaving(true)
    try {
      const payload = {
        name: data.name.trim(),
        storage_gb: data.storage_gb,
        price_nzd_per_month: data.price_nzd_per_month,
        description: data.description || null,
        sort_order: data.sort_order,
      }
      if (editPackage) {
        await apiClient.put(`/admin/storage-packages/${editPackage.id}`, payload)
        onToast('success', 'Storage package updated')
      } else {
        await apiClient.post('/admin/storage-packages', payload)
        onToast('success', 'Storage package created')
      }
      setFormOpen(false)
      setEditPackage(null)
      fetchPackages()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      onToast('error', detail || 'Failed to save storage package')
    } finally {
      setSaving(false)
    }
  }

  const handleDeactivate = async (pkg: StoragePackage) => {
    if (!window.confirm(`Deactivate storage package "${pkg.name}"?`)) return
    try {
      await apiClient.delete(`/admin/storage-packages/${pkg.id}`)
      onToast('success', `Package "${pkg.name}" deactivated`)
      fetchPackages()
    } catch {
      onToast('error', 'Failed to deactivate package')
    }
  }

  const handleReactivate = async (pkg: StoragePackage) => {
    try {
      await apiClient.put(`/admin/storage-packages/${pkg.id}`, { is_active: true })
      onToast('success', `Package "${pkg.name}" reactivated`)
      fetchPackages()
    } catch {
      onToast('error', 'Failed to reactivate package')
    }
  }

  const packageColumns: Column<StoragePackage>[] = [
    { key: 'name', header: 'Name', sortable: true },
    { key: 'storage_gb', header: 'Storage (GB)', sortable: true, render: (r) => `${r.storage_gb} GB` },
    {
      key: 'price_nzd_per_month', header: 'Price/mo (NZD)', sortable: true,
      render: (r) => formatCurrency(r.price_nzd_per_month),
    },
    {
      key: 'description', header: 'Description',
      render: (r) => r.description
        ? <span className="text-sm text-gray-600 truncate max-w-[200px] block">{r.description}</span>
        : <span className="text-xs text-gray-400">—</span>,
    },
    { key: 'sort_order', header: 'Sort Order', sortable: true },
    {
      key: 'is_active', header: 'Status',
      render: (r) => <Badge variant={r.is_active ? 'success' : 'warning'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    {
      key: 'id', header: 'Actions',
      render: (r) => (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => { setEditPackage(r); setFormOpen(true) }}>Edit</Button>
          {r.is_active ? (
            <Button size="sm" variant="danger" onClick={() => handleDeactivate(r)}>Deactivate</Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => handleReactivate(r)}>Reactivate</Button>
          )}
        </div>
      ),
    },
  ]

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading storage packages" />
      </div>
    )
  }

  if (error) {
    return <AlertBanner variant="error">Could not load storage packages.</AlertBanner>
  }

  return (
    <>
      <GlobalStoragePricing onToast={onToast} />

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Storage Packages</h2>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={showDeactivated} onChange={e => setShowDeactivated(e.target.checked)} />
            Show deactivated
          </label>
          <Button onClick={() => { setEditPackage(null); setFormOpen(true) }}>Create package</Button>
        </div>
      </div>

      <DataTable
        columns={packageColumns as unknown as Column<Record<string, unknown>>[]}
        data={packages as unknown as Record<string, unknown>[]}
        keyField="id"
        caption="Storage packages table"
      />

      <StoragePackageFormModal
        open={formOpen}
        onClose={() => { setFormOpen(false); setEditPackage(null) }}
        onSave={handleSave}
        saving={saving}
        editPackage={editPackage}
      />
    </>
  )
}

/* ── Coupon Form Modal ── */

interface CouponFormData {
  code: string
  description: string
  discount_type: 'percentage' | 'fixed_amount' | 'trial_extension'
  discount_value: string
  duration_months: string
  usage_limit: string
  starts_at: string
  expires_at: string
}

const EMPTY_COUPON_FORM: CouponFormData = {
  code: '',
  description: '',
  discount_type: 'percentage',
  discount_value: '',
  duration_months: '',
  usage_limit: '',
  starts_at: '',
  expires_at: '',
}

function CouponFormModal({ open, onClose, onSave, saving, editCoupon }: {
  open: boolean
  onClose: () => void
  onSave: (data: CouponFormData) => void
  saving: boolean
  editCoupon: Coupon | null
}) {
  const [form, setForm] = useState<CouponFormData>(EMPTY_COUPON_FORM)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      if (editCoupon) {
        setForm({
          code: editCoupon.code,
          description: editCoupon.description ?? '',
          discount_type: editCoupon.discount_type,
          discount_value: String(editCoupon.discount_value),
          duration_months: editCoupon.duration_months != null ? String(editCoupon.duration_months) : '',
          usage_limit: editCoupon.usage_limit != null ? String(editCoupon.usage_limit) : '',
          starts_at: editCoupon.starts_at ? editCoupon.starts_at.slice(0, 16) : '',
          expires_at: editCoupon.expires_at ? editCoupon.expires_at.slice(0, 16) : '',
        })
      } else {
        setForm(EMPTY_COUPON_FORM)
      }
      setErrors({})
      setApiError(null)
    }
  }, [open, editCoupon])

  const validate = (): Record<string, string> => {
    const errs: Record<string, string> = {}
    const code = form.code.trim()
    if (!code) {
      errs.code = 'Code is required'
    } else if (!/^[A-Za-z0-9_-]+$/.test(code)) {
      errs.code = 'Only letters, numbers, hyphens and underscores'
    } else if (code.length < 3 || code.length > 50) {
      errs.code = 'Must be 3–50 characters'
    }

    if (!form.discount_type) errs.discount_type = 'Discount type is required'

    const dvError = validateDiscountValue(form.discount_value, form.discount_type)
    if (dvError) errs.discount_value = dvError

    if (form.duration_months) {
      const dm = Number(form.duration_months)
      if (isNaN(dm) || dm <= 0 || !Number.isInteger(dm)) errs.duration_months = 'Must be a whole number greater than 0'
    }

    if (form.usage_limit) {
      const ul = Number(form.usage_limit)
      if (isNaN(ul) || ul <= 0 || !Number.isInteger(ul)) errs.usage_limit = 'Must be a whole number greater than 0'
    }

    if (form.starts_at && form.expires_at) {
      if (new Date(form.expires_at) <= new Date(form.starts_at)) {
        errs.expires_at = 'Must be after start date'
      }
    }

    return errs
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setApiError(null)
    const errs = validate()
    if (Object.keys(errs).length) { setErrors(errs); return }
    setErrors({})
    onSave(form)
  }

  const set = <K extends keyof CouponFormData>(k: K, v: CouponFormData[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const discountValueLabel = form.discount_type === 'percentage'
    ? 'Percentage (1-100)'
    : form.discount_type === 'fixed_amount'
      ? 'Amount (NZD)'
      : 'Additional trial days'

  return (
    <Modal open={open} onClose={onClose} title={editCoupon ? 'Edit coupon' : 'Create coupon'} className="max-w-lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        {apiError && <AlertBanner variant="error">{apiError}</AlertBanner>}

        <Input
          label="Coupon code"
          value={form.code}
          onChange={e => set('code', e.target.value)}
          error={errors.code}
          disabled={!!editCoupon}
          helperText={editCoupon ? 'Code cannot be changed after creation' : 'Letters, numbers, hyphens and underscores (3–50 chars)'}
        />

        <Input
          label="Description"
          value={form.description}
          onChange={e => set('description', e.target.value)}
        />

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Discount type</label>
          <select
            value={form.discount_type}
            onChange={e => set('discount_type', e.target.value as CouponFormData['discount_type'])}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-blue-500"
            aria-label="Discount type"
          >
            <option value="percentage">Percentage</option>
            <option value="fixed_amount">Fixed Amount</option>
            <option value="trial_extension">Trial Extension</option>
          </select>
          {errors.discount_type && <p className="mt-1 text-xs text-red-600">{errors.discount_type}</p>}
        </div>

        <Input
          label={discountValueLabel}
          type="number"
          step={form.discount_type === 'trial_extension' ? '1' : '0.01'}
          value={form.discount_value}
          onChange={e => set('discount_value', e.target.value)}
          error={errors.discount_value}
        />

        {form.discount_type !== 'trial_extension' && (
          <Input
            label="Duration (months)"
            type="number"
            min="1"
            step="1"
            value={form.duration_months}
            onChange={e => set('duration_months', e.target.value)}
            error={errors.duration_months}
            helperText="Leave empty for perpetual discount"
          />
        )}

        <Input
          label="Usage limit"
          type="number"
          min="1"
          step="1"
          value={form.usage_limit}
          onChange={e => set('usage_limit', e.target.value)}
          error={errors.usage_limit}
          helperText="Leave empty for unlimited"
        />

        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Starts at"
            type="datetime-local"
            value={form.starts_at}
            onChange={e => set('starts_at', e.target.value)}
            helperText="Optional"
          />
          <Input
            label="Expires at"
            type="datetime-local"
            value={form.expires_at}
            onChange={e => set('expires_at', e.target.value)}
            error={errors.expires_at}
            helperText="Optional"
          />
        </div>

        <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={saving}>{editCoupon ? 'Update coupon' : 'Create coupon'}</Button>
        </div>
      </form>
    </Modal>
  )
}

/* ── Main Page ── */

export function SubscriptionPlans() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [editPlan, setEditPlan] = useState<Plan | null>(null)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  /* ── Tab state (URL-persistent) ── */
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const activeMainTab: 'plans' | 'coupons' | 'storage' =
    tabParam === 'coupons' ? 'coupons' : tabParam === 'storage' ? 'storage' : 'plans'
  const setActiveMainTab = (t: 'plans' | 'coupons' | 'storage') => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('tab', t)
      return next
    }, { replace: true })
  }

  /* ── Coupon state ── */
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [couponsLoading, setCouponsLoading] = useState(false)
  const [couponsError, setCouponsError] = useState(false)
  const [couponFormOpen, setCouponFormOpen] = useState(false)
  const [editCoupon, setEditCoupon] = useState<Coupon | null>(null)
  const [couponSaving, setCouponSaving] = useState(false)

  const fetchPlans = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get('/admin/plans', { params: { include_archived: showArchived } })
      setPlans(res.data.plans ?? [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [showArchived])

  const fetchModules = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/admin/modules/registry')
      setModules(res.data.modules ?? [])
    } catch {
      // non-blocking — form will just show empty module list
    }
  }, [])

  useEffect(() => { fetchPlans() }, [fetchPlans])
  useEffect(() => { fetchModules() }, [fetchModules])

  /* ── Fetch coupons when Coupons tab is active ── */
  const fetchCoupons = useCallback(async () => {
    setCouponsLoading(true)
    setCouponsError(false)
    try {
      const res = await apiClient.get('/admin/coupons')
      setCoupons(res.data.coupons ?? [])
    } catch {
      setCouponsError(true)
    } finally {
      setCouponsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeMainTab === 'coupons') fetchCoupons()
  }, [activeMainTab, fetchCoupons])

  const handleSave = async (data: PlanFormData) => {
    setSaving(true)
    try {
      if (editPlan) {
        await apiClient.put(`/admin/plans/${editPlan.id}`, data)
        addToast('success', 'Plan updated')
      } else {
        await apiClient.post('/admin/plans', data)
        addToast('success', 'Plan created')
      }
      setFormOpen(false)
      setEditPlan(null)
      fetchPlans()
    } catch {
      addToast('error', 'Failed to save plan')
    } finally {
      setSaving(false)
    }
  }

  const handleArchive = async (plan: Plan) => {
    try {
      await apiClient.put(`/admin/plans/${plan.id}/archive`)
      addToast('success', `Plan "${plan.name}" archived`)
      fetchPlans()
    } catch {
      addToast('error', 'Failed to archive plan')
    }
  }

  /* ── Coupon handlers ── */
  const handleCouponSave = async (data: CouponFormData) => {
    setCouponSaving(true)
    try {
      const payload = {
        code: data.code.trim(),
        description: data.description || null,
        discount_type: data.discount_type,
        discount_value: Number(data.discount_value),
        duration_months: data.duration_months ? Number(data.duration_months) : null,
        usage_limit: data.usage_limit ? Number(data.usage_limit) : null,
        starts_at: data.starts_at || null,
        expires_at: data.expires_at || null,
      }
      if (editCoupon) {
        await apiClient.put(`/admin/coupons/${editCoupon.id}`, payload)
        addToast('success', 'Coupon updated')
      } else {
        await apiClient.post('/admin/coupons', payload)
        addToast('success', 'Coupon created')
      }
      setCouponFormOpen(false)
      setEditCoupon(null)
      fetchCoupons()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      addToast('error', detail || 'Failed to save coupon')
    } finally {
      setCouponSaving(false)
    }
  }

  const handleDeactivateCoupon = async (coupon: Coupon) => {
    if (!window.confirm(`Deactivate coupon "${coupon.code}"? It will no longer be redeemable.`)) return
    try {
      await apiClient.delete(`/admin/coupons/${coupon.id}`)
      addToast('success', `Coupon "${coupon.code}" deactivated`)
      fetchCoupons()
    } catch {
      addToast('error', 'Failed to deactivate coupon')
    }
  }

  const handleReactivateCoupon = async (coupon: Coupon) => {
    try {
      await apiClient.put(`/admin/coupons/${coupon.id}/reactivate`)
      addToast('success', `Coupon "${coupon.code}" reactivated`)
      fetchCoupons()
    } catch {
      addToast('error', 'Failed to reactivate coupon')
    }
  }

  const columns: Column<Plan>[] = [
    { key: 'name', header: 'Plan', sortable: true },
    {
      key: 'monthly_price_nzd', header: 'Price/mo', sortable: true,
      render: (r) => formatCurrency(r.monthly_price_nzd),
    },
    { key: 'user_seats', header: 'Seats', sortable: true },
    { key: 'storage_quota_gb', header: 'Storage', render: (r) => `${r.storage_quota_gb} GB` },
    { key: 'carjam_lookups_included', header: 'Carjam', render: (r) => r.carjam_lookups_included > 0 ? `${r.carjam_lookups_included}/mo` : <span className="text-xs text-gray-400">—</span> },
    { key: 'sms_included', header: 'SMS', render: (r) => (r as Plan).sms_included ? <span className="text-green-600">✓</span> : <span className="text-xs text-gray-400">—</span> },
    {
      key: 'enabled_modules', header: 'Modules',
      render: (r) => (
        <span className="text-xs text-gray-600">
          {r.enabled_modules.length} module{r.enabled_modules.length !== 1 ? 's' : ''}
        </span>
      ),
    },
    {
      key: 'is_public', header: 'Visibility',
      render: (r) => (
        <Badge variant={r.is_public ? 'success' : 'warning'}>
          {r.is_public ? 'Public' : 'Private'}
        </Badge>
      ),
    },
    {
      key: 'trial_duration', header: 'Trial',
      render: (r) => {
        const d = (r as Plan).trial_duration
        const u = (r as Plan).trial_duration_unit
        return d > 0 ? <span className="text-sm">{d} {u}</span> : <span className="text-xs text-gray-400">None</span>
      },
    },
    {
      key: 'is_archived', header: 'Status',
      render: (r) => (
        <Badge variant={r.is_archived ? 'warning' : 'success'}>
          {r.is_archived ? 'Archived' : 'Active'}
        </Badge>
      ),
    },
    { key: 'created_at', header: 'Created', render: (r) => formatDate(r.created_at) },
    {
      key: 'id', header: 'Actions',
      render: (r) => (
        <div className="flex gap-2">
          {!r.is_archived && (
            <Button size="sm" variant="secondary" onClick={() => { setEditPlan(r); setFormOpen(true) }}>
              Edit
            </Button>
          )}
          {!r.is_archived && (
            <Button size="sm" variant="danger" onClick={() => handleArchive(r)}>
              Archive
            </Button>
          )}
        </div>
      ),
    },
  ]

  /* ── Coupon table columns ── */
  const couponColumns: Column<Coupon>[] = [
    {
      key: 'code', header: 'Code', sortable: true,
      render: (r) => <span className="font-mono text-sm uppercase">{r.code}</span>,
    },
    {
      key: 'description', header: 'Description',
      render: (r) => r.description ? <span className="text-sm text-gray-600 truncate max-w-[200px] block">{r.description}</span> : <span className="text-xs text-gray-400">—</span>,
    },
    {
      key: 'discount_type', header: 'Type',
      render: (r) => {
        const label = r.discount_type === 'percentage' ? 'Percentage' : r.discount_type === 'fixed_amount' ? 'Fixed Amount' : 'Trial Extension'
        const variant = r.discount_type === 'percentage' ? 'info' as const : r.discount_type === 'fixed_amount' ? 'success' as const : 'neutral' as const
        return <Badge variant={variant}>{label}</Badge>
      },
    },
    {
      key: 'discount_value', header: 'Value',
      render: (r) => {
        if (r.discount_type === 'percentage') return <span>{r.discount_value}%</span>
        if (r.discount_type === 'fixed_amount') return <span>{formatCurrency(r.discount_value)}</span>
        return <span>+{r.discount_value} days</span>
      },
    },
    {
      key: 'duration_months', header: 'Duration',
      render: (r) => r.duration_months ? <span>{r.duration_months} months</span> : r.discount_type === 'trial_extension' ? <span className="text-xs text-gray-400">—</span> : <span className="text-sm text-gray-500">Perpetual</span>,
    },
    {
      key: 'times_redeemed', header: 'Usage',
      render: (r) => <span>{r.times_redeemed} / {r.usage_limit ?? '∞'}</span>,
    },
    {
      key: 'is_active', header: 'Status',
      render: (r) => <Badge variant={r.is_active ? 'success' : 'warning'}>{r.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    { key: 'created_at', header: 'Created', render: (r) => formatDate(r.created_at) },
    {
      key: 'id', header: 'Actions',
      render: (r) => (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => { setEditCoupon(r); setCouponFormOpen(true) }}>Edit</Button>
          {r.is_active ? (
            <Button size="sm" variant="danger" onClick={() => handleDeactivateCoupon(r)}>Deactivate</Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => handleReactivateCoupon(r)}>Reactivate</Button>
          )}
        </div>
      ),
    },
  ]

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading subscription plans" />
      </div>
    )
  }

  if (error) {
    return <AlertBanner variant="error" title="Error">Could not load subscription plans.</AlertBanner>
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">Subscription Management</h1>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200" role="tablist" aria-label="Subscription management tabs">
        <button
          type="button"
          role="tab"
          aria-selected={activeMainTab === 'plans'}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeMainTab === 'plans'
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
          onClick={() => setActiveMainTab('plans')}
        >
          Plans
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeMainTab === 'coupons'}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeMainTab === 'coupons'
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
          onClick={() => setActiveMainTab('coupons')}
        >
          Coupons
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeMainTab === 'storage'}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeMainTab === 'storage'
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
          onClick={() => setActiveMainTab('storage')}
        >
          Storage
        </button>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Plans tab content */}
      {activeMainTab === 'plans' && (
        <>
          <div className="flex items-center justify-end">
            <Button onClick={() => { setEditPlan(null); setFormOpen(true) }}>Create plan</Button>
          </div>

          {/* Plans table */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-gray-900">Plans</h2>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />
                Show archived plans
              </label>
            </div>
            <DataTable columns={columns as unknown as Column<Record<string, unknown>>[]} data={plans as unknown as Record<string, unknown>[]} keyField="id" caption="Subscription plans table" />
          </div>

          <PlanFormModal
            open={formOpen}
            onClose={() => { setFormOpen(false); setEditPlan(null) }}
            onSave={handleSave}
            saving={saving}
            editPlan={editPlan}
            modules={modules}
          />
        </>
      )}

      {/* Coupons tab content */}
      {activeMainTab === 'coupons' && (
        <>
          {couponsLoading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner label="Loading coupons" />
            </div>
          ) : couponsError ? (
            <AlertBanner variant="error">Could not load coupons.</AlertBanner>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900">Coupons</h2>
                <Button onClick={() => { setEditCoupon(null); setCouponFormOpen(true) }}>Create Coupon</Button>
              </div>
              <DataTable
                columns={couponColumns as unknown as Column<Record<string, unknown>>[]}
                data={coupons as unknown as Record<string, unknown>[]}
                keyField="id"
                caption="Coupons table"
              />
            </>
          )}

          <CouponFormModal
            open={couponFormOpen}
            onClose={() => { setCouponFormOpen(false); setEditCoupon(null) }}
            onSave={handleCouponSave}
            saving={couponSaving}
            editCoupon={editCoupon}
          />
        </>
      )}

      {/* Storage tab content */}
      {activeMainTab === 'storage' && (
        <StoragePackagesContent onToast={addToast} />
      )}
    </div>
  )
}
