/**
 * JobCardCreate — Task 27 port of frontend/src/pages/job-cards/JobCardCreate.tsx.
 *
 * ALL logic copied VERBATIM: the customer search + inline create modal, the
 * vehicle rego lookup (automotive), the plumbing ServiceTypeSelector, the
 * collapsible optional line-items table with catalogue-item autocomplete + GST
 * exemption + subtotal, notes, attachments (only after save), and the
 * create-then-attach flow (POST /job-cards → savedJobCardId → AttachmentUploader).
 * Trade-family gating (automotive vehicle / plumbing service-type) preserved.
 * Presentation remapped onto the design tokens (FR-2b); `secondary`→`ghost`.
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Spinner, Modal } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
import ServiceTypeSelector from '@/components/service-types/ServiceTypeSelector'
import type { FieldValue } from '@/components/service-types/ServiceTypeSelector'
import AttachmentUploader from '@/components/attachments/AttachmentUploader'
import type { Attachment } from '@/components/attachments/AttachmentUploader'
import AttachmentList from '@/components/attachments/AttachmentList'

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

const TABLE_INPUT_CLS = 'w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

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
        <label className="text-[12.5px] font-medium text-text">Customer</label>
        <div className="flex items-center gap-2 rounded-ctl border border-border bg-canvas px-3 py-2">
          <span className="flex-1 text-[13.5px] text-text">
            {selectedCustomer.first_name} {selectedCustomer.last_name}
            {selectedCustomer.phone && <span className="ml-2 text-muted">· {selectedCustomer.phone}</span>}
            {selectedCustomer.email && <span className="ml-2 text-muted">· {selectedCustomer.email}</span>}
          </span>
          <button type="button" onClick={handleClear}
            className="rounded p-1 text-muted-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
          <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-auto rounded-ctl border border-border bg-card shadow-pop">
            {loading && (
              <div className="flex items-center gap-2 px-4 py-3 text-[13px] text-muted"><Spinner size="sm" /> Searching…</div>
            )}
            {!loading && results && results.length > 0 && results.map((c) => (
              <button key={c.id} type="button" onClick={() => handleSelect(c)}
                className="min-h-[44px] w-full px-4 py-3 text-left hover:bg-canvas focus-visible:bg-canvas focus-visible:outline-none">
                <span className="font-medium text-text">{c.first_name} {c.last_name}</span>
                <span className="ml-2 text-[13px] text-muted">{c.phone}</span>
                <span className="ml-2 text-[13px] text-muted">{c.email}</span>
              </button>
            ))}
            {!loading && query.length >= 2 && results.length === 0 && (
              <div className="px-4 py-3 text-[13px] text-muted">No customers found</div>
            )}
            <button type="button" onClick={handleOpenCreateModal}
              className="min-h-[44px] w-full border-t border-border px-4 py-3 text-left text-[13px] font-medium text-accent hover:bg-accent-soft focus-visible:bg-accent-soft focus-visible:outline-none">
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
          {createErrors.submit && <p className="text-[13px] text-danger" role="alert">{createErrors.submit}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={handleCloseCreateModal}>Cancel</Button>
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
        <label className="text-[12.5px] font-medium text-text">Vehicle</label>
        <div className="rounded-ctl border border-border bg-canvas p-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="mono font-semibold text-text">{vehicle.rego}</span>
              <span className="ml-2 text-text">{vehicle.year} {vehicle.make} {vehicle.model}</span>
              {vehicle.colour && <span className="ml-2 text-muted">· {vehicle.colour}</span>}
            </div>
            <button type="button" onClick={() => { onVehicleFound(null); setRego('') }}
              className="rounded p-1 text-muted-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label="Change vehicle">✕</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-[12.5px] font-medium text-text">Vehicle registration</label>
      <div className="flex gap-2">
        <input type="text" value={rego} onChange={(e) => setRego(e.target.value.toUpperCase())}
          onKeyDown={handleKeyDown} placeholder="e.g. ABC123"
          className={`mono h-[42px] flex-1 rounded-ctl border bg-card px-[13px] text-[13.5px] text-text shadow-sm transition-colors
            placeholder:text-muted-2 focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]
            ${error || lookupError ? 'border-danger' : 'border-border focus:border-accent'}`}
          aria-label="Vehicle registration number" aria-invalid={!!(error || lookupError)} />
        <Button onClick={lookup} loading={loading} size="md">Lookup</Button>
      </div>
      {(error || lookupError) && <p className="text-[13px] text-danger" role="alert">{error || lookupError}</p>}
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
    <tr className="border-b border-border align-top hover:bg-canvas">
      {/* Item Details */}
      <td className="px-2 py-3">
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
            className={TABLE_INPUT_CLS}
            aria-label={`Line item ${index + 1} description`}
          />
          {showItemDropdown && (
            <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-48 overflow-auto rounded-ctl border border-border bg-card shadow-pop">
              {filteredItems.slice(0, 10).map((ci) => (
                <button
                  key={ci.id}
                  type="button"
                  onClick={() => handleItemSelect(ci)}
                  className="w-full px-3 py-2 text-left text-[13px] hover:bg-canvas"
                >
                  <div className="font-medium text-text">{ci.name}</div>
                  <div className="mono text-[12px] text-muted">{formatNZD(ci.default_price)}</div>
                </button>
              ))}
              {filteredItems.length === 0 && (
                <div className="px-3 py-2 text-[13px] text-muted">No items found</div>
              )}
            </div>
          )}
        </div>
      </td>
      {/* Quantity */}
      <td className="w-24 px-2 py-3">
        <input
          type="number"
          min="1"
          step="1"
          value={item.quantity}
          onChange={(e) => update({ quantity: Math.max(1, Number(e.target.value) || 1) })}
          className={`${TABLE_INPUT_CLS} mono text-right`}
          aria-label={`Line item ${index + 1} quantity`}
        />
      </td>
      {/* Rate */}
      <td className="w-32 px-2 py-3">
        <input
          type="number"
          min="0"
          step="0.01"
          value={item.unit_price}
          onChange={(e) => update({ unit_price: Math.max(0, Number(e.target.value) || 0) })}
          className={`${TABLE_INPUT_CLS} mono text-right`}
          aria-label={`Line item ${index + 1} rate`}
        />
      </td>
      {/* Amount (read-only) */}
      <td className="mono w-28 px-2 py-3 text-right text-[13px] font-medium text-text">
        {formatNZD(lineAmount)}
      </td>
      {/* Remove */}
      <td className="w-12 px-2 py-3">
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded p-1 text-muted-2 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger"
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
  const isPlumbing = (tradeFamily ?? 'automotive-transport') === 'plumbing-gas'

  const [customer, setCustomer] = useState<Customer | null>(null)
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [description, setDescription] = useState('')
  const [showLineItems, setShowLineItems] = useState(false)
  const [lineItems, setLineItems] = useState<LineItem[]>([])
  const [notes, setNotes] = useState('')

  /* Service type state (plumbing only) */
  const [serviceTypeId, setServiceTypeId] = useState<string | null>(null)
  const [serviceTypeValues, setServiceTypeValues] = useState<FieldValue[]>([])

  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

  /* Attachment state */
  const [savedJobCardId, setSavedJobCardId] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [attachmentError, setAttachmentError] = useState('')

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
  const handleShowLineItems = () => {
    setShowLineItems(true)
    if (lineItems.length === 0) {
      setLineItems([newLineItem()])
    }
  }

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
      // If all items removed, hide the section
      if (next.length === 0) {
        setShowLineItems(false)
      }
      return next
    })
  }

  /* --- Subtotal --- */
  const subtotal = lineItems.reduce(
    (sum, li) => sum + Math.round(li.quantity * li.unit_price * 100) / 100,
    0
  )

  /* --- Attachment handlers --- */
  const handleUploadComplete = useCallback((attachment: Attachment) => {
    setAttachments((prev) => [...prev, attachment])
    setAttachmentError('')
  }, [])

  const handleUploadError = useCallback((error: string) => {
    setAttachmentError(error)
  }, [])

  const handleDeleteAttachment = useCallback(
    async (attachmentId: string) => {
      if (!savedJobCardId) return
      try {
        await apiClient.delete(`/job-cards/${savedJobCardId}/attachments/${attachmentId}`)
        setAttachments((prev) => prev.filter((a) => a.id !== attachmentId))
      } catch {
        setAttachmentError('Failed to delete attachment. Please try again.')
      }
    },
    [savedJobCardId],
  )

  /* --- Validation --- */
  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!customer) errs.customer = 'Please select or create a customer'
    // Line items are optional - no validation required
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

      const res = await apiClient.post<{ id: string }>('/job-cards', {
        customer_id: customer?.id,
        branch_id: selectedBranchId || undefined,
        ...(isAutomotive && vehicle?.id ? { vehicle_id: vehicle.id } : {}),
        description: description.trim(),
        notes: notes.trim() || undefined,
        line_items,
        ...(isPlumbing && serviceTypeId
          ? {
              service_type_id: serviceTypeId,
              service_type_values: serviceTypeValues.length > 0 ? serviceTypeValues : undefined,
            }
          : {}),
      })
      const newId = res.data?.id
      if (newId) {
        setSavedJobCardId(newId)
      } else {
        window.location.href = '/job-cards'
      }
    } catch {
      setErrors({ submit: 'Failed to create job card. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page page-wide">
      <div className="mb-6 flex items-center gap-3">
        <button onClick={() => { window.location.href = '/job-cards' }}
          className="rounded p-1 text-muted-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label="Back to job cards">←</button>
        <h1 className="text-[22px] font-semibold text-text">Create Job Card</h1>
      </div>

      <div className="max-w-3xl space-y-6">
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

        {/* Service Type (plumbing only) */}
        {isPlumbing && (
          <section aria-labelledby="section-service-type">
            <h2 id="section-service-type" className="sr-only">Service Type</h2>
            <ServiceTypeSelector
              serviceTypeId={serviceTypeId}
              serviceTypeValues={serviceTypeValues}
              onServiceTypeChange={setServiceTypeId}
              onValuesChange={setServiceTypeValues}
            />
          </section>
        )}

        {/* Description */}
        <div>
          <Input label="Job description" placeholder="Brief summary of the job…" value={description}
            onChange={(e) => setDescription(e.target.value)} />
        </div>

        {/* Line Items - Collapsible Section */}
        <section aria-labelledby="section-line-items">
          {!showLineItems ? (
            /* Collapsed state - show "Add Line Item" button */
            <div>
              <Button variant="ghost" onClick={handleShowLineItems}>
                + Add Line Item
              </Button>
              <p className="mt-2 text-[13px] text-muted">Line items are optional. Click to add parts, services, or labour.</p>
            </div>
          ) : (
            /* Expanded state - show line items table */
            <>
              <div className="mb-3 flex items-center justify-between">
                <h2 id="section-line-items" className="text-[15px] font-medium text-text">Line Items</h2>
                <button
                  type="button"
                  onClick={() => setShowLineItems(false)}
                  className="rounded px-2 py-1 text-[13px] text-muted hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Hide
                </button>
              </div>

              {errors.items && <p className="mb-3 text-[13px] text-danger" role="alert">{errors.items}</p>}

              <div className="overflow-visible">
                <table className="w-full">
                  <thead>
                    <tr className="mono border-b border-border text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                      <th className="px-2 py-2">Item Details</th>
                      <th className="w-24 px-2 py-2 text-right">Qty</th>
                      <th className="w-32 px-2 py-2 text-right">Rate</th>
                      <th className="w-28 px-2 py-2 text-right">Amount</th>
                      <th className="w-12 px-2 py-2"></th>
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

              <div className="mt-3 flex items-center justify-between">
                <Button size="sm" variant="ghost" onClick={addLineItem}>
                  + Add Row
                </Button>
                <div className="text-[13px] font-medium text-muted">
                  Subtotal: <span className="mono text-text">{formatNZD(subtotal)}</span>
                </div>
              </div>
            </>
          )}
        </section>

        {/* Notes */}
        <div>
          <label className="mb-1 block text-[12.5px] font-medium text-text" htmlFor="jc-notes">Notes (optional)</label>
          <textarea id="jc-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
            className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            placeholder="Internal notes about this job…" />
        </div>

        {/* Attachments */}
        <section aria-labelledby="section-attachments">
          <h2 id="section-attachments" className="mb-3 text-[15px] font-medium text-text">Attachments</h2>

          {savedJobCardId ? (
            /* Job card saved — uploader is active */
            <div className="space-y-3">
              <AttachmentUploader
                jobCardId={savedJobCardId}
                onUploadComplete={handleUploadComplete}
                onError={handleUploadError}
              />
              {attachmentError && (
                <p className="text-[13px] text-danger" role="alert">{attachmentError}</p>
              )}
              <AttachmentList
                attachments={attachments}
                onDelete={handleDeleteAttachment}
              />
            </div>
          ) : (
            /* Job card not yet saved — show info message */
            <div className="rounded-card border-2 border-dashed border-border bg-canvas p-6 text-center">
              <svg
                className="mx-auto mb-2 h-10 w-10 text-muted-2"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                />
              </svg>
              <p className="text-[13px] text-muted">
                Save the job card first to attach photos and documents.
              </p>
              <p className="mt-1 text-[12px] text-muted-2">
                Images (JPEG, PNG, WebP, GIF) and PDFs up to 50MB
              </p>
            </div>
          )}
        </section>

        {/* Submit error */}
        {errors.submit && (
          <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
            {errors.submit}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          {savedJobCardId ? (
            /* Job card already created — show "View" / "Back to List" */
            <>
              <Button onClick={() => { window.location.href = `/job-cards/${savedJobCardId}` }}>
                View Job Card
              </Button>
              <Button variant="ghost" onClick={() => { window.location.href = '/job-cards' }}>
                Back to List
              </Button>
            </>
          ) : (
            <>
              <Button onClick={handleSave} loading={saving}>Create Job Card</Button>
              <Button variant="ghost" onClick={() => { window.location.href = '/job-cards' }}>Cancel</Button>
            </>
          )}
        </div>

        {/* Success banner after save */}
        {savedJobCardId && (
          <div className="rounded-ctl border border-ok/30 bg-ok-soft px-4 py-3 text-[13px] text-ok" role="status">
            Job card created successfully. You can now attach files or view the job card.
          </div>
        )}
      </div>
    </div>
  )
}
