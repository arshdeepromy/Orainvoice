import { useState, useCallback, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner, Modal } from '../../components/ui'
import { CustomerCreateModal } from '../../components/customers/CustomerCreateModal'
import { VehicleLiveSearch } from '../../components/vehicles/VehicleLiveSearch'
import { useTenant } from '../../contexts/TenantContext'
import { ModuleGate } from '../../components/common/ModuleGate'
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
  mobile_phone?: string
  company_name?: string
  display_name?: string
  linked_vehicles?: LinkedVehicle[]
}

interface LinkedVehicle {
  id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
}

interface LinkedCustomer {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
  mobile_phone?: string | null
  display_name?: string | null
  company_name?: string | null
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
  odometer?: number | null
  newOdometer?: number | null
  service_due_date?: string | null
  newServiceDueDate?: string | null
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

interface Salesperson {
  id: string
  name: string
}

interface LineItem {
  key: string
  item_id?: string
  description: string
  line_description?: string
  original_description?: string
  quantity: number
  rate: number
  tax_id?: string
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

const PAYMENT_TERMS_OPTIONS = [
  { value: 'due_on_receipt', label: 'Due on Receipt' },
  { value: 'net_7', label: 'Net 7' },
  { value: 'net_15', label: 'Net 15' },
  { value: 'net_30', label: 'Net 30' },
  { value: 'net_45', label: 'Net 45' },
  { value: 'net_60', label: 'Net 60' },
  { value: 'net_90', label: 'Net 90' },
  { value: 'custom', label: 'Custom' },
]

const DEFAULT_TAX_RATES: TaxRate[] = [
  { id: 'gst_15', name: 'GST (15%)', rate: 15 },
  { id: 'gst_0', name: 'GST Exempt (0%)', rate: 0 },
]

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
  }).format(amount)
}

function formatDate(date: Date): string {
  return date.toISOString().split('T')[0]
}

function calculateDueDate(invoiceDate: string, terms: string): string {
  const date = new Date(invoiceDate)
  const daysMap: Record<string, number> = {
    due_on_receipt: 0,
    net_7: 7,
    net_15: 15,
    net_30: 30,
    net_45: 45,
    net_60: 60,
    net_90: 90,
  }
  date.setDate(date.getDate() + (daysMap[terms] || 0))
  return formatDate(date)
}

function newLineItem(): LineItem {
  return {
    key: crypto.randomUUID(),
    description: '',
    quantity: 1,
    rate: 0,
    tax_rate: 15,
    tax_id: 'gst_15',
    amount: 0,
  }
}

function calcLineAmount(item: LineItem): number {
  return Math.round(item.quantity * item.rate * 100) / 100
}

/* ------------------------------------------------------------------ */
/*  Customer Search Component                                          */
/* ------------------------------------------------------------------ */

