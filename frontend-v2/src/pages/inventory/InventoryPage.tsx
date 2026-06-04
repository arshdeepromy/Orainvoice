import { Tabs } from '@/components/ui'
import StockLevels from './StockLevels'
import ReorderAlerts from './ReorderAlerts'
import SupplierList from './SupplierList'
import UsageHistory from './UsageHistory'
import StockUpdateLog from './StockUpdateLog'

/**
 * InventoryPage — Task 35 port of frontend/src/pages/inventory/InventoryPage.tsx.
 *
 * Inventory management page with tabbed navigation for stock levels, usage
 * history, stock update log, reorder alerts, and suppliers. The tab model and
 * `urlPersist` behaviour are copied VERBATIM; only the page head is reframed
 * onto the design tokens (`page page-wide` + `.page-head` eyebrow/h1).
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
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Stock</div>
          <h1>Inventory</h1>
        </div>
      </div>
      <Tabs tabs={tabs} defaultTab="stock" urlPersist />
    </div>
  )
}
