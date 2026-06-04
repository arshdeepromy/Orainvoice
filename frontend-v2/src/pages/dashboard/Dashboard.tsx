import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui'
import { SalespersonDashboard } from './SalespersonDashboard'
import { OrgAdminDashboard } from './OrgAdminDashboard'
import { GlobalAdminDashboard } from './GlobalAdminDashboard'

/* ============================================================
   Dashboard — role-dispatching entry point (Task 16 scaffold, Task 17 wired).
   ------------------------------------------------------------
   Dispatch logic is copied VERBATIM from frontend/src/pages/dashboard/
   Dashboard.tsx: read the auth role and render the matching variant.
   Each branch now renders its real ported variant (Task 17):
     • global_admin → GlobalAdminDashboard (platform MRR / errors /
                       integration costs / HA / org-branch revenue)
     • org_admin    → OrgAdminDashboard    (KPIs + branch metrics + compare
                       + automotive WidgetGrid)
     • salesperson  → SalespersonDashboard (appointments / job cards /
                       invoices / overdue)
     • default      → SalespersonDashboard (matches the original fallthrough)

   The MainDashboard prototype layout (Task 16) is NOT in this dispatch — it
   is the rich org-dashboard reference the variants draw their design
   patterns from, kept exported from the barrel for reuse/reference but not
   role-routed (the original app has no MainDashboard branch).
   ============================================================ */
export function Dashboard() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <Spinner size="lg" label="Loading dashboard" className="py-20" />
  }

  if (!user) return null

  switch (user.role) {
    case 'global_admin':
      return <GlobalAdminDashboard />
    case 'org_admin':
      return <OrgAdminDashboard />
    case 'salesperson':
      return <SalespersonDashboard />
    default:
      return <SalespersonDashboard />
  }
}

export default Dashboard
