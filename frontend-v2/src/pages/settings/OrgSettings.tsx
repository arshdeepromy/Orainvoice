import { useState, useEffect, useRef, useCallback } from 'react'
import { Button, Input, Tabs, ToastContainer, useToast, CountrySelect, resolveCountryCode } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import apiClient from '@/api/client'

/* ── Types ── */

interface TradeFamily {
  id: string
  display_name: string
  slug: string
}

interface TradeCategory {
  id: string
  display_name: string
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
  email_signature_enabled: boolean
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
  default_notes_enabled: boolean
  payment_terms_days: number
  payment_terms_text: string
  payment_terms_enabled: boolean
  allow_partial_payments: boolean
  pos_preview_enabled: boolean
}

/* ── Branding Tab ── */

function BrandingTab() {
  const { refetch: refetchTenant } = useTenant()
  const [form, setForm] = useState<BrandingForm>({
    name: '', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', sidebar_display_mode: 'icon_and_name',
    address_unit: '', address_street: '', address_city: '', address_state: '', address_country: 'NZ', address_postcode: '',
    website: '', phone: '', email: '', invoice_header_text: '', invoice_footer_text: '', email_signature: '',
    email_signature_enabled: false,
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
        email_signature_enabled: data?.email_signature_enabled ?? false,
      })
    })
  }, [])

  const update = (field: keyof BrandingForm, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }))

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!['image/png', 'image/svg+xml', 'image/jpeg', 'image/webp'].includes(file.type)) {
      addToast('error', 'Logo must be PNG, JPG, WebP, or SVG')
      return
    }
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await apiClient.post('/api/v2/setup-wizard/upload-logo', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const serverUrl = res.data?.url ?? ''
      if (serverUrl) {
        setForm((prev) => ({ ...prev, logo_url: serverUrl }))
        addToast('success', 'Logo uploaded')
      }
    } catch {
      addToast('error', 'Failed to upload logo')
    }
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
        <label className="text-sm font-medium text-text">Logo (PNG or SVG)</label>
        <div className="flex items-center gap-4">
          {form.logo_url && (
            <img src={form.logo_url} alt="Organisation logo" className="h-12 w-12 rounded object-contain border border-border" />
          )}
          <input ref={fileRef} type="file" accept=".png,.svg,image/png,image/svg+xml" onChange={handleLogoUpload} className="text-sm" />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="primary-colour" className="text-sm font-medium text-text">Primary Colour</label>
          <div className="flex items-center gap-2">
            <input id="primary-colour" type="color" value={form.primary_colour} onChange={(e) => update('primary_colour', e.target.value)} className="h-10 w-10 rounded border border-border cursor-pointer" />
            <span className="text-sm text-muted-2">{form.primary_colour}</span>
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="secondary-colour" className="text-sm font-medium text-text">Secondary Colour</label>
          <div className="flex items-center gap-2">
            <input id="secondary-colour" type="color" value={form.secondary_colour} onChange={(e) => update('secondary_colour', e.target.value)} className="h-10 w-10 rounded border border-border cursor-pointer" />
            <span className="text-sm text-muted-2">{form.secondary_colour}</span>
          </div>
        </div>
      </div>

      {/* Sidebar Display Mode */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-text">Sidebar Display</label>
        <p className="text-xs text-muted-2 mb-2">Choose how your branding appears in the sidebar</p>
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
              className={`flex-1 rounded-card border-2 p-3 text-left transition-colors ${
                form.sidebar_display_mode === opt.value
                  ? 'border-accent bg-accent-soft'
                  : 'border-border hover:border-border-strong'
              }`}
            >
              <span className="block text-sm font-medium text-text">{opt.label}</span>
              <span className="block text-xs text-muted-2 mt-0.5">{opt.desc}</span>
            </button>
          ))}
        </div>
        {form.sidebar_display_mode === 'icon_only' && !form.logo_url && (
          <p className="text-xs text-warn mt-1">No logo uploaded — organisation name will be shown as fallback</p>
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
        <div className="flex items-center gap-3 mb-1">
          <label htmlFor="email-sig-toggle" className="text-sm font-medium text-text">Enable email signature on outgoing emails</label>
          <button id="email-sig-toggle" role="switch" aria-checked={form.email_signature_enabled}
            onClick={() => setForm((p) => ({ ...p, email_signature_enabled: !p.email_signature_enabled }))}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.email_signature_enabled ? 'bg-accent' : 'bg-border-strong'}`}>
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.email_signature_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <div className={!form.email_signature_enabled ? 'opacity-50 pointer-events-none' : ''}>
          <label htmlFor="email-sig" className="text-sm font-medium text-text">Email Signature</label>
          <textarea id="email-sig" rows={3} value={form.email_signature} onChange={(e) => update('email_signature', e.target.value)}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
        </div>
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
        <label htmlFor="gst-toggle" className="text-sm font-medium text-text">Default invoice display</label>
        <button id="gst-toggle" role="switch" aria-checked={form.gst_inclusive}
          onClick={() => setForm((p) => ({ ...p, gst_inclusive: !p.gst_inclusive }))}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.gst_inclusive ? 'bg-accent' : 'bg-border-strong'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.gst_inclusive ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
        <span className="text-sm text-muted">{form.gst_inclusive ? 'GST Inclusive' : 'GST Exclusive'}</span>
      </div>
      <Button onClick={save} loading={saving}>Save GST Settings</Button>
    </div>
  )
}

/* ── Invoice Tab ── */

function InvoiceTab() {
  const { refetch: refetchTenant } = useTenant()
  const [form, setForm] = useState<InvoiceForm>({
    invoice_prefix: 'INV-', invoice_start_number: 1, default_due_days: 14,
    default_notes: '', default_notes_enabled: false, payment_terms_days: 14, payment_terms_text: '',
    payment_terms_enabled: true, allow_partial_payments: false, pos_preview_enabled: true,
  })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    apiClient.get('/org/settings').then(({ data }) => {
      setForm({
        invoice_prefix: data.invoice_prefix || 'INV-', invoice_start_number: data.invoice_start_number ?? 1,
        default_due_days: data.default_due_days ?? 14, default_notes: data.default_notes || '',
        default_notes_enabled: data?.default_notes_enabled ?? false,
        payment_terms_days: data.payment_terms_days ?? 14, payment_terms_text: data.payment_terms_text || '',
        payment_terms_enabled: data?.payment_terms_enabled ?? true,
        allow_partial_payments: data.allow_partial_payments ?? false,
        pos_preview_enabled: data?.pos_preview_enabled ?? true,
      })
    })
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await apiClient.put('/org/settings', form)
      addToast('success', 'Invoice settings saved')
      await refetchTenant()
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
        <div className="flex items-center gap-3 mb-1">
          <label htmlFor="default-notes-toggle" className="text-sm font-medium text-text">Pre-fill notes on new invoices</label>
          <button id="default-notes-toggle" role="switch" aria-checked={form.default_notes_enabled}
            onClick={() => setForm((p) => ({ ...p, default_notes_enabled: !p.default_notes_enabled }))}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.default_notes_enabled ? 'bg-accent' : 'bg-border-strong'}`}>
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.default_notes_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <div className={!form.default_notes_enabled ? 'opacity-50 pointer-events-none' : ''}>
          <label htmlFor="default-notes" className="text-sm font-medium text-text">Default Invoice Notes</label>
          <textarea id="default-notes" rows={3} value={form.default_notes}
            onChange={(e) => setForm((p) => ({ ...p, default_notes: e.target.value }))}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
        </div>
      </div>
      <hr className="border-border" />
      <h3 className="text-base font-medium text-text">Payment Terms</h3>
      <div className="flex items-center gap-3 mb-1">
        <label htmlFor="payment-terms-toggle" className="text-sm font-medium text-text">Show payment terms on invoices</label>
        <button id="payment-terms-toggle" role="switch" aria-checked={form.payment_terms_enabled}
          onClick={() => setForm((p) => ({ ...p, payment_terms_enabled: !p.payment_terms_enabled }))}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.payment_terms_enabled ? 'bg-accent' : 'bg-border-strong'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.payment_terms_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      </div>
      <Input label="Payment Terms (days)" type="number" min={0} value={String(form.payment_terms_days)}
        onChange={(e) => setForm((p) => ({ ...p, payment_terms_days: parseInt(e.target.value) || 0 }))} />
      <div className={`flex flex-col gap-1 ${!form.payment_terms_enabled ? 'opacity-50 pointer-events-none' : ''}`}>
        <label htmlFor="payment-terms" className="text-sm font-medium text-text">Payment Terms Statement</label>
        <textarea id="payment-terms" rows={2} value={form.payment_terms_text}
          onChange={(e) => setForm((p) => ({ ...p, payment_terms_text: e.target.value }))}
          placeholder="Payment is due within 14 days of invoice date."
          className="rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
      </div>
      <div className="flex items-center gap-3">
        <label htmlFor="partial-toggle" className="text-sm font-medium text-text">Allow Partial Payments</label>
        <button id="partial-toggle" role="switch" aria-checked={form.allow_partial_payments}
          onClick={() => setForm((p) => ({ ...p, allow_partial_payments: !p.allow_partial_payments }))}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.allow_partial_payments ? 'bg-accent' : 'bg-border-strong'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.allow_partial_payments ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      </div>
      <hr className="border-border" />
      <h3 className="text-base font-medium text-text">POS Receipt</h3>
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-3">
          <label htmlFor="pos-preview-toggle" className="text-sm font-medium text-text">Show POS receipt preview</label>
          <button id="pos-preview-toggle" role="switch" aria-checked={form.pos_preview_enabled}
            onClick={() => setForm((p) => ({ ...p, pos_preview_enabled: !p.pos_preview_enabled }))}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.pos_preview_enabled ? 'bg-accent' : 'bg-border-strong'}`}>
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.pos_preview_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <p className="text-xs text-muted">When off, the POS receipt panel on the invoice screen is hidden and "Print POS Receipt" is removed from the PDF/Print menu.</p>
      </div>
      <Button onClick={save} loading={saving}>Save Invoice Settings</Button>
    </div>
  )
}

/* ── Rich Text T&C Editor ── */

function TermsTab() {
  const editorRef = useRef<HTMLDivElement>(null)
  const [saving, setSaving] = useState(false)
  const [termsEnabled, setTermsEnabled] = useState(true)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    apiClient.get('/org/settings').then(({ data }) => {
      setTermsEnabled(data?.terms_and_conditions_enabled ?? true)
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
      await apiClient.put('/org/settings', {
        terms_and_conditions: editorRef.current?.innerHTML || '',
        terms_and_conditions_enabled: termsEnabled,
      })
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
      <p className="text-sm text-muted">Custom terms and conditions displayed at the bottom of every invoice PDF.</p>

      <div className="flex items-center gap-3 mb-1">
        <label htmlFor="tc-toggle" className="text-sm font-medium text-text">Show terms &amp; conditions on invoices</label>
        <button id="tc-toggle" role="switch" aria-checked={termsEnabled}
          onClick={() => setTermsEnabled((prev) => !prev)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${termsEnabled ? 'bg-accent' : 'bg-border-strong'}`}>
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${termsEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      </div>

      <div className={!termsEnabled ? 'opacity-50 pointer-events-none' : ''}>
        <div className="flex flex-wrap gap-1 rounded-t-ctl border border-b-0 border-border bg-canvas p-2" role="toolbar" aria-label="Text formatting">
          <ToolbarBtn label="Bold" onClick={() => exec('bold')}><strong>B</strong></ToolbarBtn>
          <ToolbarBtn label="Heading" onClick={() => exec('formatBlock', 'h3')}>H</ToolbarBtn>
          <ToolbarBtn label="Paragraph" onClick={() => exec('formatBlock', 'p')}>¶</ToolbarBtn>
          <ToolbarBtn label="Bullet list" onClick={() => exec('insertUnorderedList')}>•</ToolbarBtn>
          <ToolbarBtn label="Insert link" onClick={insertLink}>🔗</ToolbarBtn>
        </div>

        <div ref={editorRef} contentEditable role="textbox" aria-multiline="true" aria-label="Terms and conditions editor"
          className="min-h-[200px] rounded-b-ctl border border-border p-4 text-text prose prose-sm max-w-none focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
      </div>

      <Button onClick={save} loading={saving}>Save Terms &amp; Conditions</Button>
    </div>
  )
}

function ToolbarBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className="rounded px-2.5 py-1 text-sm font-medium text-muted hover:bg-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
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
    return <p className="text-sm text-muted-2">Loading trade categories…</p>
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <p className="text-sm text-muted">
        Select the trade category that best describes your business. This controls which catalogue items and features are shown in the sidebar.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="trade-category" className="text-sm font-medium text-text">Business Type</label>
        <select
          id="trade-category"
          value={selectedSlug ?? ''}
          onChange={(e) => setSelectedSlug(e.target.value || null)}
          className="rounded-ctl border border-border px-3 py-2 text-text shadow-sm focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] bg-card"
        >
          <option value="">— Select a trade category —</option>
          {grouped.map((g) => (
            <optgroup key={g.family.id} label={g.family.display_name}>
              {g.items.map((cat) => (
                <option key={cat.id} value={cat.slug}>
                  {cat.display_name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {selectedSlug && selectedSlug !== currentSlug && (
        <p className="text-sm text-warn">
          Changing your business type will update which features and catalogue items are visible.
        </p>
      )}

      <Button onClick={save} loading={saving} disabled={selectedSlug === currentSlug}>
        Save Business Type
      </Button>
    </div>
  )
}

/* ── Portal Tab ── */

function PortalTab() {
  const [portalEnabled, setPortalEnabled] = useState(true)
  const [portalTokenTtlDays, setPortalTokenTtlDays] = useState(90)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  // Portal analytics state (Req 47.2, 47.3)
  interface AnalyticsDayItem {
    date: string
    view: number
    quote_accepted: number
    booking_created: number
    payment_initiated: number
  }
  const [analytics, setAnalytics] = useState<{
    days: AnalyticsDayItem[]
    totals: AnalyticsDayItem
  } | null>(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    apiClient.get('/org/settings', { signal: controller.signal }).then(({ data }) => {
      setPortalEnabled(data?.portal_enabled ?? true)
      setPortalTokenTtlDays(data?.portal_token_ttl_days ?? 90)
    }).catch(() => {
      // ignore abort errors
    })
    return () => controller.abort()
  }, [])

  // Fetch portal analytics (Req 47.2)
  useEffect(() => {
    const controller = new AbortController()
    setAnalyticsLoading(true)
    apiClient.get('/org/portal-analytics', { signal: controller.signal }).then(({ data }) => {
      setAnalytics({
        days: data?.days ?? [],
        totals: data?.totals ?? { date: 'total', view: 0, quote_accepted: 0, booking_created: 0, payment_initiated: 0 },
      })
    }).catch(() => {
      // ignore abort errors
    }).finally(() => {
      if (!controller.signal.aborted) setAnalyticsLoading(false)
    })
    return () => controller.abort()
  }, [])

  const save = async () => {
    if (portalTokenTtlDays < 1 || portalTokenTtlDays > 365) {
      addToast('error', 'Token TTL must be between 1 and 365 days')
      return
    }
    setSaving(true)
    try {
      await apiClient.put('/org/settings', { portal_enabled: portalEnabled, portal_token_ttl_days: portalTokenTtlDays })
      addToast('success', 'Portal settings saved')
    } catch {
      addToast('error', 'Failed to save portal settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div>
        <div className="flex items-center gap-3">
          <label htmlFor="portal-enabled-toggle" className="text-sm font-medium text-text">Customer Portal</label>
          <button id="portal-enabled-toggle" role="switch" aria-checked={portalEnabled}
            onClick={() => setPortalEnabled((prev) => !prev)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${portalEnabled ? 'bg-accent' : 'bg-border-strong'}`}>
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${portalEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
          <span className="text-sm text-muted">{portalEnabled ? 'Enabled' : 'Disabled'}</span>
        </div>
        <p className="text-xs text-muted-2 mt-1">
          {portalEnabled
            ? 'Customers with portal access enabled can view their invoices, quotes, and bookings via a secure link.'
            : 'The customer portal is disabled for your organisation. No customers will be able to access the portal.'}
        </p>
      </div>

      {!portalEnabled && (
        <div className="rounded-ctl bg-warn-soft border border-warn p-3">
          <p className="text-sm text-warn">
            Disabling the portal will prevent all customers from accessing their portal links. Existing portal links will stop working until the portal is re-enabled.
          </p>
        </div>
      )}

      <hr className="border-border" />

      <p className="text-sm text-muted">
        Configure how long customer portal access tokens remain valid. When a token expires, the customer will need a new link to access their portal.
      </p>
      <Input
        label="Portal Token TTL (days)"
        type="number"
        min={1}
        max={365}
        value={String(portalTokenTtlDays)}
        onChange={(e) => setPortalTokenTtlDays(parseInt(e.target.value) || 90)}
        helperText="How many days a portal token remains valid after generation (default: 90)"
      />
      <Button onClick={save} loading={saving}>Save Portal Settings</Button>

      {/* Portal Analytics — Req 47.2, 47.3 */}
      <hr className="border-border" />
      <div>
        <h3 className="text-sm font-medium text-text mb-3">Portal Usage (Last 30 Days)</h3>
        {analyticsLoading ? (
          <p className="text-sm text-muted-2">Loading analytics…</p>
        ) : analytics ? (
          <div className="space-y-4">
            {/* Summary cards */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-card border border-border bg-canvas p-3">
                <p className="text-xs text-muted-2">Portal Views</p>
                <p className="text-lg font-semibold text-text mono">{(analytics.totals?.view ?? 0).toLocaleString()}</p>
              </div>
              <div className="rounded-card border border-border bg-canvas p-3">
                <p className="text-xs text-muted-2">Quotes Accepted</p>
                <p className="text-lg font-semibold text-text mono">{(analytics.totals?.quote_accepted ?? 0).toLocaleString()}</p>
              </div>
              <div className="rounded-card border border-border bg-canvas p-3">
                <p className="text-xs text-muted-2">Bookings Created</p>
                <p className="text-lg font-semibold text-text mono">{(analytics.totals?.booking_created ?? 0).toLocaleString()}</p>
              </div>
              <div className="rounded-card border border-border bg-canvas p-3">
                <p className="text-xs text-muted-2">Payments Initiated</p>
                <p className="text-lg font-semibold text-text mono">{(analytics.totals?.payment_initiated ?? 0).toLocaleString()}</p>
              </div>
            </div>

            {/* Daily breakdown table */}
            {(analytics.days ?? []).length > 0 && (
              <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
                <table className="min-w-full text-sm">
                  <thead className="bg-canvas">
                    <tr>
                      <th className="mono px-3 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Date</th>
                      <th className="mono px-3 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Views</th>
                      <th className="mono px-3 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Quotes</th>
                      <th className="mono px-3 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Bookings</th>
                      <th className="mono px-3 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Payments</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(analytics.days ?? []).filter(d =>
                      (d?.view ?? 0) > 0 || (d?.quote_accepted ?? 0) > 0 || (d?.booking_created ?? 0) > 0 || (d?.payment_initiated ?? 0) > 0
                    ).reverse().map((day) => (
                      <tr key={day?.date ?? ''} className="border-b border-border last:border-b-0 hover:bg-canvas">
                        <td className="mono px-3 py-2 text-muted">{day?.date ?? ''}</td>
                        <td className="mono px-3 py-2 text-right text-muted">{day?.view ?? 0}</td>
                        <td className="mono px-3 py-2 text-right text-muted">{day?.quote_accepted ?? 0}</td>
                        <td className="mono px-3 py-2 text-right text-muted">{day?.booking_created ?? 0}</td>
                        <td className="mono px-3 py-2 text-right text-muted">{day?.payment_initiated ?? 0}</td>
                      </tr>
                    ))}
                    {(analytics.days ?? []).filter(d =>
                      (d?.view ?? 0) > 0 || (d?.quote_accepted ?? 0) > 0 || (d?.booking_created ?? 0) > 0 || (d?.payment_initiated ?? 0) > 0
                    ).length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-3 py-4 text-center text-muted-2">No portal activity in the last 30 days</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-2">Unable to load analytics</p>
        )}
      </div>
    </div>
  )
}

/* ── Inventory Tab ── */

function InventoryTab() {
  const [autoExpense, setAutoExpense] = useState(true)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    const controller = new AbortController()
    apiClient.get('/org/settings', { signal: controller.signal }).then(({ data }) => {
      setAutoExpense(data?.auto_expense_on_stock_purchase ?? true)
    }).catch(() => {
      // ignore abort errors
    })
    return () => controller.abort()
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await apiClient.put('/org/settings', { auto_expense_on_stock_purchase: autoExpense })
      addToast('success', 'Inventory settings saved')
    } catch {
      addToast('error', 'Failed to save inventory settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div>
        <div className="flex items-center gap-3">
          <label htmlFor="auto-expense-toggle" className="text-sm font-medium text-text">Automatically create expense when adding stock</label>
          <button id="auto-expense-toggle" role="switch" aria-checked={autoExpense}
            onClick={() => setAutoExpense((prev) => !prev)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${autoExpense ? 'bg-accent' : 'bg-border-strong'}`}>
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${autoExpense ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
          <span className="text-sm text-muted">{autoExpense ? 'Enabled' : 'Disabled'}</span>
        </div>
        <p className="text-xs text-muted-2 mt-1">
          When enabled, adding stock items or positive adjustments with a purchase price will automatically create an expense entry.
        </p>
      </div>

      <Button onClick={save} loading={saving}>Save Inventory Settings</Button>
    </div>
  )
}

/* ── Employee Portal Tab (R3, R4) ── */

interface SlugAvailabilityResponse {
  result: 'available' | 'unavailable' | 'invalid'
  reason: string | null
}

interface SlugUpdateResponse {
  slug: string
}

interface EmployeePortalToggleResponse {
  enabled: boolean
}

/** Debounce before firing the live availability check (R3.1 — ≥300ms). */
const SLUG_DEBOUNCE_MS = 350
/**
 * Hard ceiling on the availability round-trip (R3.2/R3.8). If the endpoint
 * does not answer within this window the UI shows "could not complete" and
 * never reports the candidate as available.
 */
const SLUG_AVAILABILITY_TIMEOUT_MS = 1000

type AvailabilityState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'available' }
  | { status: 'unavailable'; reason: string }
  | { status: 'invalid'; reason: string }
  | { status: 'error' } // "could not complete" — timeout or endpoint error

/** Safely pull status/message/code off an unknown (Axios) error without `as any`. */
function readApiError(err: unknown): { status?: number; message?: string; code?: string } {
  const e = err as { response?: { status?: number; data?: { message?: string; code?: string } } }
  return {
    status: e?.response?.status,
    message: e?.response?.data?.message,
    code: e?.response?.data?.code,
  }
}

export function EmployeePortalTab() {
  const [slug, setSlug] = useState('')
  const [savedSlug, setSavedSlug] = useState<string | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [availability, setAvailability] = useState<AvailabilityState>({ status: 'idle' })
  const [loaded, setLoaded] = useState(false)
  const [savingSlug, setSavingSlug] = useState(false)
  const [togglingPortal, setTogglingPortal] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  // Load current slug + enablement flag (R4.1 — defaults to disabled).
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get<{ slug?: string | null; employee_portal_enabled?: boolean }>('/org/settings', {
        signal: controller.signal,
      })
      .then(({ data }) => {
        const current = data?.slug ?? ''
        setSavedSlug(data?.slug ?? null)
        setSlug(current)
        setEnabled(data?.employee_portal_enabled ?? false)
        setLoaded(true)
      })
      .catch(() => {
        // Ignore abort; surface nothing on initial load failure beyond defaults.
      })
    return () => controller.abort()
  }, [])

  // Live availability: debounce ≥300ms after typing stops, then call the
  // endpoint with a 1s ceiling (R3.1, R3.2, R3.7, R3.8). On timeout/error we
  // show "could not complete" and NEVER report the candidate as available.
  useEffect(() => {
    const candidate = slug.trim()
    if (!candidate) {
      setAvailability({ status: 'idle' })
      return
    }

    const controller = new AbortController()
    let timeoutId: number | undefined
    let timedOut = false
    let active = true

    const debounceId = window.setTimeout(() => {
      setAvailability({ status: 'checking' })
      timeoutId = window.setTimeout(() => {
        timedOut = true
        controller.abort()
      }, SLUG_AVAILABILITY_TIMEOUT_MS)

      apiClient
        .get<SlugAvailabilityResponse>('/api/v2/organisations/slug-availability', {
          params: { slug: candidate },
          signal: controller.signal,
        })
        .then((res) => {
          if (!active) return
          const result = res.data?.result
          const reason = res.data?.reason ?? ''
          if (result === 'available') {
            setAvailability({ status: 'available' })
          } else if (result === 'unavailable') {
            setAvailability({ status: 'unavailable', reason: reason || 'This slug is already taken.' })
          } else if (result === 'invalid') {
            setAvailability({ status: 'invalid', reason: reason || 'This slug is not a valid format.' })
          } else {
            // Unexpected payload — treat as "could not complete", never available.
            setAvailability({ status: 'error' })
          }
        })
        .catch(() => {
          // Surface "could not complete" only for a genuine timeout/error —
          // never for a cancellation caused by re-typing or unmount (R3.8).
          if (!active && !timedOut) return
          setAvailability({ status: 'error' })
        })
        .finally(() => {
          if (timeoutId) window.clearTimeout(timeoutId)
        })
    }, SLUG_DEBOUNCE_MS)

    return () => {
      active = false
      window.clearTimeout(debounceId)
      if (timeoutId) window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [slug])

  const saveSlug = async () => {
    const candidate = slug.trim()
    if (!candidate) {
      addToast('error', 'Enter a slug before saving')
      return
    }
    setSavingSlug(true)
    try {
      const res = await apiClient.put<SlugUpdateResponse>('/api/v2/organisations/slug', {
        slug: candidate,
      })
      const stored = res.data?.slug ?? candidate
      setSavedSlug(stored)
      setSlug(stored)
      setAvailability({ status: 'available' })
      addToast('success', 'Organisation slug saved')
    } catch (err) {
      const { status, message } = readApiError(err)
      if (status === 409) {
        // Save-time race — slug taken since the live check (R3.9). Retain the
        // entered value and reflect the new unavailable state.
        const reason = message || 'This slug is no longer available.'
        setAvailability({ status: 'unavailable', reason })
        addToast('error', reason)
      } else if (status === 422) {
        const reason = message || 'This slug is invalid or reserved.'
        setAvailability({ status: 'invalid', reason })
        addToast('error', reason)
      } else {
        addToast('error', message || 'Failed to save slug')
      }
    } finally {
      setSavingSlug(false)
    }
  }

  const togglePortal = async () => {
    const next = !enabled
    setTogglingPortal(true)
    try {
      const res = await apiClient.put<EmployeePortalToggleResponse>(
        '/api/v2/organisations/employee-portal',
        { enabled: next },
      )
      setEnabled(res.data?.enabled ?? next)
      addToast('success', next ? 'Employee Portal enabled' : 'Employee Portal disabled')
    } catch (err) {
      const { message } = readApiError(err)
      // 422 slug_required when enabling without a slug (R4.4). The server
      // leaves the flag disabled, so `enabled` stays at its previous value.
      addToast('error', message || 'Failed to update the Employee Portal')
    } finally {
      setTogglingPortal(false)
    }
  }

  const renderAvailability = () => {
    switch (availability.status) {
      case 'checking':
        return <p className="text-sm text-muted-2">Checking availability…</p>
      case 'available':
        return <p className="text-sm text-ok">✓ Available</p>
      case 'unavailable':
        return <p className="text-sm text-danger">✗ {availability.reason}</p>
      case 'invalid':
        return <p className="text-sm text-danger">✗ {availability.reason}</p>
      case 'error':
        return <p className="text-sm text-warn">Could not complete the availability check. Try again.</p>
      default:
        return null
    }
  }

  const slugDirty = slug.trim() !== (savedSlug ?? '')

  return (
    <div className="space-y-6 max-w-2xl">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <p className="text-sm text-muted">
        The Employee Portal gives your staff an organisation-branded login at{' '}
        <span className="mono">/e/{slug.trim() || 'your-slug'}</span> where they can view their
        profile and roster. Choose a unique slug, then enable the portal.
      </p>

      <div className="flex flex-col gap-1">
        <Input
          label="Organisation Slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="e.g. acme-motors"
          helperText="3–63 characters: lowercase letters, digits, and single internal hyphens."
          autoComplete="off"
          spellCheck={false}
        />
        <div aria-live="polite" className="min-h-[1.25rem]">
          {renderAvailability()}
        </div>
      </div>

      <Button
        onClick={saveSlug}
        loading={savingSlug}
        disabled={!slugDirty || !slug.trim() || availability.status === 'checking'}
      >
        Save Slug
      </Button>

      <hr className="border-border" />

      <div>
        <div className="flex items-center gap-3">
          <label htmlFor="employee-portal-toggle" className="text-sm font-medium text-text">
            Employee Portal
          </label>
          <button
            id="employee-portal-toggle"
            role="switch"
            aria-checked={enabled}
            disabled={togglingPortal || !loaded}
            onClick={togglePortal}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50 ${enabled ? 'bg-accent' : 'bg-border-strong'}`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enabled ? 'translate-x-6' : 'translate-x-1'}`}
            />
          </button>
          <span className="text-sm text-muted">{enabled ? 'Enabled' : 'Disabled'}</span>
        </div>
        <p className="text-xs text-muted-2 mt-1">
          {enabled
            ? 'Your staff can log in at your organisation-branded portal URL.'
            : 'Set a valid slug above, then enable the portal so your staff can log in.'}
        </p>
      </div>
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
    { id: 'inventory', label: 'Inventory', content: <InventoryTab /> },
    { id: 'terms', label: 'Terms & Conditions', content: <TermsTab /> },
    { id: 'portal', label: 'Portal', content: <PortalTab /> },
    { id: 'employee-portal', label: 'Employee Portal', content: <EmployeePortalTab /> },
  ]

  return (
    <div>
      <h1 className="text-xl font-semibold text-text mb-6">Organisation Settings</h1>
      <Tabs tabs={tabs} defaultTab="branding" />
    </div>
  )
}
