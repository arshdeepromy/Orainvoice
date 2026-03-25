import { Tabs } from '../../components/ui'
import StockLevels from './StockLevels'
import ReorderAlerts from './ReorderAlerts'
import StockAdjustment from './StockAdjustment'
import SupplierList from './SupplierList'

/**
 * Inventory management page with tabbed navigation for stock levels, reorder alerts,
 * stock adjustments, and suppliers.
 */
export default function InventoryPage() {
  const tabs = [
    { id: 'stock', label: 'Stock Levels', content: <StockLevels /> },
    { id: 'alerts', label: 'Reorder Alerts', content: <ReorderAlerts /> },
    { id: 'adjust', label: 'Adjust Stock', content: <StockAdjustment /> },
    { id: 'suppliers', label: 'Suppliers', content: <SupplierList /> },
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Inventory</h1>
      <Tabs tabs={tabs} defaultTab="stock" />
    </div>
  )
}
