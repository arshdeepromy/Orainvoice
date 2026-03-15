import { Tabs } from '../../components/ui'
import ServiceCatalogue from './ServiceCatalogue'
import PartsCatalogue from './PartsCatalogue'
import LabourRates from './LabourRates'

/**
 * Catalogue management page with tabbed navigation for services, parts, and labour rates.
 *
 * Requirements: 27.1-27.3, 28.1-28.3
 */
export default function CataloguePage() {
  const tabs = [
    { id: 'services', label: 'Services', content: <ServiceCatalogue /> },
    { id: 'parts', label: 'Parts', content: <PartsCatalogue /> },
    { id: 'labour-rates', label: 'Labour Rates', content: <LabourRates /> },
  ]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-4">Catalogue</h1>
      <Tabs tabs={tabs} defaultTab="services" />
    </div>
  )
}
