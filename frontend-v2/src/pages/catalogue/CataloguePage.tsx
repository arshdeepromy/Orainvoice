import { Tabs } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import PartsCatalogue from './PartsCatalogue'
import FluidOilForm from './FluidOilForm'

/**
 * Catalogue management page with tabbed navigation for parts and fluids/oils.
 * Parts and Fluids/Oils tabs are only shown for automotive-transport trade family.
 * Non-automotive orgs see an empty state directing them to the Items page.
 * The Services tab has been removed — items_catalogue records are managed on the Items page.
 *
 * Task 38 port of frontend/src/pages/catalogue/CataloguePage.tsx. The tab model
 * and the automotive trade-family gate are copied VERBATIM; only the page head /
 * empty state are reframed onto the design tokens (`page page-wide` + `.page-head`
 * eyebrow/h1/sub).
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
      <div className="page page-wide">
        <div className="page-head">
          <div>
            <div className="eyebrow">Stock</div>
            <h1>Catalogue</h1>
          </div>
        </div>
        <p className="text-muted">No catalogue sections available for your trade type. Manage your items on the Items page.</p>
      </div>
    )
  }

  return (
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Stock</div>
          <h1>Catalogue</h1>
          <p className="sub">Public-facing product catalogue</p>
        </div>
      </div>
      <Tabs tabs={tabs} defaultTab="parts" urlPersist />
    </div>
  )
}
