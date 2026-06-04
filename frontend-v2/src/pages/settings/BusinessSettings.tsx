/**
 * BusinessSettings — Business entity type, NZBN, GST registration, and tax settings.
 *
 * Sprint 7: Req 29.1, 29.2, 30.1, 30.2
 */
import { useState, useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { Button, ToastContainer, useToast, Spinner } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'

interface BusinessTypeData {
  business_type: string
  nzbn: string | null
  nz_company_number: string | null
  gst_registered: boolean
  gst_registration_date: string | null
  income_tax_year_end: string | null
  provisional_tax_method: string | null
}

const BUSINESS_TYPES = [
  { value: 'sole_trader', label: 'Sole Trader' },
  { value: 'partnership', label: 'Partnership' },
  { value: 'company', label: 'Company' },
  { value: 'trust', label: 'Trust' },
  { value: 'other', label: 'Other' },
]

const PROVISIONAL_METHODS = [
  { value: 'standard', label: 'Standard' },
  { value: 'estimation', label: 'Estimation' },
  { value: 'ratio', label: 'Ratio' },
]

export default function BusinessSettings() {
  const { isEnabled } = useModules()
  const { toasts, addToast, dismissToast } = useToast()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [orgId, setOrgId] = useState<string | null>(null)

  const [form, setForm] = useState<BusinessTypeData>({
    business_type: 'sole_trader',
    nzbn: null,
    nz_company_number: null,
    gst_registered: false,
    gst_registration_date: null,
    income_tax_year_end: null,
    provisional_tax_method: 'standard',
  })
  const [nzbnError, setNzbnError] = useState<string | null>(null)

  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      try {
        const res = await apiClient.get('/org/settings', { signal: controller.signal })
        const orgIdVal = res.data?.org_id ?? null
        setOrgId(orgIdVal)
        setForm({
          business_type: res.data?.business_type ?? 'sole_trader',
          nzbn: res.data?.nzbn ?? null,
          nz_company_number: res.data?.nz_company_number ?? null,
          gst_registered: res.data?.gst_registered ?? false,
          gst_registration_date: res.data?.gst_registration_date ?? null,
          income_tax_year_end: res.data?.income_tax_year_end ?? null,
          provisional_tax_method: res.data?.provisional_tax_method ?? 'standard',
        })
      } catch {
        if (!controller.signal.aborted) {
          addToast('error', 'Failed to load business settings')
        }
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const validateNzbn = (value: string): boolean => {
    if (!value) return true // optional
    if (!/^\d{13}$/.test(value)) {
      setNzbnError('NZBN must be exactly 13 digits')
      return false
    }
    setNzbnError(null)
    return true
  }

  const handleSave = async () => {
    if (form.nzbn && !validateNzbn(form.nzbn)) return
    if (!orgId) {
      addToast('error', 'Organisation ID not found')
      return
    }

    setSaving(true)
    try {
      await apiClient.put(`/organisations/${orgId}/business-type`, {
        business_type: form.business_type,
        nzbn: form.nzbn || null,
        nz_company_number: form.nz_company_number || null,
        gst_registered: form.gst_registered,
        gst_registration_date: form.gst_registration_date || null,
        income_tax_year_end: form.income_tax_year_end || null,
        provisional_tax_method: form.provisional_tax_method,
      })
      addToast('success', 'Business settings updated')
    } catch {
      addToast('error', 'Failed to update business settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <h2 className="text-lg font-semibold text-text">Business Entity Settings</h2>
      <p className="text-sm text-muted">
        Configure your business entity type, NZBN, and tax settings. These affect tax calculations and IRD return types.
      </p>

      {/* Business Type */}
      <div className="flex flex-col gap-1">
        <label htmlFor="business-type" className="text-sm font-medium text-text">
          Business Type
        </label>
        <select
          id="business-type"
          value={form.business_type}
          onChange={(e) => setForm({ ...form, business_type: e.target.value })}
          className="rounded-ctl border border-border px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] bg-card"
        >
          {BUSINESS_TYPES.map((bt) => (
            <option key={bt.value} value={bt.value}>{bt.label}</option>
          ))}
        </select>
      </div>

      {/* NZBN */}
      <div className="flex flex-col gap-1">
        <label htmlFor="nzbn" className="text-sm font-medium text-text">
          NZBN (New Zealand Business Number)
        </label>
        <input
          id="nzbn"
          type="text"
          maxLength={13}
          placeholder="13-digit NZBN"
          value={form.nzbn ?? ''}
          onChange={(e) => {
            setForm({ ...form, nzbn: e.target.value || null })
            if (nzbnError) validateNzbn(e.target.value)
          }}
          onBlur={(e) => validateNzbn(e.target.value)}
          className={`rounded-ctl border px-3 py-2 text-text shadow-sm focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] ${
            nzbnError ? 'border-danger' : 'border-border focus:border-accent'
          }`}
        />
        {nzbnError && <p className="text-sm text-danger">{nzbnError}</p>}
      </div>

      {/* NZ Company Number */}
      <div className="flex flex-col gap-1">
        <label htmlFor="company-number" className="text-sm font-medium text-text">
          NZ Company Number
        </label>
        <input
          id="company-number"
          type="text"
          maxLength={10}
          placeholder="Companies Office number"
          value={form.nz_company_number ?? ''}
          onChange={(e) => setForm({ ...form, nz_company_number: e.target.value || null })}
          className="rounded-ctl border border-border px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
        />
      </div>

      {/* GST Registered Toggle */}
      <div className="flex items-center gap-3">
        <input
          id="gst-registered"
          type="checkbox"
          checked={form.gst_registered}
          onChange={(e) => setForm({ ...form, gst_registered: e.target.checked })}
          className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
        />
        <label htmlFor="gst-registered" className="text-sm font-medium text-text">
          GST Registered
        </label>
      </div>

      {/* GST Registration Date */}
      {form.gst_registered && (
        <div className="flex flex-col gap-1">
          <label htmlFor="gst-reg-date" className="text-sm font-medium text-text">
            GST Registration Date
          </label>
          <input
            id="gst-reg-date"
            type="date"
            value={form.gst_registration_date ?? ''}
            onChange={(e) => setForm({ ...form, gst_registration_date: e.target.value || null })}
            className="rounded-ctl border border-border px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
        </div>
      )}

      {/* Income Tax Year End */}
      <div className="flex flex-col gap-1">
        <label htmlFor="tax-year-end" className="text-sm font-medium text-text">
          Income Tax Year End
        </label>
        <input
          id="tax-year-end"
          type="date"
          value={form.income_tax_year_end ?? ''}
          onChange={(e) => setForm({ ...form, income_tax_year_end: e.target.value || null })}
          className="rounded-ctl border border-border px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
        />
      </div>

      {/* Provisional Tax Method */}
      <div className="flex flex-col gap-1">
        <label htmlFor="prov-method" className="text-sm font-medium text-text">
          Provisional Tax Method
        </label>
        <select
          id="prov-method"
          value={form.provisional_tax_method ?? 'standard'}
          onChange={(e) => setForm({ ...form, provisional_tax_method: e.target.value })}
          className="rounded-ctl border border-border px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] bg-card"
        >
          {PROVISIONAL_METHODS.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
      </div>

      <Button onClick={handleSave} loading={saving}>
        Save Business Settings
      </Button>
    </div>
  )
}
