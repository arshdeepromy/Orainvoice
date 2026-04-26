import { useState, useCallback, useEffect, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Modal } from '../../components/ui'
import { useTenant } from '../../contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'

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
  display_name?: string
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

interface CatalogueItem {
  id: string
  name: string
  description?: string
  default_price: number
  gst_applicable: boolean
  gst_inclusive?: boolean
  category?: string
  sku?: string
}

interface LineItem {
  key: string
  catalogue_item_id: string | null
  item_type: 'service' | 'part' | 'labour'
  description: string
  quantity: number
  unit_price: number
  is_gst_exempt: boolean
}

interface FormErrors {
  customer?: string
  vehicle?: string
  items?: string
  submit?: string
  [key: string]: string | undefined
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function newLineItem(): LineItem {
  return {
    key: crypto.randomUUID(),
    catalogue_item_id: null,
    item_type: 'service',
    description: '',
    quantity: 1,
    unit_price: 0,
    is_gst_exempt: false,
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
  const [showCreateModal, setShowCreateModal] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

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
    if (q.length < 2) { setResults([]); return }
    setLoading(true)
    try {
      const res = await apiClient.get<{ customers: Customer[]; total: number } | Customer[]>('/customers', { params: { q: q } })
      const customers = Array.isArray(res.data) ? res.data : (res.data?.customers || [])
      const term = q.toLowerCase()
      const matchesSequence = (haystack: string, needle: string): boolean => {
        let ni = 0
        const h = haystack.toLowerCase()
        for (let i = 0; i < h.length && ni < needle.length; i++) {
          if (h[i] === needle[ni]) ni++
        }
        return ni === needle.length
      }
      const filtered = customers.filter((c: Customer) => {
        const firstName = (c.first_name || '').toLowerCase()
        const lastName = (c.last_name || '').toLowerCase()
        const displayName = (c.display_name || '').toLowerCase()
        const phone = (c.phone || '').toLowerCase()
        return (
          matchesSequence(firstName, term) ||
          matchesSequence(lastName, term) ||
          matchesSequence(displayName, term) ||
          matchesSequence(phone, term)
        )
      })
      setResults(filtered)
    } catch { setResults([]) }
    finally { setLoading(false) }
  }, [])

  const handleInputChange = (value: string) => {
    setQuery(value)
    setShowDropdown(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(value), 300)
  }

  const handleSelect = (c: Customer) => {
    onSelect(c)
    setQuery(`${c.first_name} ${c.last_name}`)
    setShowDropdown(false)
  }

  const handleClear = () => { onSelect(null); setQuery(''); setResults([]) }

  const resetCreateForm = () => {
    setNewFirst(''); setNewLast(''); setNewEmail(''); setNewPhone(''); setNewAddress('')
    setCreateErrors({})
  }

  const handleOpenCreateModal = () => {
    setShowDropdown(false)
    resetCreateForm()
    setShowCreateModal(true)
  }

