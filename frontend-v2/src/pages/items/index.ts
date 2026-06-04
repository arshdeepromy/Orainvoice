/**
 * Items pages barrel (Task 37).
 *
 * Re-exports the Items tabbed container + its tab pages so route wiring and
 * tests can import from a single entry point.
 */
export { default as ItemsPage } from './ItemsPage'
export { default as ItemsCatalogue } from './ItemsCatalogue'
export { default as LabourRates } from './LabourRates'
export { default as ServiceTypesTab } from './ServiceTypesTab'
export { default as ServiceTypeModal } from './ServiceTypeModal'
export type { ServiceTypeForEdit } from './ServiceTypeModal'
