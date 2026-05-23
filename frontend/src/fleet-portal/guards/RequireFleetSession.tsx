/**
 * Route guards for fleet portal — symmetric with `RequireAuth` /
 * `RequireOrgAdmin` in the staff app.
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 19.5, 19.6.
 */
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useFleetSession } from '../contexts/FleetSessionContext'

/** Redirects to /fleet/login if the session is not authenticated. */
export function RequireFleetSession() {
  const { user, loading } = useFleetSession()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <span className="sr-only">Loading…</span>
        <div className="h-12 w-12 animate-spin rounded-full border-4 border-gray-200 border-t-brand-600" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/fleet/login" state={{ from: location.pathname }} replace />
  }
  return <Outlet />
}

/** Restricts a route to fleet_admin only. Drivers are redirected back. */
export function RequireFleetAdmin() {
  const { user } = useFleetSession()
  if (!user) return <Navigate to="/fleet/login" replace />
  if (user.portal_user_role !== 'fleet_admin') {
    return <Navigate to="/fleet/dashboard" replace />
  }
  return <Outlet />
}

/** Both roles allowed; downstream components discriminate by role. */
export function RequireDriverOrAdmin() {
  const { user } = useFleetSession()
  if (!user) return <Navigate to="/fleet/login" replace />
  return <Outlet />
}
