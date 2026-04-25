export interface InventoryItem {
  id: string
  name: string
  sku: string | null
  description: string | null
  unit_price: number
  stock_level: number
  reorder_level: number | null
  supplier: string | null
  category: string | null
}
