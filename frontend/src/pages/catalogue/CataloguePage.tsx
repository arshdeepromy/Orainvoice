import { Tabs } from '../../components/ui'
import { useTenant } from '@/contexts/TenantContext'
import ServiceCatalogue from './ServiceCatalogue'
import PartsCatalogue from './PartsCatalogue'
import LabourRates from './LabourRates'
import FluidOilForm from './FluidOilForm'

/**
 * Catalogue management page with tabbed navigation for services, parts, labour rates, and fluids/oils.
 * Parts and Fluids/Oils tabs are only shown for automotive-transport trade family.
 */
export default function CataloguePage() {
  const { tradeFamily } = useTenant()
  // Null tradeFamily treated as automotive for backward compat (all existing orgs are automotive)
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const tabs = [
    { id: 'services', label: 'Services', content: <ServiceCatalogue /> },
    ...(isAutomotive ? [{ id: 'parts', label: 'Parts', content: <PartsCatalogue /> }] : []),
    { id: 'labour-rates', label: 'Labour Rates', content: <LabourRates /> },
    ...(isAutomotive ? [{ id: 'fluids', label: 'Fluids / Oils', content: <FluidOilForm /> }] : []),
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Catalogue</h1>
      <Tabs tabs={tabs} defaultTab="services" urlPersist />
    </div>
  )
}
