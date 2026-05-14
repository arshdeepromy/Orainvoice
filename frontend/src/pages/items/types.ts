/* ------------------------------------------------------------------ */
/*  Service Package Builder — TypeScript Types                         */
/* ------------------------------------------------------------------ */

/**
 * A single inventory component within a service package.
 * Stored as JSONB on the items_catalogue row.
 */
export interface PackageComponent {
  catalogue_item_id: string
  catalogue_type: 'part' | 'tyre' | 'fluid'
  quantity?: number
  volume?: number
  cost_per_unit_snapshot?: number
  fluid_type?: string
  oil_type?: string
  grade?: string
}

/**
 * Stock option returned when a component has multiple stock items
 * across branches/locations.
 */
export interface StockOption {
  stock_item_id: string
  branch_id: string | null
  location: string | null
  available_qty: number
  cost_per_unit?: number
}

/**
 * A resolved component with live cost and availability data,
 * returned from GET /catalogue/items/:id/package-costs.
 */
export interface PackageCostComponent {
  catalogue_item_id: string
  catalogue_type: 'part' | 'tyre' | 'fluid'
  name: string
  quantity?: number
  volume?: number
  cost_per_unit?: number
  line_total?: number
  stock_available: number
  is_available: boolean
  stock_options?: StockOption[]
}

/**
 * Response from GET /catalogue/items/:id/package-costs.
 * Cost fields (total_cost, sell_price, profit) are omitted for non-admin roles.
 */
export interface PackageCostResponse {
  components: PackageCostComponent[]
  total_cost?: number
  sell_price?: number
  profit?: number
}

/**
 * Extended item interface for the items catalogue.
 * Adds package-related fields to the base item shape.
 */
export interface CatalogueItem {
  id: string
  name: string
  description: string | null
  default_price: string
  is_gst_exempt: boolean
  gst_inclusive: boolean
  category: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  /* Package fields */
  is_package: boolean
  package_components: PackageComponent[] | null
  package_cost?: number
  package_profit?: number
  has_unavailable_components: boolean
}

/**
 * Search result item from GET /catalogue/parts/search.
 */
export interface PartSearchResult {
  id: string
  name: string
  part_number: string | null
  part_type: 'part' | 'tyre'
  brand: string | null
  cost_per_unit?: number
  stock_available: number
}

/**
 * Search result item from GET /catalogue/fluids/search.
 */
export interface FluidSearchResult {
  id: string
  product_name: string
  brand_name: string | null
  fluid_type: 'oil' | 'non-oil'
  oil_type: string | null
  grade: string | null
  cost_per_unit?: number
  stock_available: number
}
