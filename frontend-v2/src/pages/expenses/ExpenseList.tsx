import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal } from '@/components/ui'
import { useBranch } from '@/contexts/BranchContext'

/* ── Types ── */
interface Expense {
  id: string; job_id: string | null; project_id: string | null; invoice_id: string | null
  customer_id: string | null; date: string; description: string; amount: string
  tax_amount: string; category: string | null; reference_number: string | null
  notes: string | null; receipt_file_key: string | null; is_pass_through: boolean
  is_billable: boolean; is_invoiced: boolean; tax_inclusive: boolean
  expense_type: string; created_at: string; branch_id?: string | null
}
interface Customer { id: string; display_name: string | null; first_name: string; last_name: string }
interface MileageRate { id?: string; start_date: string | null; rate_per_unit: string; currency: string }
interface MileagePrefs { default_unit: string; default_account: string | null; rates: MileageRate[] }

const CATEGORIES = [
  { value: '', label: 'Select Category' },
  { value: 'materials', label: 'Materials' }, { value: 'travel', label: 'Travel' },
  { value: 'subcontractor', label: 'Subcontractor' }, { value: 'equipment', label: 'Equipment' },
  { value: 'fuel', label: 'Fuel' }, { value: 'accommodation', label: 'Accommodation' },
  { value: 'meals', label: 'Meals' }, { value: 'office', label: 'Office' },
  { value: 'other', label: 'Other' },
]

const TAX_OPTIONS = [
  { value: '', label: 'Select a Tax' },
  { value: '15', label: 'GST (15%)' },
  { value: '0', label: 'GST Exempt (0%)' },
]

function formatNZD(v: string | number) {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(Number(v))
}

function catLabel(cat: string | null) {
  return CATEGORIES.find(c => c.value === cat)?.label || cat || '—'
}

type Tab = 'expense' | 'mileage' | 'bulk'

