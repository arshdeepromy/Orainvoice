import { Tabs } from '../../components/ui'
import { useTenant } from '@/contexts/TenantContext'
import PartsCatalogue from './PartsCatalogue'
import FluidOilForm from './FluidOilForm'

/**
 * Catalogue management page with tabbed navigation for parts and fluids/oils.
 * Parts and Fluids/Oils tabs are only shown for automotive-transport trade family.
 * Non-automotive orgs see an empty state directing them to the Items page.
 * The Services tab has been removed — items_catalogue records are managed on the Items page.
 */
export default function CataloguePage() {
  const { tradeFamily } = useTenant()
  // Null tradeFamily treated as automotive for backward compat (all existing orgs are automotive)
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const tabs = [
    ...(isAutomotive ? [{ id: 'parts', label: 'Parts', content: <PartsCatalogue /> }] : []),
    ...(isAutomotive ? [{ id: 'fluids', label: 'Fluids / Oils', content: <FluidOilForm /> }] : []),
  ]

  if (tabs.length === 0) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <h1 className="text-2xl font-semibold text-gray-900 mb-4">Catalogue</h1>
        <p className="text-gray-500">No catalogue sections available for your trade type. Manage your items on the Items page.</p>
      </div>
    )
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Catalogue</h1>
      <Tabs tabs={tabs} defaultTab="parts" urlPersist />
    </div>
  )
}
