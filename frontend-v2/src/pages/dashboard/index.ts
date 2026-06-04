/**
 * Dashboard barrel.
 *
 * Mirrors frontend/src/pages/dashboard/index.ts (Dashboard + the three role
 * variants), plus the redesign's MainDashboard prototype layout (Task 16)
 * which the variants borrow their design patterns from. The dispatcher
 * (Dashboard) role-routes to the variants; MainDashboard is exported for
 * reuse/reference but is not part of the role dispatch.
 */
export { Dashboard } from './Dashboard'
export { MainDashboard } from './MainDashboard'
export { SalespersonDashboard } from './SalespersonDashboard'
export { OrgAdminDashboard } from './OrgAdminDashboard'
export { GlobalAdminDashboard } from './GlobalAdminDashboard'
