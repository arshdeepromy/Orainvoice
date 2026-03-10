import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button } from '../../components/ui'
import { useModules } from '../../contexts/ModuleContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Customer {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  address?: string
}

interface Vehicle {
  id: string
  rego: string
  make: string
  model: string
  year: number | null
  colour: string
}

interface Project {
  id: string
  name: string
  status: string
}

interface CatalogueItem {
  id: string
  name: string
  description?: string
  default_price: number
  gst_applicable: boolean
  category?: string
  sku?: string
}

interface TaxRate {
  id: string
  name: string
  rate: number
}

interface LineItem {
  key: string
  item_id?: string
  description: string
  quantity: number
  rate: number
  tax_id: string
  tax_rate: number
  amount: number
}

interface FormErrors {
  customer?: string
  lineItems?: string
  submit?: string
  [key: string]: string | undefined
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const VALIDITY_OPTIONS = [
  { value: '7', label: '7 days' },
  { value: '14', label: '14 days' },
  { value: '30', label: '30 days' },
]

const DEFAULT_TAX_RATES: TaxRate[] = [
  { id: 'gst_15', name: 'GST (15%)', rate: 15 },
  { id: 'gst_0', name: 'GST Exempt (0%)', rate: 0 },
]

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

function formatDate(d: Date): string {
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(d)
}

function formatDateISO(d: Date): string {
  return d.toISOString().split('T')[0]
}

function newLineItem(): LineItem {
  return {
    key: crypto.randomUUID(),
    description: '',
    quantity: 1,
    rate: 0,
    tax_id: 'gst_15',
    tax_rate: 15,
    amount: 0,
  }
}

function calcLineAmount(item: LineItem): number {
  return Math.round(item.quantity * item.rate * 100) / 100
}

/* ------------------------------------------------------------------ */
/*  Customer Search                                                    */
/* ------------------------------------------------------------------ */

function CustomerSearch({
  selectedCustomer,
  onSelect,
  error,
}: {
  selectedCustomer: Customer | null
  onSelect: (c: Customer | null) => void
  error?: string
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setShowDropdown(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setResults([]); return }
    setLoading(true)
    try {
      const res = await apiClient.get('/customers', { params: { search: q } })
      const data = res.data as any
      setResults(Array.isArray(data) ? data : (data?.customers ?? []))
    } catch { setResults([]) }
    finally { setLoading(false) }
  }, [])

  const handleInput = (value: string) => {
    setQuery(value)
    setShowDropdown(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(value), 300)
  }

