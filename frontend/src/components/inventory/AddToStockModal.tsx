import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import apiClient from '../../api/client'
import { Modal, Button, FormField, Badge, Spinner } from '../ui'
import { useToast, ToastContainer } from '../ui/Toast'
import { useTenant } from '../../contexts/TenantContext'
import { InlineCreateForm } from './InlineCreateForm'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AddToStockModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

type Category = 'part' | 'tyre' | 'fluid'
type Step = 'category' | 'catalogue' | 'details'

interface CatalogueItem {
  id: string
  name: string
  part_number?: string | null
  brand?: string | null
  supplier_id?: string | null
  supplier_name?: string | null
  description?: string | null
  // Pricing
  sell_price?: string | null
  purchase_price?: string | null
  cost_per_unit?: string | null
  margin_pct?: string | null
  margin_amount?: string | null
  // Packaging
  qty_per_pack?: number | null
  total_packs?: number | null
  packaging_type?: string | null
  // Tyre-specific
  tyre_size?: string | null
  // Fluid-specific
  fluid_type?: string | null
  grade?: string | null
  pack_size?: string | null
  // General
  part_type?: string | null
  category_name?: string | null
}

interface PartCatalogueEntry {
  id: string
  name: string
  part_number?: string | null
  brand?: string | null
  supplier_id?: string | null
  supplier_name?: string | null
  description?: string | null
  part_type: string
  is_active: boolean
  default_price?: string | null
  purchase_price?: string | null
  sell_price_per_unit?: string | null
  cost_per_unit?: string | null
  margin_pct?: string | null
  margin?: string | null
  category_name?: string | null
  packaging_type?: string | null
  qty_per_pack?: number | null
  total_packs?: number | null
  tyre_width?: string | null
  tyre_profile?: string | null
  tyre_rim_dia?: string | null
  tyre_load_index?: string | null
  tyre_speed_index?: string | null
}

interface FluidCatalogueEntry {
  id: string
  product_name?: string | null
  brand_name?: string | null
  supplier_id?: string | null
  description?: string | null
  fluid_type: string
  oil_type?: string | null
  grade?: string | null
  is_active: boolean
  purchase_price?: string | number | null
  sell_price_per_unit?: string | number | null
  cost_per_unit?: string | number | null
  margin_pct?: string | number | null
  margin?: string | number | null
  pack_size?: string | null
  qty_per_pack?: number | null
  total_quantity?: number | null
}

interface StockItemRecord {
  catalogue_item_id: string
}

const REASON_OPTIONS = [
  { value: 'Purchase Order received', label: 'Purchase Order received' },
  { value: 'Initial stock count', label: 'Initial stock count' },
  { value: 'Transfer in', label: 'Transfer in' },
  { value: 'Other', label: 'Other' },
]

const inputClassName =
  'h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500'

const selectClassName =
  'h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500'

/* ------------------------------------------------------------------ */
/*  Category icons (inline SVG)                                        */
/* ------------------------------------------------------------------ */

function PartsIcon() {
  return (
    <svg className="h-10 w-10 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085" />
    </svg>
  )
}

function TyresIcon() {
  return (
    <svg className="h-10 w-10 text-gray-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <circle cx="12" cy="12" r="9" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="4" strokeLinecap="round" strokeLinejoin="round" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v5M12 16v5M3 12h5M16 12h5" />
    </svg>
  )
}

function FluidsIcon() {
  return (
    <svg className="h-10 w-10 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
    </svg>
  )
}

const CATEGORIES: { key: Category; label: string; icon: () => React.JSX.Element; automotiveOnly?: boolean }[] = [
  { key: 'part', label: 'Parts', icon: PartsIcon },
  { key: 'tyre', label: 'Tyres', icon: TyresIcon, automotiveOnly: true },
  { key: 'fluid', label: 'Fluids / Oils', icon: FluidsIcon, automotiveOnly: true },
]

/**
 * Determines whether a category is visible for a given trade family.
 * Tyres and fluids are only visible for 'automotive-transport'.
 * Parts are always visible.
 * When tradeFamily is null/undefined, defaults to 'automotive-transport' (all categories visible).
 */
export function isCategoryVisibleForTradeFamily(
  category: string,
  tradeFamily: string | null | undefined,
): boolean {
  const cat = CATEGORIES.find(c => c.key === category)
  if (!cat) return true // unknown categories are not gated
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  return !cat.automotiveOnly || isAutomotive
}

/* ------------------------------------------------------------------ */
/*  Step 1 — CategorySelector                                         */
/* ------------------------------------------------------------------ */

