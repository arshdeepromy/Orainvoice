/**
 * Inventory barrel — Tasks 35–36 (Phase 8 Inventory).
 *
 * Task 35 exported the tabbed InventoryPage container (Stock Levels / Usage
 * History / Stock Update Log / Reorder Alerts / Suppliers) plus the standalone
 * ProductList, ProductDetail and StockMovements pages. Task 36 adds the
 * remaining inventory pages: StockAdjustment, StockTake, StockTransfers,
 * PurchaseOrders, CSVImport, PricingRules and CategoryTree. The Items /
 * Catalogue pages belong to later tasks (37–38).
 */
export { default as InventoryPage } from './InventoryPage'
export { default as StockLevels } from './StockLevels'
export { default as ReorderAlerts } from './ReorderAlerts'
export { default as SupplierList } from './SupplierList'
export { default as UsageHistory } from './UsageHistory'
export { default as StockUpdateLog } from './StockUpdateLog'
export { default as ProductList } from './ProductList'
export { default as ProductDetail } from './ProductDetail'
export { default as StockMovements } from './StockMovements'
export { default as StockAdjustment } from './StockAdjustment'
export { default as StockTake } from './StockTake'
export { default as StockTransfers } from './StockTransfers'
export { default as PurchaseOrders } from './PurchaseOrders'
export { default as CSVImport } from './CSVImport'
export { default as PricingRules } from './PricingRules'
export { default as CategoryTree } from './CategoryTree'