  if (selectedCustomer) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Customer Name *</label>
        <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2">
          <span className="flex-1 text-gray-900">
            {selectedCustomer.first_name} {selectedCustomer.last_name}
            {selectedCustomer.email && <span className="ml-2 text-gray-500">· {selectedCustomer.email}</span>}
          </span>
          <button type="button" onClick={() => { onSelect(null); setQuery('') }}
            className="rounded p-1 text-gray-400 hover:text-gray-600" aria-label="Change customer">✕</button>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">Customer Name *</label>
      <input type="text" value={query} onChange={(e) => handleInput(e.target.value)}
        onFocus={() => query.length >= 2 && setShowDropdown(true)}
        placeholder="Search or select a customer"
        className={`w-full rounded-md border px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ${error ? 'border-red-500' : 'border-gray-300'}`}
        autoComplete="off" />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      {showDropdown && (
        <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-56 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
          {loading && <div className="px-4 py-3 text-sm text-gray-500">Searching…</div>}
          {!loading && results.map((c) => (
            <button key={c.id} type="button"
              onClick={() => { onSelect(c); setQuery(`${c.first_name} ${c.last_name}`); setShowDropdown(false) }}
              className="w-full px-4 py-2.5 text-left hover:bg-gray-50 text-sm">
              <span className="font-medium text-gray-900">{c.first_name} {c.last_name}</span>
              {c.email && <span className="ml-2 text-gray-500">{c.email}</span>}
            </button>
          ))}
          {!loading && query.length >= 2 && results.length === 0 && (
            <div className="px-4 py-3 text-sm text-gray-500">No customers found</div>
          )}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Item Table Row                                                     */
/* ------------------------------------------------------------------ */

function ItemTableRow({
  item,
  index,
  catalogueItems,
  taxRates,
  onChange,
  onRemove,
}: {
  item: LineItem
  index: number
  catalogueItems: CatalogueItem[]
  taxRates: TaxRate[]
  onChange: (index: number, updated: LineItem) => void
  onRemove: (index: number) => void
}) {
  const [showItemDropdown, setShowItemDropdown] = useState(false)
  const [itemSearch, setItemSearch] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setShowItemDropdown(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const update = (patch: Partial<LineItem>) => {
    const updated = { ...item, ...patch }
    updated.amount = calcLineAmount(updated)
    onChange(index, updated)
  }

  const handleItemSelect = (ci: CatalogueItem) => {
    update({
      item_id: ci.id,
      description: ci.name,
      rate: ci.default_price,
      tax_rate: ci.gst_applicable ? 15 : 0,
      tax_id: ci.gst_applicable ? 'gst_15' : 'gst_0',
    })
    setShowItemDropdown(false)
    setItemSearch('')
  }

  const handleTaxChange = (taxId: string) => {
    const tax = taxRates.find(t => t.id === taxId)
    update({ tax_id: taxId, tax_rate: tax?.rate || 0 })
  }

  const filteredItems = (Array.isArray(catalogueItems) ? catalogueItems : []).filter(ci =>
    ci.name.toLowerCase().includes(itemSearch.toLowerCase()) ||
    (ci.sku && ci.sku.toLowerCase().includes(itemSearch.toLowerCase()))
  )

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50">
      <td className="py-3 px-2">
        <div ref={containerRef} className="relative">
          <input type="text" value={item.description}
            onChange={(e) => { update({ description: e.target.value }); setItemSearch(e.target.value) }}
            onFocus={() => setShowItemDropdown(true)}
            placeholder="Type or click to select an item"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          {showItemDropdown && (
            <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
              {filteredItems.slice(0, 10).map((ci) => (
                <button key={ci.id} type="button" onClick={() => handleItemSelect(ci)}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50">
                  <div className="font-medium text-gray-900">{ci.name}</div>
                  {ci.sku && <div className="text-xs text-gray-500">SKU: {ci.sku}</div>}
                  <div className="text-xs text-gray-500">{formatNZD(ci.default_price)}</div>
                </button>
              ))}
              {filteredItems.length === 0 && (
                <div className="px-3 py-2 text-sm text-gray-500">No items found</div>
              )}
            </div>
          )}
        </div>
      </td>
      <td className="py-3 px-2 w-24">
        <input type="number" min="1" step="1" value={item.quantity}
          onChange={(e) => update({ quantity: Math.max(1, Number(e.target.value) || 1) })}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </td>
      <td className="py-3 px-2 w-32">
        <input type="number" min="0" step="0.01" value={item.rate}
          onChange={(e) => update({ rate: Math.max(0, Number(e.target.value) || 0) })}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </td>
      <td className="py-3 px-2 w-36">
        <select value={item.tax_id || ''} onChange={(e) => handleTaxChange(e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          {taxRates.map((tax) => (
            <option key={tax.id} value={tax.id}>{tax.name}</option>
          ))}
        </select>
      </td>
      <td className="py-3 px-2 w-28 text-right text-sm font-medium text-gray-900">
        {formatNZD(item.amount)}
      </td>
      <td className="py-3 px-2 w-12">
        <button type="button" onClick={() => onRemove(index)}
          className="rounded p-1 text-gray-400 hover:text-red-500" aria-label="Remove item">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </td>
    </tr>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function QuoteCreate() {
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id: string }>()
  const isEditMode = Boolean(editId)
  const { isEnabled } = useModules()
  const projectsEnabled = isEnabled('projects')

  // Header fields
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [vehicleRego, setVehicleRego] = useState('')
  const [vehicleLookupLoading, setVehicleLookupLoading] = useState(false)
  const [vehicleLookupError, setVehicleLookupError] = useState('')
  const [subject, setSubject] = useState('')
  const [validityDays, setValidityDays] = useState('30')
  const [quoteDate] = useState(() => formatDateISO(new Date()))

  // Projects
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState('')

  // Line items
  const [lineItems, setLineItems] = useState<LineItem[]>([newLineItem()])
  const [catalogueItems, setCatalogueItems] = useState<CatalogueItem[]>([])
  const [taxRates] = useState<TaxRate[]>(DEFAULT_TAX_RATES)

  // Totals adjustments (aligned with invoice)
  const [discountType, setDiscountType] = useState<'percentage' | 'fixed'>('percentage')
  const [discountValue, setDiscountValue] = useState(0)
  const [shippingCharges, setShippingCharges] = useState(0)
  const [adjustment, setAdjustment] = useState(0)

  // Notes and terms
  const [notes, setNotes] = useState('')
  const [terms, setTerms] = useState('')

  // Form state
  const [saving, setSaving] = useState(false)
  const [sendingAndSaving, setSendingAndSaving] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
  const [loadingQuote, setLoadingQuote] = useState(isEditMode)

  const expiryDate = formatDate(new Date(Date.now() + Number(validityDays) * 86400000))

  // Calculate totals (same approach as InvoiceCreate)
  const subTotal = lineItems.reduce((sum, item) => sum + item.amount, 0)
  const discountAmount = discountType === 'percentage'
    ? (subTotal * discountValue / 100)
    : discountValue
  const afterDiscount = subTotal - discountAmount
  const taxAmount = lineItems.reduce((sum, item) => sum + (item.amount * item.tax_rate / 100), 0)
  const total = afterDiscount + taxAmount + shippingCharges + adjustment

  // Load existing quote for edit mode
  useEffect(() => {
    if (!editId) return
    let cancelled = false
    async function loadQuote() {
      try {
        const res = await apiClient.get(`/quotes/${editId}`)
        const q = (res.data as any)?.quote || (res.data as any)
        if (cancelled) return

        if (q.customer_id) {
          try {
            const custRes = await apiClient.get(`/customers/${q.customer_id}`)
            const cust = (custRes.data as any)?.customer || custRes.data
            if (!cancelled) setCustomer(cust)
          } catch { /* non-blocking */ }
        }

        if (q.vehicle_rego) {
          setVehicleRego(q.vehicle_rego)
          setVehicle({
            id: '', rego: q.vehicle_rego,
            make: q.vehicle_make || '', model: q.vehicle_model || '',
            year: q.vehicle_year || null, colour: '',
          })
        }

        setSubject(q.subject || '')
        setNotes(q.notes || '')
        setTerms(q.terms || '')
        if (q.project_id) setSelectedProjectId(q.project_id)

        // Populate discount/shipping/adjustment
        if (q.discount_type) setDiscountType(q.discount_type === 'fixed' ? 'fixed' : 'percentage')
        if (q.discount_value != null) setDiscountValue(Number(q.discount_value))
        if (q.shipping_charges != null) setShippingCharges(Number(q.shipping_charges))
        if (q.adjustment != null) setAdjustment(Number(q.adjustment))

        // Populate line items (convert from quote format to invoice-aligned format)
        if (q.line_items && q.line_items.length > 0) {
          setLineItems(q.line_items.map((li: any) => ({
            key: crypto.randomUUID(),
            item_id: '',
            description: li.description || '',
            quantity: Number(li.quantity) || 1,
            rate: Number(li.unit_price) || 0,
            tax_id: li.is_gst_exempt ? 'gst_0' : 'gst_15',
            tax_rate: li.is_gst_exempt ? 0 : 15,
            amount: Number(li.line_total) || 0,
          })))
        }
      } catch {
        setErrors({ submit: 'Failed to load quote for editing' })
      } finally {
        if (!cancelled) setLoadingQuote(false)
      }
    }
    loadQuote()
    return () => { cancelled = true }
  }, [editId])

  // Load catalogue items
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await apiClient.get('/catalogue/services', { params: { active: true } })
        const data = res.data as any
        if (!cancelled) setCatalogueItems(Array.isArray(data) ? data : (data?.services || []))
      } catch { /* non-blocking */ }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // Load projects if enabled
  useEffect(() => {
    if (!projectsEnabled || !customer) return
    let cancelled = false
    async function load() {
      try {
        const res = await apiClient.get('/projects', {
          baseURL: '/api/v2',
          params: { customer_id: customer?.id, page_size: 100 },
        })
        const data = res.data as any
        if (!cancelled) setProjects(data?.projects ?? [])
      } catch { /* non-blocking */ }
    }
    load()
    return () => { cancelled = true }
  }, [projectsEnabled, customer])

  // Vehicle lookup
  const lookupVehicle = async () => {
    const cleaned = vehicleRego.trim().toUpperCase()
    if (!cleaned) return
    setVehicleLookupLoading(true)
    setVehicleLookupError('')
    try {
      const res = await apiClient.get(`/vehicles/lookup/${encodeURIComponent(cleaned)}`)
      setVehicle(res.data as Vehicle)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setVehicleLookupError(status === 404 ? 'Vehicle not found' : 'Lookup failed')
      setVehicle(null)
    } finally { setVehicleLookupLoading(false) }
  }

  // Line item management
  const addLineItem = () => setLineItems(prev => [...prev, newLineItem()])
  const updateLineItem = (index: number, updated: LineItem) => {
    setLineItems(prev => prev.map((item, i) => i === index ? updated : item))
  }
  const removeLineItem = (index: number) => {
    if (lineItems.length > 1) setLineItems(prev => prev.filter((_, i) => i !== index))
  }

  // Validation
  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!customer) errs.customer = 'Please select a customer'
    if (lineItems.every(item => !item.description.trim())) errs.lineItems = 'Add at least one item'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  // Build payload — sends fields matching backend QuoteCreate/QuoteUpdate schemas
  const buildPayload = () => ({
    customer_id: customer?.id,
    vehicle_rego: vehicle?.rego ?? (vehicleRego.trim() || undefined),
    vehicle_make: vehicle?.make ?? undefined,
    vehicle_model: vehicle?.model ?? undefined,
    vehicle_year: vehicle?.year ?? undefined,
    project_id: selectedProjectId || undefined,
    validity_days: Number(validityDays),
    notes: notes || undefined,
    terms: terms || undefined,
    subject: subject || undefined,
    discount_type: discountType === 'fixed' ? 'fixed' : 'percentage',
    discount_value: discountValue,
    shipping_charges: shippingCharges,
    adjustment: adjustment,
    line_items: lineItems.filter(item => item.description.trim()).map((item, i) => ({
      item_type: 'service',
      description: item.description,
      quantity: item.quantity,
      unit_price: item.rate,
      is_gst_exempt: item.tax_rate === 0,
      sort_order: i,
    })),
  })

  // Save as Draft
  const handleSaveDraft = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      if (isEditMode && editId) {
        await apiClient.put(`/quotes/${editId}`, buildPayload())
        navigate(`/quotes/${editId}`)
      } else {
        await apiClient.post('/quotes', buildPayload())
        navigate('/quotes')
      }
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setErrors({ submit: detail ?? 'Failed to save quote' })
    } finally { setSaving(false) }
  }

  // Save and Send
  const handleSaveAndSend = async () => {
    if (!validate()) return
    setSendingAndSaving(true)
    try {
      let quoteId = editId
      if (isEditMode && editId) {
        await apiClient.put(`/quotes/${editId}`, buildPayload())
      } else {
        const createRes = await apiClient.post('/quotes', buildPayload())
        const quoteData = (createRes.data as any)?.quote ?? createRes.data
        quoteId = quoteData?.id
      }
      if (quoteId) await apiClient.post(`/quotes/${quoteId}/send`)
      navigate('/quotes')
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail
      setErrors({ submit: detail ?? 'Failed to save and send quote' })
    } finally { setSendingAndSaving(false) }
  }

  const handleCancel = () => {
    navigate(isEditMode && editId ? `/quotes/${editId}` : '/quotes')
  }

  const isBusy = saving || sendingAndSaving

  if (loadingQuote) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 text-center">
        <div className="text-gray-500">Loading quote…</div>
      </div>
    )
  }

