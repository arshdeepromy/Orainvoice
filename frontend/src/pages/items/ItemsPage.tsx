import { Tabs } from '../../components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { useTerm } from '@/contexts/TerminologyContext'
import ItemsCatalogue from './ItemsCatalogue'
import LabourRates from './LabourRates'
import ServiceTypesTab from './ServiceTypesTab'

/**
 * Items management page with tabbed navigation for items catalogue, labour rates,
 * and (for plumbing-gas orgs) service types.
 */
export default function ItemsPage() {
  const { tradeFamily } = useTenant()
  const isPlumbing = (tradeFamily ?? 'automotive-transport') === 'plumbing-gas'
  const serviceTypesLabel = useTerm('service_types', 'Service Types')

  const tabs = [
    { id: 'items', label: 'Items', content: <ItemsCatalogue /> },
    { id: 'labour-rates', label: 'Labour Rates', content: <LabourRates /> },
    ...(isPlumbing ? [{ id: 'service-types', label: serviceTypesLabel, content: <ServiceTypesTab /> }] : []),
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Items</h1>
      <Tabs tabs={tabs} defaultTab="items" urlPersist />
    </div>
  )
}
