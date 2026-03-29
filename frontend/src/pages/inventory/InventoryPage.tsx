import { Tabs } from '../../components/ui'
import StockLevels from './StockLevels'
import ReorderAlerts from './ReorderAlerts'
import SupplierList from './SupplierList'
import UsageHistory from './UsageHistory'
import StockUpdateLog from './StockUpdateLog'

/**
 * Inventory management page with tabbed navigation for stock levels, usage history,
 * stock update log, reorder alerts, and suppliers.
 */
export default function InventoryPage() {
  const tabs = [
    { id: 'stock', label: 'Stock Levels', content: <StockLevels /> },
    { id: 'usage', label: 'Usage History', content: <UsageHistory /> },
    { id: 'log', label: 'Stock Update Log', content: <StockUpdateLog /> },
    { id: 'alerts', label: 'Reorder Alerts', content: <ReorderAlerts /> },
    { id: 'suppliers', label: 'Suppliers', content: <SupplierList /> },
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Inventory</h1>
      <Tabs tabs={tabs} defaultTab="stock" />
    </div>
  )
}