  const handleCloseCreateModal = () => {
    setShowCreateModal(false)
    resetCreateForm()
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
        first_name: newFirst.trim(), last_name: newLast.trim(),
        email: newEmail.trim() || undefined, phone: newPhone.trim() || undefined,
        address: newAddress.trim() || undefined,
      })
      onSelect(res.data)
      setQuery(`${res.data.first_name} ${res.data.last_name}`)
      handleCloseCreateModal()
    } catch {
      setCreateErrors({ submit: 'Failed to create customer. Please try again.' })
    } finally { setCreating(false) }
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
          <button type="button" onClick={handleClear}
            className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Change customer">✕</button>
        </div>
      </div>
    )
  }

  return (
    <>
      <div ref={containerRef} className="relative flex flex-col gap-1">
        <Input label="Customer" placeholder="Search by name, phone, or email…" value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => query.length >= 2 && setShowDropdown(true)}
          error={error} autoComplete="off" />
        {showDropdown && (
          <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-64 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
            {loading && (
              <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500"><Spinner size="sm" /> Searching…</div>
            )}
            {!loading && results && results.length > 0 && results.map((c) => (
              <button key={c.id} type="button" onClick={() => handleSelect(c)}
                className="w-full px-4 py-3 text-left hover:bg-gray-50 focus-visible:bg-gray-50 focus-visible:outline-none min-h-[44px]">
                <span className="font-medium text-gray-900">{c.first_name} {c.last_name}</span>
                <span className="ml-2 text-sm text-gray-500">{c.phone}</span>
                <span className="ml-2 text-sm text-gray-500">{c.email}</span>
              </button>
            ))}
            {!loading && query.length >= 2 && results.length === 0 && (
              <div className="px-4 py-3 text-sm text-gray-500">No customers found</div>
            )}
            <button type="button" onClick={handleOpenCreateModal}
              className="w-full border-t border-gray-100 px-4 py-3 text-left text-sm font-medium text-blue-600 hover:bg-blue-50 focus-visible:bg-blue-50 focus-visible:outline-none min-h-[44px]">
              + Create new customer
            </button>
          </div>
        )}
      </div>

      <Modal open={showCreateModal} onClose={handleCloseCreateModal} title="Create New Customer" className="max-w-md">
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input label="First name" value={newFirst} onChange={(e) => setNewFirst(e.target.value)} error={createErrors.first_name} />
            <Input label="Last name" value={newLast} onChange={(e) => setNewLast(e.target.value)} error={createErrors.last_name} />
          </div>
          <Input label="Email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} error={createErrors.email} />
          <Input label="Phone" type="tel" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} error={createErrors.contact} />
          <Input label="Address (optional)" value={newAddress} onChange={(e) => setNewAddress(e.target.value)} />
          {createErrors.submit && <p className="text-sm text-red-600" role="alert">{createErrors.submit}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={handleCloseCreateModal}>Cancel</Button>
            <Button onClick={handleCreate} loading={creating}>Create &amp; Select</Button>
          </div>
        </div>
      </Modal>
    </>
  )
}

