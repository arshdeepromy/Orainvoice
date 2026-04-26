import { Tabs } from '../../components/ui'
import ItemsCatalogue from './ItemsCatalogue'
import LabourRates from './LabourRates'

/**
 * Items management page with tabbed navigation for items catalogue and labour rates.
 */
export default function ItemsPage() {
  const tabs = [
    { id: 'items', label: 'Items', content: <ItemsCatalogue /> },
    { id: 'labour-rates', label: 'Labour Rates', content: <LabourRates /> },
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Items</h1>
      <Tabs tabs={tabs} defaultTab="items" urlPersist />
    </div>
  )
}
