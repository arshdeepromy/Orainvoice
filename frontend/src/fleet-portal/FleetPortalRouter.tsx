/**
 * Top-level router for the Fleet Portal SPA.
 *
 * Mounted by `frontend/src/App.tsx` when the request URL matches the
 * fleet portal host or path. Owns the auth provider and the route
 * tree under `/fleet/*`.
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 2.1, 2.2, 2.7.
 */
import { Route, Routes } from 'react-router-dom'

import { FleetSessionProvider } from './contexts/FleetSessionContext'
import {
  RequireDriverOrAdmin,
  RequireFleetSession,
} from './guards/RequireFleetSession'
import { FleetPortalLayout } from './layouts/FleetPortalLayout'
import Login from './pages/Login'
import ForgotPassword from './pages/ForgotPassword'
import AcceptInvite from './pages/AcceptInvite'
import ResetPassword from './pages/ResetPassword'
import Dashboard from './pages/Dashboard'
import VehicleList from './pages/VehicleList'
import VehicleDetail from './pages/VehicleDetail'
import BookingsPage from './pages/BookingsPage'
import DriversPage from './pages/DriversPage'
import QuotesPage from './pages/QuotesPage'
import RemindersPage from './pages/RemindersPage'
import ChecklistsPage from './pages/ChecklistsPage'
import ChecklistSubmit from './pages/ChecklistSubmit'
import DriverDetail from './pages/DriverDetail'
import KioskChecklist from './pages/KioskChecklist'
import NotificationsPage from './pages/NotificationsPage'
import ProfilePage from './pages/ProfilePage'
import AdminsPage from './pages/AdminsPage'
import {
  InvoicesPage,
  SecurityPage,
} from './pages/PlaceholderPages'

/** Detect whether the current location is a fleet portal page. */
export function isFleetPortalRoute(): boolean {
  if (typeof window === 'undefined') return false
  const host = window.location.host.toLowerCase()
  // Subdomain mode: anything ending with .fleet.<domain> OR exactly fleet.<domain>.
  if (host.startsWith('fleet.') || host.includes('.fleet.')) return true
  // Path mode: /fleet/* prefix (covers /fleet/login, /fleet/api proxied to backend).
  return window.location.pathname.startsWith('/fleet')
}

export function FleetPortalRouter() {
  return (
    <FleetSessionProvider>
      <Routes>
        {/* Public auth screens */}
        <Route path="/fleet/login" element={<Login />} />
        <Route path="/fleet/forgot-password" element={<ForgotPassword />} />
        <Route path="/fleet/reset-password/:token" element={<ResetPassword />} />
        <Route path="/fleet/accept-invite/:token" element={<AcceptInvite />} />
        <Route path="/fleet/kiosk/checklist" element={<KioskChecklist />} />

        {/* Authenticated layout */}
        <Route element={<RequireFleetSession />}>
          <Route element={<FleetPortalLayout />}>
            <Route path="/fleet" element={<Dashboard />} />
            <Route path="/fleet/dashboard" element={<Dashboard />} />
            <Route element={<RequireDriverOrAdmin />}>
              <Route path="/fleet/vehicles" element={<VehicleList />} />
              <Route
                path="/fleet/vehicles/:vehicleId"
                element={<VehicleDetail />}
              />
              <Route path="/fleet/checklists" element={<ChecklistsPage />} />
              <Route path="/fleet/checklists/:submissionId" element={<ChecklistSubmit />} />
              <Route path="/fleet/bookings" element={<BookingsPage />} />
              <Route path="/fleet/security" element={<SecurityPage />} />
              <Route path="/fleet/profile" element={<ProfilePage />} />
              <Route path="/fleet/notifications" element={<NotificationsPage />} />
            </Route>
            {/* Admin-only screens render placeholders for now; the
                backend role gate enforces 403 on the API side either way. */}
            <Route path="/fleet/drivers" element={<DriversPage />} />
            <Route path="/fleet/drivers/:driverId" element={<DriverDetail />} />
            <Route path="/fleet/admins" element={<AdminsPage />} />
            <Route path="/fleet/quotes" element={<QuotesPage />} />
            <Route path="/fleet/invoices" element={<InvoicesPage />} />
            <Route path="/fleet/reminders" element={<RemindersPage />} />
          </Route>
        </Route>
      </Routes>
    </FleetSessionProvider>
  )
}
