import { useState, useCallback, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner, Modal } from '../../components/ui'
import { CustomerCreateModal } from '../../components/customers/CustomerCreateModal'
import { VehicleLiveSearch } from '../../components/vehicles/VehicleLiveSearch'
import { useTenant } from '../../contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
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
  newWofExpiry?: string | null
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
  stock_item_id?: string
  description: string
  line_description?: string
  original_description?: string
  quantity: number
  rate: number
  tax_id?: string
  tax_rate: number
  amount: number
  gst_inclusive?: boolean
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

/** Safely extract a human-readable string from any API error shape.
 *  Handles: string, Pydantic array [{msg, loc, ...}], or unknown objects. */
function extractErrorMsg(detail: unknown, fallback: string): string {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first = detail[0]
    if (first && typeof first === 'object' && 'msg' in first) {
      const loc = Array.isArray((first as any).loc) ? (first as any).loc.join(' → ') : ''
      return loc ? `${loc}: ${(first as any).msg}` : String((first as any).msg)
    }
    return fallback
  }
  return fallback
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
  const [inlineGstMode, setInlineGstMode] = useState<'inclusive' | 'exclusive' | 'exempt' | ''>('')
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
    // GST-inclusive: back-calculate ex-GST rate so invoice shows proper breakdown
    // GST-exempt: rate as-is, 0% tax
    // GST-exclusive (default): rate as-is, 15% tax
    const isGstInclusive = catalogueItem.gst_inclusive === true
    const isGstExempt = !catalogueItem.gst_applicable
    let rate: number
    let taxRate: number
    let taxId: string
    if (isGstExempt) {
      rate = catalogueItem.default_price
      taxRate = 0
      taxId = 'gst_0'
    } else if (isGstInclusive) {
      rate = Math.round((catalogueItem.default_price / 1.15) * 100) / 100
      taxRate = 15
      taxId = 'gst_15'
    } else {
      rate = catalogueItem.default_price
      taxRate = 15
      taxId = 'gst_15'
    }
    update({
      item_id: catalogueItem.id,
      description: catalogueItem.name,
      line_description: catalogueItem.description || '',
      original_description: catalogueItem.description || '',
      rate,
      tax_rate: taxRate,
      tax_id: taxId,
      gst_inclusive: isGstInclusive,
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
    if (!inlineGstMode) { setInlineError('Please select a GST type.'); return }
    if (!inlinePrice.trim() || isNaN(Number(inlinePrice))) { setInlineError('Valid selling price is required.'); return }
    setInlineSaving(true)
    setInlineError('')
    try {
      const res = await apiClient.post<{ item: { id: string; name: string; default_price: string; is_gst_exempt: boolean; gst_inclusive: boolean; category: string | null; description: string | null } }>('/catalogue/items', {
        name: inlineName.trim(),
        default_price: inlinePrice.trim(),
        is_gst_exempt: inlineGstMode === 'exempt',
        gst_inclusive: inlineGstMode === 'inclusive',
        description: inlineDescription.trim() || null,
        category: inlineUnit.trim() || null,
      })
      const created = res.data.item
      const mapped: CatalogueItem = {
        id: created.id,
        name: created.name,
        default_price: Number(created.default_price),
        gst_applicable: !created.is_gst_exempt,
        gst_inclusive: created.gst_inclusive ?? false,
        category: created.category || undefined,
      }
      onItemCreated(mapped)
      handleItemSelect(mapped)
      setShowInlineForm(false)
      setInlineName(''); setInlinePrice(''); setInlineDescription(''); setInlineUnit(''); setInlineGstMode('')
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
              {item.gst_inclusive && (
                <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5 mb-1">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                  GST inclusive — rate shows ex-GST, GST added in totals
                </span>
              )}
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
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">GST *</label>
                <div className="flex rounded-md border border-gray-300 overflow-hidden">
                  {(['inclusive', 'exclusive', 'exempt'] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setInlineGstMode(mode)}
                      className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
                        inlineGstMode === mode
                          ? 'bg-blue-600 text-white'
                          : 'bg-white text-gray-700 hover:bg-gray-50'
                      } ${mode !== 'inclusive' ? 'border-l border-gray-300' : ''}`}
                    >
                      GST {mode.charAt(0).toUpperCase() + mode.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    {!inlineGstMode ? (
                      <span className="flex items-center gap-1 text-amber-600">
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" /></svg>
                        Select a GST type above to unlock
                      </span>
                    ) : inlineGstMode === 'inclusive' ? 'Default price (incl. GST) *'
                      : inlineGstMode === 'exempt' ? 'Default price *'
                      : 'Default price (ex-GST) *'}
                  </label>
                  <input type="number" min="0" step="0.01" value={inlinePrice} onChange={(e) => setInlinePrice(e.target.value)} placeholder="e.g. 85.00"
                    disabled={!inlineGstMode}
                    className={`w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${!inlineGstMode ? 'bg-gray-100 cursor-not-allowed border-dashed border-amber-300' : ''}`} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
                  <input type="text" value={inlineUnit} onChange={(e) => setInlineUnit(e.target.value)} placeholder="e.g. Plumbing, Electrical"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
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
  const navigate = useNavigate()
  const isEditMode = Boolean(editId)
  const { settings, tradeFamily } = useTenant()
  const { selectedBranchId } = useBranch()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
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
          const primaryVehicle = {
            id: inv.vehicle?.id || '',
            rego: inv.vehicle_rego,
            make: inv.vehicle_make || '',
            model: inv.vehicle_model || '',
            year: inv.vehicle_year || null,
            colour: inv.vehicle?.colour || '',
            body_type: '',
            fuel_type: '',
            engine_size: '',
            wof_expiry: inv.vehicle?.wof_expiry || null,
            registration_expiry: null,
            odometer: inv.vehicle_odometer || null,
            service_due_date: inv.vehicle?.service_due_date || null,
          }
          const additionalVehicles = (inv.additional_vehicles || []).map((av: Record<string, unknown>) => ({
            id: (av.id as string) || '',
            rego: (av.rego as string) || '',
            make: (av.make as string) || '',
            model: (av.model as string) || '',
            year: (av.year as number) || null,
            colour: '',
            body_type: '',
            fuel_type: '',
            engine_size: '',
            wof_expiry: (av.wof_expiry as string) || null,
            registration_expiry: null,
            odometer: (av.odometer as number) || null,
            service_due_date: null,
          }))
          setVehicles([primaryVehicle, ...additionalVehicles])
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
            key: String(li.id || crypto.randomUUID()),
            item_id: li.catalogue_item_id ? String(li.catalogue_item_id) : '',
            stock_item_id: li.stock_item_id ? String(li.stock_item_id) : undefined,
            description: String(li.description || ''),
            quantity: Number(li.quantity || 1),
            rate: Number(li.unit_price || li.rate || 0),
            tax_id: li.is_gst_exempt ? 'gst_0' : 'gst_15',
            tax_rate: li.is_gst_exempt ? 0 : 15,
            amount: Number(li.line_total || 0),
          })))
        }

        // Load fluid usage from invoice_data_json
        const savedFluidUsage = inv.fluid_usage || []
        if (savedFluidUsage.length > 0) {
          setFluidUsages(savedFluidUsage.map((fu: Record<string, unknown>) => ({
            key: crypto.randomUUID(),
            stock_item_id: String(fu.stock_item_id || ''),
            item_name: String(fu.item_name || ''),
            litres: Number(fu.litres || 0),
            catalogue_item_id: String(fu.catalogue_item_id || ''),
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
            gst_inclusive: item.gst_inclusive ?? false,
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

  // Inventory stock picker state
  const [stockPickerOpen, setStockPickerOpen] = useState(false)
  const [stockItems, setStockItems] = useState<{id:string;catalogue_item_id:string;catalogue_type:string;item_name:string;part_number:string|null;brand:string|null;subtitle:string|null;current_quantity:number;reserved_quantity:number;available_quantity:number;sell_price:number|null;cost_per_unit:number|null;gst_mode:string|null;supplier_name:string|null;location:string|null}[]>([])
  const [stockLoading, setStockLoading] = useState(false)
  const [stockSearch, setStockSearch] = useState('')
  const [stockFilter, setStockFilter] = useState<'all'|'part'|'tyre'>('all')
  const [labourPickerOpen, setLabourPickerOpen] = useState(false)
  const [labourRates, setLabourRates] = useState<{id:string;name:string;hourly_rate:string}[]>([])
  const [labourLoading, setLabourLoading] = useState(false)

  const openStockPicker = async () => {
    setStockPickerOpen(true); setStockSearch(''); setStockFilter('all'); setStockLoading(true)
    try {
      const res = await apiClient.get('/inventory/stock-items', { params: { limit: 500 } })
      setStockItems((res.data as any).stock_items || [])
    } catch { setStockItems([]) } finally { setStockLoading(false) }
  }
  const addStockLineItem = (item: typeof stockItems[0]) => {
    const sellPrice = item.sell_price || 0
    const isGstInclusive = item.gst_mode === 'inclusive'
    const isGstExempt = item.gst_mode === 'exempt'
    // GST-inclusive: back-calculate ex-GST rate so GST breakdown shows correctly
    // GST-exclusive: rate is already ex-GST, apply 15%
    // GST-exempt: rate as-is, 0% tax
    let rate: number
    let taxRate: number
    let taxId: string
    if (isGstExempt) {
      rate = sellPrice
      taxRate = 0
      taxId = 'gst_0'
    } else if (isGstInclusive) {
      // Back-calculate: ex-GST = inclusive / 1.15
      rate = Math.round((sellPrice / 1.15) * 100) / 100
      taxRate = 15
      taxId = 'gst_15'
    } else {
      rate = sellPrice
      taxRate = 15
      taxId = 'gst_15'
    }
    const desc = item.subtitle ? `${item.item_name} (${item.subtitle})` : item.item_name
    setLineItems(prev => [...prev, {
      key: crypto.randomUUID(),
      item_id: item.catalogue_item_id,
      stock_item_id: item.id,
      description: desc,
      quantity: 1,
      rate,
      tax_rate: taxRate,
      tax_id: taxId,
      amount: rate,
      gst_inclusive: isGstInclusive,
    }])
    setStockPickerOpen(false)
  }
  const openLabourPicker = async () => {
    setLabourPickerOpen(true); setLabourLoading(true)
    try { setLabourRates((await apiClient.get('/catalogue/labour-rates')).data.labour_rates || []) }
    catch { setLabourRates([]) } finally { setLabourLoading(false) }
  }
  const addLabourLineItem = (rate: typeof labourRates[0]) => {
    setLineItems(prev => [...prev, { key: crypto.randomUUID(), description: `Labour: ${rate.name}`, quantity: 1, rate: parseFloat(rate.hourly_rate) || 0, tax_rate: 15, tax_id: 'gst_15', amount: parseFloat(rate.hourly_rate) || 0 }])
    setLabourPickerOpen(false)
  }

  // Fluid / Oil usage tracking (not invoiced, just inventory tracking)
  interface FluidUsage { key: string; stock_item_id: string; item_name: string; litres: number; catalogue_item_id: string }
  const [fluidUsages, setFluidUsages] = useState<FluidUsage[]>([])
  const [fluidPickerOpen, setFluidPickerOpen] = useState(false)
  const [fluidItems, setFluidItems] = useState<typeof stockItems>([])
  const [fluidLoading, setFluidLoading] = useState(false)
  const [fluidSearch, setFluidSearch] = useState('')

  const openFluidPicker = async () => {
    setFluidPickerOpen(true); setFluidSearch(''); setFluidLoading(true)
    try {
      const res = await apiClient.get('/inventory/stock-items', { params: { limit: 500 } })
      const all = (res.data as any).stock_items || []
      setFluidItems(all.filter((si: any) => si.catalogue_type === 'fluid' && si.available_quantity > 0))
    } catch { setFluidItems([]) } finally { setFluidLoading(false) }
  }
  const addFluidUsage = (item: typeof stockItems[0]) => {
    setFluidUsages(prev => [...prev, {
      key: crypto.randomUUID(),
      stock_item_id: item.id,
      item_name: item.item_name,
      litres: 1,
      catalogue_item_id: item.catalogue_item_id,
    }])
    setFluidPickerOpen(false)
  }
  const updateFluidLitres = (key: string, litres: number) => {
    setFluidUsages(prev => prev.map(f => f.key === key ? { ...f, litres: Math.max(0, litres) } : f))
  }
  const removeFluidUsage = (key: string) => {
    setFluidUsages(prev => prev.filter(f => f.key !== key))
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
    branch_id: selectedBranchId || undefined,
    // Only include vehicle fields when vehicles module is enabled and trade is automotive
    ...(isAutomotive && vehiclesEnabled ? {
      vehicle_rego: vehicles[0]?.rego,
      vehicle_make: vehicles[0]?.make,
      vehicle_model: vehicles[0]?.model,
      vehicle_year: vehicles[0]?.year,
      vehicle_odometer: vehicles[0]?.newOdometer ?? vehicles[0]?.odometer ?? undefined,
      global_vehicle_id: vehicles[0]?.id || undefined,
      vehicle_service_due_date: vehicles[0]?.newServiceDueDate ?? vehicles[0]?.service_due_date ?? undefined,
      vehicle_wof_expiry_date: vehicles[0]?.newWofExpiry ?? vehicles[0]?.wof_expiry ?? undefined,
      vehicles: vehicles.map(v => ({
        id: v.id || undefined,
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
    fluid_usage: fluidUsages.filter(f => f.litres > 0).map(f => ({
      stock_item_id: f.stock_item_id,
      catalogue_item_id: f.catalogue_item_id,
      litres: f.litres,
      item_name: f.item_name,
    })),
    line_items: lineItems.filter(item => item.description.trim()).map(item => ({
      item_type: item.stock_item_id ? 'part' : (item.item_id ? 'service' : 'service'),
      catalogue_item_id: item.item_id || undefined,
      stock_item_id: item.stock_item_id || undefined,
      description: (item.line_description
        ? `${item.description}\n${item.line_description}`
        : item.description).slice(0, 2000),
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
        navigate(`/invoices/${editId}`)
      } else {
        const res = await apiClient.post('/invoices', buildPayload('draft'))
        const newId = (res.data as any)?.id || (res.data as any)?.invoice?.id
        navigate(newId ? `/invoices/${newId}` : '/invoices')
      }
    } catch (err: unknown) {
      const msg = extractErrorMsg((err as any)?.response?.data?.detail, 'Failed to save draft. Please try again.')
      setErrors({ submit: msg })
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
        navigate(`/invoices/${editId}`)
      } else {
        const res = await apiClient.post('/invoices', buildPayload('sent'))
        const newId = (res.data as any)?.id || (res.data as any)?.invoice?.id
        navigate(newId ? `/invoices/${newId}` : '/invoices')
      }
    } catch (err: unknown) {
      const msg = extractErrorMsg((err as any)?.response?.data?.detail, 'Failed to send invoice. Please try again.')
      setErrors({ submit: msg })
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

      // 4. Send email (fire-and-forget — don't block UI)
      apiClient.post(`/invoices/${invoiceId}/email`).catch(() => {})

      setPaidModalOpen(false)
      navigate(`/invoices/${invoiceId}`)
    } catch {
      setErrors({ submit: 'Failed to process. Please try again.' })
    } finally {
      setPaidSaving(false)
    }
  }

  const handleCancel = () => {
    if (isEditMode && editId) {
      navigate(`/invoices/${editId}`)
    } else {
      navigate('/invoices')
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
    <div className="bg-gray-100 min-h-full">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <h1 className="text-lg font-semibold text-gray-900">{isEditMode ? 'Edit Invoice' : 'New Invoice'}</h1>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={handleCancel}>Cancel</Button>
            <Button variant="secondary" size="sm" onClick={handleSaveDraft} loading={saving}>Save as Draft</Button>
            <Button variant="secondary" size="sm" onClick={() => { if (validate()) setPaidModalOpen(true) }} loading={paidSaving}>Mark Paid &amp; Email</Button>
            <Button size="sm" onClick={handleSaveAndSend} loading={saving}>Save and Send</Button>
          </div>
        </div>
      </div>

      <div className="px-6 py-8">
        <div className="max-w-4xl mx-auto bg-white rounded-xl shadow-lg border border-gray-200 p-8 space-y-6">
          
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
              
              {/* Vehicle Search — only shown when vehicles module is enabled and trade is automotive */}
              {isAutomotive && <ModuleGate module="vehicles">
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
                      <div className="mt-2 flex items-center gap-2">
                        <label className="text-xs text-gray-500 whitespace-nowrap">WOF Expiry:</label>
                        <input
                          type="date"
                          value={v.newWofExpiry ?? v.wof_expiry ?? ''}
                          onChange={(e) => {
                            const val = e.target.value || null
                            setVehicles(prev => prev.map((veh, i) => i === index ? { ...veh, newWofExpiry: val } : veh))
                          }}
                          className="w-40 rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        {v.wof_expiry && !v.newWofExpiry && (
                          <span className="text-xs text-gray-400">
                            Current: {new Date(v.wof_expiry).toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' })}
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
              </ModuleGate>}
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

          {/* Line Items */}
          <div>
            {errors.lineItems && <p className="text-sm text-red-600 mb-2">{errors.lineItems}</p>}
            
            <div className="overflow-visible border border-gray-200 rounded-lg">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <th className="py-3 px-2">Details</th>
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
              <Button variant="secondary" size="sm" onClick={openStockPicker}>+ Add from Inventory</Button>
              {isAutomotive && vehiclesEnabled && (
                <>
                  <Button variant="secondary" size="sm" onClick={openLabourPicker}>+ Labour Charge</Button>
                </>
              )}
              <Button variant="secondary" size="sm" disabled>
                Add Items in Bulk
              </Button>
            </div>
          </div>

          {/* Fluid / Oil Usage Tracking (not invoiced — inventory tracking only) */}
          {isAutomotive && vehiclesEnabled && vehicles.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>
                  <span className="text-sm font-medium text-amber-900">Oil / Fluid Used</span>
                  <span className="text-xs text-amber-600">(tracked against vehicle — not added to invoice total)</span>
                </div>
                <Button variant="secondary" size="sm" onClick={openFluidPicker}>+ Add Fluid</Button>
              </div>
              {fluidUsages.length > 0 && (
                <div className="space-y-2">
                  {fluidUsages.map(f => (
                    <div key={f.key} className="flex items-center gap-3 bg-white rounded-md border border-amber-100 px-3 py-2">
                      <span className="flex-1 text-sm text-gray-900">{f.item_name}</span>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          min="0.1"
                          step="0.1"
                          value={f.litres}
                          onChange={e => updateFluidLitres(f.key, parseFloat(e.target.value) || 0)}
                          className="w-20 rounded border border-gray-300 px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        <span className="text-xs text-gray-500">L</span>
                      </div>
                      <button type="button" onClick={() => removeFluidUsage(f.key)} className="text-gray-400 hover:text-red-500 p-1" aria-label="Remove">
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {fluidUsages.length === 0 && (
                <p className="text-xs text-amber-700">No fluids recorded. Click "+ Add Fluid" to track oil/fluid used on this vehicle.</p>
              )}
            </div>
          )}

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
          <div className="flex justify-end gap-2 pt-4 border-t border-gray-200">
            <Button variant="secondary" size="sm" onClick={handleCancel}>Cancel</Button>
            <Button variant="secondary" size="sm" onClick={handleSaveDraft} loading={saving}>Save as Draft</Button>
            <Button variant="secondary" size="sm" onClick={() => { if (validate()) setPaidModalOpen(true) }} loading={paidSaving}>Mark Paid &amp; Email</Button>
            <Button size="sm" onClick={handleSaveAndSend} loading={saving}>Save and Send</Button>
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

      {/* Inventory Stock Picker Modal */}
      <Modal open={stockPickerOpen} onClose={() => setStockPickerOpen(false)} title="Add from Inventory">
        <div className="space-y-3">
          <input type="text" placeholder="Search by name, part number, brand..." value={stockSearch} onChange={e => setStockSearch(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
          <div className="flex gap-2">
            {(['all', 'part', 'tyre'] as const).map(f => (
              <button key={f} type="button" onClick={() => setStockFilter(f)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${stockFilter === f ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1) + 's'}
              </button>
            ))}
          </div>
          {stockLoading ? <div className="py-8 text-center text-sm text-gray-500">Loading inventory...</div> : (
            <div className="max-h-80 overflow-y-auto divide-y divide-gray-100">
              {stockItems
                .filter(si => si.catalogue_type !== 'fluid')
                .filter(si => stockFilter === 'all' || si.catalogue_type === stockFilter)
                .filter(si => !stockSearch || si.item_name.toLowerCase().includes(stockSearch.toLowerCase()) || (si.part_number && si.part_number.toLowerCase().includes(stockSearch.toLowerCase())) || (si.brand && si.brand.toLowerCase().includes(stockSearch.toLowerCase())))
                .filter(si => si.available_quantity > 0)
                .map(si => (
                <button key={si.id} onClick={() => addStockLineItem(si)} className="w-full text-left px-3 py-2.5 hover:bg-blue-50 flex items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">{si.item_name}</div>
                    <div className="text-xs text-gray-500 flex flex-wrap gap-x-2">
                      {si.part_number && <span>{si.part_number}</span>}
                      <span className="capitalize">{si.catalogue_type}</span>
                      {si.brand && <span>· {si.brand}</span>}
                      {si.subtitle && <span>· {si.subtitle}</span>}
                      {si.location && <span>· 📍 {si.location}</span>}
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      Available: {si.available_quantity}{si.catalogue_type === 'fluid' ? 'L' : ' units'}
                      {si.reserved_quantity > 0 && <span className="ml-1 text-orange-500">({si.reserved_quantity} held)</span>}
                      {si.supplier_name && <span> · {si.supplier_name}</span>}
                      {si.gst_mode === 'inclusive' && <span className="ml-1 text-amber-600">(GST inc.)</span>}
                      {si.gst_mode === 'exempt' && <span className="ml-1 text-amber-600">(GST exempt)</span>}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-medium text-gray-900">{si.sell_price != null ? formatNZD(si.sell_price) : '—'}</div>
                    <div className="text-xs text-gray-500">{si.catalogue_type === 'fluid' ? '/L' : '/unit'}</div>
                  </div>
                </button>
              ))}
              {stockItems.filter(si => si.available_quantity > 0).length === 0 && !stockLoading && <div className="py-8 text-center text-sm text-gray-500">No items in stock.</div>}
            </div>
          )}
        </div>
      </Modal>

      {/* Labour Picker Modal */}
      <Modal open={labourPickerOpen} onClose={() => setLabourPickerOpen(false)} title="Add Labour Charge">
        {labourLoading ? <div className="py-8 text-center text-sm text-gray-500">Loading...</div> : (
          <div className="max-h-64 overflow-y-auto divide-y divide-gray-100">
            {labourRates.map(rate => (
              <button key={rate.id} onClick={() => addLabourLineItem(rate)} className="w-full text-left px-3 py-2.5 hover:bg-blue-50 flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900">{rate.name}</span>
                <span className="text-sm font-medium text-gray-900">${rate.hourly_rate}/hr</span>
              </button>
            ))}
            {labourRates.length === 0 && !labourLoading && <div className="py-8 text-center text-sm text-gray-500">No labour rates configured.</div>}
          </div>
        )}
      </Modal>

      {/* Fluid / Oil Picker Modal */}
      <Modal open={fluidPickerOpen} onClose={() => setFluidPickerOpen(false)} title="Add Oil / Fluid Usage">
        <div className="space-y-3">
          <p className="text-xs text-gray-500">Select a fluid from inventory to track usage against this vehicle. This will not be added to the invoice total — it only decrements stock.</p>
          <input type="text" placeholder="Search fluids..." value={fluidSearch} onChange={e => setFluidSearch(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
          {fluidLoading ? <div className="py-8 text-center text-sm text-gray-500">Loading...</div> : (
            <div className="max-h-64 overflow-y-auto divide-y divide-gray-100">
              {fluidItems
                .filter(si => !fluidSearch || si.item_name.toLowerCase().includes(fluidSearch.toLowerCase()) || (si.brand && si.brand.toLowerCase().includes(fluidSearch.toLowerCase())))
                .map(si => (
                <button key={si.id} onClick={() => addFluidUsage(si)} className="w-full text-left px-3 py-2.5 hover:bg-amber-50 flex items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900">{si.item_name}</div>
                    <div className="text-xs text-gray-500">
                      {si.brand && <span>{si.brand} · </span>}
                      Available: {si.available_quantity}L
                      {si.reserved_quantity > 0 && <span className="text-orange-500"> ({si.reserved_quantity}L held)</span>}
                      {si.supplier_name && <span> · {si.supplier_name}</span>}
                      {si.location && <span> · 📍 {si.location}</span>}
                    </div>
                  </div>
                  <span className="text-xs text-gray-400 shrink-0">{si.available_quantity}L avail</span>
                </button>
              ))}
              {fluidItems.length === 0 && !fluidLoading && <div className="py-8 text-center text-sm text-gray-500">No fluids in stock.</div>}
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