  return (
    <div className="bg-gray-50">
      {/* Header — matches InvoiceCreate */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">{isEditMode ? 'Edit Quote' : 'New Quote'}</h1>
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={handleCancel} disabled={isBusy}>Cancel</Button>
            <Button variant="secondary" onClick={handleSaveDraft} loading={saving} disabled={isBusy}>Save as Draft</Button>
            <Button onClick={handleSaveAndSend} loading={sendingAndSaving} disabled={isBusy}>Save and Send</Button>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-6">

          {/* Customer and Quote Details — 2-column layout like InvoiceCreate */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left Column — Customer + Vehicle */}
            <div className="space-y-4">
              <CustomerSearch selectedCustomer={customer} onSelect={setCustomer} error={errors.customer} />

              {/* Vehicle (module-gated) */}
              {isEnabled('vehicles') && (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-gray-700">Vehicle</label>
                  {vehicle ? (
                    <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm">
                      <span className="font-semibold">{vehicle.rego}</span>
                      <span className="text-gray-600">{vehicle.year} {vehicle.make} {vehicle.model}</span>
                      <button type="button" onClick={() => { setVehicle(null); setVehicleRego('') }}
                        className="ml-auto text-gray-400 hover:text-gray-600" aria-label="Clear vehicle">✕</button>
                    </div>
                  ) : (
                    <div>
                      <div className="flex gap-2">
                        <input type="text" value={vehicleRego} onChange={(e) => setVehicleRego(e.target.value.toUpperCase())}
                          onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), lookupVehicle())}
                          placeholder="e.g. ABC123"
                          className="w-40 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                        <Button size="sm" onClick={lookupVehicle} loading={vehicleLookupLoading}>Lookup</Button>
                      </div>
                      {vehicleLookupError && <p className="mt-1 text-xs text-red-600">{vehicleLookupError}</p>}
                    </div>
                  )}
                </div>
              )}

              {/* Project (module-gated) */}
              {projectsEnabled && customer && (
                <div className="space-y-1">
                  <label className="text-sm font-medium text-gray-700">Project</label>
                  <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="">Select a project</option>
                    {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
              )}
            </div>

            {/* Right Column — Quote details */}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-sm font-medium text-gray-700">Quote Date</label>
                  <input type="date" value={quoteDate} disabled
                    className="w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500" />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium text-gray-700">Expiry Date</label>
                  <div className="rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">
                    {expiryDate}
                  </div>
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium text-gray-700">Valid For</label>
                <select value={validityDays} onChange={(e) => setValidityDays(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {VALIDITY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Subject — full width like InvoiceCreate */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Subject</label>
            <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)}
              placeholder="Let your customer know what this quote is for"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {/* Item Table — matches InvoiceCreate layout */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-3">Item Table</h3>
            {errors.lineItems && <p className="text-sm text-red-600 mb-2">{errors.lineItems}</p>}

            <div className="overflow-visible border border-gray-200 rounded-lg">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <th className="py-3 px-2">Item Details</th>
                    <th className="py-3 px-2 w-24">Quantity</th>
                    <th className="py-3 px-2 w-32">Rate</th>
                    <th className="py-3 px-2 w-36">Tax</th>
                    <th className="py-3 px-2 w-28 text-right">Amount</th>
                    <th className="py-3 px-2 w-12"></th>
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((item, index) => (
                    <ItemTableRow
                      key={item.key}
                      item={item}
                      index={index}
                      catalogueItems={catalogueItems}
                      taxRates={taxRates}
                      onChange={updateLineItem}
                      onRemove={removeLineItem}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex gap-3 mt-3">
              <Button variant="secondary" size="sm" onClick={addLineItem}>+ Add New Row</Button>
            </div>
          </div>

          {/* Totals Section — matches InvoiceCreate exactly */}
          <div className="flex justify-end">
            <div className="w-full max-w-sm space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Sub Total</span>
                <span className="font-medium text-gray-900">{formatNZD(subTotal)}</span>
              </div>

              {/* Discount */}
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-gray-600">Discount</span>
                <div className="flex items-center gap-2">
                  <div className="inline-flex rounded-md border border-gray-300 overflow-hidden">
                    <button type="button" onClick={() => setDiscountType('percentage')}
                      className={`min-w-[36px] px-2.5 py-1.5 text-sm font-medium text-center transition-colors ${discountType === 'percentage' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                      %
                    </button>
                    <button type="button" onClick={() => setDiscountType('fixed')}
                      className={`min-w-[36px] px-2.5 py-1.5 text-sm font-medium text-center border-l border-gray-300 transition-colors ${discountType === 'fixed' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                      $
                    </button>
                  </div>
                  <input type="number" min="0" step={discountType === 'percentage' ? '1' : '0.01'}
                    value={discountValue}
                    onChange={(e) => setDiscountValue(Math.max(0, Number(e.target.value) || 0))}
                    className="w-24 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
                </div>
              </div>
              {discountAmount > 0 && (
                <div className="flex justify-between text-sm text-red-600">
                  <span></span>
                  <span>-{formatNZD(discountAmount)}</span>
                </div>
              )}

              {/* Tax */}
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">GST (15%)</span>
                <span className="text-gray-900">{formatNZD(taxAmount)}</span>
              </div>

              {/* Shipping */}
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-gray-600">Shipping Charges</span>
                <input type="number" min="0" step="0.01" value={shippingCharges}
                  onChange={(e) => setShippingCharges(Math.max(0, Number(e.target.value) || 0))}
                  className="w-24 rounded border border-gray-300 px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              {/* Adjustment */}
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-gray-600">Adjustment</span>
                <input type="number" step="0.01" value={adjustment}
                  onChange={(e) => setAdjustment(Number(e.target.value) || 0)}
                  className="w-24 rounded border border-gray-300 px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              {/* Total */}
              <div className="flex justify-between text-base font-semibold border-t border-gray-200 pt-3">
                <span className="text-gray-900">Total (NZD)</span>
                <span className="text-gray-900">{formatNZD(total)}</span>
              </div>
            </div>
          </div>

          {/* Customer Notes — full width like InvoiceCreate */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Customer Notes</label>
            <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Enter any notes to be displayed in your transaction"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {/* Terms & Conditions — full width like InvoiceCreate */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Terms & Conditions</label>
            <textarea rows={3} value={terms} onChange={(e) => setTerms(e.target.value)}
              placeholder="Enter the terms and conditions of your business to be displayed in your transaction"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {/* Submit Error */}
          {errors.submit && (
            <p className="text-sm text-red-600" role="alert">{errors.submit}</p>
          )}

          {/* Bottom Actions — matches InvoiceCreate */}
          <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
            <Button variant="secondary" onClick={handleCancel} disabled={isBusy}>Cancel</Button>
            <Button variant="secondary" onClick={handleSaveDraft} loading={saving} disabled={isBusy}>Save as Draft</Button>
            <Button onClick={handleSaveAndSend} loading={sendingAndSaving} disabled={isBusy}>Save and Send</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
