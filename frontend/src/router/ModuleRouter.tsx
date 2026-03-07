import { Routes, Route } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import type { ComponentType } from 'react'

export interface RouteConfig {
  path: string
  component: ComponentType
}

/**
 * Maps module slugs to their route configurations.
 * Only routes for enabled modules will be rendered.
 */
const MODULE_ROUTES: Record<string, RouteConfig[]> = {
  inventory: [
    { path: '/inventory/*', component: InventoryPlaceholder },
  ],
  jobs: [
    { path: '/job-cards/*', component: JobCardsPlaceholder },
  ],
  quotes: [
    { path: '/quotes/*', component: QuotesPlaceholder },
  ],
  bookings: [
    { path: '/bookings/*', component: BookingsPlaceholder },
  ],
  vehicles: [
    { path: '/vehicles/*', component: VehiclesPlaceholder },
  ],
}

/**
 * Core routes that are always available regardless of module enablement.
 */
const CORE_ROUTES: RouteConfig[] = [
  { path: '/dashboard/*', component: DashboardPlaceholder },
  { path: '/invoices/*', component: InvoicesPlaceholder },
  { path: '/customers/*', component: CustomersPlaceholder },
  { path: '/settings/*', component: SettingsPlaceholder },
  { path: '/reports/*', component: ReportsPlaceholder },
]

export function ModuleRouter() {
  const { enabledModules } = useModules()

  return (
    <Routes>
      {/* Core routes always available */}
      {CORE_ROUTES.map((r) => (
        <Route key={r.path} path={r.path} element={<r.component />} />
      ))}

      {/* Module routes conditionally rendered */}
      {Object.entries(MODULE_ROUTES).map(([moduleSlug, routes]) =>
        enabledModules.includes(moduleSlug)
          ? routes.map((r) => (
              <Route key={r.path} path={r.path} element={<r.component />} />
            ))
          : null,
      )}
    </Routes>
  )
}

/* Placeholder components — these will be replaced with real page imports as modules are built */
function DashboardPlaceholder() { return <div>Dashboard</div> }
function InvoicesPlaceholder() { return <div>Invoices</div> }
function CustomersPlaceholder() { return <div>Customers</div> }
function SettingsPlaceholder() { return <div>Settings</div> }
function ReportsPlaceholder() { return <div>Reports</div> }
function InventoryPlaceholder() { return <div>Inventory</div> }
function JobCardsPlaceholder() { return <div>Job Cards</div> }
function QuotesPlaceholder() { return <div>Quotes</div> }
function BookingsPlaceholder() { return <div>Bookings</div> }
function VehiclesPlaceholder() { return <div>Vehicles</div> }

export { MODULE_ROUTES, CORE_ROUTES }
