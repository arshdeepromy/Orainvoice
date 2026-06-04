import { Tabs } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { useTerm } from '@/contexts/TerminologyContext'
import ItemsCatalogue from './ItemsCatalogue'
import LabourRates from './LabourRates'
import ServiceTypesTab from './ServiceTypesTab'

/**
 * Items management page with tabbed navigation for items catalogue, labour rates,
 * and (for plumbing-gas orgs) service types.
 *
 * Task 37 port of frontend/src/pages/items/ItemsPage.tsx. The tab model and the
 * plumbing-gas trade-family gate are copied VERBATIM; only the page head is
 * reframed onto the design tokens (`page page-wide` + `.page-head` eyebrow/h1).
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
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Stock</div>
          <h1>Items</h1>
        </div>
      </div>
      <Tabs tabs={tabs} defaultTab="items" urlPersist />
    </div>
  )
}
