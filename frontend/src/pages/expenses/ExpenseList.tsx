import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal } from '@/components/ui'

/* ── Types ── */
interface Expense {
  id: string; job_id: string | null; project_id: string | null; invoice_id: string | null
  customer_id: string | null; date: string; description: string; amount: string
  tax_amount: string; category: string | null; reference_number: string | null
  notes: string | null; receipt_file_key: string | null; is_pass_through: boolean
  is_billable: boolean; is_invoiced: boolean; tax_inclusive: boolean
  expense_type: string; created_at: string
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
    <div className="flex items-start gap-4 py-3 border-b border-gray-100 last:border-0">
      <label className={`w-36 shrink-0 text-sm pt-2 ${required ? 'text-red-500 font-medium' : 'text-gray-600'}`}>
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
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    setUploading(true)
    try { onUpload(file) } finally { setUploading(false) }
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
      className={`rounded-lg border-2 border-dashed p-6 text-center transition-colors ${dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-gray-50'}`}
    >
      {fileKey ? (
        <div className="space-y-2">
          <div className="text-green-600 text-sm font-medium">✓ Receipt attached</div>
          <button type="button" onClick={onRemove} className="text-xs text-red-500 hover:underline">Remove</button>
        </div>
      ) : (
        <>
          <div className="mx-auto mb-3 h-12 w-12 rounded-lg bg-blue-100 flex items-center justify-center">
            <svg className="h-6 w-6 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
          <p className="text-sm text-gray-600 font-medium">Drag or Drop your Receipts</p>
          <p className="text-xs text-gray-400 mb-3">Maximum file size allowed is 10MB</p>
          <button type="button" onClick={() => inputRef.current?.click()}
            className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
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
        <div className="flex flex-1 items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm">
          <span className="flex-1">{selectedName}</span>
          <button type="button" onClick={clear} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
      ) : (
        <input type="text" value={query} onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)} placeholder="Select or add a customer"
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      )}
      <button type="button" className="rounded-md bg-blue-600 px-3 py-2 text-white hover:bg-blue-700">
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </button>
      {open && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 rounded-md border border-gray-200 bg-white shadow-lg">
          {results.map(c => (
            <button key={c.id} type="button" onClick={() => select(c)}
              className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50">
              {c.display_name || `${c.first_name} ${c.last_name}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Record Expense Tab ── */
function RecordExpenseTab({ onSaved }: { onSaved: () => void }) {
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
            className="rounded-md border border-gray-300 px-3 py-2 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </FieldRow>
        <FieldRow label="Category Name" required>
          <div className="space-y-1">
            <select value={form.category} onChange={e => setForm(p => ({ ...p, category: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            <button type="button" className="text-xs text-blue-600 hover:underline flex items-center gap-1">
              <span>≡</span> Itemize
            </button>
          </div>
        </FieldRow>
        <FieldRow label="Amount" required>
          <div className="flex items-center gap-2">
            <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-600">NZD</span>
            <input type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
              className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
          </div>
        </FieldRow>
        <FieldRow label="Amount Is">
          <div className="flex gap-4 pt-1">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" name="tax_mode" checked={form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: true }))} className="text-blue-600" />
              Tax Inclusive
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" name="tax_mode" checked={!form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: false }))} className="text-blue-600" />
              Tax Exclusive
            </label>
          </div>
        </FieldRow>
        <FieldRow label="Tax">
          <select value={form.tax_rate} onChange={e => setForm(p => ({ ...p, tax_rate: e.target.value }))}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {TAX_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </FieldRow>
        <FieldRow label="Reference#">
          <input type="text" value={form.reference} onChange={e => setForm(p => ({ ...p, reference: e.target.value }))}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </FieldRow>
        <FieldRow label="Notes">
          <textarea value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} rows={3}
            placeholder="Max. 500 characters"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
        </FieldRow>
        <FieldRow label="Customer Name">
          <CustomerSearch value={form.customer_id} onChange={(id) => setForm(p => ({ ...p, customer_id: id }))} />
        </FieldRow>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        {success && <p className="mt-2 text-sm text-green-600">✓ Expense saved successfully.</p>}
        <div className="mt-4 flex gap-2">
          <Button onClick={handleSave} loading={saving}>Save Expense</Button>
          <Button variant="secondary" onClick={() => setForm({ date: new Date().toISOString().split('T')[0], category: '', amount: '', tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false, receipt_file_key: '' })}>
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
      <div className="flex justify-end mb-2">
        <button type="button" onClick={() => { setPrefsForm(prefs); setShowPrefs(true) }}
          className="text-sm text-blue-600 hover:underline">Set mileage preferences</button>
      </div>
      <div className="flex gap-6">
        <div className="flex-1">
          <FieldRow label="Date" required>
            <input type="date" value={form.date} onChange={e => setForm(p => ({ ...p, date: e.target.value }))}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </FieldRow>
          <FieldRow label="Employee">
            <input type="text" value={form.employee} onChange={e => setForm(p => ({ ...p, employee: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </FieldRow>
          <FieldRow label="Calculate mileage using" required>
            <div className="flex gap-4 pt-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="calc" checked={form.calc_method === 'distance'} onChange={() => setForm(p => ({ ...p, calc_method: 'distance' }))} className="text-blue-600" />
                Distance travelled
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="calc" checked={form.calc_method === 'odometer'} onChange={() => setForm(p => ({ ...p, calc_method: 'odometer' }))} className="text-blue-600" />
                Odometer reading
              </label>
            </div>
          </FieldRow>
          <FieldRow label="Distance" required>
            <div className="flex items-center gap-2">
              <input type="number" min="0" step="0.1" value={form.distance} onChange={e => setForm(p => ({ ...p, distance: e.target.value }))}
                className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <span className="text-sm text-gray-500">{prefs.default_unit === 'km' ? 'Kilometer(s)' : 'Mile(s)'}</span>
            </div>
          </FieldRow>
          <FieldRow label="Amount" required>
            <div className="flex items-center gap-2">
              <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-600">NZD</span>
              <input type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
                className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
            </div>
          </FieldRow>
          <FieldRow label="Amount Is">
            <div className="flex gap-4 pt-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="tax_mode_m" checked={form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: true }))} className="text-blue-600" />
                Tax Inclusive
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="tax_mode_m" checked={!form.tax_inclusive} onChange={() => setForm(p => ({ ...p, tax_inclusive: false }))} className="text-blue-600" />
                Tax Exclusive
              </label>
            </div>
          </FieldRow>
          <FieldRow label="Tax">
            <select value={form.tax_rate} onChange={e => setForm(p => ({ ...p, tax_rate: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {TAX_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </FieldRow>
          <FieldRow label="Reference#">
            <input type="text" value={form.reference} onChange={e => setForm(p => ({ ...p, reference: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </FieldRow>
          <FieldRow label="Notes">
            <textarea value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} rows={3}
              placeholder="Max. 500 characters"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </FieldRow>
          <FieldRow label="Customer Name">
            <CustomerSearch value={form.customer_id} onChange={(id) => setForm(p => ({ ...p, customer_id: id }))} />
          </FieldRow>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          {success && <p className="mt-2 text-sm text-green-600">✓ Mileage expense saved.</p>}
          <div className="mt-4 flex gap-2">
            <Button onClick={handleSave} loading={saving}>Save Mileage</Button>
            <Button variant="secondary" onClick={() => setForm({ date: new Date().toISOString().split('T')[0], employee: '', calc_method: 'distance', distance: '', amount: '', tax_rate: '', reference: '', notes: '', customer_id: '', tax_inclusive: false })}>Cancel</Button>
          </div>
        </div>
      </div>

      {/* Mileage Preferences Modal */}
      <Modal open={showPrefs} onClose={() => setShowPrefs(false)} title="Set your mileage preferences">
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <label className="w-40 text-sm text-gray-700">Default Mileage Account</label>
            <select value={prefsForm.default_account || ''} onChange={e => setPrefsForm(p => ({ ...p, default_account: e.target.value || null }))}
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Fuel/Mileage Expenses</option>
              <option value="travel">Travel</option>
            </select>
          </div>
          <div className="flex items-center gap-4">
            <label className="w-40 text-sm text-gray-700">Default Unit</label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="unit" checked={prefsForm.default_unit === 'km'} onChange={() => setPrefsForm(p => ({ ...p, default_unit: 'km' }))} className="text-blue-600" />
                Km
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="unit" checked={prefsForm.default_unit === 'mile'} onChange={() => setPrefsForm(p => ({ ...p, default_unit: 'mile' }))} className="text-blue-600" />
                Mile
              </label>
            </div>
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900 mb-1">MILEAGE RATES</p>
            <p className="text-xs text-gray-500 mb-3">Any mileage expense recorded on or after the start date will have the corresponding mileage rate.</p>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <div className="text-xs font-medium text-gray-500 uppercase">Start Date</div>
              <div className="text-xs font-medium text-gray-500 uppercase">Mileage Rate</div>
            </div>
            {prefsForm.rates.map((r, i) => (
              <div key={i} className="grid grid-cols-2 gap-2 mb-2 items-center">
                <input type="date" value={r.start_date || ''} onChange={e => setPrefsForm(p => ({ ...p, rates: p.rates.map((rr, ii) => ii === i ? { ...rr, start_date: e.target.value || null } : rr) }))}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-500">NZD</span>
                  <input type="number" min="0" step="0.0001" value={r.rate_per_unit} onChange={e => setPrefsForm(p => ({ ...p, rates: p.rates.map((rr, ii) => ii === i ? { ...rr, rate_per_unit: e.target.value } : rr) }))}
                    className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="0.00" />
                  <button type="button" onClick={() => removeRate(i)} className="text-red-500 hover:text-red-700 text-xs">✕</button>
                </div>
              </div>
            ))}
            <button type="button" onClick={addRate} className="text-sm text-blue-600 hover:underline flex items-center gap-1">
              <span>+</span> Add Mileage Rate
            </button>
          </div>
          <div className="flex gap-2 pt-2">
            <Button onClick={handleSavePrefs} loading={savingPrefs}>Save</Button>
            <Button variant="secondary" onClick={() => setShowPrefs(false)}>Cancel</Button>
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
            <tr className="border-b border-gray-200">
              <th className="w-8 px-2 py-2">
                <input type="checkbox" className="rounded border-gray-300" />
              </th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-red-500 uppercase w-32">Date *</th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-red-500 uppercase w-40">Category Name *</th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-red-500 uppercase w-36">Amount *</th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-gray-500 uppercase w-40">Tax</th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-gray-500 uppercase w-40">Customer Name</th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-gray-500 uppercase w-36">Projects</th>
              <th className="px-2 py-2 text-left text-xs font-semibold text-gray-500 uppercase w-16">Billable</th>
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-gray-100">
                <td className="px-2 py-1.5">
                  <input type="checkbox" className="rounded border-gray-300" />
                </td>
                <td className="px-2 py-1.5">
                  <input type="date" value={row.date} onChange={e => updateRow(i, { date: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </td>
                <td className="px-2 py-1.5">
                  <select value={row.category} onChange={e => updateRow(i, { category: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                    {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label || 'Select an account'}</option>)}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-gray-500 shrink-0">NZD</span>
                    <input type="number" min="0" step="0.01" value={row.amount} onChange={e => updateRow(i, { amount: e.target.value })}
                      className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" placeholder="0.00" />
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <div className="space-y-0.5">
                    <select value={row.tax_rate} onChange={e => updateRow(i, { tax_rate: e.target.value })}
                      className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                      {TAX_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                    <label className="flex items-center gap-1 text-xs text-gray-500 cursor-pointer">
                      <input type="checkbox" checked={row.tax_inclusive} onChange={e => updateRow(i, { tax_inclusive: e.target.checked })} className="rounded border-gray-300" />
                      Tax Inclusive
                    </label>
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <select className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                    <option value="">—</option>
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <select className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                    <option value="">—</option>
                  </select>
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={row.is_billable} onChange={e => updateRow(i, { is_billable: e.target.checked })} className="rounded border-gray-300" />
                </td>
                <td className="px-2 py-1.5">
                  <button type="button" onClick={() => removeRow(i)} className="text-gray-400 hover:text-gray-600 p-1">
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
      <button type="button" onClick={addRows} className="mt-3 text-sm text-blue-600 hover:underline flex items-center gap-1">
        <span>+</span> Add More Expenses
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {success && <p className="mt-2 text-sm text-green-600">✓ Expenses saved successfully.</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={handleSave} loading={saving}>Save All</Button>
        <Button variant="secondary" onClick={() => setRows(Array.from({ length: 10 }, emptyRow))}>Clear</Button>
      </div>
    </div>
  )
}

/* ── Main Page ── */
export default function ExpenseList() {
  const [tab, setTab] = useState<Tab>('expense')
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const pageSize = 20

  const fetchExpenses = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), page_size: String(pageSize) }
      const res = await apiClient.get('/api/v2/expenses', { params })
      setExpenses(res.data.expenses || [])
      setTotal(res.data.total || 0)
    } catch { setExpenses([]) }
    finally { setLoading(false) }
  }, [page])

  useEffect(() => { fetchExpenses() }, [fetchExpenses])

  const totalPages = Math.ceil(total / pageSize)

  const filtered = search.trim()
    ? expenses.filter(e => e.description.toLowerCase().includes(search.toLowerCase()) || (e.category || '').toLowerCase().includes(search.toLowerCase()))
    : expenses

  const tabClass = (t: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${tab === t ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-600 hover:text-gray-900'}`

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Search bar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search in Expenses ( / )"
            className="w-full rounded-md border border-gray-300 pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-6">
        <button className={tabClass('expense')} onClick={() => setTab('expense')}>Record Expense</button>
        <button className={tabClass('mileage')} onClick={() => setTab('mileage')}>Record Mileage</button>
        <button className={tabClass('bulk')} onClick={() => setTab('bulk')}>Bulk Add Expenses</button>
      </div>

      {/* Tab content */}
      <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
        {tab === 'expense' && <RecordExpenseTab onSaved={fetchExpenses} />}
        {tab === 'mileage' && <RecordMileageTab onSaved={fetchExpenses} />}
        {tab === 'bulk' && <BulkAddTab onSaved={fetchExpenses} />}
      </div>

      {/* Expense list */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Recent Expenses</h2>
        {loading ? (
          <div className="py-8 text-center"><Spinner label="Loading expenses" /></div>
        ) : filtered.length === 0 ? (
          <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
            No expenses recorded yet.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                    <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount</th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Receipt</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {filtered.map(exp => (
                    <tr key={exp.id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{new Date(exp.date).toLocaleDateString('en-NZ')}</td>
                      <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">{exp.description}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{catLabel(exp.category)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-medium tabular-nums">{formatNZD(exp.amount)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {exp.expense_type === 'mileage' ? <Badge variant="info">Mileage</Badge> : <Badge variant="neutral">Expense</Badge>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {exp.is_invoiced ? <Badge variant="success">Invoiced</Badge> : exp.is_billable ? <Badge variant="warning">Billable</Badge> : <span className="text-gray-400 text-xs">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {exp.receipt_file_key ? (
                          <a href={`/api/v2/files/${exp.receipt_file_key}`} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline text-xs">View</a>
                        ) : <span className="text-gray-400 text-xs">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-sm text-gray-500">{total} expense{total !== 1 ? 's' : ''}</p>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                  <span className="flex items-center text-sm text-gray-600">Page {page} of {totalPages}</span>
                  <Button size="sm" variant="secondary" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
