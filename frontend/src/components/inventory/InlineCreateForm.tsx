import { useState } from 'react'
import apiClient from '../../api/client'
import { Button, FormField } from '../ui'

/* ------------------------------------------------------------------ */
/*  Types — re-exported from AddToStockModal for shared use            */
/* ------------------------------------------------------------------ */

export type Category = 'part' | 'tyre' | 'fluid' | 'service'

export interface CatalogueItem {
  id: string
  name: string
  part_number?: string | null
  brand?: string | null
  supplier_id?: string | null
  supplier_name?: string | null
  description?: string | null
  sell_price?: string | null
  purchase_price?: string | null
  cost_per_unit?: string | null
  margin_pct?: string | null
  margin_amount?: string | null
  qty_per_pack?: number | null
  total_packs?: number | null
  packaging_type?: string | null
  tyre_size?: string | null
  fluid_type?: string | null
  grade?: string | null
  pack_size?: string | null
  part_type?: string | null
  category_name?: string | null
}

export interface InlineCreateFormProps {
  category: Category
  onSuccess: (item: CatalogueItem) => void
  onCancel: () => void
}

/* ------------------------------------------------------------------ */
/*  Category labels — mirrors CATEGORIES in AddToStockModal            */
/* ------------------------------------------------------------------ */

const CATEGORY_LABELS: Record<Category, string> = {
  part: 'Part',
  tyre: 'Tyre',
  fluid: 'Fluid/Oil',
  service: 'Service',
}

type GstMode = 'inclusive' | 'exclusive' | 'exempt'

const GST_MODES: { value: GstMode; label: string }[] = [
  { value: 'inclusive', label: 'Inclusive' },
  { value: 'exclusive', label: 'Exclusive' },
  { value: 'exempt', label: 'Exempt' },
]

/* ------------------------------------------------------------------ */
/*  Shared styles — same as AddToStockModal                            */
/* ------------------------------------------------------------------ */

const inputClassName =
  'h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500'

const selectClassName =
  'h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500'

/* ------------------------------------------------------------------ */
/*  Form state interfaces per category                                 */
/* ------------------------------------------------------------------ */

export interface PartFormState {
  name: string
  sell_price_per_unit: string
  purchase_price: string
  gst_mode: GstMode
  part_number: string
  brand: string
  description: string
  packaging_type: string
  qty_per_pack: string
  total_packs: string
}

export interface TyreFormState {
  name: string
  sell_price_per_unit: string
  purchase_price: string
  gst_mode: GstMode
  tyre_width: string
  tyre_profile: string
  tyre_rim_dia: string
  tyre_load_index: string
  tyre_speed_index: string
  brand: string
  packaging_type: string
  qty_per_pack: string
  total_packs: string
}

export interface FluidFormState {
  product_name: string
  sell_price_per_unit: string
  gst_mode: GstMode
  fluid_type: 'oil' | 'non-oil'
  oil_type: string
  grade: string
  brand_name: string
}

export interface ServiceFormState {
  name: string
  default_price: string
  gst_mode: GstMode
  description: string
}

/* ------------------------------------------------------------------ */
/*  GST Mode Segmented Toggle                                          */
/* ------------------------------------------------------------------ */

