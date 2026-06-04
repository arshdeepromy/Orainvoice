/**
 * Customers page barrel (Task 23).
 *
 * The original frontend/src/pages/customers/index.ts exports CustomerList,
 * CustomerProfile, FleetAccounts and DiscountRules (CustomerCreate is imported
 * directly in the router, not via the barrel). This barrel mirrors that for the
 * three pages in Task 23's scope; CustomerCreate is also exported here for the
 * v2 router. FleetAccounts + DiscountRules are owned by Task 24 and exported
 * below now that they're ported.
 */
export { default as CustomerList } from './CustomerList'
export { default as CustomerCreate } from './CustomerCreate'
export { default as CustomerProfile } from './CustomerProfile'
export { default as FleetAccounts } from './FleetAccounts'
export { default as DiscountRules } from './DiscountRules'