function CustomerSearch({
  selectedCustomer,
  onSelect,
  onVehicleAutoSelect,
  error,
  includeVehicles = true,
}: {
  selectedCustomer: Customer | null
  onSelect: (c: Customer | null) => void
  onVehicleAutoSelect?: (v: LinkedVehicle) => void
  error?: string
  includeVehicles?: boolean
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

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
      const res = await apiClient.get<{ customers: Customer[]; total: number } | Customer[]>('/customers', { 
        params: { q: q, ...(includeVehicles ? { include_vehicles: true } : {}) } 
      })
      const customers = Array.isArray(res.data) ? res.data : (res.data?.customers || [])
      // Client-side sequential character matching — letters must appear in order
      const term = q.toLowerCase()
      const matchesSequence = (haystack: string, needle: string): boolean => {
        let ni = 0
        const h = haystack.toLowerCase()
        for (let i = 0; i < h.length && ni < needle.length; i++) {
          if (h[i] === needle[ni]) ni++
        }
        return ni === needle.length
      }
      const filtered = customers.filter((c) => {
        const firstName = (c.first_name || '').toLowerCase()
        const lastName = (c.last_name || '').toLowerCase()
        const displayName = (c.display_name || '').toLowerCase()
        const phone = (c.phone || '').toLowerCase()
        const company = (c.company_name || '').toLowerCase()
        // Check rego from linked vehicles
        const regoMatch = (c.linked_vehicles || []).some((v: LinkedVehicle) =>
          matchesSequence(v.rego || '', term)
        )
        return (
          matchesSequence(firstName, term) ||
          matchesSequence(lastName, term) ||
          matchesSequence(displayName, term) ||
          matchesSequence(phone, term) ||
          matchesSequence(company, term) ||
          regoMatch
        )
      })
      setResults(filtered)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleInputChange = (value: string) => {
    setQuery(value)
    setShowDropdown(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(value), 300)
  }

  const handleSelect = (c: Customer) => {
    onSelect(c)
    setQuery(c.display_name || `${c.first_name} ${c.last_name}`)
    setShowDropdown(false)
    
    // Auto-select first linked vehicle if available
    if (onVehicleAutoSelect && c.linked_vehicles && c.linked_vehicles.length > 0) {
      onVehicleAutoSelect(c.linked_vehicles[0])
    }
  }

  const handleClear = () => {
    onSelect(null)
    setQuery('')
    setResults([])
  }

  const handleCustomerCreated = (customer: Customer) => {
    onSelect(customer)
    setQuery(customer.display_name || `${customer.first_name} ${customer.last_name}`)
    setShowCreateModal(false)
  }

  if (selectedCustomer) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Customer Name *</label>
        <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2">
          <svg className="h-4 w-4 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <span className="flex-1 text-gray-900">
            {selectedCustomer.display_name || `${selectedCustomer.first_name} ${selectedCustomer.last_name}`}
            {selectedCustomer.company_name && <span className="ml-2 text-gray-500">({selectedCustomer.company_name})</span>}
          </span>
          <button type="button" onClick={handleClear} className="rounded p-1 text-gray-400 hover:text-gray-600" aria-label="Change customer">✕</button>
        </div>
      </div>
    )
  }

  return (
    <>
      <div ref={containerRef} className="relative flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Customer Name *</label>
        <div className={`flex items-center gap-2 rounded-md border px-3 shadow-sm focus-within:ring-2 focus-within:ring-blue-500 ${error ? 'border-red-500' : 'border-gray-300'}`}>
          <svg className="h-4 w-4 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search or select a customer"
            value={query}
            onChange={(e) => handleInputChange(e.target.value)}
            onFocus={() => query.length >= 2 && setShowDropdown(true)}
            className="w-full py-2 text-gray-900 bg-transparent placeholder:text-gray-400 focus:outline-none"
            autoComplete="off"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {showDropdown && (
          <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-64 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
            {loading && <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500"><Spinner size="sm" /> Searching…</div>}
            {!loading && results.length > 0 && results.map((c) => (
              <button key={c.id} type="button" onClick={() => handleSelect(c)} className="w-full px-4 py-3 text-left hover:bg-gray-50">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-gray-900">{c.display_name || `${c.first_name} ${c.last_name}`}</span>
                    {c.company_name && <span className="ml-2 text-sm text-gray-500">({c.company_name})</span>}
                  </div>
                  {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                    <span className="text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                      {c.linked_vehicles.length} vehicle{c.linked_vehicles.length > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                  <div className="mt-1 text-xs text-gray-500">
                    {c.linked_vehicles.slice(0, 2).map(v => v.rego).join(', ')}
                    {c.linked_vehicles.length > 2 && ` +${c.linked_vehicles.length - 2} more`}
                  </div>
                )}
              </button>
            ))}
            {!loading && query.length >= 2 && results.length === 0 && <div className="px-4 py-3 text-sm text-gray-500">No customers found</div>}
            <button type="button" onClick={() => { setShowDropdown(false); setShowCreateModal(true) }} className="w-full border-t border-gray-100 px-4 py-3 text-left text-sm font-medium text-blue-600 hover:bg-blue-50">
              + Add New Customer
            </button>
          </div>
        )}
      </div>
      <CustomerCreateModal open={showCreateModal} onClose={() => setShowCreateModal(false)} onCustomerCreated={handleCustomerCreated} />
    </>
  )
}


/* ------------------------------------------------------------------ */
/*  Item Table Row Component                                           */
/* ------------------------------------------------------------------ */