function GstModeToggle({
  value,
  onChange,
  id,
}: {
  value: GstMode
  onChange: (mode: GstMode) => void
  id?: string
}) {
  return (
    <div
      id={id}
      className="inline-flex rounded-md border border-gray-300 overflow-hidden"
      role="radiogroup"
      aria-label="GST mode"
    >
      {GST_MODES.map((mode) => (
        <button
          key={mode.value}
          type="button"
          role="radio"
          aria-checked={value === mode.value}
          onClick={() => onChange(mode.value)}
          className={`px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset ${
            value === mode.value
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-700 hover:bg-gray-50'
          }`}
        >
          {mode.label}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Validation                                                         */
/* ------------------------------------------------------------------ */

/** Errors keyed by field name */
export type FormErrors = Record<string, string>

const VALID_GST_MODES: readonly string[] = ['inclusive', 'exclusive', 'exempt']

function isValidPositiveNumber(value: string): boolean {
  if (value.trim() === '') return false
  const num = Number(value)
  return !isNaN(num) && num > 0
}

/**
 * Pure validation function — exported for testability / property tests.
 * Returns an errors object; empty object means valid.
 */
export function validateForm(
  category: Category,
  form: PartFormState | TyreFormState | FluidFormState | ServiceFormState,
): FormErrors {
  const errors: FormErrors = {}

  // Name / product_name
  if (category === 'fluid') {
    const f = form as FluidFormState
    if (!f.product_name.trim()) errors.product_name = 'Product name is required'
  } else {
    const f = form as PartFormState | TyreFormState | ServiceFormState
    if (!f.name.trim()) errors.name = 'Name is required'
  }

  // Price
  if (category === 'service') {
    const f = form as ServiceFormState
    if (!isValidPositiveNumber(f.default_price)) errors.default_price = 'A valid positive price is required'
  } else {
    const f = form as PartFormState | TyreFormState | FluidFormState
    if (!isValidPositiveNumber(f.sell_price_per_unit)) errors.sell_price_per_unit = 'A valid positive price is required'
  }

  // GST mode
  if (!VALID_GST_MODES.includes(form.gst_mode)) errors.gst_mode = 'GST mode must be inclusive, exclusive, or exempt'

  // Fluid-specific: fluid_type
  if (category === 'fluid') {
    const f = form as FluidFormState
    if (f.fluid_type !== 'oil' && f.fluid_type !== 'non-oil') errors.fluid_type = 'Fluid type must be oil or non-oil'
  }

  return errors
}

/* ------------------------------------------------------------------ */
/*  API endpoint mapping — exported for property tests (task 1.5)      */
/* ------------------------------------------------------------------ */

/**
 * Returns the catalogue API endpoint for a given category.
 * Exported for testability in property-based tests.
 */
export function getEndpointForCategory(category: Category): string {
  switch (category) {
    case 'part':
    case 'tyre':
      return '/catalogue/parts'
    case 'fluid':
      return '/catalogue/fluids'
    case 'service':
      return '/catalogue/items'
  }
}

/**
 * Builds the API payload for a given category and form state.
 * Optional string fields are sent as `null` when empty.
 * Exported for testability in property-based tests.
 */
export function buildPayload(
  category: Category,
  form: PartFormState | TyreFormState | FluidFormState | ServiceFormState,
): Record<string, unknown> {
  switch (category) {
    case 'part': {
      const f = form as PartFormState
      return {
        name: f.name.trim(),
        default_price: f.sell_price_per_unit,
        sell_price_per_unit: f.sell_price_per_unit,
        purchase_price: f.purchase_price.trim() || null,
        gst_mode: f.gst_mode,
        part_type: 'part',
        part_number: f.part_number.trim() || null,
        brand: f.brand.trim() || null,
        description: f.description.trim() || null,
        packaging_type: f.packaging_type || 'single',
        qty_per_pack: f.packaging_type !== 'single' && f.qty_per_pack.trim() ? parseInt(f.qty_per_pack) : 1,
        total_packs: f.packaging_type !== 'single' && f.total_packs.trim() ? parseInt(f.total_packs) : 1,
      }
    }
    case 'tyre': {
      const f = form as TyreFormState
      return {
        name: f.name.trim(),
        default_price: f.sell_price_per_unit,
        sell_price_per_unit: f.sell_price_per_unit,
        purchase_price: f.purchase_price.trim() || null,
        gst_mode: f.gst_mode,
        part_type: 'tyre',
        tyre_width: f.tyre_width.trim() || null,
        tyre_profile: f.tyre_profile.trim() || null,
        tyre_rim_dia: f.tyre_rim_dia.trim() || null,
        tyre_load_index: f.tyre_load_index.trim() || null,
        tyre_speed_index: f.tyre_speed_index.trim() || null,
        brand: f.brand.trim() || null,
        packaging_type: f.packaging_type || 'single',
        qty_per_pack: f.packaging_type !== 'single' && f.qty_per_pack.trim() ? parseInt(f.qty_per_pack) : 1,
        total_packs: f.packaging_type !== 'single' && f.total_packs.trim() ? parseInt(f.total_packs) : 1,
      }
    }
    case 'fluid': {
      const f = form as FluidFormState
      return {
        product_name: f.product_name.trim(),
        sell_price_per_unit: f.sell_price_per_unit,
        gst_mode: f.gst_mode,
        fluid_type: f.fluid_type,
        oil_type: f.oil_type.trim() || null,
        grade: f.grade.trim() || null,
        brand_name: f.brand_name.trim() || null,
      }
    }
    case 'service': {
      const f = form as ServiceFormState
      return {
        name: f.name.trim(),
        default_price: f.default_price,
        is_gst_exempt: f.gst_mode === 'exempt',
        gst_inclusive: f.gst_mode === 'inclusive',
        category: 'service',
        description: f.description.trim() || null,
      }
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Response mapping — exported for property tests (tasks 4.4, 4.5)    */
/* ------------------------------------------------------------------ */

/**
 * Maps a catalogue creation API response to the CatalogueItem interface.
 * Each category returns a different response shape:
 *   - Parts/Tyres: { part: { id, name, ... } }
 *   - Fluids:      { product: { id, product_name, ... } }
 *   - Services:    { item: { id, name, ... } }
 *
 * Uses safe-api-consumption patterns: `?.` and `?? null` on all access.
 * Exported for use in property-based tests.
 */
export function mapResponseToCatalogueItem(
  category: Category,
  data: Record<string, unknown>,
): CatalogueItem {
  switch (category) {
    case 'part':
    case 'tyre': {
      const part = (data?.part ?? {}) as Record<string, unknown>
      return {
        id: String(part?.id ?? ''),
        name: String(part?.name ?? ''),
        part_number: part?.part_number != null ? String(part.part_number) : null,
        brand: part?.brand != null ? String(part.brand) : null,
        sell_price: part?.sell_price_per_unit != null
          ? String(part.sell_price_per_unit)
          : (part?.default_price != null ? String(part.default_price) : null),
        part_type: part?.part_type != null ? String(part.part_type) : null,
        description: part?.description != null ? String(part.description) : null,
        tyre_size: buildTyreSize(part),
        supplier_id: null,
        supplier_name: null,
        purchase_price: part?.purchase_price != null ? String(part.purchase_price) : null,
        cost_per_unit: part?.cost_per_unit != null ? String(part.cost_per_unit) : null,
        margin_pct: part?.margin_pct != null ? String(part.margin_pct) : null,
        margin_amount: part?.margin != null ? String(part.margin) : null,
        qty_per_pack: part?.qty_per_pack != null ? Number(part.qty_per_pack) : null,
        total_packs: part?.total_packs != null ? Number(part.total_packs) : null,
        packaging_type: part?.packaging_type != null ? String(part.packaging_type) : null,
        fluid_type: null,
        grade: null,
        pack_size: null,
        category_name: part?.category_name != null ? String(part.category_name) : null,
      }
    }
    case 'fluid': {
      // Fluid endpoint returns FluidOilResponse directly (not wrapped)
      const product = (data?.product ?? data ?? {}) as Record<string, unknown>
      const productName = product?.product_name != null
        ? String(product.product_name)
        : String(product?.fluid_type ?? '')
      return {
        id: String(product?.id ?? ''),
        name: productName,
        brand: product?.brand_name != null ? String(product.brand_name) : null,
        sell_price: product?.sell_price_per_unit != null ? String(product.sell_price_per_unit) : null,
        part_type: 'fluid',
        fluid_type: product?.oil_type != null ? String(product.oil_type) : (product?.fluid_type != null ? String(product.fluid_type) : null),
        grade: product?.grade != null ? String(product.grade) : null,
        description: product?.description != null ? String(product.description) : null,
        part_number: null,
        supplier_id: null,
        supplier_name: null,
        purchase_price: product?.purchase_price != null ? String(product.purchase_price) : null,
        cost_per_unit: product?.cost_per_unit != null ? String(product.cost_per_unit) : null,
        margin_pct: product?.margin_pct != null ? String(product.margin_pct) : null,
        margin_amount: product?.margin != null ? String(product.margin) : null,
        qty_per_pack: product?.qty_per_pack != null ? Number(product.qty_per_pack) : null,
        total_packs: product?.total_quantity != null ? Number(product.total_quantity) : null,
        packaging_type: null,
        tyre_size: null,
        pack_size: product?.pack_size != null ? String(product.pack_size) : null,
        category_name: null,
      }
    }
    case 'service': {
      const item = (data?.item ?? {}) as Record<string, unknown>
      return {
        id: String(item?.id ?? ''),
        name: String(item?.name ?? ''),
        sell_price: item?.default_price != null ? String(item.default_price) : null,
        part_type: 'service',
        description: item?.description != null ? String(item.description) : null,
        part_number: null,
        brand: null,
        supplier_id: null,
        supplier_name: null,
        purchase_price: null,
        cost_per_unit: null,
        margin_pct: null,
        margin_amount: null,
        qty_per_pack: null,
        total_packs: null,
        packaging_type: null,
        tyre_size: null,
        fluid_type: null,
        grade: null,
        pack_size: null,
        category_name: null,
      }
    }
  }
}

/** Build a tyre size string from component fields, or null if none present. */
function buildTyreSize(part: Record<string, unknown>): string | null {
  const width = part?.tyre_width != null ? String(part.tyre_width) : null
  const profile = part?.tyre_profile != null ? String(part.tyre_profile) : null
  const rimDia = part?.tyre_rim_dia != null ? String(part.tyre_rim_dia) : null

  const parts = [
    width,
    profile ? `/${profile}` : null,
    rimDia ? `R${rimDia}` : null,
  ].filter(Boolean)

  return parts.length > 0 ? parts.join('') : null
}

/* ------------------------------------------------------------------ */
/*  Shared Pricing & Packaging section (matches PartsCatalogue)        */
/* ------------------------------------------------------------------ */

function PricingPackagingFields({
  sellPrice, onSellPriceChange,
  purchasePrice, onPurchasePriceChange,
  packagingType, onPackagingTypeChange,
  qtyPerPack, onQtyPerPackChange,
  totalPacks, onTotalPacksChange,
  gstMode, onGstModeChange,
  errors,
}: {
  sellPrice: string; onSellPriceChange: (v: string) => void
  purchasePrice: string; onPurchasePriceChange: (v: string) => void
  packagingType: string; onPackagingTypeChange: (v: string) => void
  qtyPerPack: string; onQtyPerPackChange: (v: string) => void
  totalPacks: string; onTotalPacksChange: (v: string) => void
  gstMode: GstMode; onGstModeChange: (mode: GstMode) => void
  errors: FormErrors
}) {
  const isSingle = packagingType === 'single'
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-3">
      <p className="text-sm font-medium text-gray-900">Pricing &amp; Packaging</p>

      <FormField label="GST Mode" required error={errors.gst_mode}>
        {(props) => <GstModeToggle id={props.id} value={gstMode} onChange={onGstModeChange} />}
      </FormField>

      {/* Packaging Type */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Packaging Type</label>
        <select value={packagingType} onChange={(e) => onPackagingTypeChange(e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="single">Single</option>
          <option value="box">Box</option>
          <option value="carton">Carton</option>
          <option value="pack">Pack</option>
          <option value="bag">Bag</option>
          <option value="pallet">Pallet</option>
        </select>
      </div>

      {/* Qty Per Pack & Total Packs */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Qty Per Pack</label>
          <input type="number" min="1" step="1" value={qtyPerPack} onChange={(e) => onQtyPerPackChange(e.target.value)}
            disabled={isSingle}
            className={`w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${isSingle ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''}`}
            placeholder="e.g. 10" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Total Packs</label>
          <input type="number" min="1" step="1" value={totalPacks} onChange={(e) => onTotalPacksChange(e.target.value)}
            disabled={isSingle}
            className={`w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${isSingle ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''}`}
            placeholder="e.g. 2" />
        </div>
      </div>

      {/* Purchase Price & Sell Price */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Purchase Price</label>
          <div className="flex">
            <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">$</span>
            <input type="number" min="0" step="0.01" value={purchasePrice} onChange={(e) => onPurchasePriceChange(e.target.value)}
              className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="0.00" />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Sell Price Per Unit *</label>
          <div className="flex">
            <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">$</span>
            <input type="number" min="0" step="0.01" value={sellPrice} onChange={(e) => onSellPriceChange(e.target.value)}
              className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="0.00" />
          </div>
          {errors.sell_price_per_unit && <p className="mt-1 text-xs text-red-600">{errors.sell_price_per_unit}</p>}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Category-specific field renderers                                  */
/* ------------------------------------------------------------------ */

function PartFields({
  form,
  setForm,
  errors,
  clearError,
}: {
  form: PartFormState
  setForm: React.Dispatch<React.SetStateAction<PartFormState>>
  errors: FormErrors
  clearError: (field: string) => void
}) {
  return (
    <>
      <FormField label="Name" required error={errors.name}>
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.name}
            onChange={(e) => { setForm((f) => ({ ...f, name: e.target.value })); clearError('name') }}
            placeholder="e.g. Brake Pad Set"
          />
        )}
      </FormField>

      <FormField label="Part Number" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.part_number}
            onChange={(e) => setForm((f) => ({ ...f, part_number: e.target.value }))}
            placeholder="e.g. BP-1234"
          />
        )}
      </FormField>

      <FormField label="Brand" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.brand}
            onChange={(e) => setForm((f) => ({ ...f, brand: e.target.value }))}
            placeholder="e.g. Bosch"
          />
        )}
      </FormField>

      <FormField label="Description" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            placeholder="Brief description"
          />
        )}
      </FormField>

      {/* Pricing & Packaging — matching PartsCatalogue layout */}
      <PricingPackagingFields
        sellPrice={form.sell_price_per_unit}
        onSellPriceChange={(v) => { setForm((f) => ({ ...f, sell_price_per_unit: v })); clearError('sell_price_per_unit') }}
        purchasePrice={form.purchase_price}
        onPurchasePriceChange={(v) => setForm((f) => ({ ...f, purchase_price: v }))}
        packagingType={form.packaging_type}
        onPackagingTypeChange={(v) => {
          if (v === 'single') setForm((f) => ({ ...f, packaging_type: v, qty_per_pack: '1', total_packs: '1' }))
          else setForm((f) => ({ ...f, packaging_type: v }))
        }}
        qtyPerPack={form.qty_per_pack}
        onQtyPerPackChange={(v) => setForm((f) => ({ ...f, qty_per_pack: v }))}
        totalPacks={form.total_packs}
        onTotalPacksChange={(v) => setForm((f) => ({ ...f, total_packs: v }))}
        gstMode={form.gst_mode}
        onGstModeChange={(mode) => { setForm((f) => ({ ...f, gst_mode: mode })); clearError('gst_mode') }}
        errors={errors}
      />
    </>
  )
}

function TyreFields({
  form,
  setForm,
  errors,
  clearError,
}: {
  form: TyreFormState
  setForm: React.Dispatch<React.SetStateAction<TyreFormState>>
  errors: FormErrors
  clearError: (field: string) => void
}) {
  return (
    <>
      <FormField label="Name" required error={errors.name}>
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.name}
            onChange={(e) => { setForm((f) => ({ ...f, name: e.target.value })); clearError('name') }}
            placeholder="e.g. Michelin Pilot Sport 4"
          />
        )}
      </FormField>

      {/* Tyre dimensions — 5-column grid matching PartsCatalogue */}
      <div className="grid grid-cols-5 gap-2">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Width</label>
          <input value={form.tyre_width} onChange={(e) => setForm((f) => ({ ...f, tyre_width: e.target.value }))}
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" placeholder="205" />
        </div>
        <div className="flex items-end pb-1 justify-center text-gray-400 font-bold">/</div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Profile</label>
          <input value={form.tyre_profile} onChange={(e) => setForm((f) => ({ ...f, tyre_profile: e.target.value }))}
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" placeholder="55" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Rim Dia</label>
          <div className="flex items-center gap-1">
            <span className="text-gray-400 font-bold text-sm">R</span>
            <input value={form.tyre_rim_dia} onChange={(e) => setForm((f) => ({ ...f, tyre_rim_dia: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" placeholder="16" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Load/Speed</label>
          <div className="flex gap-1">
            <input value={form.tyre_load_index} onChange={(e) => setForm((f) => ({ ...f, tyre_load_index: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-1 py-1.5 text-sm" placeholder="91" />
            <input value={form.tyre_speed_index} onChange={(e) => setForm((f) => ({ ...f, tyre_speed_index: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-1 py-1.5 text-sm" placeholder="V" />
          </div>
        </div>
      </div>

      <FormField label="Brand" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.brand}
            onChange={(e) => setForm((f) => ({ ...f, brand: e.target.value }))}
            placeholder="e.g. Michelin"
          />
        )}
      </FormField>

      {/* Pricing & Packaging — matching PartsCatalogue layout */}
      <PricingPackagingFields
        sellPrice={form.sell_price_per_unit}
        onSellPriceChange={(v) => { setForm((f) => ({ ...f, sell_price_per_unit: v })); clearError('sell_price_per_unit') }}
        purchasePrice={form.purchase_price}
        onPurchasePriceChange={(v) => setForm((f) => ({ ...f, purchase_price: v }))}
        packagingType={form.packaging_type}
        onPackagingTypeChange={(v) => {
          if (v === 'single') setForm((f) => ({ ...f, packaging_type: v, qty_per_pack: '1', total_packs: '1' }))
          else setForm((f) => ({ ...f, packaging_type: v }))
        }}
        qtyPerPack={form.qty_per_pack}
        onQtyPerPackChange={(v) => setForm((f) => ({ ...f, qty_per_pack: v }))}
        totalPacks={form.total_packs}
        onTotalPacksChange={(v) => setForm((f) => ({ ...f, total_packs: v }))}
        gstMode={form.gst_mode}
        onGstModeChange={(mode) => { setForm((f) => ({ ...f, gst_mode: mode })); clearError('gst_mode') }}
        errors={errors}
      />
    </>
  )
}

function FluidFields({
  form,
  setForm,
  errors,
  clearError,
}: {
  form: FluidFormState
  setForm: React.Dispatch<React.SetStateAction<FluidFormState>>
  errors: FormErrors
  clearError: (field: string) => void
}) {
  return (
    <>
      <FormField label="Product Name" required error={errors.product_name}>
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.product_name}
            onChange={(e) => { setForm((f) => ({ ...f, product_name: e.target.value })); clearError('product_name') }}
            placeholder="e.g. Castrol Edge 5W-30"
          />
        )}
      </FormField>

      <FormField label="Sell Price per Unit" required error={errors.sell_price_per_unit}>
        {(props) => (
          <input
            {...props}
            type="number"
            min="0"
            step="0.01"
            className={inputClassName}
            value={form.sell_price_per_unit}
            onChange={(e) => { setForm((f) => ({ ...f, sell_price_per_unit: e.target.value })); clearError('sell_price_per_unit') }}
            placeholder="0.00"
          />
        )}
      </FormField>

      <FormField label="GST Mode" required error={errors.gst_mode}>
        {(props) => (
          <GstModeToggle
            id={props.id}
            value={form.gst_mode}
            onChange={(mode) => { setForm((f) => ({ ...f, gst_mode: mode })); clearError('gst_mode') }}
          />
        )}
      </FormField>

      <FormField label="Fluid Type" required error={errors.fluid_type}>
        {(props) => (
          <div id={props.id} className="inline-flex rounded-md border border-gray-300 overflow-hidden" role="radiogroup" aria-label="Fluid type">
            {(['oil', 'non-oil'] as const).map((type) => (
              <button
                key={type}
                type="button"
                role="radio"
                aria-checked={form.fluid_type === type}
                onClick={() => { setForm((f) => ({ ...f, fluid_type: type, oil_type: type === 'non-oil' ? '' : f.oil_type })); clearError('fluid_type') }}
                className={`px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset ${
                  form.fluid_type === type
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-50'
                }`}
              >
                {type === 'oil' ? 'Oil' : 'Non-Oil'}
              </button>
            ))}
          </div>
        )}
      </FormField>

      {form.fluid_type === 'oil' && (
        <FormField label="Oil Type" helperText="Optional">
          {(props) => (
            <select
              {...props}
              className={selectClassName}
              value={form.oil_type}
              onChange={(e) => setForm((f) => ({ ...f, oil_type: e.target.value }))}
            >
              <option value="">Select oil type…</option>
              <option value="engine">Engine Oil</option>
              <option value="transmission">Transmission Oil</option>
              <option value="brake">Brake Fluid</option>
              <option value="power_steering">Power Steering Fluid</option>
              <option value="coolant">Coolant</option>
              <option value="other">Other</option>
            </select>
          )}
        </FormField>
      )}

      <FormField label="Grade" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.grade}
            onChange={(e) => setForm((f) => ({ ...f, grade: e.target.value }))}
            placeholder="e.g. 5W-30"
          />
        )}
      </FormField>

      <FormField label="Brand" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.brand_name}
            onChange={(e) => setForm((f) => ({ ...f, brand_name: e.target.value }))}
            placeholder="e.g. Castrol"
          />
        )}
      </FormField>
    </>
  )
}

