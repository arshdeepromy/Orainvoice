import { useState, useEffect, useRef, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { CountrySelect, resolveCountryCode } from '@/components/ui/CountrySelect'
import { useTenant } from '@/contexts/TenantContext'
import apiClient from '@/api/client'

/* ── Types ── */

interface TradeFamily {
  id: string
  name: string
  slug: string
}

interface TradeCategory {
  id: string
  name: string
  slug: string
  family_id: string
}

interface BrandingForm {
  name: string
  logo_url: string | null
  primary_colour: string
  secondary_colour: string
  sidebar_display_mode: string
  address_unit: string
  address_street: string
  address_city: string
  address_state: string
  address_country: string
  address_postcode: string
  website: string
  phone: string
  email: string
  invoice_header_text: string
  invoice_footer_text: string
  email_signature: string
}

interface GstForm {
  gst_number: string
  gst_percentage: number
  gst_inclusive: boolean
}

interface InvoiceForm {
  invoice_prefix: string
  invoice_start_number: number
  default_due_days: number
  default_notes: string
  payment_terms_days: number
  payment_terms_text: string
  allow_partial_payments: boolean
}

/* ── Branding Tab ── */

function BrandingTab() {
  const { refetch: refetchTenant } = useTenant()
  const [form, setForm] = useState<BrandingForm>({
    name: '', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', sidebar_display_mode: 'icon_and_name',
    address_unit: '', address_street: '', address_city: '', address_state: '', address_country: 'NZ', address_postcode: '',
    website: '', phone: '', email: '', invoice_header_text: '', invoice_footer_text: '', email_signature: '',
  })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiClient.get('/org/settings').then(({ data }) => {
      setForm({
        name: data.org_name || data.name || '', logo_url: data.logo_url || null,
        primary_colour: data.primary_colour || '#2563eb', secondary_colour: data.secondary_colour || '#1e40af',
        sidebar_display_mode: data.sidebar_display_mode || 'icon_and_name',
        address_unit: data.address_unit || '', address_street: data.address_street || data.address || '',
        address_city: data.address_city || '', address_state: data.address_state || '',
        address_country: resolveCountryCode(data.address_country || 'NZ'), address_postcode: data.address_postcode || '',
        website: data.website || '', phone: data.phone || '', email: data.email || '',
        invoice_header_text: data.invoice_header_text || '', invoice_footer_text: data.invoice_footer_text || '',
        email_signature: data.email_signature || '',
      })
    })
  }, [])

  const update = (field: keyof BrandingForm, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }))

  const handleLogoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!['image/png', 'image/svg+xml'].includes(file.type)) {
      addToast('error', 'Logo must be PNG or SVG')
      return
    }
    const reader = new FileReader()
    reader.onload = () => setForm((prev) => ({ ...prev, logo_url: reader.result as string }))
    reader.readAsDataURL(file)
  }

  const save = async () => {
    setSaving(true)
    try {
      await apiClient.put('/org/settings', { ...form, org_name: form.name })
      await refetchTenant()
      addToast('success', 'Branding saved')
    } catch {
      addToast('error', 'Failed to save branding')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Input label="Organisation Name" value={form.name} onChange={(e) => update('name', e.target.value)} required />

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Logo (PNG or SVG)</label>
        <div className="flex items-center gap-4">
          {form.logo_url && (
            <img src={form.logo_url} alt="Organisation logo" className="h-12 w-12 rounded object-contain border" />
          )}
          <input ref={fileRef} type="file" accept=".png,.svg,image/png,image/svg+xml" onChange={handleLogoUpload} className="text-sm" />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="primary-colour" className="text-sm font-medium text-gray-700">Primary Colour</label>
          <div className="flex items-center gap-2">
            <input id="primary-colour" type="color" value={form.primary_colour} onChange={(e) => update('primary_colour', e.target.value)} className="h-10 w-10 rounded border cursor-pointer" />
            <span className="text-sm text-gray-500">{form.primary_colour}</span>
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="secondary-colour" className="text-sm font-medium text-gray-700">Secondary Colour</label>
          <div className="flex items-center gap-2">
            <input id="secondary-colour" type="color" value={form.secondary_colour} onChange={(e) => update('secondary_colour', e.target.value)} className="h-10 w-10 rounded border cursor-pointer" />
            <span className="text-sm text-gray-500">{form.secondary_colour}</span>
          </div>
        </div>
      </div>

      {/* Sidebar Display Mode */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Sidebar Display</label>
        <p className="text-xs text-gray-500 mb-2">Choose how your branding appears in the sidebar</p>
        <div className="flex gap-3">
          {([
            { value: 'icon_and_name', label: 'Icon & Name', desc: 'Show logo and organisation name' },
            { value: 'icon_only', label: 'Icon Only', desc: 'Show only the logo' },
            { value: 'name_only', label: 'Name Only', desc: 'Show only the organisation name' },
          ] as const).map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => update('sidebar_display_mode', opt.value)}
              className={`flex-1 rounded-lg border-2 p-3 text-left transition-colors ${
                form.sidebar_display_mode === opt.value
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <span className="block text-sm font-medium text-gray-900">{opt.label}</span>
              <span className="block text-xs text-gray-500 mt-0.5">{opt.desc}</span>
            </button>
          ))}
        </div>
        {form.sidebar_display_mode === 'icon_only' && !form.logo_url && (
          <p className="text-xs text-amber-600 mt-1">No logo uploaded — organisation name will be shown as fallback</p>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input label="Unit / Suite" value={form.address_unit} onChange={(e) => update('address_unit', e.target.value)} placeholder="e.g. Unit 3" />
        <Input label="Street Number & Name" value={form.address_street} onChange={(e) => update('address_street', e.target.value)} placeholder="e.g. 34 Wai Iti Place" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Input label="City / Town" value={form.address_city} onChange={(e) => update('address_city', e.target.value)} placeholder="e.g. Auckland" />
        <Input label="State / Region" value={form.address_state} onChange={(e) => update('address_state', e.target.value)} placeholder="e.g. Auckland" />
        <Input label="Postcode" value={form.address_postcode} onChange={(e) => update('address_postcode', e.target.value)} placeholder="e.g. 0600" />
      </div>
      <CountrySelect label="Country" value={form.address_country} onChange={(code) => update('address_country', code)} />
      <Input label="Website" value={form.website} onChange={(e) => update('website', e.target.value)} placeholder="e.g. https://www.example.co.nz" type="url" />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input label="Phone" value={form.phone} onChange={(e) => update('phone', e.target.value)} type="tel" />
        <Input label="Email" value={form.email} onChange={(e) => update('email', e.target.value)} type="email" />
      </div>
      <Input label="Invoice Header Text" value={form.invoice_header_text} onChange={(e) => update('invoice_header_text', e.target.value)} />
      <Input label="Invoice Footer Text" value={form.invoice_footer_text} onChange={(e) => update('invoice_footer_text', e.target.value)} />
      <div className="flex flex-col gap-1">
        <label htmlFor="email-sig" className="text-sm font-medium text-gray-700">Email Signature</label>
        <textarea id="email-sig" rows={3} value={form.email_signature} onChange={(e) => update('email_signature', e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      <Button onClick={save} loading={saving}>Save Branding</Button>
    </div>
  )
}

/* ── GST Tab ── */

function GstTab() {
  const [form, setForm] = useState<GstForm>({ gst_number: '', gst_percentage: 15, gst_inclusive: true })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()
  const [gstError, setGstError] = useState('')

  useEffect(() => {
    apiClient.get('/org/settings').then(({ data }) => {
      setForm({ gst_number: data.gst_number || '', gst_percentage: data.gst_percentage ?? 15, gst_inclusive: data.gst_inclusive ?? true })
    })
  }, [])

  const validateGst = (value: string) => {
    if (value && !/^\d{8,9}$/.test(value.replace(/-/g, ''))) {
      setGstError('GST number must be 8 or 9 digits (IRD format)')
      return false
    }
    setGstError('')
    return true
  }

  const save = async () => {
    if (!validateGst(form.gst_number)) return
    setSaving(true)
    try {
      await apiClient.put('/org/settings', form)
      addToast('success', 'GST settings saved')
    } catch {
      addToast('error', 'Failed to save GST settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Input label="GST Number" value={form.gst_number}
        onChange={(e) => { setForm((p) => ({ ...p, gst_number: e.target.value })); validateGst(e.target.value) }}
        error={gstError} helperText="IRD GST number (8 or 9 digits)" placeholder="123456789" />
      <Input label="GST Percentage" type="number" min={0} max={100} step={0.5}
        value={String(form.gst_percentage)}
        onChange={(e) => setForm((p) => ({ ...p, gst_percentage: parseFloat(e.target.value) || 0 }))}
        helperText="Default: 15%" />
      <div className="flex items-center gap-3">
        <label htmlFor="gst-toggle" className="text-sm font-medium text-gray-700">Default invoice display</label>
        <button id="gst-toggle" role="switch" aria-checked={form.gst_inclusive}
          onClick={() => setForm((p) => ({ ...p, gst_inclusive: !p.gst_inclusive }))}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.gst_inclusive ? 'bg-blue-600' : 'bg-gray-300'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.gst_inclusive ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
        <span className="text-sm text-gray-600">{form.gst_inclusive ? 'GST Inclusive' : 'GST Exclusive'}</span>
      </div>
      <Button onClick={save} loading={saving}>Save GST Settings</Button>
    </div>
  )
}

/* ── Invoice Tab ── */

function InvoiceTab() {
  const [form, setForm] = useState<InvoiceForm>({
    invoice_prefix: 'INV-', invoice_start_number: 1, default_due_days: 14,
    default_notes: '', payment_terms_days: 14, payment_terms_text: '', allow_partial_payments: false,
  })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    apiClient.get('/org/settings').then(({ data }) => {
      setForm({
        invoice_prefix: data.invoice_prefix || 'INV-', invoice_start_number: data.invoice_start_number ?? 1,
        default_due_days: data.default_due_days ?? 14, default_notes: data.default_notes || '',
        payment_terms_days: data.payment_terms_days ?? 14, payment_terms_text: data.payment_terms_text || '',
        allow_partial_payments: data.allow_partial_payments ?? false,
      })
    })
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await apiClient.put('/org/settings', form)
      addToast('success', 'Invoice settings saved')
    } catch {
      addToast('error', 'Failed to save invoice settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Input label="Invoice Prefix" value={form.invoice_prefix} onChange={(e) => setForm((p) => ({ ...p, invoice_prefix: e.target.value }))} placeholder="INV-" />
        <Input label="Starting Invoice Number" type="number" min={1} value={String(form.invoice_start_number)} onChange={(e) => setForm((p) => ({ ...p, invoice_start_number: parseInt(e.target.value) || 1 }))} />
      </div>
      <Input label="Default Due Days" type="number" min={0} value={String(form.default_due_days)}
        onChange={(e) => setForm((p) => ({ ...p, default_due_days: parseInt(e.target.value) || 0 }))} helperText="Days from issue date" />
      <div className="flex flex-col gap-1">
        <label htmlFor="default-notes" className="text-sm font-medium text-gray-700">Default Invoice Notes</label>
        <textarea id="default-notes" rows={3} value={form.default_notes}
          onChange={(e) => setForm((p) => ({ ...p, default_notes: e.target.value }))}
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      <hr className="border-gray-200" />
      <h3 className="text-base font-medium text-gray-900">Payment Terms</h3>
      <Input label="Payment Terms (days)" type="number" min={0} value={String(form.payment_terms_days)}
        onChange={(e) => setForm((p) => ({ ...p, payment_terms_days: parseInt(e.target.value) || 0 }))} />
      <div className="flex flex-col gap-1">
        <label htmlFor="payment-terms" className="text-sm font-medium text-gray-700">Payment Terms Statement</label>
        <textarea id="payment-terms" rows={2} value={form.payment_terms_text}
          onChange={(e) => setForm((p) => ({ ...p, payment_terms_text: e.target.value }))}
          placeholder="Payment is due within 14 days of invoice date."
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      <div className="flex items-center gap-3">
        <label htmlFor="partial-toggle" className="text-sm font-medium text-gray-700">Allow Partial Payments</label>
        <button id="partial-toggle" role="switch" aria-checked={form.allow_partial_payments}
          onClick={() => setForm((p) => ({ ...p, allow_partial_payments: !p.allow_partial_payments }))}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.allow_partial_payments ? 'bg-blue-600' : 'bg-gray-300'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.allow_partial_payments ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      </div>
      <Button onClick={save} loading={saving}>Save Invoice Settings</Button>
    </div>
  )
}

/* ── Rich Text T&C Editor ── */

function TermsTab() {
  const editorRef = useRef<HTMLDivElement>(null)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    apiClient.get('/org/settings').then(({ data }) => {
      if (editorRef.current && data.terms_and_conditions) {
        editorRef.current.innerHTML = data.terms_and_conditions
      }
    })
  }, [])

  const exec = useCallback((command: string, value?: string) => {
    document.execCommand(command, false, value)
    editorRef.current?.focus()
  }, [])

  const insertLink = () => {
    const url = prompt('Enter URL:')
    if (url) exec('createLink', url)
  }

  const save = async () => {
    setSaving(true)
    try {
      await apiClient.put('/org/settings', { terms_and_conditions: editorRef.current?.innerHTML || '' })
      addToast('success', 'Terms & Conditions saved')
    } catch {
      addToast('error', 'Failed to save T&C')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <p className="text-sm text-gray-600">Custom terms and conditions displayed at the bottom of every invoice PDF.</p>

      <div className="flex flex-wrap gap-1 rounded-t-md border border-b-0 border-gray-300 bg-gray-50 p-2" role="toolbar" aria-label="Text formatting">
        <ToolbarBtn label="Bold" onClick={() => exec('bold')}><strong>B</strong></ToolbarBtn>
        <ToolbarBtn label="Heading" onClick={() => exec('formatBlock', 'h3')}>H</ToolbarBtn>
        <ToolbarBtn label="Paragraph" onClick={() => exec('formatBlock', 'p')}>¶</ToolbarBtn>
        <ToolbarBtn label="Bullet list" onClick={() => exec('insertUnorderedList')}>•</ToolbarBtn>
        <ToolbarBtn label="Insert link" onClick={insertLink}>🔗</ToolbarBtn>
      </div>

      <div ref={editorRef} contentEditable role="textbox" aria-multiline="true" aria-label="Terms and conditions editor"
        className="min-h-[200px] rounded-b-md border border-gray-300 p-4 text-gray-900 prose prose-sm max-w-none focus:outline-none focus:ring-2 focus:ring-blue-500" />

      <Button onClick={save} loading={saving}>Save Terms &amp; Conditions</Button>
    </div>
  )
}

function ToolbarBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className="rounded px-2.5 py-1 text-sm font-medium text-gray-700 hover:bg-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
      {children}
    </button>
  )
}

/* ── Business Type Tab ── */

function BusinessTypeTab() {
  const { refetch: refetchTenant } = useTenant()
  const [families, setFamilies] = useState<TradeFamily[]>([])
  const [categories, setCategories] = useState<TradeCategory[]>([])
  const [currentSlug, setCurrentSlug] = useState<string | null>(null)
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      try {
        const [famRes, catRes, settingsRes] = await Promise.all([
          apiClient.get('/api/v2/trade-families', { signal: controller.signal }),
          apiClient.get('/api/v2/trade-categories', { signal: controller.signal }),
          apiClient.get('/org/settings', { signal: controller.signal }),
        ])
        setFamilies(famRes.data?.families ?? [])
        setCategories(catRes.data?.categories ?? [])
        const slug = settingsRes.data?.trade_category ?? null
        setCurrentSlug(slug)
        setSelectedSlug(slug)
      } catch {
        if (!controller.signal.aborted) {
          addToast('error', 'Failed to load trade categories')
        }
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    return () => controller.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (selectedSlug === currentSlug) return
    setSaving(true)
    try {
      await apiClient.put('/org/settings', { trade_category_slug: selectedSlug })
      setCurrentSlug(selectedSlug)
      await refetchTenant()
      addToast('success', 'Business type updated')
    } catch {
      addToast('error', 'Failed to update business type')
    } finally {
      setSaving(false)
    }
  }

  // Group categories by family
  const grouped = families
    .map((fam) => ({
      family: fam,
      items: categories.filter((cat) => cat.family_id === fam.id),
    }))
    .filter((g) => g.items.length > 0)

  if (loading) {
    return <p className="text-sm text-gray-500">Loading trade categories…</p>
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <p className="text-sm text-gray-600">
        Select the trade category that best describes your business. This controls which catalogue items and features are shown in the sidebar.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="trade-category" className="text-sm font-medium text-gray-700">Business Type</label>
        <select
          id="trade-category"
          value={selectedSlug ?? ''}
          onChange={(e) => setSelectedSlug(e.target.value || null)}
          className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
        >
          <option value="">— Select a trade category —</option>
          {grouped.map((g) => (
            <optgroup key={g.family.id} label={g.family.name}>
              {g.items.map((cat) => (
                <option key={cat.id} value={cat.slug}>
                  {cat.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {selectedSlug && selectedSlug !== currentSlug && (
        <p className="text-sm text-amber-600">
          Changing your business type will update which features and catalogue items are visible.
        </p>
      )}

      <Button onClick={save} loading={saving} disabled={selectedSlug === currentSlug}>
        Save Business Type
      </Button>
    </div>
  )
}

/* ── Main Export ── */

export function OrgSettings() {
  const tabs = [
    { id: 'branding', label: 'Branding', content: <BrandingTab /> },
    { id: 'business-type', label: 'Business Type', content: <BusinessTypeTab /> },
    { id: 'gst', label: 'GST', content: <GstTab /> },
    { id: 'invoice', label: 'Invoice', content: <InvoiceTab /> },
    { id: 'terms', label: 'Terms & Conditions', content: <TermsTab /> },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Organisation Settings</h1>
      <Tabs tabs={tabs} defaultTab="branding" />
    </div>
  )
}
