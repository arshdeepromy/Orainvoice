import { useState, useCallback, useEffect, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner } from '../../components/ui'

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
  body_type: string
  fuel_type: string
  engine_size: string
  wof_expiry: string | null
  registration_expiry: string | null
}

interface CatalogueService {
  id: string
  name: string
  default_price: number
  gst_applicable: boolean
  category: string
}

interface LabourRate {
  id: string
  name: string
  hourly_rate: number
}

type LineItemType = 'service' | 'part' | 'labour'
type DiscountType = 'percentage' | 'fixed'

interface LineItem {
  key: string
  type: LineItemType
  description: string
  service_id?: string
  part_number?: string
  quantity: number
  unit_price: number
  hours?: number
  hourly_rate?: number
  labour_rate_id?: string
  gst_exempt: boolean
  discount_type: DiscountType
  discount_value: number
  warranty_note: string
}

interface InvoiceLevelDiscount {
  type: DiscountType
  value: number
}

interface FormErrors {
  customer?: string
  vehicle?: string
  lineItems?: string
  [key: string]: string | undefined
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const GST_RATE = 0.15

function calcLineTotal(item: LineItem): number {
  let base: number
  if (item.type === 'labour') {
    base = (item.hours ?? 0) * (item.hourly_rate ?? 0)
  } else {
    base = item.quantity * item.unit_price
  }
  // Apply per-line discount
  if (item.discount_value > 0) {
    if (item.discount_type === 'percentage') {
      base = base * (1 - item.discount_value / 100)
    } else {
      base = Math.max(0, base - item.discount_value)
    }
  }
  return Math.round(base * 100) / 100
}

function calcTotals(
  items: LineItem[],
  invoiceDiscount: InvoiceLevelDiscount,
) {
  let subtotalExGst = 0
  let gstAmount = 0

  for (const item of items) {
    const lineTotal = calcLineTotal(item)
    subtotalExGst += lineTotal
    if (!item.gst_exempt) {
      gstAmount += lineTotal * GST_RATE
    }
  }

  // Apply invoice-level discount to subtotal
  if (invoiceDiscount.value > 0) {
    let discountAmount: number
    if (invoiceDiscount.type === 'percentage') {
      discountAmount = subtotalExGst * (invoiceDiscount.value / 100)
    } else {
      discountAmount = invoiceDiscount.value
    }
    // Proportionally reduce GST as well
    const ratio = discountAmount / (subtotalExGst || 1)
    subtotalExGst = Math.max(0, subtotalExGst - discountAmount)
    gstAmount = Math.max(0, gstAmount * (1 - ratio))
  }

  subtotalExGst = Math.round(subtotalExGst * 100) / 100
  gstAmount = Math.round(gstAmount * 100) / 100
  const totalInclGst = Math.round((subtotalExGst + gstAmount) * 100) / 100

  return { subtotalExGst, gstAmount, totalInclGst }
}

function newLineItem(type: LineItemType): LineItem {
  return {
    key: crypto.randomUUID(),
    type,
    description: '',
    quantity: type === 'labour' ? 0 : 1,
    unit_price: 0,
    hours: type === 'labour' ? 0 : undefined,
    hourly_rate: type === 'labour' ? 0 : undefined,
    gst_exempt: false,
    discount_type: 'percentage',
    discount_value: 0,
    warranty_note: '',
  }
}

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
  }).format(amount)
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
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
  const [showCreateForm, setShowCreateForm] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  // Inline create form state
  const [newFirst, setNewFirst] = useState('')
  const [newLast, setNewLast] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [newPhone, setNewPhone] = useState('')
  const [newAddress, setNewAddress] = useState('')
  const [creating, setCreating] = useState(false)
  const [createErrors, setCreateErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const search = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([])
      return
    }
    setLoading(true)
    try {
      const res = await apiClient.get<Customer[]>('/customers', { params: { search: q } })
      setResults(res.data)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleInputChange = (value: string) => {
    setQuery(value)
    setShowDropdown(true)
    setShowCreateForm(false)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(value), 300)
  }

  const handleSelect = (c: Customer) => {
    onSelect(c)
    setQuery(`${c.first_name} ${c.last_name}`)
    setShowDropdown(false)
  }

  const handleClear = () => {
    onSelect(null)
    setQuery('')
    setResults([])
  }

  const validateCreate = (): boolean => {
    const errs: Record<string, string> = {}
    if (!newFirst.trim()) errs.first_name = 'First name is required'
    if (!newLast.trim()) errs.last_name = 'Last name is required'
    if (!newPhone.trim() && !newEmail.trim()) errs.contact = 'Phone or email is required'
    if (newEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newEmail)) errs.email = 'Invalid email format'
    setCreateErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleCreate = async () => {
    if (!validateCreate()) return
    setCreating(true)
    try {
      const res = await apiClient.post<Customer>('/customers', {
        first_name: newFirst.trim(),
        last_name: newLast.trim(),
        email: newEmail.trim() || undefined,
        phone: newPhone.trim() || undefined,
        address: newAddress.trim() || undefined,
      })
      onSelect(res.data)
      setQuery(`${res.data.first_name} ${res.data.last_name}`)
      setShowCreateForm(false)
      setShowDropdown(false)
      setNewFirst('')
      setNewLast('')
      setNewEmail('')
      setNewPhone('')
      setNewAddress('')
    } catch {
      setCreateErrors({ submit: 'Failed to create customer. Please try again.' })
    } finally {
      setCreating(false)
    }
  }

  if (selectedCustomer) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Customer</label>
        <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2">
          <span className="flex-1 text-gray-900">
            {selectedCustomer.first_name} {selectedCustomer.last_name}
            {selectedCustomer.phone && <span className="ml-2 text-gray-500">· {selectedCustomer.phone}</span>}
            {selectedCustomer.email && <span className="ml-2 text-gray-500">· {selectedCustomer.email}</span>}
          </span>
          <button
            type="button"
            onClick={handleClear}
            className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Change customer"
          >
            ✕
          </button>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative flex flex-col gap-1">
      <Input
        label="Customer"
        placeholder="Search by name, phone, or email…"
        value={query}
        onChange={(e) => handleInputChange(e.target.value)}
        onFocus={() => query.length >= 2 && setShowDropdown(true)}
        error={error}
        autoComplete="off"
      />
      {showDropdown && (
        <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-64 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
          {loading && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500">
              <Spinner size="sm" /> Searching…
            </div>
          )}
          {!loading && results.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => handleSelect(c)}
              className="w-full px-4 py-3 text-left hover:bg-gray-50 focus-visible:bg-gray-50 focus-visible:outline-none min-h-[44px]"
            >
              <span className="font-medium text-gray-900">{c.first_name} {c.last_name}</span>
              <span className="ml-2 text-sm text-gray-500">{c.phone}</span>
              <span className="ml-2 text-sm text-gray-500">{c.email}</span>
            </button>
          ))}
          {!loading && query.length >= 2 && results.length === 0 && !showCreateForm && (
            <div className="px-4 py-3 text-sm text-gray-500">No customers found</div>
          )}
          <button
            type="button"
            onClick={() => setShowCreateForm(true)}
            className="w-full border-t border-gray-100 px-4 py-3 text-left text-sm font-medium text-blue-600 hover:bg-blue-50 focus-visible:bg-blue-50 focus-visible:outline-none min-h-[44px]"
          >
            + Create new customer
          </button>
          {showCreateForm && (
            <div className="border-t border-gray-100 p-4 space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Input label="First name" value={newFirst} onChange={(e) => setNewFirst(e.target.value)} error={createErrors.first_name} />
                <Input label="Last name" value={newLast} onChange={(e) => setNewLast(e.target.value)} error={createErrors.last_name} />
              </div>
              <Input label="Email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} error={createErrors.email} />
              <Input label="Phone" type="tel" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} error={createErrors.contact} />
              <Input label="Address (optional)" value={newAddress} onChange={(e) => setNewAddress(e.target.value)} />
              {createErrors.submit && <p className="text-sm text-red-600" role="alert">{createErrors.submit}</p>}
              <div className="flex gap-2">
                <Button size="sm" onClick={handleCreate} loading={creating}>Create &amp; select</Button>
                <Button size="sm" variant="secondary" onClick={() => setShowCreateForm(false)}>Cancel</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function VehicleRegoLookup({
  vehicle,
  onVehicleFound,
  error,
}: {
  vehicle: Vehicle | null
  onVehicleFound: (v: Vehicle | null) => void
  error?: string
}) {
  const [rego, setRego] = useState('')
  const [loading, setLoading] = useState(false)
  const [lookupError, setLookupError] = useState('')

  const lookup = async () => {
    const cleaned = rego.trim().toUpperCase()
    if (!cleaned) return
    setLoading(true)
    setLookupError('')
    try {
      const res = await apiClient.get<Vehicle>(`/vehicles/lookup/${encodeURIComponent(cleaned)}`)
      onVehicleFound(res.data)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        setLookupError('Vehicle not found. You can enter details manually.')
      } else {
        setLookupError('Lookup failed. Please try again.')
      }
      onVehicleFound(null)
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      lookup()
    }
  }

  if (vehicle) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Vehicle</label>
        <div className="rounded-md border border-gray-300 bg-gray-50 p-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-semibold text-gray-900">{vehicle.rego}</span>
              <span className="ml-2 text-gray-700">
                {vehicle.year} {vehicle.make} {vehicle.model}
              </span>
              {vehicle.colour && <span className="ml-2 text-gray-500">· {vehicle.colour}</span>}
            </div>
            <button
              type="button"
              onClick={() => { onVehicleFound(null); setRego('') }}
              className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Change vehicle"
            >
              ✕
            </button>
          </div>
          {vehicle.body_type && (
            <div className="mt-1 text-sm text-gray-500">
              {vehicle.body_type} · {vehicle.fuel_type} · {vehicle.engine_size}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">Vehicle registration</label>
      <div className="flex gap-2">
        <input
          type="text"
          value={rego}
          onChange={(e) => setRego(e.target.value.toUpperCase())}
          onKeyDown={handleKeyDown}
          placeholder="e.g. ABC123"
          className={`flex-1 rounded-md border px-3 py-2 text-gray-900 shadow-sm transition-colors
            placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
            ${error || lookupError ? 'border-red-500' : 'border-gray-300'}`}
          aria-label="Vehicle registration number"
          aria-invalid={!!(error || lookupError)}
        />
        <Button onClick={lookup} loading={loading} size="md">
          Lookup
        </Button>
      </div>
      {(error || lookupError) && (
        <p className="text-sm text-red-600" role="alert">{error || lookupError}</p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Line Item Row                                                      */
/* ------------------------------------------------------------------ */

function LineItemRow({
  item,
  index,
  services,
  labourRates,
  onChange,
  onRemove,
}: {
  item: LineItem
  index: number
  services: CatalogueService[]
  labourRates: LabourRate[]
  onChange: (index: number, updated: LineItem) => void
  onRemove: (index: number) => void
}) {
  const update = (patch: Partial<LineItem>) => onChange(index, { ...item, ...patch })

  const handleServiceSelect = (serviceId: string) => {
    const svc = services.find((s) => s.id === serviceId)
    if (svc) {
      update({
        service_id: svc.id,
        description: svc.name,
        unit_price: svc.default_price,
        gst_exempt: !svc.gst_applicable,
      })
    }
  }

  const handleLabourRateSelect = (rateId: string) => {
    const rate = labourRates.find((r) => r.id === rateId)
    if (rate) {
      update({
        labour_rate_id: rate.id,
        description: rate.name,
        hourly_rate: rate.hourly_rate,
      })
    }
  }

  const lineTotal = calcLineTotal(item)

  return (
    <div className="rounded-md border border-gray-200 bg-white p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-500">
          {item.type === 'service' ? 'Service' : item.type === 'part' ? 'Part' : 'Labour'} #{index + 1}
        </span>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="rounded p-1 text-gray-400 hover:text-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label={`Remove line item ${index + 1}`}
        >
          ✕
        </button>
      </div>

      {/* Type-specific fields */}
      {item.type === 'service' && (
        <Select
          label="Service"
          options={services.map((s) => ({ value: s.id, label: `${s.name} — ${formatNZD(s.default_price)}` }))}
          value={item.service_id || ''}
          onChange={(e) => handleServiceSelect(e.target.value)}
          placeholder="Select a service…"
        />
      )}

      <Input
        label="Description"
        value={item.description}
        onChange={(e) => update({ description: e.target.value })}
        placeholder={item.type === 'service' ? 'Auto-filled from catalogue' : 'Describe the item…'}
      />

      {item.type === 'part' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input
            label="Part number"
            value={item.part_number || ''}
            onChange={(e) => update({ part_number: e.target.value })}
            placeholder="Optional"
          />
          <Input
            label="Quantity"
            type="number"
            min="1"
            step="1"
            value={String(item.quantity)}
            onChange={(e) => update({ quantity: Math.max(1, Number(e.target.value) || 1) })}
          />
          <Input
            label="Unit price (ex-GST)"
            type="number"
            min="0"
            step="0.01"
            value={String(item.unit_price)}
            onChange={(e) => update({ unit_price: Math.max(0, Number(e.target.value) || 0) })}
          />
        </div>
      )}

      {item.type === 'service' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input
            label="Quantity"
            type="number"
            min="1"
            step="1"
            value={String(item.quantity)}
            onChange={(e) => update({ quantity: Math.max(1, Number(e.target.value) || 1) })}
          />
          <Input
            label="Unit price (ex-GST)"
            type="number"
            min="0"
            step="0.01"
            value={String(item.unit_price)}
            onChange={(e) => update({ unit_price: Math.max(0, Number(e.target.value) || 0) })}
          />
        </div>
      )}

      {item.type === 'labour' && (
        <>
          <Select
            label="Labour rate"
            options={labourRates.map((r) => ({ value: r.id, label: `${r.name} — ${formatNZD(r.hourly_rate)}/hr` }))}
            value={item.labour_rate_id || ''}
            onChange={(e) => handleLabourRateSelect(e.target.value)}
            placeholder="Select a rate…"
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Input
              label="Hours"
              type="number"
              min="0"
              step="0.25"
              value={String(item.hours ?? 0)}
              onChange={(e) => update({ hours: Math.max(0, Number(e.target.value) || 0) })}
            />
            <Input
              label="Hourly rate"
              type="number"
              min="0"
              step="0.01"
              value={String(item.hourly_rate ?? 0)}
              onChange={(e) => update({ hourly_rate: Math.max(0, Number(e.target.value) || 0) })}
            />
          </div>
        </>
      )}

      {/* Discount, GST-exempt, warranty */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Select
          label="Discount type"
          options={[
            { value: 'percentage', label: 'Percentage (%)' },
            { value: 'fixed', label: 'Fixed ($)' },
          ]}
          value={item.discount_type}
          onChange={(e) => update({ discount_type: e.target.value as DiscountType })}
        />
        <Input
          label={item.discount_type === 'percentage' ? 'Discount (%)' : 'Discount ($)'}
          type="number"
          min="0"
          step={item.discount_type === 'percentage' ? '1' : '0.01'}
          value={String(item.discount_value)}
          onChange={(e) => update({ discount_value: Math.max(0, Number(e.target.value) || 0) })}
        />
        <div className="flex items-end pb-1">
          <label className="flex items-center gap-2 min-h-[44px] cursor-pointer">
            <input
              type="checkbox"
              checked={item.gst_exempt}
              onChange={(e) => update({ gst_exempt: e.target.checked })}
              className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-gray-700">GST exempt</span>
          </label>
        </div>
      </div>

      <Input
        label="Warranty note (optional)"
        value={item.warranty_note}
        onChange={(e) => update({ warranty_note: e.target.value })}
        placeholder="e.g. 12-month warranty on parts and labour"
      />

      <div className="text-right text-sm font-medium text-gray-700">
        Line total: <span className="text-gray-900">{formatNZD(lineTotal)}</span>
        {item.gst_exempt && <span className="ml-1 text-gray-500">(GST exempt)</span>}
      </div>
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function InvoiceCreate() {
  /* --- State --- */
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [lineItems, setLineItems] = useState<LineItem[]>([])
  const [invoiceDiscount, setInvoiceDiscount] = useState<InvoiceLevelDiscount>({
    type: 'percentage',
    value: 0,
  })
  const [notes, setNotes] = useState('')

  const [services, setServices] = useState<CatalogueService[]>([])
  const [labourRates, setLabourRates] = useState<LabourRate[]>([])
  const [catalogueLoading, setCatalogueLoading] = useState(true)

  const [saving, setSaving] = useState(false)
  const [issuing, setIssuing] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

  /* --- Load catalogue data --- */
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [svcRes, rateRes] = await Promise.all([
          apiClient.get<CatalogueService[]>('/catalogue/services', { params: { active: true } }),
          apiClient.get<LabourRate[]>('/catalogue/labour-rates'),
        ])
        if (!cancelled) {
          setServices(svcRes.data)
          setLabourRates(rateRes.data)
        }
      } catch {
        // Catalogue load failure is non-blocking — user can still add parts/labour manually
      } finally {
        if (!cancelled) setCatalogueLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  /* --- Totals (auto-calculated) --- */
  const { subtotalExGst, gstAmount, totalInclGst } = calcTotals(lineItems, invoiceDiscount)

  /* --- Line item management --- */
  const addLineItem = (type: LineItemType) => {
    setLineItems((prev) => [...prev, newLineItem(type)])
    // Clear line items error when adding
    if (errors.lineItems) {
      setErrors((prev) => { const { lineItems: _, ...rest } = prev; return rest })
    }
  }

  const updateLineItem = (index: number, updated: LineItem) => {
    setLineItems((prev) => prev.map((item, i) => (i === index ? updated : item)))
  }

  const removeLineItem = (index: number) => {
    setLineItems((prev) => prev.filter((_, i) => i !== index))
  }

  /* --- Validation --- */
  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!customer) errs.customer = 'Please select or create a customer'
    if (lineItems.length === 0) errs.lineItems = 'Add at least one line item'
    // Check each line item has a description
    for (let i = 0; i < lineItems.length; i++) {
      const item = lineItems[i]
      if (!item.description.trim()) {
        errs[`line_${i}_description`] = `Line item ${i + 1}: description is required`
      }
      if (item.type === 'labour' && (!item.hours || item.hours <= 0)) {
        errs[`line_${i}_hours`] = `Line item ${i + 1}: hours must be greater than 0`
      }
      if (item.type === 'labour' && (!item.hourly_rate || item.hourly_rate <= 0)) {
        errs[`line_${i}_rate`] = `Line item ${i + 1}: hourly rate is required`
      }
      if (item.type !== 'labour' && item.unit_price <= 0) {
        errs[`line_${i}_price`] = `Line item ${i + 1}: unit price must be greater than 0`
      }
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  /* --- Build payload --- */
  const buildPayload = () => ({
    customer_id: customer?.id,
    vehicle_id: vehicle?.id,
    notes,
    discount_type: invoiceDiscount.type,
    discount_value: invoiceDiscount.value,
    line_items: lineItems.map((item) => ({
      type: item.type,
      description: item.description,
      service_id: item.service_id,
      part_number: item.part_number,
      quantity: item.type === 'labour' ? undefined : item.quantity,
      unit_price: item.type === 'labour' ? undefined : item.unit_price,
      hours: item.hours,
      hourly_rate: item.hourly_rate,
      labour_rate_id: item.labour_rate_id,
      gst_exempt: item.gst_exempt,
      discount_type: item.discount_type,
      discount_value: item.discount_value,
      warranty_note: item.warranty_note || undefined,
    })),
  })

  /* --- Save as Draft --- */
  const handleSaveDraft = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      await apiClient.post('/invoices', { ...buildPayload(), status: 'draft' })
      // Navigate to invoice list or show success — for now, reset form
      window.location.href = '/invoices'
    } catch {
      setErrors({ submit: 'Failed to save draft. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  /* --- Issue Invoice --- */
  const handleIssue = async () => {
    if (!validate()) return
    setIssuing(true)
    try {
      await apiClient.post('/invoices', { ...buildPayload(), status: 'issued' })
      window.location.href = '/invoices'
    } catch {
      setErrors({ submit: 'Failed to issue invoice. Please try again.' })
    } finally {
      setIssuing(false)
    }
  }

  /* --- Collect line-item-level errors for display --- */
  const lineItemErrors = Object.entries(errors)
    .filter(([key]) => key.startsWith('line_'))
    .map(([, msg]) => msg)
    .filter(Boolean) as string[]

  /* --- Render --- */
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Create Invoice</h1>

      {/* Two-column on md+, single-column on mobile */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-[1fr_320px]">
        {/* ---- Left column: main form ---- */}
        <div className="space-y-6">
          {/* Customer */}
          <section aria-labelledby="section-customer">
            <h2 id="section-customer" className="sr-only">Customer</h2>
            <CustomerSearch
              selectedCustomer={customer}
              onSelect={setCustomer}
              error={errors.customer}
            />
          </section>

          {/* Vehicle */}
          <section aria-labelledby="section-vehicle">
            <h2 id="section-vehicle" className="sr-only">Vehicle</h2>
            <VehicleRegoLookup
              vehicle={vehicle}
              onVehicleFound={setVehicle}
              error={errors.vehicle}
            />
          </section>

          {/* Line Items */}
          <section aria-labelledby="section-line-items">
            <h2 id="section-line-items" className="text-lg font-medium text-gray-900 mb-3">
              Line Items
            </h2>

            {lineItems.length === 0 && (
              <p className="text-sm text-gray-500 mb-3">No line items yet. Add a service, part, or labour entry below.</p>
            )}

            {errors.lineItems && (
              <p className="text-sm text-red-600 mb-3" role="alert">{errors.lineItems}</p>
            )}

            <div className="space-y-4">
              {lineItems.map((item, i) => (
                <LineItemRow
                  key={item.key}
                  item={item}
                  index={i}
                  services={services}
                  labourRates={labourRates}
                  onChange={updateLineItem}
                  onRemove={removeLineItem}
                />
              ))}
            </div>

            {/* Line item validation errors */}
            {lineItemErrors.length > 0 && (
              <div className="mt-3 space-y-1">
                {lineItemErrors.map((msg, i) => (
                  <p key={i} className="text-sm text-red-600" role="alert">{msg}</p>
                ))}
              </div>
            )}

            {/* Add line item buttons — large touch targets on mobile */}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="md"
                onClick={() => addLineItem('service')}
                disabled={catalogueLoading}
                className="min-h-[44px]"
              >
                + Service
              </Button>
              <Button
                variant="secondary"
                size="md"
                onClick={() => addLineItem('part')}
                className="min-h-[44px]"
              >
                + Part
              </Button>
              <Button
                variant="secondary"
                size="md"
                onClick={() => addLineItem('labour')}
                disabled={catalogueLoading}
                className="min-h-[44px]"
              >
                + Labour
              </Button>
            </div>
          </section>

          {/* Notes */}
          <section aria-labelledby="section-notes">
            <h2 id="section-notes" className="sr-only">Notes</h2>
            <div className="flex flex-col gap-1">
              <label htmlFor="invoice-notes" className="text-sm font-medium text-gray-700">
                Notes (optional)
              </label>
              <textarea
                id="invoice-notes"
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Internal notes or customer-facing message…"
                className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
                  placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </section>
        </div>

        {/* ---- Right column: totals & actions (sticky on desktop) ---- */}
        <aside className="md:sticky md:top-6 md:self-start">
          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm space-y-4">
            <h2 className="text-lg font-medium text-gray-900">Summary</h2>

            {/* Invoice-level discount */}
            <div className="space-y-2">
              <p className="text-sm font-medium text-gray-700">Invoice discount</p>
              <div className="grid grid-cols-2 gap-2">
                <Select
                  label=""
                  options={[
                    { value: 'percentage', label: '%' },
                    { value: 'fixed', label: '$' },
                  ]}
                  value={invoiceDiscount.type}
                  onChange={(e) =>
                    setInvoiceDiscount((prev) => ({ ...prev, type: e.target.value as DiscountType }))
                  }
                />
                <input
                  type="number"
                  min="0"
                  step={invoiceDiscount.type === 'percentage' ? '1' : '0.01'}
                  value={String(invoiceDiscount.value)}
                  onChange={(e) =>
                    setInvoiceDiscount((prev) => ({
                      ...prev,
                      value: Math.max(0, Number(e.target.value) || 0),
                    }))
                  }
                  className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
                    focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  aria-label={invoiceDiscount.type === 'percentage' ? 'Discount percentage' : 'Discount amount'}
                />
              </div>
            </div>

            {/* Totals */}
            <div className="border-t border-gray-100 pt-4 space-y-2">
              <div className="flex justify-between text-sm text-gray-600">
                <span>Subtotal (ex-GST)</span>
                <span>{formatNZD(subtotalExGst)}</span>
              </div>
              <div className="flex justify-between text-sm text-gray-600">
                <span>GST (15%)</span>
                <span>{formatNZD(gstAmount)}</span>
              </div>
              <div className="flex justify-between text-base font-semibold text-gray-900 border-t border-gray-200 pt-2">
                <span>Total (incl. GST)</span>
                <span>{formatNZD(totalInclGst)}</span>
              </div>
            </div>

            {/* Submit error */}
            {errors.submit && (
              <p className="text-sm text-red-600" role="alert">{errors.submit}</p>
            )}

            {/* Action buttons — large touch targets */}
            <div className="space-y-2 pt-2">
              <Button
                variant="primary"
                size="lg"
                className="w-full min-h-[48px]"
                onClick={handleIssue}
                loading={issuing}
                disabled={saving}
              >
                Issue Invoice
              </Button>
              <Button
                variant="secondary"
                size="lg"
                className="w-full min-h-[48px]"
                onClick={handleSaveDraft}
                loading={saving}
                disabled={issuing}
              >
                Save as Draft
              </Button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