function ItemTableRow({
  item,
  index,
  catalogueItems,
  taxRates,
  onChange,
  onRemove,
  onItemCreated,
}: {
  item: LineItem
  index: number
  catalogueItems: CatalogueItem[]
  taxRates: TaxRate[]
  onChange: (index: number, updated: LineItem) => void
  onRemove: (index: number) => void
  onItemCreated: (ci: CatalogueItem) => void
}) {
  const [showItemDropdown, setShowItemDropdown] = useState(false)
  const [itemSearch, setItemSearch] = useState('')
  const [showInlineForm, setShowInlineForm] = useState(false)
  const [inlineType, setInlineType] = useState<'goods' | 'service'>('goods')
  const [inlineName, setInlineName] = useState('')
  const [inlineUnit, setInlineUnit] = useState('')
  const [inlinePrice, setInlinePrice] = useState('')
  const [inlineDescription, setInlineDescription] = useState('')
  const [inlineGstExempt, setInlineGstExempt] = useState(false)
  const [inlineSaving, setInlineSaving] = useState(false)
  const [inlineError, setInlineError] = useState('')
  const [descUpdating, setDescUpdating] = useState(false)
  const [descUpdated, setDescUpdated] = useState(false)
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
    updated.amount = calcLineAmount(updated)
    onChange(index, updated)
  }

  const handleItemSelect = (catalogueItem: CatalogueItem) => {
    update({
      item_id: catalogueItem.id,
      description: catalogueItem.name,
      line_description: catalogueItem.description || '',
      original_description: catalogueItem.description || '',
      rate: catalogueItem.default_price,
      tax_rate: catalogueItem.gst_applicable ? 15 : 0,
      tax_id: catalogueItem.gst_applicable ? 'gst_15' : 'gst_0',
    })
    setShowItemDropdown(false)
    setItemSearch('')
    setDescUpdated(false)
  }

  const handleTaxChange = (taxId: string) => {
    const tax = taxRates.find(t => t.id === taxId)
    update({ tax_id: taxId, tax_rate: tax?.rate || 0 })
  }

  const filteredItems = (Array.isArray(catalogueItems) ? catalogueItems : []).filter(ci =>
    ci.name.toLowerCase().includes(itemSearch.toLowerCase()) ||
    (ci.sku && ci.sku.toLowerCase().includes(itemSearch.toLowerCase()))
  )

  const handleInlineItemSubmit = async () => {
    if (!inlineName.trim()) { setInlineError('Name is required.'); return }
    if (!inlinePrice.trim() || isNaN(Number(inlinePrice))) { setInlineError('Valid selling price is required.'); return }
    setInlineSaving(true)
    setInlineError('')
    try {
      const res = await apiClient.post<{ item: { id: string; name: string; default_price: string; is_gst_exempt: boolean; category: string | null; description: string | null } }>('/catalogue/items', {
        name: inlineName.trim(),
        default_price: inlinePrice.trim(),
        is_gst_exempt: inlineGstExempt,
        description: inlineDescription.trim() || null,
        category: inlineUnit.trim() || null,
      })
      const created = res.data.item
      const mapped: CatalogueItem = {
        id: created.id,
        name: created.name,
        default_price: Number(created.default_price),
        gst_applicable: !created.is_gst_exempt,
        category: created.category || undefined,
      }
      onItemCreated(mapped)
      handleItemSelect(mapped)
      setShowInlineForm(false)
      setInlineName(''); setInlinePrice(''); setInlineDescription(''); setInlineUnit('')
    } catch (err: any) {
      setInlineError(err?.response?.data?.detail || 'Failed to create item.')
    } finally {
      setInlineSaving(false)
    }
  }

  const descriptionChanged = item.item_id && item.line_description !== undefined && item.line_description !== (item.original_description || '')

  const handleUpdateDescriptionPermanently = async () => {
    if (!item.item_id || !item.line_description) return
    setDescUpdating(true)
    try {
      await apiClient.put(`/catalogue/items/${item.item_id}`, { description: item.line_description.trim() })
      update({ original_description: item.line_description })
      setDescUpdated(true)
      setTimeout(() => setDescUpdated(false), 3000)
    } catch { /* silent */ }
    finally { setDescUpdating(false) }
  }

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 align-top">
      {/* Item Details */}
      <td className="py-3 px-2">
        <div ref={containerRef} className="relative">
          <input
            type="text"
            value={item.description}
            onChange={(e) => { update({ description: e.target.value }); setItemSearch(e.target.value) }}
            onFocus={() => setShowItemDropdown(true)}
            placeholder="Type or click to select an item"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {item.item_id && (
            <div className="mt-1">
              <textarea
                value={item.line_description || ''}
                onChange={(e) => { update({ line_description: e.target.value }); setDescUpdated(false) }}
                placeholder="Item description"
                rows={2}
                className="w-full rounded border border-gray-200 px-2 py-1 text-xs text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-y"
              />
              {descUpdated ? (
                <span className="text-[10px] text-green-600 flex items-center gap-1">
                  <svg className="w-3 h-3 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                  Updated
                </span>
              ) : descriptionChanged ? (
                <span className="text-[10px] text-red-500">
                  Description changed —{' '}
                  <button type="button" disabled={descUpdating} onClick={handleUpdateDescriptionPermanently}
                    className="text-blue-600 hover:underline font-medium disabled:opacity-50">
                    {descUpdating ? 'Updating…' : 'Update permanently'}
                  </button>
                </span>
              ) : null}
            </div>
          )}
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
                  {ci.sku && <div className="text-xs text-gray-500">SKU: {ci.sku}</div>}
                  <div className="text-xs text-gray-500">{formatNZD(ci.default_price)}</div>
                </button>
              ))}
              {filteredItems.length === 0 && (
                <div className="px-3 py-2 text-sm text-gray-500">No items found</div>
              )}
              <button type="button"
                onClick={() => { setShowInlineForm(true); setInlineName(itemSearch.trim()); setShowItemDropdown(false) }}
                className="w-full px-3 py-2 text-left text-sm text-blue-600 font-medium hover:bg-blue-50">
                + Add new item
              </button>
            </div>
          )}
          {showInlineForm && (
            <div className="mt-2 rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-gray-900">New Item</h4>
                <button type="button" onClick={() => setShowInlineForm(false)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
              </div>
              <hr className="border-gray-200" />
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Item name *</label>
                <input type="text" value={inlineName} onChange={(e) => setInlineName(e.target.value)}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                <textarea value={inlineDescription} onChange={(e) => setInlineDescription(e.target.value)} rows={3} placeholder="Optional item description"
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Default price (ex-GST) *</label>
                  <input type="number" min="0" step="0.01" value={inlinePrice} onChange={(e) => setInlinePrice(e.target.value)} placeholder="e.g. 85.00"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
                  <input type="text" value={inlineUnit} onChange={(e) => setInlineUnit(e.target.value)} placeholder="e.g. Plumbing, Electrical"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={inlineGstExempt} onChange={(e) => setInlineGstExempt(e.target.checked)} className="rounded border-gray-300" />
                GST exempt
              </label>
              {inlineError && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{inlineError}</div>}
              <div className="flex justify-end gap-2">
                <button type="button" disabled={inlineSaving} onClick={() => setShowInlineForm(false)}
                  className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">
                  Cancel
                </button>
                <button type="button" disabled={inlineSaving} onClick={handleInlineItemSubmit}
                  className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                  {inlineSaving ? 'Saving…' : 'Create Item'}
                </button>
              </div>
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
        />
      </td>
      {/* Rate */}
      <td className="py-3 px-2 w-32">
        <input
          type="number"
          min="0"
          step="0.01"
          value={item.rate}
          onChange={(e) => update({ rate: Math.max(0, Number(e.target.value) || 0) })}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </td>
      {/* Tax */}
      <td className="py-3 px-2 w-36">
        <select
          value={item.tax_id || ''}
          onChange={(e) => handleTaxChange(e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {taxRates.map((tax) => (
            <option key={tax.id} value={tax.id}>{tax.name}</option>
          ))}
        </select>
      </td>
      {/* Amount */}
      <td className="py-3 px-2 w-28 text-right text-sm font-medium text-gray-900">
        {formatNZD(item.amount)}
      </td>
      {/* Remove */}
      <td className="py-3 px-2 w-12">
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="rounded p-1 text-gray-400 hover:text-red-500"
          aria-label="Remove item"
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

export default function InvoiceCreate() {
  const { id: editId } = useParams<{ id: string }>()
  const isEditMode = Boolean(editId)
  const { settings } = useTenant()
  const { isEnabled } = useModules()
  const vehiclesEnabled = isEnabled('vehicles')
  const [loadingInvoice, setLoadingInvoice] = useState(isEditMode)
  
  // Invoice header fields
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [invoiceNumber, setInvoiceNumber] = useState('')
  const [orderNumber, setOrderNumber] = useState('')
  const [invoiceDate, setInvoiceDate] = useState(() => formatDate(new Date()))
  const [terms, setTerms] = useState('due_on_receipt')
  const [dueDate, setDueDate] = useState(() => formatDate(new Date()))
  const [salesperson, setSalesperson] = useState('')
  const [subject, setSubject] = useState('')
  
  // GST from org settings
  const gstNumber = settings?.gst?.gst_number || ''

  // Auto-fill linked vehicles when customer is selected
  useEffect(() => {
    if (!customer || !vehiclesEnabled || vehicles.length > 0) return
    // If customer already has linked_vehicles from search results, use those
    if (customer.linked_vehicles && customer.linked_vehicles.length > 0) {
      setVehicles(customer.linked_vehicles.map(v => ({
        id: v.id,
        rego: v.rego,
        make: v.make || '',
        model: v.model || '',
        year: v.year,
        colour: v.colour || '',
        body_type: '',
        fuel_type: '',
        engine_size: '',
        wof_expiry: null,
        registration_expiry: null,
        odometer: null,
      })))
      return
    }
    // Otherwise fetch linked vehicles from API
    let cancelled = false
    async function fetchLinkedVehicles() {
      try {
        const res = await apiClient.get('/customers', {
          params: { q: customer!.email || `${customer!.first_name} ${customer!.last_name}`, include_vehicles: true, limit: 1 }
        })
        if (cancelled) return
        const customers = Array.isArray(res.data) ? res.data : (res.data?.customers || [])
        const match = customers.find((c: Customer) => c.id === customer!.id)
        if (match?.linked_vehicles && match.linked_vehicles.length > 0) {
          setVehicles(match.linked_vehicles.map((v: LinkedVehicle) => ({
            id: v.id,
            rego: v.rego,
            make: v.make || '',
            model: v.model || '',
            year: v.year,
            colour: v.colour || '',
            body_type: '',
            fuel_type: '',
            engine_size: '',
            wof_expiry: null,
            registration_expiry: null,
            odometer: null,
          })))
        }
      } catch {
        // Non-blocking
      }
    }
    fetchLinkedVehicles()
    return () => { cancelled = true }
  }, [customer, vehiclesEnabled])
  
  // Line items
  const [lineItems, setLineItems] = useState<LineItem[]>([newLineItem()])
  
  // Totals adjustments
  const [discountType, setDiscountType] = useState<'percentage' | 'fixed'>('percentage')
  const [discountValue, setDiscountValue] = useState(0)
  const [shippingCharges, setShippingCharges] = useState(0)
  const [adjustment, setAdjustment] = useState(0)
  
  // Notes and terms
  const [customerNotes, setCustomerNotes] = useState('')
  const [termsAndConditions, setTermsAndConditions] = useState(settings?.invoice?.terms_and_conditions || '')
  
  // Attachments
  const [attachments, setAttachments] = useState<File[]>([])
  
  // Payment gateway
  const [paymentGateway, setPaymentGateway] = useState('cash')
  
  // Make recurring
  const [makeRecurring, setMakeRecurring] = useState(false)
  
  // Catalogue data
  const [catalogueItems, setCatalogueItems] = useState<CatalogueItem[]>([])
  const [taxRates] = useState<TaxRate[]>(DEFAULT_TAX_RATES)
  const [salespeople, setSalespeople] = useState<Salesperson[]>([])
  
  // Form state
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
  const [paidModalOpen, setPaidModalOpen] = useState(false)
  const [paidMethod, setPaidMethod] = useState('cash')
  const [paidSaving, setPaidSaving] = useState(false)
  // Load existing invoice for edit mode
  useEffect(() => {
    if (!editId) return
    let cancelled = false
    async function loadInvoice() {
      try {
        const res = await apiClient.get(`/invoices/${editId}`)
        const inv = res.data?.invoice || res.data
        if (cancelled) return
        
        // Populate form fields from existing invoice
        if (inv.customer) {
          setCustomer(inv.customer)
        }
        if (inv.vehicle_rego) {
          setVehicles([{
            id: '',
            rego: inv.vehicle_rego,
            make: inv.vehicle_make || '',
            model: inv.vehicle_model || '',
            year: inv.vehicle_year || null,
            colour: '',
            body_type: '',
            fuel_type: '',
            engine_size: '',
            wof_expiry: null,
            registration_expiry: null,
            odometer: inv.vehicle_odometer || null,
            service_due_date: inv.vehicle?.service_due_date || null,
          }])
        }
        if (inv.invoice_number) setInvoiceNumber(inv.invoice_number)
        if (inv.due_date) setDueDate(inv.due_date)
        if (inv.issue_date) setInvoiceDate(inv.issue_date)
        if (inv.notes_customer) setCustomerNotes(inv.notes_customer)
        if (inv.discount_type) setDiscountType(inv.discount_type)
        if (inv.discount_value != null) setDiscountValue(Number(inv.discount_value))
        
        // Load line items
        if (inv.line_items && inv.line_items.length > 0) {
          setLineItems(inv.line_items.map((li: Record<string, unknown>) => ({
            id: String(li.id || crypto.randomUUID()),
            item_id: '',
            description: String(li.description || ''),
            quantity: Number(li.quantity || 1),
            rate: Number(li.unit_price || li.rate || 0),
            tax_id: '',
            tax_rate: li.is_gst_exempt ? 0 : 15,
            amount: Number(li.line_total || 0),
          })))
        }
      } catch {
        // Failed to load invoice for editing
      } finally {
        if (!cancelled) setLoadingInvoice(false)
      }
    }
    loadInvoice()
    return () => { cancelled = true }
  }, [editId])

  // Load catalogue data
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [itemsRes, salespeopleRes] = await Promise.all([
          apiClient.get<CatalogueItem[] | { items: CatalogueItem[] }>('/catalogue/items', { params: { active_only: true } }).catch(() => ({ data: [] })),
          apiClient.get<{ salespeople: Salesperson[] }>('/org/salespeople').catch(() => ({ data: { salespeople: [] } })),
        ])
        if (!cancelled) {
          // Handle both array and object response formats
          const items = itemsRes.data
          const rawItems = Array.isArray(items) ? items : ((items as any)?.items || [])
          setCatalogueItems(rawItems.map((item: any) => ({
            id: item.id,
            name: item.name,
            description: item.description ?? undefined,
            default_price: typeof item.default_price === 'string' ? parseFloat(item.default_price) : (item.default_price ?? 0),
            gst_applicable: item.gst_applicable ?? (item.is_gst_exempt === false),
            category: item.category ?? undefined,
            sku: item.sku ?? undefined,
          })))
          // Set salespeople from API
          const salespeopleData = salespeopleRes.data
          const salespeopleArray = Array.isArray(salespeopleData) ? salespeopleData : (salespeopleData?.salespeople || [])
          setSalespeople(salespeopleArray)
        }
      } catch {
        // Non-blocking
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // Update due date when terms or invoice date changes
  useEffect(() => {
    if (terms !== 'custom') {
      setDueDate(calculateDueDate(invoiceDate, terms))
    }
  }, [invoiceDate, terms])

  // Update terms and conditions from settings
  useEffect(() => {
    if (settings?.invoice?.terms_and_conditions) {
      setTermsAndConditions(settings.invoice.terms_and_conditions)
    }
  }, [settings])

  // Calculate totals
  const subTotal = lineItems.reduce((sum, item) => sum + item.amount, 0)
  const discountAmount = discountType === 'percentage' 
    ? (subTotal * discountValue / 100) 
    : discountValue
  const afterDiscount = subTotal - discountAmount
  const taxAmount = lineItems.reduce((sum, item) => sum + (item.amount * item.tax_rate / 100), 0)
  const total = afterDiscount + taxAmount + shippingCharges + adjustment

  // Line item management
  const addLineItem = () => {
    setLineItems(prev => [...prev, newLineItem()])
  }

  const updateLineItem = (index: number, updated: LineItem) => {
    setLineItems(prev => prev.map((item, i) => i === index ? updated : item))
  }

  const removeLineItem = (index: number) => {
    if (lineItems.length > 1) {
      setLineItems(prev => prev.filter((_, i) => i !== index))
    }
  }

  // File handling
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setAttachments(prev => [...prev, ...Array.from(e.target.files!)])
    }
  }

  const removeAttachment = (index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index))
  }

  // Validation
  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!customer) errs.customer = 'Please select a customer'
    if (lineItems.every(item => !item.description.trim())) {
      errs.lineItems = 'Add at least one item'
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  // Build payload
  const buildPayload = (status: 'draft' | 'sent') => ({
    customer_id: customer?.id,
    // Only include vehicle fields when vehicles module is enabled
    ...(vehiclesEnabled ? {
      vehicle_rego: vehicles[0]?.rego,
      vehicle_make: vehicles[0]?.make,
      vehicle_model: vehicles[0]?.model,
      vehicle_year: vehicles[0]?.year,
      vehicle_odometer: vehicles[0]?.newOdometer ?? vehicles[0]?.odometer ?? undefined,
      global_vehicle_id: vehicles[0]?.id || undefined,
      vehicle_service_due_date: vehicles[0]?.newServiceDueDate ?? vehicles[0]?.service_due_date ?? undefined,
      vehicles: vehicles.filter(v => v.id).map(v => ({
        id: v.id,
        rego: v.rego,
        make: v.make,
        model: v.model,
        year: v.year,
        odometer: v.newOdometer ?? v.odometer ?? undefined,
      })),
    } : {}),
    invoice_number: isEditMode ? invoiceNumber : undefined,
    order_number: orderNumber || undefined,
    issue_date: invoiceDate,
    due_date: dueDate,
    payment_terms: terms,
    salesperson_id: salesperson || undefined,
    subject: subject || undefined,
    gst_number: gstNumber || undefined,
    status,
    discount_type: discountType,
    discount_value: discountValue,
    shipping_charges: shippingCharges,
    adjustment,
    customer_notes: customerNotes || undefined,
    terms_and_conditions: termsAndConditions || undefined,
    payment_gateway: paymentGateway,
    is_recurring: makeRecurring,
    line_items: lineItems.filter(item => item.description.trim()).map(item => ({
      item_id: item.item_id,
      description: item.line_description ? `${item.description}\n${item.line_description}` : item.description,
      quantity: item.quantity,
      rate: item.rate,
      tax_id: item.tax_id,
      tax_rate: item.tax_rate,
      amount: item.amount,
    })),
  })

  // Save handlers
  const handleSaveDraft = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      if (isEditMode && editId) {
        await apiClient.put(`/invoices/${editId}`, buildPayload('draft'))
        window.location.href = `/invoices/${editId}`
      } else {
        await apiClient.post('/invoices', buildPayload('draft'))
        window.location.href = '/invoices'
      }
    } catch {
      setErrors({ submit: 'Failed to save draft. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  const handleSaveAndSend = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      if (isEditMode && editId) {
        await apiClient.put(`/invoices/${editId}`, buildPayload('sent'))
        window.location.href = `/invoices/${editId}`
      } else {
        await apiClient.post('/invoices', buildPayload('sent'))
        window.location.href = '/invoices'
      }
    } catch {
      setErrors({ submit: 'Failed to send invoice. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  const handleMarkPaidAndEmail = async () => {
    if (!validate()) return
    setPaidSaving(true)
    try {
      // 1. Save as draft first
      let invoiceId = editId
      if (isEditMode && editId) {
        await apiClient.put(`/invoices/${editId}`, buildPayload('draft'))
      } else {
        const res = await apiClient.post('/invoices', buildPayload('draft'))
        invoiceId = (res.data as any)?.id || (res.data as any)?.invoice?.id
      }
      if (!invoiceId) throw new Error('No invoice ID')

      // 2. Issue the invoice (assigns number, sets status to issued)
      await apiClient.put(`/invoices/${invoiceId}/issue`)

      // 3. Record full payment
      const detailRes = await apiClient.get(`/invoices/${invoiceId}`)
      const inv = (detailRes.data as any)?.invoice || detailRes.data
      const total = Number(inv?.total || inv?.total_incl_gst || 0)
      if (total > 0) {
        await apiClient.post('/payments/cash', {
          invoice_id: invoiceId,
          amount: total,
          method: paidMethod,
          note: 'Paid at invoice creation',
        })
      }

      // 4. Send email if customer has email
      try {
        await apiClient.post(`/invoices/${invoiceId}/email`)
      } catch {
        // Email send is best-effort — don't fail the whole flow
      }

      setPaidModalOpen(false)
      window.location.href = `/invoices/${invoiceId}`
    } catch {
      setErrors({ submit: 'Failed to process. Please try again.' })
    } finally {
      setPaidSaving(false)
    }
  }

  const handleCancel = () => {
    if (isEditMode && editId) {
      window.location.href = `/invoices/${editId}`
    } else {
      window.location.href = '/invoices'
    }
  }

  if (loadingInvoice) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading invoice" />
      </div>
    )
  }

  return (
    <div className="bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">{isEditMode ? 'Edit Invoice' : 'New Invoice'}</h1>
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={handleCancel}>Cancel</Button>
            <Button variant="secondary" onClick={handleSaveDraft} loading={saving}>Save as Draft</Button>
            <Button variant="secondary" onClick={() => { if (validate()) setPaidModalOpen(true) }} loading={paidSaving}>Mark Paid &amp; Email</Button>
            <Button onClick={handleSaveAndSend} loading={saving}>Save and Send</Button>
          </div>
        </div>
      </div>

      <div className="px-6 py-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-6">
          
          {/* Customer and Invoice Details */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left Column */}
            <div className="space-y-4">
              <CustomerSearch
                selectedCustomer={customer}
                onSelect={(c) => {
                  setCustomer(c)
                  if (!c) setVehicles([])
                }}
                includeVehicles={vehiclesEnabled}
                onVehicleAutoSelect={vehiclesEnabled ? (v) => {
                  // Only auto-select if no vehicles are currently selected
                  if (vehicles.length === 0) {
                    setVehicles([{
                      id: v.id,
                      rego: v.rego,
                      make: v.make || '',
                      model: v.model || '',
                      year: v.year,
                      colour: v.colour || '',
                      body_type: '',
                      fuel_type: '',
                      engine_size: '',
                      wof_expiry: null,
                      registration_expiry: null,
                      odometer: null,
                    }])
                  }
                } : undefined}
                error={errors.customer}
              />
              
              {/* Vehicle Search — only shown when vehicles module is enabled */}
              <ModuleGate module="vehicles">
              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-700">Vehicles</label>
                {vehicles.map((v, index) => (
                  <div key={v.id || index} className="flex items-center gap-2">
                    <div className="flex-1 rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="font-medium">{v.rego}</span>
                          {(v.make || v.model) && (
                            <span className="ml-2 text-gray-500">
                              {[v.year, v.make, v.model].filter(Boolean).join(' ')}
                            </span>
                          )}
                          {v.odometer != null && v.odometer > 0 && (
                            <span className="ml-2 text-gray-400">
                              Current: {v.odometer.toLocaleString()} km
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <label className="text-xs text-gray-500 whitespace-nowrap">New Odo Reading:</label>
                        <input
                          type="number"
                          min="0"
                          placeholder={v.odometer ? `${v.odometer}` : 'km'}
                          value={v.newOdometer ?? ''}
                          onChange={(e) => {
                            const val = e.target.value ? Number(e.target.value) : null
                            setVehicles(prev => prev.map((veh, i) => i === index ? { ...veh, newOdometer: val } : veh))
                          }}
                          className="w-32 rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        <span className="text-xs text-gray-400">Kms</span>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <label className="text-xs text-gray-500 whitespace-nowrap">Service Due:</label>
                        <input
                          type="date"
                          value={v.newServiceDueDate ?? v.service_due_date ?? ''}
                          onChange={(e) => {
                            const val = e.target.value || null
                            setVehicles(prev => prev.map((veh, i) => i === index ? { ...veh, newServiceDueDate: val } : veh))
                          }}
                          className="w-40 rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        {v.service_due_date && !v.newServiceDueDate && (
                          <span className="text-xs text-gray-400">
                            Current: {new Date(v.service_due_date).toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' })}
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setVehicles(prev => prev.filter((_, i) => i !== index))}
                      className="rounded p-1 text-gray-400 hover:text-red-500"
                      aria-label="Remove vehicle"
                    >
                      <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
                <VehicleLiveSearch
                  vehicle={null}
                  onVehicleFound={(v) => {
                    if (v && !vehicles.some(existing => existing.id === v.id)) {
                      setVehicles(prev => [...prev, v])
                    }
                  }}
                  onCustomerAutoSelect={(c) => {
                    // Only auto-select if no customer is currently selected
                    if (!customer) {
                      setCustomer({
                        id: c.id,
                        first_name: c.first_name,
                        last_name: c.last_name,
                        email: c.email || '',
                        phone: c.phone || '',
                        mobile_phone: c.mobile_phone || undefined,
                        display_name: c.display_name || undefined,
                        company_name: c.company_name || undefined,
                      })
                    }
                  }}
                />
                {vehicles.length > 0 && (
                  <p className="text-xs text-gray-500">
                    {vehicles.length} vehicle{vehicles.length > 1 ? 's' : ''} added. Search above to add more.
                  </p>
                )}
              </div>
              </ModuleGate>
            </div>
            
            {/* Right Column */}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <Input
                  label="Invoice#"
                  value={invoiceNumber}
                  onChange={(e) => setInvoiceNumber(e.target.value)}
                  placeholder="Auto-generated on issue"
                  disabled={!isEditMode}
                />
                <Input
                  label="Order Number"
                  value={orderNumber}
                  onChange={(e) => setOrderNumber(e.target.value)}
                  placeholder="Optional"
                />
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <Input
                  label="Invoice Date"
                  type="date"
                  value={invoiceDate}
                  onChange={(e) => setInvoiceDate(e.target.value)}
                />
                <Select
                  label="Terms"
                  options={PAYMENT_TERMS_OPTIONS}
                  value={terms}
                  onChange={(e) => setTerms(e.target.value)}
                />
              </div>
              <div>
                <Input
                  label="Due Date"
                  type="date"
                  value={dueDate}
                  onChange={(e) => { setDueDate(e.target.value); setTerms('custom') }}
                />
              </div>
              
              <Select
                label="Salesperson"
                options={[{ value: '', label: 'Select a salesperson' }, ...salespeople.map(s => ({ value: s.id, label: s.name }))]}
                value={salesperson}
                onChange={(e) => setSalesperson(e.target.value)}
              />
            </div>
          </div>

          {/* GST Number */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Input
              label="GST No*"
              value={gstNumber}
              disabled
              helperText={gstNumber ? 'Auto-populated from organisation settings' : 'Configure GST in organisation settings'}
            />
            <Input
              label="Subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Let your customer know what this invoice is for"
            />
          </div>

          {/* Item Table */}
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
                      onItemCreated={(ci) => setCatalogueItems(prev => [...prev, ci])}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            
            <div className="flex gap-3 mt-3">
              <Button variant="secondary" size="sm" onClick={addLineItem}>
                + Add New Row
              </Button>
              <Button variant="secondary" size="sm" disabled>
                Add Items in Bulk
              </Button>
            </div>
          </div>


          {/* Totals Section */}
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
                  <div className="inline-flex rounded-md border border-gray-300">
                    <button
                      type="button"
                      onClick={() => setDiscountType('percentage')}
                      className={`min-w-[40px] px-3 py-1.5 text-sm font-semibold text-center rounded-l-md transition-colors ${discountType === 'percentage' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                    >
                      %
                    </button>
                    <button
                      type="button"
                      onClick={() => setDiscountType('fixed')}
                      className={`min-w-[40px] px-3 py-1.5 text-sm font-semibold text-center rounded-r-md border-l border-gray-300 transition-colors ${discountType === 'fixed' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                    >
                      $
                    </button>
                  </div>
                  <input
                    type="number"
                    min="0"
                    step={discountType === 'percentage' ? '1' : '0.01'}
                    value={discountValue}
                    onChange={(e) => setDiscountValue(Math.max(0, Number(e.target.value) || 0))}
                    className="w-24 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
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
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={shippingCharges}
                  onChange={(e) => setShippingCharges(Math.max(0, Number(e.target.value) || 0))}
                  className="w-24 rounded border border-gray-300 px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              
              {/* Adjustment */}
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-gray-600">Adjustment</span>
                <input
                  type="number"
                  step="0.01"
                  value={adjustment}
                  onChange={(e) => setAdjustment(Number(e.target.value) || 0)}
                  className="w-24 rounded border border-gray-300 px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              
              {/* Total */}
              <div className="flex justify-between text-base font-semibold border-t border-gray-200 pt-3">
                <span className="text-gray-900">Total (NZD)</span>
                <span className="text-gray-900">{formatNZD(total)}</span>
              </div>
            </div>
          </div>

          {/* Customer Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Customer Notes</label>
            <textarea
              value={customerNotes}
              onChange={(e) => setCustomerNotes(e.target.value)}
              rows={3}
              placeholder="Enter any notes to be displayed in your transaction"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Terms & Conditions */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Terms & Conditions</label>
            <textarea
              value={termsAndConditions}
              onChange={(e) => setTermsAndConditions(e.target.value)}
              rows={3}
              placeholder="Enter the terms and conditions of your business to be displayed in your transaction"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Attach Files */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Attach File(s) to Invoice</label>
            <div className="flex items-center gap-4">
              <label className="cursor-pointer inline-flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50">
                <svg className="h-5 w-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                Upload Files
                <input type="file" multiple onChange={handleFileChange} className="hidden" />
              </label>
              <span className="text-sm text-gray-500">You can upload a maximum of 5 files, 5MB each</span>
            </div>
            {attachments.length > 0 && (
              <div className="mt-3 space-y-2">
                {attachments.map((file, index) => (
                  <div key={index} className="flex items-center gap-2 text-sm text-gray-600">
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span>{file.name}</span>
                    <button type="button" onClick={() => removeAttachment(index)} className="text-red-500 hover:text-red-700">✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Payment Method */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Payment Method</label>
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="paymentGateway"
                  value="cash"
                  checked={paymentGateway === 'cash'}
                  onChange={(e) => setPaymentGateway(e.target.value)}
                  className="h-4 w-4 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">Cash</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="paymentGateway"
                  value="eftpos"
                  checked={paymentGateway === 'eftpos'}
                  onChange={(e) => setPaymentGateway(e.target.value)}
                  className="h-4 w-4 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">EFTPOS</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="paymentGateway"
                  value="bank_transfer"
                  checked={paymentGateway === 'bank_transfer'}
                  onChange={(e) => setPaymentGateway(e.target.value)}
                  className="h-4 w-4 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">Bank Transfer</span>
              </label>
              <label className="flex items-center gap-2 cursor-not-allowed opacity-50" title="Stripe integration coming soon">
                <input
                  type="radio"
                  name="paymentGateway"
                  value="stripe"
                  disabled
                  className="h-4 w-4 text-gray-400"
                />
                <span className="text-sm text-gray-400">Stripe <span className="text-xs italic">(coming soon)</span></span>
              </label>
            </div>
          </div>

          {/* Make Recurring */}
          <div className="border-t border-gray-200 pt-4">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={makeRecurring}
                onChange={(e) => setMakeRecurring(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm font-medium text-gray-700">Make Recurring</span>
            </label>
            {makeRecurring && (
              <p className="mt-2 text-sm text-gray-500 ml-7">
                Recurring invoice settings will be available after saving.
              </p>
            )}
          </div>

          {/* Submit Error */}
          {errors.submit && (
            <p className="text-sm text-red-600" role="alert">{errors.submit}</p>
          )}

          {/* Bottom Actions */}
          <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
            <Button variant="secondary" onClick={handleCancel}>Cancel</Button>
            <Button variant="secondary" onClick={handleSaveDraft} loading={saving}>Save as Draft</Button>
            <Button variant="secondary" onClick={() => { if (validate()) setPaidModalOpen(true) }} loading={paidSaving}>Mark Paid &amp; Email</Button>
            <Button onClick={handleSaveAndSend} loading={saving}>Save and Send</Button>
          </div>
        </div>
      </div>

      {/* Mark Paid & Email Modal */}
      <Modal open={paidModalOpen} onClose={() => setPaidModalOpen(false)} title="Mark Paid & Email">
        <p className="text-sm text-gray-600 mb-4">
          This will issue the invoice, record full payment, and email the paid invoice to the customer.
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Payment Method</label>
          <select
            value={paidMethod}
            onChange={(e) => setPaidMethod(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="cash">Cash</option>
            <option value="eftpos">EFTPOS</option>
            <option value="bank_transfer">Bank Transfer</option>
            <option value="card">Card</option>
            <option value="cheque">Cheque</option>
          </select>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setPaidModalOpen(false)}>Cancel</Button>
          <Button onClick={handleMarkPaidAndEmail} loading={paidSaving}>Confirm &amp; Send</Button>
        </div>
      </Modal>
    </div>
  )
}