function VehicleRegoLookup({
  vehicle, onVehicleFound, error,
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
    setLoading(true); setLookupError('')
    try {
      const res = await apiClient.get<Vehicle>(`/vehicles/lookup/${encodeURIComponent(cleaned)}`)
      onVehicleFound(res.data)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setLookupError(status === 404 ? 'Vehicle not found. You can enter details manually.' : 'Lookup failed. Please try again.')
      onVehicleFound(null)
    } finally { setLoading(false) }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === 'Enter') { e.preventDefault(); lookup() } }

  if (vehicle) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Vehicle</label>
        <div className="rounded-md border border-gray-300 bg-gray-50 p-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-semibold text-gray-900">{vehicle.rego}</span>
              <span className="ml-2 text-gray-700">{vehicle.year} {vehicle.make} {vehicle.model}</span>
              {vehicle.colour && <span className="ml-2 text-gray-500">· {vehicle.colour}</span>}
            </div>
            <button type="button" onClick={() => { onVehicleFound(null); setRego('') }}
              className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Change vehicle">✕</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">Vehicle registration</label>
      <div className="flex gap-2">
        <input type="text" value={rego} onChange={(e) => setRego(e.target.value.toUpperCase())}
          onKeyDown={handleKeyDown} placeholder="e.g. ABC123"
          className={`flex-1 rounded-md border px-3 py-2 text-gray-900 shadow-sm transition-colors
            placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
            ${error || lookupError ? 'border-red-500' : 'border-gray-300'}`}
          aria-label="Vehicle registration number" aria-invalid={!!(error || lookupError)} />
        <Button onClick={lookup} loading={loading} size="md">Lookup</Button>
      </div>
      {(error || lookupError) && <p className="text-sm text-red-600" role="alert">{error || lookupError}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Line Item Row                                                      */
/* ------------------------------------------------------------------ */

function LineItemRow({
  item,
  index,
  catalogueItems,
  onChange,
  onRemove,
}: {
  item: LineItem
  index: number
  catalogueItems: CatalogueItem[]
  onChange: (index: number, updated: LineItem) => void
  onRemove: (index: number) => void
}) {
  const [showItemDropdown, setShowItemDropdown] = useState(false)
  const [itemSearch, setItemSearch] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowItemDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const update = (patch: Partial<LineItem>) => {
    const updated = { ...item, ...patch }
    onChange(index, updated)
  }

  const handleItemSelect = (catalogueItem: CatalogueItem) => {
    const isGstExempt = !catalogueItem.gst_applicable
    update({
      catalogue_item_id: catalogueItem.id,
      description: catalogueItem.name,
      unit_price: catalogueItem.default_price,
      is_gst_exempt: isGstExempt,
    })
    setShowItemDropdown(false)
    setItemSearch('')
  }

  const filteredItems = (Array.isArray(catalogueItems) ? catalogueItems : []).filter(ci =>
    ci.name.toLowerCase().includes(itemSearch.toLowerCase())
  )

  const lineAmount = Math.round(item.quantity * item.unit_price * 100) / 100

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 align-top">
      {/* Item Details */}
      <td className="py-3 px-2">
        <div ref={containerRef} className="relative">
          <input
            type="text"
            value={item.description}
            onChange={(e) => {
              update({ description: e.target.value, catalogue_item_id: null })
              setItemSearch(e.target.value)
            }}
            onFocus={() => setShowItemDropdown(true)}
            placeholder="Type or search catalogue items"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label={`Line item ${index + 1} description`}
          />
          {showItemDropdown && (
            <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
              {filteredItems.slice(0, 10).map((ci) => (
                <button
                  key={ci.id}
                  type="button"
                  onClick={() => handleItemSelect(ci)}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50"
                >
                  <div className="font-medium text-gray-900">{ci.name}</div>
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
      {/* Quantity */}
      <td className="py-3 px-2 w-24">
        <input
          type="number"
          min="1"
          step="1"
          value={item.quantity}
          onChange={(e) => update({ quantity: Math.max(1, Number(e.target.value) || 1) })}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label={`Line item ${index + 1} quantity`}
        />
      </td>
      {/* Rate */}
      <td className="py-3 px-2 w-32">
        <input
          type="number"
          min="0"
          step="0.01"
          value={item.unit_price}
          onChange={(e) => update({ unit_price: Math.max(0, Number(e.target.value) || 0) })}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label={`Line item ${index + 1} rate`}
        />
      </td>
      {/* Amount (read-only) */}
      <td className="py-3 px-2 w-28 text-right text-sm font-medium text-gray-900">
        {formatNZD(lineAmount)}
      </td>
      {/* Remove */}
      <td className="py-3 px-2 w-12">
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="rounded p-1 text-gray-400 hover:text-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label={`Remove line item ${index + 1}`}
        >
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

export default function JobCardCreate() {
  const { tradeFamily } = useTenant()
  const { selectedBranchId } = useBranch()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const [customer, setCustomer] = useState<Customer | null>(null)
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [description, setDescription] = useState('')
  const [lineItems, setLineItems] = useState<LineItem[]>([newLineItem()])
  const [notes, setNotes] = useState('')

  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

  /* --- Catalogue data --- */
  const [catalogueItems, setCatalogueItems] = useState<CatalogueItem[]>([])

  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get<CatalogueItem[] | { items: CatalogueItem[] }>('/catalogue/items', {
        params: { active_only: true },
        signal: controller.signal,
      })
      .then((res) => {
        const items = res.data
        const rawItems = Array.isArray(items) ? items : (items?.items ?? [])
        setCatalogueItems(
          rawItems.map((item: CatalogueItem & { default_price?: number | string; is_gst_exempt?: boolean }) => ({
            id: item.id,
            name: item.name,
            description: item.description ?? undefined,
            default_price:
              typeof item.default_price === 'string'
                ? parseFloat(item.default_price)
                : (item.default_price ?? 0),
            gst_applicable: item.gst_applicable ?? (item.is_gst_exempt === false),
            gst_inclusive: item.gst_inclusive ?? false,
            category: item.category ?? undefined,
            sku: item.sku ?? undefined,
          }))
        )
      })
      .catch(() => {
        if (!controller.signal.aborted) setCatalogueItems([])
      })
    return () => controller.abort()
  }, [])

  /* --- Line item management --- */
  const addLineItem = () => {
    setLineItems((prev) => [...prev, newLineItem()])
    if (errors.items) {
      setErrors((prev) => {
        const { items: _, ...rest } = prev
        return rest
      })
    }
  }

  const updateLineItem = (index: number, updated: LineItem) => {
    setLineItems((prev) => prev.map((item, i) => (i === index ? updated : item)))
  }

  const removeLineItem = (index: number) => {
    setLineItems((prev) => {
      const next = prev.filter((_, i) => i !== index)
      return next.length === 0 ? [newLineItem()] : next
    })
  }

  /* --- Subtotal --- */
  const subtotal = lineItems.reduce(
    (sum, li) => sum + Math.round(li.quantity * li.unit_price * 100) / 100,
    0
  )

  /* --- Validation --- */
  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!customer) errs.customer = 'Please select or create a customer'
    const filledItems = lineItems.filter((li) => li.description.trim())
    if (filledItems.length === 0) errs.items = 'Add at least one line item with a description'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  /* --- Save --- */
  const handleSave = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      const line_items = lineItems
        .filter((li) => li.description.trim())
        .map((li, i) => ({
          item_type: li.item_type,
          description: li.description.trim(),
          quantity: li.quantity,
          unit_price: li.unit_price,
          is_gst_exempt: li.is_gst_exempt,
          sort_order: i,
          ...(li.catalogue_item_id ? { catalogue_item_id: li.catalogue_item_id } : {}),
        }))

      await apiClient.post('/job-cards', {
        customer_id: customer?.id,
        branch_id: selectedBranchId || undefined,
        ...(isAutomotive && vehicle?.id ? { vehicle_id: vehicle.id } : {}),
        description: description.trim(),
        notes: notes.trim() || undefined,
        line_items,
      })
      window.location.href = '/job-cards'
    } catch {
      setErrors({ submit: 'Failed to create job card. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => { window.location.href = '/job-cards' }}
          className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          aria-label="Back to job cards">←</button>
        <h1 className="text-2xl font-semibold text-gray-900">Create Job Card</h1>
      </div>

      <div className="space-y-6">
        {/* Customer */}
        <section aria-labelledby="section-customer">
          <h2 id="section-customer" className="sr-only">Customer</h2>
          <CustomerSearch selectedCustomer={customer} onSelect={setCustomer} error={errors.customer} />
        </section>

        {/* Vehicle */}
        {isAutomotive && (
        <section aria-labelledby="section-vehicle">
          <h2 id="section-vehicle" className="sr-only">Vehicle</h2>
          <VehicleRegoLookup vehicle={vehicle} onVehicleFound={setVehicle} error={errors.vehicle} />
        </section>
        )}

        {/* Description */}
        <div>
          <Input label="Job description" placeholder="Brief summary of the job…" value={description}
            onChange={(e) => setDescription(e.target.value)} />
        </div>

        {/* Line Items */}
        <section aria-labelledby="section-line-items">
          <h2 id="section-line-items" className="text-lg font-medium text-gray-900 mb-3">Line Items</h2>

          {errors.items && <p className="text-sm text-red-600 mb-3" role="alert">{errors.items}</p>}

          <div className="overflow-visible">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  <th className="py-2 px-2">Item Details</th>
                  <th className="py-2 px-2 w-24 text-right">Qty</th>
                  <th className="py-2 px-2 w-32 text-right">Rate</th>
                  <th className="py-2 px-2 w-28 text-right">Amount</th>
                  <th className="py-2 px-2 w-12"></th>
                </tr>
              </thead>
              <tbody>
                {lineItems.map((item, index) => (
                  <LineItemRow
                    key={item.key}
                    item={item}
                    index={index}
                    catalogueItems={catalogueItems}
                    onChange={updateLineItem}
                    onRemove={removeLineItem}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-3">
            <Button size="sm" variant="secondary" onClick={addLineItem}>
              + Add Row
            </Button>
            <div className="text-sm font-medium text-gray-700">
              Subtotal: <span className="text-gray-900">{formatNZD(subtotal)}</span>
            </div>
          </div>
        </section>

        {/* Notes */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="jc-notes">Notes (optional)</label>
          <textarea id="jc-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm
              placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="Internal notes about this job…" />
        </div>

        {/* Submit error */}
        {errors.submit && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {errors.submit}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          <Button onClick={handleSave} loading={saving}>Create Job Card</Button>
          <Button variant="secondary" onClick={() => { window.location.href = '/job-cards' }}>Cancel</Button>
        </div>
      </div>
    </div>
  )
}