/* ── Shared field row ── */
function FieldRow({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4 border-b border-border py-3 last:border-0">
      <label className={`w-36 shrink-0 pt-2 text-sm ${required ? 'font-medium text-danger' : 'text-muted'}`}>
        {label}{required && '*'}
      </label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

/* ── Receipt upload zone ── */
function ReceiptZone({ fileKey, onUpload, onRemove }: { fileKey: string; onUpload: (f: File) => void; onRemove: () => void }) {
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [localPreview, setLocalPreview] = useState<string | null>(null)
  const [localFileName, setLocalFileName] = useState('')
  const [previewOpen, setPreviewOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const isImage = (name: string) => /\.(jpe?g|png|webp|gif)$/i.test(name)
  const isPdf = (name: string) => /\.pdf$/i.test(name)

  const handleFile = async (file: File) => {
    setUploading(true)
    setLocalFileName(file.name)
    // Create local blob URL for preview (works for both images and PDFs)
    const url = URL.createObjectURL(file)
    setLocalPreview(url)
    try { onUpload(file) } finally { setUploading(false) }
  }

  const handleRemove = () => {
    if (localPreview) URL.revokeObjectURL(localPreview)
    setLocalPreview(null)
    setLocalFileName('')
    onRemove()
  }

  return (
    <>
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
        className={`rounded-card border-2 border-dashed p-4 text-center transition-colors ${dragging ? 'border-accent bg-accent-soft' : fileKey ? 'border-ok bg-ok-soft' : 'border-border bg-canvas'}`}
      >
        {fileKey ? (
          <div className="space-y-2">
            {/* Thumbnail preview */}
            {localPreview && isImage(localFileName) ? (
              <img src={localPreview} alt="Receipt" className="mx-auto h-24 w-auto rounded-ctl border border-border object-cover shadow-card" />
            ) : isPdf(localFileName || fileKey) ? (
              <div className="mx-auto flex h-24 w-20 flex-col items-center justify-center rounded-ctl border border-danger-soft bg-danger-soft">
                <svg className="h-8 w-8 text-danger" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <span className="mt-1 text-[10px] font-semibold text-danger">PDF</span>
              </div>
            ) : (
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-ctl border border-border bg-canvas">
                <svg className="h-7 w-7 text-muted-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
                </svg>
              </div>
            )}
            <p className="mx-auto max-w-[200px] truncate text-xs text-muted">{localFileName || 'Receipt'}</p>
            <div className="flex items-center justify-center gap-3">
              <button type="button" onClick={() => setPreviewOpen(true)}
                className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:text-accent-press">
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Preview
              </button>
              <button type="button" onClick={handleRemove}
                className="text-xs font-medium text-danger hover:brightness-90">Remove</button>
            </div>
          </div>
        ) : (
          <>
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-ctl bg-accent-soft">
              <svg className="h-6 w-6 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-muted">Drag or Drop your Receipts</p>
            <p className="mb-3 text-xs text-muted-2">Maximum file size allowed is 10MB</p>
            <button type="button" onClick={() => inputRef.current?.click()}
              className="inline-flex items-center gap-2 rounded-ctl border border-border bg-card px-4 py-2 text-sm text-text hover:bg-canvas">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              {uploading ? 'Uploading…' : 'Upload your Files'}
            </button>
            <input ref={inputRef} type="file" accept="image/*,.pdf" className="hidden"
              onChange={e => { if (e.target.files?.[0]) handleFile(e.target.files[0]) }} />
          </>
        )}
      </div>

      {/* Preview Modal */}
      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title={localFileName || 'Receipt Preview'}>
        <div className="flex min-h-[300px] items-center justify-center">
          {localPreview && isImage(localFileName) ? (
            <img src={localPreview} alt="Receipt preview" className="max-h-[70vh] max-w-full rounded-card shadow-pop" />
          ) : localPreview && isPdf(localFileName) ? (
            <div className="h-[70vh] w-full">
              <iframe src={localPreview} className="h-full w-full rounded-card border border-border" title="PDF Preview" />
            </div>
          ) : localPreview ? (
            <div className="space-y-3 text-center">
              <p className="text-sm text-muted">Preview not available for this file type</p>
              <a href={localPreview} download={localFileName} className="inline-flex items-center gap-2 rounded-ctl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-press">
                Download file
              </a>
            </div>
          ) : (
            <p className="text-sm text-muted-2">No file to preview</p>
          )}
        </div>
      </Modal>
    </>
  )
}

/* ── Customer search ── */
function CustomerSearch({ onChange }: { value: string; onChange: (id: string, name: string) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Customer[]>([])
  const [open, setOpen] = useState(false)
  const [selectedName, setSelectedName] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setResults([]); return }
    try {
      const res = await apiClient.get('/customers', { params: { q } })
      setResults((res.data.customers || res.data || []).slice(0, 8))
    } catch { setResults([]) }
  }, [])

  useEffect(() => {
    const t = setTimeout(() => search(query), 300)
    return () => clearTimeout(t)
  }, [query, search])

  const select = (c: Customer) => {
    const name = c.display_name || `${c.first_name} ${c.last_name}`
    setSelectedName(name)
    setQuery(name)
    setOpen(false)
    onChange(c.id, name)
  }

  const clear = () => { setSelectedName(''); setQuery(''); onChange('', '') }

  return (
    <div ref={ref} className="relative flex gap-2">
      {selectedName ? (
        <div className="flex flex-1 items-center gap-2 rounded-ctl border border-border bg-canvas px-3 py-2 text-sm">
          <span className="flex-1">{selectedName}</span>
          <button type="button" onClick={clear} className="text-muted-2 hover:text-muted">✕</button>
        </div>
      ) : (
        <input type="text" value={query} onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)} placeholder="Select or add a customer"
          className="flex-1 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
      )}
      <button type="button" className="rounded-ctl bg-accent px-3 py-2 text-white hover:bg-accent-press">
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </button>
      {open && results.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-ctl border border-border bg-card shadow-pop">
          {results.map(c => (
            <button key={c.id} type="button" onClick={() => select(c)}
              className="w-full px-3 py-2 text-left text-sm hover:bg-canvas">
              {c.display_name || `${c.first_name} ${c.last_name}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
// CustomerSearch is ported verbatim but its only usages in RecordExpenseTab /
// RecordMileageTab are commented out ("disabled until feature is complete").
// `void` keeps the component referenced so v2's noUnusedLocals build passes —
// mirroring this file's own `void today` idiom — without dropping the component.
void CustomerSearch

/* ── Record Expense Tab ── */
function RecordExpenseTab({ onSaved }: { onSaved: () => void }) {
  const { selectedBranchId } = useBranch()
  const today = new Date().toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' })
  void today // used for display reference
  const [form, setForm] = useState({
    date: new Date().toISOString().split('T')[0],
    category: '', amount: '', tax_rate: '', reference: '', notes: '',
    customer_id: '', tax_inclusive: false, receipt_file_key: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const handleReceiptUpload = async (file: File) => {
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await apiClient.post('/api/v2/uploads/receipts', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setForm(p => ({ ...p, receipt_file_key: res.data.file_key || '' }))
    } catch { /* silent */ }
  }

  const handleSave = async () => {
    if (!form.category) { setError('Category is required.'); return }
    if (!form.amount || Number(form.amount) <= 0) { setError('Amount is required.'); return }
    setSaving(true); setError('')
    try {
      const taxAmt = form.tax_rate ? Number(form.amount) * (Number(form.tax_rate) / 100) : 0
      await apiClient.post('/api/v2/expenses', {
        date: form.date,
        description: form.category,
        amount: Number(form.amount),
        tax_amount: taxAmt,
        category: form.category,
        reference_number: form.reference || null,
        notes: form.notes || null,
        customer_id: form.customer_id || null,
        tax_inclusive: form.tax_inclusive,
        receipt_file_key: form.receipt_file_key || null,
        expense_type: 'expense',
        branch_id: selectedBranchId || undefined,
      })
      setSuccess(true)
      setForm({ date: new Date().toISOString().split('T')[0], category: '', amount: '', tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false, receipt_file_key: '' })
      setTimeout(() => setSuccess(false), 3000)
      onSaved()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save expense.')
    } finally { setSaving(false) }
  }

  return (
    <div className="flex gap-6">
      <div className="flex-1">
        <FieldRow label="Date" required>
          <input type="date" value={form.date} onChange={e => setForm(p => ({ ...p, date: e.target.value }))}
            className="w-48 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
        </FieldRow>
        <FieldRow label="Category Name" required>
          <div className="space-y-1">
            <select value={form.category} onChange={e => setForm(p => ({ ...p, category: e.target.value }))}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
              {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            <button type="button" className="flex items-center gap-1 text-xs text-accent hover:underline">
              <span>≡</span> Itemize
            </button>
          </div>
        </FieldRow>
        <FieldRow label="Amount" required>
          <div className="flex items-center gap-2">
            <span className="rounded-l-ctl border border-r-0 border-border bg-canvas px-3 py-2 text-sm text-muted">NZD</span>
            <input type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
              className="flex-1 rounded-r-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" placeholder="0.00" />
          </div>
        </FieldRow>
        <FieldRow label="Amount Is">
          <div className="flex gap-4 pt-1">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="radio" name="tax_mode" checked={form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: true }))} className="text-accent" />
              Tax Inclusive
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="radio" name="tax_mode" checked={!form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: false }))} className="text-accent" />
              Tax Exclusive
            </label>
          </div>
        </FieldRow>
        <FieldRow label="Tax">
          <select value={form.tax_rate} onChange={e => setForm(p => ({ ...p, tax_rate: e.target.value }))}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
            {TAX_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </FieldRow>
        <FieldRow label="Reference#">
          <input type="text" value={form.reference} onChange={e => setForm(p => ({ ...p, reference: e.target.value }))}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
        </FieldRow>
        <FieldRow label="Notes">
          <textarea value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} rows={3}
            placeholder="Max. 500 characters"
            className="w-full resize-none rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
        </FieldRow>
        {/* Customer Name — disabled until feature is complete */}
        {/* <FieldRow label="Customer Name">
          <CustomerSearch value={form.customer_id} onChange={(id) => setForm(p => ({ ...p, customer_id: id }))} />
        </FieldRow> */}
        {error && <p className="mt-2 text-sm text-danger">{error}</p>}
        {success && <p className="mt-2 text-sm text-ok">✓ Expense saved successfully.</p>}
        <div className="mt-4 flex gap-2">
          <Button onClick={handleSave} loading={saving}>Save Expense</Button>
          <Button variant="ghost" onClick={() => setForm({ date: new Date().toISOString().split('T')[0], category: '', amount: '', tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false, receipt_file_key: '' })}>
            Cancel
          </Button>
        </div>
      </div>
      <div className="w-64 shrink-0">
        <ReceiptZone fileKey={form.receipt_file_key} onUpload={handleReceiptUpload} onRemove={() => setForm(p => ({ ...p, receipt_file_key: '' }))} />
      </div>
    </div>
  )
}

/* ── Record Mileage Tab ── */
function RecordMileageTab({ onSaved }: { onSaved: () => void }) {
  const { selectedBranchId } = useBranch()
  const [form, setForm] = useState({
    date: new Date().toISOString().split('T')[0],
    employee: '', calc_method: 'distance', distance: '', amount: '',
    tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false,
  })
  const [prefs, setPrefs] = useState<MileagePrefs>({ default_unit: 'km', default_account: null, rates: [] })
  const [showPrefs, setShowPrefs] = useState(false)
  const [prefsForm, setPrefsForm] = useState<MileagePrefs>({ default_unit: 'km', default_account: null, rates: [] })
  const [saving, setSaving] = useState(false)
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    apiClient.get('/api/v2/expenses/mileage-preferences').then(r => {
      setPrefs(r.data)
      setPrefsForm(r.data)
    }).catch(() => {})
  }, [])

  // Auto-calculate amount from distance + rate
  useEffect(() => {
    if (form.calc_method === 'distance' && form.distance && prefs.rates.length > 0) {
      const rate = prefs.rates[prefs.rates.length - 1]
      const amt = Number(form.distance) * Number(rate.rate_per_unit)
      setForm(p => ({ ...p, amount: amt.toFixed(2) }))
    }
  }, [form.distance, form.calc_method, prefs.rates])

  const handleSave = async () => {
    if (!form.distance && form.calc_method === 'distance') { setError('Distance is required.'); return }
    if (!form.amount || Number(form.amount) <= 0) { setError('Amount is required.'); return }
    setSaving(true); setError('')
    try {
      const taxAmt = form.tax_rate ? Number(form.amount) * (Number(form.tax_rate) / 100) : 0
      await apiClient.post('/api/v2/expenses', {
        date: form.date,
        description: `Mileage - ${form.distance}${prefs.default_unit}`,
        amount: Number(form.amount),
        tax_amount: taxAmt,
        category: 'travel',
        reference_number: form.reference || null,
        notes: form.notes || null,
        customer_id: form.customer_id || null,
        tax_inclusive: form.tax_inclusive,
        expense_type: 'mileage',
        branch_id: selectedBranchId || undefined,
      })
      setSuccess(true)
      setForm({ date: new Date().toISOString().split('T')[0], employee: '', calc_method: 'distance', distance: '', amount: '', tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false })
      setTimeout(() => setSuccess(false), 3000)
      onSaved()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save mileage expense.')
    } finally { setSaving(false) }
  }

  const handleSavePrefs = async () => {
    setSavingPrefs(true)
    try {
      const res = await apiClient.put('/api/v2/expenses/mileage-preferences', {
        default_unit: prefsForm.default_unit,
        default_account: prefsForm.default_account,
        rates: prefsForm.rates.map(r => ({ start_date: r.start_date || null, rate_per_unit: Number(r.rate_per_unit), currency: r.currency || 'NZD' })),
      })
      setPrefs(res.data)
      setShowPrefs(false)
    } catch { /* silent */ }
    finally { setSavingPrefs(false) }
  }

  const addRate = () => setPrefsForm(p => ({ ...p, rates: [...p.rates, { start_date: null, rate_per_unit: '', currency: 'NZD' }] }))
  const removeRate = (i: number) => setPrefsForm(p => ({ ...p, rates: p.rates.filter((_, idx) => idx !== i) }))

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button type="button" onClick={() => { setPrefsForm(prefs); setShowPrefs(true) }}
          className="text-sm text-accent hover:underline">Set mileage preferences</button>
      </div>
      <div className="flex gap-6">
        <div className="flex-1">
          <FieldRow label="Date" required>
            <input type="date" value={form.date} onChange={e => setForm(p => ({ ...p, date: e.target.value }))}
              className="w-48 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
          </FieldRow>
          <FieldRow label="Employee">
            <input type="text" value={form.employee} onChange={e => setForm(p => ({ ...p, employee: e.target.value }))}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
          </FieldRow>
          <FieldRow label="Calculate mileage using" required>
            <div className="flex gap-4 pt-1">
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="calc" checked={form.calc_method === 'distance'} onChange={() => setForm(p => ({ ...p, calc_method: 'distance' }))} className="text-accent" />
                Distance travelled
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="calc" checked={form.calc_method === 'odometer'} onChange={() => setForm(p => ({ ...p, calc_method: 'odometer' }))} className="text-accent" />
                Odometer reading
              </label>
            </div>
          </FieldRow>
          <FieldRow label="Distance" required>
            <div className="flex items-center gap-2">
              <input type="number" min="0" step="0.1" value={form.distance} onChange={e => setForm(p => ({ ...p, distance: e.target.value }))}
                className="flex-1 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
              <span className="text-sm text-muted">{prefs.default_unit === 'km' ? 'Kilometer(s)' : 'Mile(s)'}</span>
            </div>
          </FieldRow>
          <FieldRow label="Amount" required>
            <div className="flex items-center gap-2">
              <span className="rounded-l-ctl border border-r-0 border-border bg-canvas px-3 py-2 text-sm text-muted">NZD</span>
              <input type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
                className="flex-1 rounded-r-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" placeholder="0.00" />
            </div>
          </FieldRow>
          <FieldRow label="Amount Is">
            <div className="flex gap-4 pt-1">
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="tax_mode_m" checked={form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: true }))} className="text-accent" />
                Tax Inclusive
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="tax_mode_m" checked={!form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: false }))} className="text-accent" />
                Tax Exclusive
              </label>
            </div>
          </FieldRow>
          <FieldRow label="Tax">
            <select value={form.tax_rate} onChange={e => setForm(p => ({ ...p, tax_rate: e.target.value }))}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
              {TAX_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </FieldRow>
          <FieldRow label="Reference#">
            <input type="text" value={form.reference} onChange={e => setForm(p => ({ ...p, reference: e.target.value }))}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
          </FieldRow>
          <FieldRow label="Notes">
            <textarea value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} rows={3}
              placeholder="Max. 500 characters"
              className="w-full resize-none rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
          </FieldRow>
          {/* Customer Name — disabled until feature is complete */}
          {/* <FieldRow label="Customer Name">
            <CustomerSearch value={form.customer_id} onChange={(id) => setForm(p => ({ ...p, customer_id: id }))} />
          </FieldRow> */}
          {error && <p className="mt-2 text-sm text-danger">{error}</p>}
          {success && <p className="mt-2 text-sm text-ok">✓ Mileage expense saved.</p>}
          <div className="mt-4 flex gap-2">
            <Button onClick={handleSave} loading={saving}>Save Mileage</Button>
            <Button variant="ghost" onClick={() => setForm({ date: new Date().toISOString().split('T')[0], employee: '', calc_method: 'distance', distance: '', amount: '', tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false })}>Cancel</Button>
          </div>
        </div>
      </div>

      {/* Mileage Preferences Modal */}
      <Modal open={showPrefs} onClose={() => setShowPrefs(false)} title="Set your mileage preferences">
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <label className="w-40 text-sm text-text">Default Mileage Account</label>
            <select value={prefsForm.default_account || ''} onChange={e => setPrefsForm(p => ({ ...p, default_account: e.target.value || null }))}
              className="flex-1 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
              <option value="">Fuel/Mileage Expenses</option>
              <option value="travel">Travel</option>
            </select>
          </div>
          <div className="flex items-center gap-4">
            <label className="w-40 text-sm text-text">Default Unit</label>
            <div className="flex gap-4">
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="unit" checked={prefsForm.default_unit === 'km'} onChange={() => setPrefsForm(p => ({ ...p, default_unit: 'km' }))} className="text-accent" />
                Km
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="unit" checked={prefsForm.default_unit === 'mile'} onChange={() => setPrefsForm(p => ({ ...p, default_unit: 'mile' }))} className="text-accent" />
                Mile
              </label>
            </div>
          </div>
          <div>
            <p className="mb-1 text-sm font-semibold text-text">MILEAGE RATES</p>
            <p className="mb-3 text-xs text-muted">Any mileage expense recorded on or after the start date will have the corresponding mileage rate.</p>
            <div className="mb-2 grid grid-cols-2 gap-2">
              <div className="text-xs font-medium uppercase text-muted">Start Date</div>
              <div className="text-xs font-medium uppercase text-muted">Mileage Rate</div>
            </div>
            {prefsForm.rates.map((r, i) => (
              <div key={i} className="mb-2 grid grid-cols-2 items-center gap-2">
                <input type="date" value={r.start_date || ''} onChange={e => setPrefsForm(p => ({ ...p, rates: p.rates.map((rr, ii) => ii === i ? { ...rr, start_date: e.target.value || null } : rr) }))}
                  className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted">NZD</span>
                  <input type="number" min="0" step="0.0001" value={r.rate_per_unit} onChange={e => setPrefsForm(p => ({ ...p, rates: p.rates.map((rr, ii) => ii === i ? { ...rr, rate_per_unit: e.target.value } : rr) }))}
                    className="flex-1 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" placeholder="0.00" />
                  <button type="button" onClick={() => removeRate(i)} className="text-xs text-danger hover:brightness-90">✕</button>
                </div>
              </div>
            ))}
            <button type="button" onClick={addRate} className="flex items-center gap-1 text-sm text-accent hover:underline">
              <span>+</span> Add Mileage Rate
            </button>
          </div>
          <div className="flex gap-2 pt-2">
            <Button onClick={handleSavePrefs} loading={savingPrefs}>Save</Button>
            <Button variant="ghost" onClick={() => setShowPrefs(false)}>Cancel</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

/* ── Bulk Add Expenses Tab ── */
interface BulkRow {
  date: string; category: string; amount: string; tax_rate: string
  customer_id: string; customer_name: string; project_id: string; is_billable: boolean; tax_inclusive: boolean
}

function emptyRow(): BulkRow {
  return { date: '', category: '', amount: '', tax_rate: '', customer_id: '', customer_name: '', project_id: '', is_billable: false, tax_inclusive: false }
}

function BulkAddTab({ onSaved }: { onSaved: () => void }) {
  const [rows, setRows] = useState<BulkRow[]>(() => Array.from({ length: 10 }, emptyRow))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const updateRow = (i: number, patch: Partial<BulkRow>) => {
    setRows(prev => prev.map((r, idx) => idx === i ? { ...r, ...patch } : r))
  }

  const addRows = () => setRows(prev => [...prev, ...Array.from({ length: 5 }, emptyRow)])

  const removeRow = (i: number) => setRows(prev => prev.filter((_, idx) => idx !== i))

  const handleSave = async () => {
    const valid = rows.filter(r => r.date && r.category && r.amount && Number(r.amount) > 0)
    if (valid.length === 0) { setError('Add at least one complete row.'); return }
    setSaving(true); setError('')
    try {
      await apiClient.post('/api/v2/expenses/bulk', {
        expenses: valid.map(r => ({
          date: r.date,
          description: r.category,
          amount: Number(r.amount),
          tax_amount: r.tax_rate ? Number(r.amount) * (Number(r.tax_rate) / 100) : 0,
          category: r.category,
          customer_id: r.customer_id || null,
          project_id: r.project_id || null,
          is_billable: r.is_billable,
          tax_inclusive: r.tax_inclusive,
          expense_type: 'expense',
        })),
      })
      setSuccess(true)
      setRows(Array.from({ length: 10 }, emptyRow))
      setTimeout(() => setSuccess(false), 3000)
      onSaved()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save expenses.')
    } finally { setSaving(false) }
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="w-8 px-2 py-2">
                <input type="checkbox" className="rounded border-border" />
              </th>
              <th className="w-32 px-2 py-2 text-left text-xs font-semibold uppercase text-danger">Date *</th>
              <th className="w-40 px-2 py-2 text-left text-xs font-semibold uppercase text-danger">Category Name *</th>
              <th className="w-36 px-2 py-2 text-left text-xs font-semibold uppercase text-danger">Amount *</th>
              <th className="w-40 px-2 py-2 text-left text-xs font-semibold uppercase text-muted">Tax</th>
              {/* Customer Name, Projects, Billable — disabled until features complete */}
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border">
                <td className="px-2 py-1.5">
                  <input type="checkbox" className="rounded border-border" />
                </td>
                <td className="px-2 py-1.5">
                  <input type="date" value={row.date} onChange={e => updateRow(i, { date: e.target.value })}
                    className="w-full rounded-ctl border border-border bg-card px-2 py-1 text-xs text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
                </td>
                <td className="px-2 py-1.5">
                  <select value={row.category} onChange={e => updateRow(i, { category: e.target.value })}
                    className="w-full rounded-ctl border border-border bg-card px-2 py-1 text-xs text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
                    {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label || 'Select an account'}</option>)}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-1">
                    <span className="shrink-0 text-xs text-muted">NZD</span>
                    <input type="number" min="0" step="0.01" value={row.amount} onChange={e => updateRow(i, { amount: e.target.value })}
                      className="w-full rounded-ctl border border-border bg-card px-2 py-1 text-xs text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" placeholder="0.00" />
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <div className="space-y-0.5">
                    <select value={row.tax_rate} onChange={e => updateRow(i, { tax_rate: e.target.value })}
                      className="w-full rounded-ctl border border-border bg-card px-2 py-1 text-xs text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
                      {TAX_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                    <label className="flex cursor-pointer items-center gap-1 text-xs text-muted">
                      <input type="checkbox" checked={row.tax_inclusive} onChange={e => updateRow(i, { tax_inclusive: e.target.checked })} className="rounded border-border" />
                      Tax Inclusive
                    </label>
                  </div>
                </td>
                {/* Customer Name, Projects, Billable — disabled until features complete */}
                <td className="px-2 py-1.5">
                  <button type="button" onClick={() => removeRow(i)} className="p-1 text-muted-2 hover:text-muted">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                    </svg>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" onClick={addRows} className="mt-3 flex items-center gap-1 text-sm text-accent hover:underline">
        <span>+</span> Add More Expenses
      </button>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
      {success && <p className="mt-2 text-sm text-ok">✓ Expenses saved successfully.</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={handleSave} loading={saving}>Save All</Button>
        <Button variant="ghost" onClick={() => setRows(Array.from({ length: 10 }, emptyRow))}>Clear</Button>
      </div>
    </div>
  )
}

/* ── Main Page ── */
const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

export default function ExpenseList() {
  const { branches: branchList } = useBranch()
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const pageSize = 20

  /* Create modal state */
  const [createOpen, setCreateOpen] = useState(false)
  const [createTab, setCreateTab] = useState<Tab>('expense')

  /* Receipt preview modal state */
  const [receiptPreviewUrl, setReceiptPreviewUrl] = useState<string | null>(null)
  const [receiptPreviewName, setReceiptPreviewName] = useState('')
  const [receiptPreviewOpen, setReceiptPreviewOpen] = useState(false)
  const [receiptLoading, setReceiptLoading] = useState(false)

  const fetchExpenses = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), page_size: String(pageSize) }
      const res = await apiClient.get('/api/v2/expenses', { params })
      setExpenses(res.data?.expenses ?? [])
      setTotal(res.data?.total ?? 0)
    } catch { setExpenses([]) }
    finally { setLoading(false) }
  }, [page])

  useEffect(() => { fetchExpenses() }, [fetchExpenses])

  const totalPages = Math.ceil((total ?? 0) / pageSize)

  const filtered = search.trim()
    ? (expenses ?? []).filter(e => (e.description ?? '').toLowerCase().includes(search.toLowerCase()) || (e.category ?? '').toLowerCase().includes(search.toLowerCase()))
    : (expenses ?? [])

  const handleSaved = () => {
    setCreateOpen(false)
    fetchExpenses()
  }

  const tabClass = (t: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${createTab === t ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-text'}`

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header with search and + Expense button */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-text">Expenses</h1>
        <Button variant="primary" onClick={() => { setCreateTab('expense'); setCreateOpen(true) }}>
          + Expense
        </Button>
      </div>

      {/* Search bar */}
      <div className="mb-4 flex items-center gap-3">
        <div className="relative max-w-sm flex-1">
          <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search expenses..."
            className="w-full rounded-ctl border border-border bg-card py-2 pl-9 pr-3 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
        </div>
        <span className="text-sm text-muted">{(total ?? 0).toLocaleString()} expense{total !== 1 ? 's' : ''}</span>
      </div>

      {/* Expense list */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading expenses" /></div>
      ) : filtered.length === 0 ? (
        <div className="rounded-card border border-border bg-card p-12 text-center">
          <p className="mb-4 text-muted">No expenses recorded yet.</p>
          <Button variant="primary" onClick={() => { setCreateTab('expense'); setCreateOpen(true) }}>
            + Record Your First Expense
          </Button>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full">
              <thead>
                <tr>
                  <th className={TH}>Date</th>
                  <th className={TH}>Description</th>
                  <th className={TH}>Category</th>
                  <th className={TH}>Branch</th>
                  <th className={TH_RIGHT}>Amount</th>
                  <th className={TH}>Type</th>
                  <th className={TH}>Status</th>
                  <th className={TH}>Receipt</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(exp => (
                  <tr key={exp.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">{new Date(exp.date).toLocaleDateString('en-NZ')}</td>
                    <td className="max-w-xs truncate px-4 py-3 text-sm text-text">{exp.description}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{catLabel(exp.category)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                      {exp.branch_id ? ((branchList ?? []).find(b => b.id === exp.branch_id)?.name ?? '—') : '—'}
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm font-medium text-text">{formatNZD(exp.amount)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {exp.expense_type === 'mileage' ? <Badge variant="info">Mileage</Badge> : <Badge variant="neutral">Expense</Badge>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {exp.is_invoiced ? <Badge variant="success">Invoiced</Badge> : exp.is_billable ? <Badge variant="warn">Billable</Badge> : <span className="text-xs text-muted-2">—</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {exp.receipt_file_key ? (
                        <button
                          type="button"
                          onClick={async () => {
                            setReceiptLoading(true)
                            setReceiptPreviewName(exp.receipt_file_key?.split('/').pop() ?? 'Receipt')
                            setReceiptPreviewOpen(true)
                            try {
                              const res = await apiClient.get(`/api/v2/uploads/${exp.receipt_file_key}`, { responseType: 'blob' })
                              const blob = res.data as Blob
                              const url = URL.createObjectURL(blob)
                              setReceiptPreviewUrl(url)
                            } catch {
                              setReceiptPreviewUrl(null)
                            } finally {
                              setReceiptLoading(false)
                            }
                          }}
                          className="text-xs text-accent hover:underline"
                        >View</button>
                      ) : <span className="text-xs text-muted-2">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-muted">{(total ?? 0).toLocaleString()} expense{total !== 1 ? 's' : ''}</p>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                <span className="flex items-center text-sm text-muted">Page {page} of {totalPages}</span>
                <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Create Expense Modal */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Record Expense"
        className="max-w-3xl"
      >
        {/* Tabs inside modal */}
        <div className="-mx-6 mb-4 flex border-b border-border px-6">
          <button className={tabClass('expense')} onClick={() => setCreateTab('expense')}>Record Expense</button>
          <button className={tabClass('mileage')} onClick={() => setCreateTab('mileage')}>Record Mileage</button>
          <button className={tabClass('bulk')} onClick={() => setCreateTab('bulk')}>Bulk Add</button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto">
          {createTab === 'expense' && <RecordExpenseTab onSaved={handleSaved} />}
          {createTab === 'mileage' && <RecordMileageTab onSaved={handleSaved} />}
          {createTab === 'bulk' && <BulkAddTab onSaved={handleSaved} />}
        </div>
      </Modal>

      {/* Receipt Preview Modal */}
      <Modal open={receiptPreviewOpen} onClose={() => { setReceiptPreviewOpen(false); if (receiptPreviewUrl) { URL.revokeObjectURL(receiptPreviewUrl); setReceiptPreviewUrl(null) } }} title={receiptPreviewName}>
        <div className="flex min-h-[300px] items-center justify-center">
          {receiptLoading ? (
            <Spinner label="Loading receipt..." />
          ) : receiptPreviewUrl ? (
            receiptPreviewName.toLowerCase().endsWith('.pdf') ? (
              <iframe src={receiptPreviewUrl} className="h-[70vh] w-full rounded-card border border-border" title="PDF Preview" />
            ) : (
              <img src={receiptPreviewUrl} alt="Receipt" className="max-h-[70vh] max-w-full rounded-card shadow-pop" />
            )
          ) : (
            <p className="text-sm text-danger">Failed to load receipt. The file may no longer exist.</p>
          )}
        </div>
      </Modal>
    </div>
  )
}