function CategorySelector({ onSelect }: { onSelect: (cat: Category) => void }) {
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const visibleCategories = CATEGORIES.filter(c => !c.automotiveOnly || isAutomotive)

  return (
    <div>
      <p className="mb-4 text-sm text-gray-600">Select a product category to get started.</p>
      <div className={`grid gap-4 ${visibleCategories.length === 1 ? 'grid-cols-1 max-w-[200px] mx-auto' : visibleCategories.length === 2 ? 'grid-cols-2' : 'grid-cols-3'}`}>
        {visibleCategories.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => onSelect(key)}
            className="flex flex-col items-center gap-3 rounded-lg border border-gray-200 bg-white p-6 shadow-sm transition-all hover:border-blue-400 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            aria-label={`Select ${label}`}
          >
            <Icon />
            <span className="text-sm font-medium text-gray-900">{label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 2 — CataloguePicker                                           */
/* ------------------------------------------------------------------ */

const CATEGORY_SINGULAR_LABELS: Record<Category, string> = {
  part: 'Part',
  tyre: 'Tyre',
  fluid: 'Fluid/Oil',
}

function CataloguePicker({
  category,
  onSelect,
  onBack,
  existingStockItemIds,
  onCreateNew,
}: {
  category: Category
  onSelect: (item: CatalogueItem) => void
  onBack: () => void
  existingStockItemIds: Set<string>
  onCreateNew?: () => void
}) {
  const [items, setItems] = useState<CatalogueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    setItems([])

    async function fetchItems() {
      try {
        if (category === 'fluid') {
          const res = await apiClient.get<{ products: FluidCatalogueEntry[] }>(
            '/catalogue/fluids',
            { params: { active_only: true, limit: 500 } },
          )
          if (cancelled) return
          setItems(
            (res.data?.products ?? []).map((f) => ({
              id: String(f.id),
              name: f.product_name || `${f.fluid_type}${f.oil_type ? ` – ${f.oil_type}` : ''}${f.grade ? ` ${f.grade}` : ''}`,
              brand: f.brand_name,
              supplier_id: f.supplier_id ? String(f.supplier_id) : null,
              description: f.description,
              sell_price: f.sell_price_per_unit != null ? String(f.sell_price_per_unit) : null,
              purchase_price: f.purchase_price != null ? String(f.purchase_price) : null,
              cost_per_unit: f.cost_per_unit != null ? String(f.cost_per_unit) : null,
              margin_pct: f.margin_pct != null ? String(f.margin_pct) : null,
              margin_amount: f.margin != null ? String(f.margin) : null,
              qty_per_pack: f.qty_per_pack ? Number(f.qty_per_pack) : null,
              total_packs: f.total_quantity ? Number(f.total_quantity) : null,
              packaging_type: f.pack_size ? 'pack' : null,
              fluid_type: f.oil_type || f.fluid_type,
              grade: f.grade,
              pack_size: f.pack_size,
              part_type: 'fluid',
            })),
          )
        } else {
          // part or tyre — both come from /catalogue/parts
          const res = await apiClient.get<{ parts: PartCatalogueEntry[] }>(
            '/catalogue/parts',
            { params: { active_only: true, limit: 500 } },
          )
          if (cancelled) return
          const filtered = (res.data?.parts ?? []).filter((p) => p.part_type === category)
          setItems(
            filtered.map((p) => {
              // Build tyre size string from components
              const tyreParts = [p.tyre_width, p.tyre_profile ? `/${p.tyre_profile}` : null, p.tyre_rim_dia ? `R${p.tyre_rim_dia}` : null].filter(Boolean)
              const tyreSize = tyreParts.length > 0 ? tyreParts.join('') : null
              const tyreExtra = [p.tyre_load_index, p.tyre_speed_index].filter(Boolean).join('')

              return {
                id: String(p.id),
                name: p.name,
                part_number: p.part_number,
                brand: p.brand,
                supplier_id: p.supplier_id ? String(p.supplier_id) : null,
                supplier_name: p.supplier_name,
                description: p.description,
                sell_price: p.sell_price_per_unit || p.default_price,
                purchase_price: p.purchase_price,
                cost_per_unit: p.cost_per_unit,
                margin_pct: p.margin_pct,
                margin_amount: p.margin || null,
                packaging_type: p.packaging_type || null,
                qty_per_pack: p.qty_per_pack || null,
                total_packs: p.total_packs || null,
                tyre_size: tyreSize ? `${tyreSize}${tyreExtra ? ` ${tyreExtra}` : ''}` : null,
                part_type: p.part_type,
                category_name: p.category_name,
              }
            }),
          )
        }
      } catch {
        if (!cancelled) setError('Failed to load catalogue items.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchItems()
    return () => { cancelled = true }
  }, [category])

  const filtered = useMemo(() => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter(
      (i) =>
        i.name.toLowerCase().includes(q) ||
        (i.part_number && i.part_number.toLowerCase().includes(q)) ||
        (i.brand && i.brand.toLowerCase().includes(q)) ||
        (i.description && i.description.toLowerCase().includes(q)) ||
        (i.tyre_size && i.tyre_size.toLowerCase().includes(q)),
    )
  }, [items, search])

  const categoryLabel = CATEGORIES.find((c) => c.key === category)?.label ?? category
  const singularLabel = CATEGORY_SINGULAR_LABELS[category] ?? category

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onBack} type="button" aria-label="Back to category selection">
          ← Back
        </Button>
        <span className="text-sm font-medium text-gray-700">
          Select a {categoryLabel.toLowerCase()} item
        </span>
      </div>

      <div className="mb-3">
        <input
          type="text"
          className={inputClassName}
          placeholder={`Search ${categoryLabel.toLowerCase()} by name, part number, or brand…`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={`Search ${categoryLabel.toLowerCase()} catalogue`}
        />
      </div>

      {error && (
        <div className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && <Spinner label="Loading catalogue items" />}

      {!loading && items.length === 0 && !error && (
        <div className="rounded-md border border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          {onCreateNew ? (
            <>
              <p className="mb-3">No active {categoryLabel.toLowerCase()} items found.</p>
              <Button variant="secondary" size="sm" onClick={onCreateNew} type="button">
                + Create New {singularLabel}
              </Button>
            </>
          ) : (
            <>No active {categoryLabel.toLowerCase()} items found. Add items to the catalogue first.</>
          )}
        </div>
      )}

      {!loading && items.length > 0 && filtered.length === 0 && (
        <div className="rounded-md border border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
          {onCreateNew ? (
            <>
              <p className="mb-3">No items match your search.</p>
              <Button variant="secondary" size="sm" onClick={onCreateNew} type="button">
                + Create New {singularLabel}
              </Button>
            </>
          ) : (
            <>No items match your search.</>
          )}
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="max-h-64 overflow-y-auto rounded-md border border-gray-200 divide-y divide-gray-100">
          {filtered.map((item) => {
            const alreadyInStock = existingStockItemIds.has(item.id)
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelect(item)}
                className={`flex w-full items-center justify-between px-4 py-3 text-left transition-colors
                  hover:bg-blue-50 focus-visible:bg-blue-50
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500`}
                aria-label={`${item.name}${alreadyInStock ? ' (in stock — will add to existing)' : ''}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {item.name}
                    {item.tyre_size && <span className="font-normal text-gray-500"> ({item.tyre_size})</span>}
                  </p>
                  <p className="text-xs text-gray-500 truncate">
                    {[item.part_number, item.brand].filter(Boolean).join(' · ') || '\u00A0'}
                  </p>
                </div>
                {alreadyInStock && (
                  <Badge variant="neutral" className="ml-2 shrink-0">In stock</Badge>
                )}
              </button>
            )
          })}
        </div>
      )}

      {!loading && filtered.length > 0 && onCreateNew && (
        <div className="mt-3 text-center">
          <Button variant="secondary" size="sm" onClick={onCreateNew} type="button">
            + Create New {singularLabel}
          </Button>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 3 — StockDetailsForm                                          */
/* ------------------------------------------------------------------ */

function StockDetailsForm({
  item,
  onBack,
  onSubmit,
  submitting,
}: {
  item: CatalogueItem
  onBack: () => void
  onSubmit: (data: { quantity: number; reason: string; barcode: string; supplier_id: string; purchase_price?: number; sell_price?: number; cost_per_unit?: number; location?: string }) => void
  submitting: boolean
}) {
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const [barcode, setBarcode] = useState('')
  const [locationText, setLocationText] = useState('')
  const [locationSearch, setLocationSearch] = useState('')
  const [locationDropdownOpen, setLocationDropdownOpen] = useState(false)
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([])
  const [locationsLoading, setLocationsLoading] = useState(false)
  const locationDropRef = useRef<HTMLDivElement>(null)
  const [supplierId, setSupplierId] = useState(item.supplier_id ?? '')
  const [supplierDisplay, setSupplierDisplay] = useState(item.supplier_name ?? '')
  const [supplierSearch, setSupplierSearch] = useState('')
  const [supplierDropdownOpen, setSupplierDropdownOpen] = useState(false)
  const [suppliers, setSuppliers] = useState<{ id: string; name: string }[]>([])
  const [suppliersLoading, setSuppliersLoading] = useState(false)
  const supplierDropRef = useRef<HTMLDivElement>(null)
  const [showNewSupplierModal, setShowNewSupplierModal] = useState(false)
  const [newSupplier, setNewSupplier] = useState({ name: '', contact_name: '', email: '', phone: '', address: '', account_number: '' })
  const [newSupplierSaving, setNewSupplierSaving] = useState(false)
  const [newSupplierError, setNewSupplierError] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [editPricing, setEditPricing] = useState(false)
  const [overrideSellPrice, setOverrideSellPrice] = useState(item.sell_price || '')
  const [overridePurchasePrice, setOverridePurchasePrice] = useState(item.purchase_price || '')

  // Live pricing calculations
  const totalUnits = (item.qty_per_pack || 1) * (item.total_packs || 1)
  const pp = parseFloat(String(overridePurchasePrice)) || 0
  const sp = parseFloat(String(overrideSellPrice)) || 0
  const computedCpu = totalUnits > 0 ? pp / totalUnits : 0
  const computedMargin = sp - computedCpu
  const computedMarginPct = computedCpu > 0 ? (computedMargin / computedCpu) * 100 : 0
  const isFluid = item.part_type === 'fluid'
  const unitLabel = isFluid ? 'Litre' : 'Unit'

  // Fetch suppliers list on mount
  useEffect(() => {
    setSuppliersLoading(true)
    apiClient
      .get<{ suppliers: { id: string; name: string }[] }>('/inventory/suppliers', { params: { limit: 500 } })
      .then((res) => setSuppliers(res.data.suppliers))
      .catch(() => setSuppliers([]))
      .finally(() => setSuppliersLoading(false))
  }, [])

  // Fetch locations list on mount
  useEffect(() => {
    setLocationsLoading(true)
    apiClient
      .get<{ locations: { id: string; name: string }[] }>('/inventory/stock-items/locations')
      .then((res) => setLocations(res.data.locations))
      .catch(() => setLocations([]))
      .finally(() => setLocationsLoading(false))
  }, [])

  // Click outside to close dropdowns
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (supplierDropRef.current && !supplierDropRef.current.contains(e.target as Node)) setSupplierDropdownOpen(false)
      if (locationDropRef.current && !locationDropRef.current.contains(e.target as Node)) setLocationDropdownOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const filteredSuppliers = useMemo(() => {
    if (!supplierSearch.trim()) return suppliers
    const q = supplierSearch.toLowerCase()
    return suppliers.filter((s) => s.name.toLowerCase().includes(q))
  }, [suppliers, supplierSearch])

  const filteredLocations = useMemo(() => {
    if (!locationSearch.trim()) return locations
    const q = locationSearch.toLowerCase()
    return locations.filter((l) => l.name.toLowerCase().includes(q))
  }, [locations, locationSearch])

  const showAddLocationOption = locationSearch.trim().length > 0 &&
    !locations.some((l) => l.name.toLowerCase() === locationSearch.trim().toLowerCase())

  function validate(): Record<string, string> {
    const errs: Record<string, string> = {}
    const qty = parseFloat(quantity)
    if (!quantity || isNaN(qty) || qty <= 0) {
      errs.quantity = 'Quantity must be greater than 0'
    }
    if (!reason) {
      errs.reason = 'Please select a reason'
    }
    return errs
  }

  function handleSubmit() {
    const errs = validate()
    setErrors(errs)
    if (Object.keys(errs).length > 0) return
    onSubmit({
      quantity: parseFloat(quantity),
      reason,
      barcode,
      supplier_id: supplierId,
      purchase_price: overridePurchasePrice ? parseFloat(String(overridePurchasePrice)) : undefined,
      sell_price: overrideSellPrice ? parseFloat(String(overrideSellPrice)) : undefined,
      cost_per_unit: computedCpu > 0 ? computedCpu : undefined,
      location: locationText || undefined,
    })
  }

  const supplierLabel = item.supplier_name
    ? `Auto-populated from catalogue: ${item.supplier_name}`
    : 'No supplier linked in catalogue'

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onBack} type="button" aria-label="Back to catalogue picker">
          ← Back
        </Button>
        <span className="text-sm font-medium text-gray-700 truncate">
          Adding: {item.name}
        </span>
      </div>

      <div className="space-y-4">
        {/* Item details card */}
        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
          <div className="flex justify-end mb-1">
            <button type="button" onClick={() => setEditPricing(!editPricing)} className="text-gray-400 hover:text-blue-600 transition-colors" aria-label="Edit pricing" title={editPricing ? 'Done editing' : 'Edit pricing for this stock entry'}>
              {editPricing ? (
                <span className="text-xs text-blue-600 font-medium">Done</span>
              ) : (
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
              )}
            </button>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            {item.brand && (
              <>
                <span className="text-gray-500">Brand</span>
                <span className="text-gray-900">{item.brand}</span>
              </>
            )}
            {item.part_number && (
              <>
                <span className="text-gray-500">Part Number</span>
                <span className="text-gray-900">{item.part_number}</span>
              </>
            )}
            {item.category_name && (
              <>
                <span className="text-gray-500">Category</span>
                <span className="text-gray-900">{item.category_name}</span>
              </>
            )}
            {item.tyre_size && (
              <>
                <span className="text-gray-500">Tyre Size</span>
                <span className="text-gray-900">{item.tyre_size}</span>
              </>
            )}
            {item.fluid_type && item.part_type === 'fluid' && (
              <>
                <span className="text-gray-500">Type</span>
                <span className="text-gray-900">{item.fluid_type}{item.grade ? ` ${item.grade}` : ''}</span>
              </>
            )}
            {item.pack_size && (
              <>
                <span className="text-gray-500">Pack Size</span>
                <span className="text-gray-900">{item.pack_size}</span>
              </>
            )}
            {item.sell_price && (
              <>
                <span className="text-gray-500">{isFluid ? `Sell Price / ${unitLabel}` : `Sell Price / ${unitLabel}`}</span>
                {editPricing ? (
                  <input type="number" min="0" step="0.01" className="w-full rounded border border-gray-300 px-2 py-0.5 text-sm" value={overrideSellPrice} onChange={e => setOverrideSellPrice(e.target.value)} />
                ) : (
                  <span className="text-gray-900 font-medium">${sp.toFixed(2)}</span>
                )}
              </>
            )}
            {item.purchase_price && (
              <>
                <span className="text-gray-500">Purchase Price{totalUnits > 1 ? ` (${totalUnits} ${isFluid ? 'L' : 'units'})` : ''}</span>
                {editPricing ? (
                  <input type="number" min="0" step="0.01" className="w-full rounded border border-gray-300 px-2 py-0.5 text-sm" value={overridePurchasePrice} onChange={e => setOverridePurchasePrice(e.target.value)} />
                ) : (
                  <span className="text-gray-900">${pp.toFixed(2)}</span>
                )}
              </>
            )}
            {(item.packaging_type || totalUnits > 1) && (
              <>
                <span className="text-gray-500">Packaging</span>
                <span className="text-gray-900">{item.packaging_type || 'single'} — {item.qty_per_pack || 1} × {item.total_packs || 1} = {totalUnits} {isFluid ? 'L' : 'units'}</span>
              </>
            )}
            {pp > 0 && totalUnits > 0 && (
              <>
                <span className="text-gray-500">{isFluid ? `Cost / ${unitLabel}` : `Cost / ${unitLabel}`}</span>
                <span className="text-gray-900">${computedCpu.toFixed(2)}</span>
              </>
            )}
            {sp > 0 && computedCpu > 0 && (
              <>
                <span className="text-gray-500">Profit</span>
                <span className={`font-medium ${computedMargin >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  ${computedMargin.toFixed(2)} ({computedMarginPct.toFixed(1)}%)
                </span>
              </>
            )}
          </div>
          {item.description && (
            <p className="mt-2 text-xs text-gray-500 border-t border-gray-200 pt-2">{item.description}</p>
          )}
        </div>

        <FormField label={isFluid ? 'Quantity (Litres)' : 'Quantity (Individual Units)'} error={errors.quantity} required>
          {(props) => (
            <div>
              <input
                {...props}
                type="number"
                min={1}
                step="any"
                className={inputClassName}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder={isFluid ? 'e.g. 30 (total litres)' : 'e.g. 10 (total individual items)'}
              />
              <p className="mt-1 flex items-center gap-1 text-xs text-blue-600">
                <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                {isFluid
                  ? 'Enter total litres, not number of bottles or packs'
                  : totalUnits > 1
                    ? `Enter total individual units, not number of ${item.packaging_type || 'pack'}s (1 ${item.packaging_type || 'pack'} = ${totalUnits} units)`
                    : 'Enter total individual units, not boxes or packs'
                }
              </p>
            </div>
          )}
        </FormField>

        <FormField label="Reason for adding" error={errors.reason} required>
          {(props) => (
            <select
              {...props}
              className={selectClassName}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              <option value="" disabled>Select a reason…</option>
              {REASON_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          )}
        </FormField>

        <FormField label="Barcode / Code / Serial Number" helperText="Optional — for tracking purposes">
          {(props) => (
            <input
              {...props}
              type="text"
              className={inputClassName}
              value={barcode}
              onChange={(e) => setBarcode(e.target.value)}
              placeholder="Enter barcode or serial number"
            />
          )}
        </FormField>

        <FormField label="Location" helperText="Optional — where this item is stored">
          {(props) => (
            <div className="relative" ref={locationDropRef}>
              {locationText && !locationDropdownOpen ? (
                <div className="flex gap-2">
                  <div className={`${inputClassName} flex items-center bg-gray-50`}>
                    <span className="truncate">{locationText}</span>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => { setLocationSearch(''); setLocationDropdownOpen(true) }}
                    type="button"
                    aria-label="Change location"
                  >
                    Change
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => { setLocationText(''); setLocationSearch('') }}
                    type="button"
                    aria-label="Clear location"
                  >
                    Clear
                  </Button>
                </div>
              ) : (
                <div>
                  <input
                    {...props}
                    type="text"
                    className={inputClassName}
                    value={locationSearch}
                    onChange={(e) => { setLocationSearch(e.target.value); setLocationDropdownOpen(true) }}
                    onFocus={() => setLocationDropdownOpen(true)}
                    placeholder="Search or type a new location…"
                    aria-label="Search locations"
                  />
                  {locationDropdownOpen && (
                    <div className="absolute z-10 mt-1 w-full max-h-40 overflow-y-auto rounded-md border border-gray-200 bg-white shadow-lg">
                      {locationsLoading && (
                        <div className="px-3 py-2 text-sm text-gray-500">Loading…</div>
                      )}
                      {!locationsLoading && filteredLocations.length === 0 && !showAddLocationOption && (
                        <div className="px-3 py-2 text-sm text-gray-500">No locations found. Type to create one.</div>
                      )}
                      {!locationsLoading && filteredLocations.map((l) => (
                        <div key={l.id} className="flex items-center justify-between hover:bg-blue-50">
                          <button
                            type="button"
                            className={`flex-1 px-3 py-2 text-left text-sm focus-visible:outline-none ${l.name === locationText ? 'bg-blue-50 font-medium' : ''}`}
                            onClick={() => {
                              setLocationText(l.name)
                              setLocationSearch('')
                              setLocationDropdownOpen(false)
                            }}
                          >
                            {l.name}
                          </button>
                          <button
                            type="button"
                            className="px-2 py-1 text-gray-400 hover:text-red-600 transition-colors"
                            aria-label={`Delete location ${l.name}`}
                            onClick={async (e) => {
                              e.stopPropagation()
                              try {
                                await apiClient.delete(`/inventory/stock-items/locations/${l.id}`)
                                setLocations((prev) => prev.filter((loc) => loc.id !== l.id))
                              } catch { /* ignore */ }
                            }}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                      {showAddLocationOption && (
                        <button
                          type="button"
                          className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm text-blue-600 hover:bg-blue-50 font-medium"
                          onClick={async () => {
                            const name = locationSearch.trim()
                            try {
                              const res = await apiClient.post<{ id: string; name: string; created_at: string }>(
                                '/inventory/stock-items/locations',
                                { name },
                              )
                              setLocations((prev) => [...prev, { id: res.data.id, name: res.data.name }])
                              setLocationText(res.data.name)
                            } catch {
                              // If creation fails (e.g. duplicate), just use the text
                              setLocationText(name)
                            }
                            setLocationSearch('')
                            setLocationDropdownOpen(false)
                          }}
                        >
                          + Add location &lsquo;{locationSearch.trim()}&rsquo;
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </FormField>

        <FormField label="Supplier" helperText={supplierLabel}>
          {(props) => (
            <div className="relative">
              {/* Selected supplier display or search input */}
              {supplierId && !supplierDropdownOpen ? (
                <div className="flex gap-2">
                  <div className={`${inputClassName} flex items-center bg-gray-50`}>
                    <span className="truncate">{supplierDisplay}</span>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setSupplierDropdownOpen(true)}
                    type="button"
                    aria-label="Change supplier"
                  >
                    Change
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => { setSupplierId(''); setSupplierDisplay(''); setSupplierSearch('') }}
                    type="button"
                    aria-label="Clear supplier"
                  >
                    Clear
                  </Button>
                </div>
              ) : (
                <div>
                  <input
                    {...props}
                    type="text"
                    className={inputClassName}
                    value={supplierSearch}
                    onChange={(e) => { setSupplierSearch(e.target.value); setSupplierDropdownOpen(true) }}
                    onFocus={() => setSupplierDropdownOpen(true)}
                    placeholder="Search suppliers…"
                    aria-label="Search suppliers"
                  />
                  {supplierDropdownOpen && (
                    <div className="absolute z-10 mt-1 w-full max-h-40 overflow-y-auto rounded-md border border-gray-200 bg-white shadow-lg">
                      {suppliersLoading && (
                        <div className="px-3 py-2 text-sm text-gray-500">Loading…</div>
                      )}
                      {!suppliersLoading && filteredSuppliers.length === 0 && (
                        <div className="px-3 py-2 text-sm text-gray-500">No suppliers found</div>
                      )}
                      {!suppliersLoading && filteredSuppliers.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          className={`w-full px-3 py-2 text-left text-sm hover:bg-blue-50 focus-visible:bg-blue-50 focus-visible:outline-none ${s.id === supplierId ? 'bg-blue-50 font-medium' : ''}`}
                          onClick={() => {
                            setSupplierId(s.id)
                            setSupplierDisplay(s.name)
                            setSupplierSearch('')
                            setSupplierDropdownOpen(false)
                          }}
                        >
                          {s.name}
                        </button>
                      ))}
                      {supplierId && (
                        <button
                          type="button"
                          className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                          onClick={() => {
                            setSupplierId('')
                            setSupplierDisplay('')
                            setSupplierSearch('')
                            setSupplierDropdownOpen(false)
                          }}
                        >
                          Clear supplier
                        </button>
                      )}
                      <button
                        type="button"
                        className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm font-medium text-blue-600 hover:bg-blue-50"
                        onClick={() => {
                          setNewSupplier({ name: supplierSearch.trim(), contact_name: '', email: '', phone: '', address: '', account_number: '' })
                          setNewSupplierError('')
                          setShowNewSupplierModal(true)
                          setSupplierDropdownOpen(false)
                        }}
                      >
                        + Add New Supplier{supplierSearch.trim() ? ` "${supplierSearch.trim()}"` : ''}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </FormField>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" size="sm" onClick={onBack} disabled={submitting} type="button">
            Back
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            loading={submitting}
            disabled={submitting}
            type="button"
          >
            {submitting ? 'Adding…' : 'Add to Stock'}
          </Button>
        </div>
      </div>

      {/* New Supplier Modal */}
      <Modal open={showNewSupplierModal} onClose={() => setShowNewSupplierModal(false)} title="New Supplier">
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Supplier name *</label>
            <input type="text" value={newSupplier.name} onChange={e => setNewSupplier(p => ({ ...p, name: e.target.value }))}
              className={inputClassName} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Contact person</label>
            <input type="text" value={newSupplier.contact_name} onChange={e => setNewSupplier(p => ({ ...p, contact_name: e.target.value }))}
              className={inputClassName} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input type="email" value={newSupplier.email} onChange={e => setNewSupplier(p => ({ ...p, email: e.target.value }))}
                className={inputClassName} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
              <input type="text" value={newSupplier.phone} onChange={e => setNewSupplier(p => ({ ...p, phone: e.target.value }))}
                className={inputClassName} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Address</label>
            <input type="text" value={newSupplier.address} onChange={e => setNewSupplier(p => ({ ...p, address: e.target.value }))}
              className={inputClassName} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Account number</label>
            <input type="text" value={newSupplier.account_number} onChange={e => setNewSupplier(p => ({ ...p, account_number: e.target.value }))}
              className={inputClassName} placeholder="Your account # with this supplier" />
          </div>
          {newSupplierError && <p className="text-sm text-red-600">{newSupplierError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" onClick={() => setShowNewSupplierModal(false)}>Cancel</Button>
            <Button variant="primary" size="sm" loading={newSupplierSaving} onClick={async () => {
              if (!newSupplier.name.trim()) { setNewSupplierError('Supplier name is required'); return }
              setNewSupplierSaving(true)
              setNewSupplierError('')
              try {
                const body: Record<string, string> = { name: newSupplier.name.trim() }
                if (newSupplier.contact_name.trim()) body.contact_name = newSupplier.contact_name.trim()
                if (newSupplier.email.trim()) body.email = newSupplier.email.trim()
                if (newSupplier.phone.trim()) body.phone = newSupplier.phone.trim()
                if (newSupplier.address.trim()) body.address = newSupplier.address.trim()
                if (newSupplier.account_number.trim()) body.account_number = newSupplier.account_number.trim()
                const res = await apiClient.post<any>('/inventory/suppliers', body)
                const created = res.data.supplier || res.data
                setSuppliers(prev => [...prev, { id: created.id, name: created.name }])
                setSupplierId(created.id)
                setSupplierDisplay(created.name)
                setShowNewSupplierModal(false)
                setNewSupplier({ name: '', contact_name: '', email: '', phone: '', address: '', account_number: '' })
              } catch (err: any) {
                setNewSupplierError(err?.response?.data?.detail || 'Failed to create supplier')
              } finally { setNewSupplierSaving(false) }
            }}>Create Supplier</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Modal Component                                               */
/* ------------------------------------------------------------------ */

export function AddToStockModal({ isOpen, onClose, onSuccess }: AddToStockModalProps) {
  const { toasts, addToast, dismissToast } = useToast()
  const { tradeFamily } = useTenant()

  const [step, setStep] = useState<Step>('category')
  const [selectedCategory, setSelectedCategory] = useState<Category | null>(null)
  const [selectedItem, setSelectedItem] = useState<CatalogueItem | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [apiError, setApiError] = useState('')
  const [existingStockItemIds, setExistingStockItemIds] = useState<Set<string>>(new Set())
  const [showInlineCreate, setShowInlineCreate] = useState(false)

  // Reset state when modal opens/closes
  useEffect(() => {
    if (isOpen) {
      setStep('category')
      setSelectedCategory(null)
      setSelectedItem(null)
      setSubmitting(false)
      setApiError('')
      setShowInlineCreate(false)
      // Fetch existing stock items to mark "already in stock"
      apiClient
        .get<{ stock_items: StockItemRecord[] }>('/inventory/stock-items', { params: { limit: 500 } })
        .then((res) => {
          setExistingStockItemIds(new Set((res.data?.stock_items ?? []).map((s) => s.catalogue_item_id)))
        })
        .catch(() => {
          // Non-critical — badge just won't show
          setExistingStockItemIds(new Set())
        })
    }
  }, [isOpen])

  const handleCategorySelect = useCallback((cat: Category) => {
    setSelectedCategory(cat)
    setStep('catalogue')
    setApiError('')
  }, [])

  const handleItemSelect = useCallback((item: CatalogueItem) => {
    setSelectedItem(item)
    setStep('details')
    setApiError('')
  }, [])

  const handleBackToCatalogue = useCallback(() => {
    setStep('catalogue')
    setSelectedItem(null)
    setApiError('')
    setShowInlineCreate(false)
  }, [])

  const handleBackToCategory = useCallback(() => {
    setStep('category')
    setSelectedCategory(null)
    setSelectedItem(null)
    setApiError('')
    setShowInlineCreate(false)
  }, [])

  const handleSubmit = useCallback(
    async (data: { quantity: number; reason: string; barcode: string; supplier_id: string; purchase_price?: number; sell_price?: number; cost_per_unit?: number; location?: string }) => {
      if (!selectedItem || !selectedCategory) return

      setSubmitting(true)
      setApiError('')

      try {
        await apiClient.post('/inventory/stock-items', {
          catalogue_item_id: selectedItem.id,
          catalogue_type: selectedCategory,
          quantity: data.quantity,
          reason: data.reason,
          barcode: data.barcode || null,
          supplier_id: data.supplier_id || null,
          purchase_price: data.purchase_price ?? null,
          sell_price: data.sell_price ?? null,
          cost_per_unit: data.cost_per_unit ?? null,
          location: data.location || null,
        })
        addToast('success', `${selectedItem.name} added to stock`)
        onClose()
        onSuccess()
      } catch (err: unknown) {
        const axiosErr = err as { response?: { data?: { detail?: string } } }
        const detail = axiosErr?.response?.data?.detail
        if (detail) {
          setApiError(detail)
        } else {
          setApiError('Something went wrong. Please try again.')
        }
      } finally {
        setSubmitting(false)
      }
    },
    [selectedItem, selectedCategory, addToast, onClose, onSuccess],
  )

  const stepTitle = step === 'category'
    ? 'Add to Stock'
    : step === 'catalogue'
      ? 'Select Item'
      : 'Stock Details'

  return (
    <>
      <Modal open={isOpen} onClose={onClose} title={stepTitle}>
        <div className="space-y-4">
          {apiError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
              {apiError}
            </div>
          )}

          {step === 'category' && (
            <CategorySelector onSelect={handleCategorySelect} />
          )}

          {step === 'catalogue' && selectedCategory && !showInlineCreate && (
            <CataloguePicker
              category={selectedCategory}
              onSelect={handleItemSelect}
              onBack={handleBackToCategory}
              existingStockItemIds={existingStockItemIds}
              onCreateNew={
                isCategoryVisibleForTradeFamily(selectedCategory, tradeFamily)
                  ? () => setShowInlineCreate(true)
                  : undefined
              }
            />
          )}

          {step === 'catalogue' && selectedCategory && showInlineCreate && (
            <InlineCreateForm
              category={selectedCategory}
              onCancel={() => setShowInlineCreate(false)}
              onSuccess={(item) => {
                setShowInlineCreate(false)
                setSelectedItem(item)
                setStep('details')
                setApiError('')
              }}
            />
          )}

          {step === 'details' && selectedItem && selectedCategory && (
            <StockDetailsForm
              item={selectedItem}
              onBack={handleBackToCatalogue}
              onSubmit={handleSubmit}
              submitting={submitting}
            />
          )}
        </div>
      </Modal>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}
