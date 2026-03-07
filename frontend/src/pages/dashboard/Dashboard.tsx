import { useAuth } from '@/contexts/AuthContext'
import { Spinner } from '@/components/ui/Spinner'
import { SalespersonDashboard } from './SalespersonDashboard'
import { OrgAdminDashboard } from './OrgAdminDashboard'
import { GlobalAdminDashboard } from './GlobalAdminDashboard'

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