function ServiceFields({
  form,
  setForm,
  errors,
  clearError,
}: {
  form: ServiceFormState
  setForm: React.Dispatch<React.SetStateAction<ServiceFormState>>
  errors: FormErrors
  clearError: (field: string) => void
}) {
  return (
    <>
      <FormField label="Name" required error={errors.name}>
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.name}
            onChange={(e) => { setForm((f) => ({ ...f, name: e.target.value })); clearError('name') }}
            placeholder="e.g. Wheel Alignment"
          />
        )}
      </FormField>

      <FormField label="Default Price" required error={errors.default_price}>
        {(props) => (
          <input
            {...props}
            type="number"
            min="0"
            step="0.01"
            className={inputClassName}
            value={form.default_price}
            onChange={(e) => { setForm((f) => ({ ...f, default_price: e.target.value })); clearError('default_price') }}
            placeholder="0.00"
          />
        )}
      </FormField>

      <FormField label="GST Mode" required error={errors.gst_mode}>
        {(props) => (
          <GstModeToggle
            id={props.id}
            value={form.gst_mode}
            onChange={(mode) => { setForm((f) => ({ ...f, gst_mode: mode })); clearError('gst_mode') }}
          />
        )}
      </FormField>

      <FormField label="Description" helperText="Optional">
        {(props) => (
          <input
            {...props}
            type="text"
            className={inputClassName}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            placeholder="Brief description"
          />
        )}
      </FormField>
    </>
  )
}

/* ------------------------------------------------------------------ */
/*  Main InlineCreateForm Component                                    */
/* ------------------------------------------------------------------ */

export function InlineCreateForm({ category, onSuccess, onCancel }: InlineCreateFormProps) {
  const categoryLabel = CATEGORY_LABELS[category] ?? category

  /* --- Validation errors & saving state --- */
  const [errors, setErrors] = useState<FormErrors>({})
  const [saving, setSaving] = useState(false)
  // formError is for API-level errors (task 1.3/1.4 will use this)
  const [formError, setFormError] = useState<string | null>(null)

  const clearError = (field: string) => {
    setErrors((prev) => {
      if (!prev[field]) return prev
      const next = { ...prev }
      delete next[field]
      return next
    })
  }

  /* --- Local form state per category --- */
  const [partForm, setPartForm] = useState<PartFormState>({
    name: '',
    sell_price_per_unit: '',
    purchase_price: '',
    gst_mode: 'exclusive',
    part_number: '',
    brand: '',
    description: '',
    packaging_type: 'single',
    qty_per_pack: '1',
    total_packs: '1',
  })

  const [tyreForm, setTyreForm] = useState<TyreFormState>({
    name: '',
    sell_price_per_unit: '',
    purchase_price: '',
    gst_mode: 'exclusive',
    tyre_width: '',
    tyre_profile: '',
    tyre_rim_dia: '',
    tyre_load_index: '',
    tyre_speed_index: '',
    brand: '',
    packaging_type: 'single',
    qty_per_pack: '1',
    total_packs: '1',
  })

  const [fluidForm, setFluidForm] = useState<FluidFormState>({
    product_name: '',
    sell_price_per_unit: '',
    gst_mode: 'exclusive',
    fluid_type: 'oil',
    oil_type: '',
    grade: '',
    brand_name: '',
  })

  const [serviceForm, setServiceForm] = useState<ServiceFormState>({
    name: '',
    default_price: '',
    gst_mode: 'exclusive',
    description: '',
  })

  /* --- Get the active form for the current category --- */
  const getActiveForm = () => {
    switch (category) {
      case 'part': return partForm
      case 'tyre': return tyreForm
      case 'fluid': return fluidForm
      case 'service': return serviceForm
    }
  }

  /* --- Submit handler: validate, then call catalogue API --- */
  const handleSubmit = async () => {
    const validationErrors = validateForm(category, getActiveForm())
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return

    const endpoint = getEndpointForCategory(category)
    const payload = buildPayload(category, getActiveForm())

    setSaving(true)
    setFormError(null)
    try {
      const res = await apiClient.post<Record<string, unknown>>(endpoint, payload)
      const mappedItem = mapResponseToCatalogueItem(category, res.data ?? {})
      onSuccess(mappedItem)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } }
      const detail = axiosErr?.response?.data?.detail
      if (detail) {
        // FastAPI returns detail as a string for simple errors,
        // or as an array of {type, loc, msg, input} for Pydantic validation errors
        if (typeof detail === 'string') {
          setFormError(detail)
        } else if (Array.isArray(detail)) {
          // Extract human-readable messages from Pydantic validation errors
          const messages = detail
            .map((e: { msg?: string; loc?: unknown[] }) => {
              const field = (e.loc ?? []).slice(-1)[0]
              return field ? `${field}: ${e.msg ?? 'invalid'}` : (e.msg ?? 'Validation error')
            })
            .join('; ')
          setFormError(messages || 'Validation error')
        } else {
          setFormError(String(detail))
        }
      } else {
        const label = CATEGORY_LABELS[category] ?? category
        setFormError(`Failed to create ${label.toLowerCase()}. Please check your connection and try again.`)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {/* Banner */}
      <div className="mb-4 rounded-md bg-blue-50 border border-blue-200 px-4 py-3">
        <p className="text-sm font-medium text-blue-800">
          Quick-create a new {categoryLabel} catalogue item
        </p>
        <p className="mt-1 text-xs text-blue-600">
          This creates a catalogue entry. You can update full details (packaging, supplier, category) later from the Catalogue page.
        </p>
      </div>

      {/* Category-specific fields */}
      <div className="space-y-4">
        {category === 'part' && (
          <PartFields form={partForm} setForm={setPartForm} errors={errors} clearError={clearError} />
        )}

        {category === 'tyre' && (
          <TyreFields form={tyreForm} setForm={setTyreForm} errors={errors} clearError={clearError} />
        )}

        {category === 'fluid' && (
          <FluidFields form={fluidForm} setForm={setFluidForm} errors={errors} clearError={clearError} />
        )}

        {category === 'service' && (
          <ServiceFields form={serviceForm} setForm={setServiceForm} errors={errors} clearError={clearError} />
        )}
      </div>

      {/* API / form-level error */}
      {formError && (
        <div className="mt-4 rounded-md bg-red-50 border border-red-200 px-4 py-3">
          <p className="text-sm text-red-700">{formError}</p>
        </div>
      )}

      {/* Actions */}
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onCancel} type="button" disabled={saving}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={handleSubmit} type="button" disabled={saving}>
          {saving ? 'Creating…' : `Create ${categoryLabel}`}
        </Button>
      </div>
    </div>
  )
}
