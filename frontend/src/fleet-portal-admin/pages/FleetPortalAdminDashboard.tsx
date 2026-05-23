/**
 * Fleet Portal Admin Dashboard — workshop-staff view of fleet portal activity.
 *
 * Shows pending booking requests, pending quote requests, recent
 * checklist failures, and fleet account summary. Module-gated by
 * `b2b-fleet-management`.
 *
 * Implements: B2B Fleet Portal task 17.1 — Requirements 16.1–16.7.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../../api/client'

interface FleetAdminSummary {
  fleet_accounts: number
  pending_bookings: number
  pending_quotes: number
  recent_failures: number
}

export default function FleetPortalAdminDashboard() {
  const [data, setData] = useState<FleetAdminSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const res = await apiClient.get<FleetAdminSummary>(
          '/api/v2/fleet-portal/admin/summary',
          { signal: controller.signal },
        )
        setData({
          fleet_accounts: res.data?.fleet_accounts ?? 0,
          pending_bookings: res.data?.pending_bookings ?? 0,
          pending_quotes: res.data?.pending_quotes ?? 0,
          recent_failures: res.data?.recent_failures ?? 0,
        })
      } catch {
        if (!controller.signal.aborted) {
          setData({ fleet_accounts: 0, pending_bookings: 0, pending_quotes: 0, recent_failures: 0 })
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Fleet Portal</h1>
      <p className="text-sm text-gray-500">
        Manage fleet portal access for your business customers. Customers with fleet portal
        access can log in at <code className="rounded bg-gray-100 px-1 py-0.5 text-xs dark:bg-gray-800">/fleet/login</code> to
        manage their vehicles, drivers, checklists, and service bookings.
      </p>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="Fleet Accounts" value={data?.fleet_accounts ?? 0} />
        <Card label="Pending Bookings" value={data?.pending_bookings ?? 0} linkTo="/fleet-portal-admin/bookings" accent={((data?.pending_bookings ?? 0) > 0) ? 'blue' : undefined} />
        <Card label="Pending Quotes" value={data?.pending_quotes ?? 0} linkTo="/fleet-portal-admin/quotes" accent={((data?.pending_quotes ?? 0) > 0) ? 'blue' : undefined} />
        <Card label="Recent Failures (7d)" value={data?.recent_failures ?? 0} accent={((data?.recent_failures ?? 0) > 0) ? 'red' : undefined} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-base font-medium mb-3">Quick Actions</h2>
          <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
            <li>• To invite a business customer, go to their profile → Edit → "Invite to Fleet Portal"</li>
            <li>• Fleet accounts are listed below once customers accept their invites</li>
            <li>• Customers log in at <code className="rounded bg-gray-100 px-1 py-0.5 text-xs dark:bg-gray-800">/fleet/login</code></li>
          </ul>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-base font-medium mb-3">Manage</h2>
          <div className="space-y-2">
            <Link to="/fleet-portal-admin/bookings" className="block rounded-md border border-gray-200 px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 min-h-[44px] flex items-center justify-between">
              <span>Booking Requests</span>
              {((data?.pending_bookings ?? 0) > 0) && <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">{data?.pending_bookings}</span>}
            </Link>
            <Link to="/fleet-portal-admin/quotes" className="block rounded-md border border-gray-200 px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 min-h-[44px] flex items-center justify-between">
              <span>Quote Requests</span>
              {((data?.pending_quotes ?? 0) > 0) && <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">{data?.pending_quotes}</span>}
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

function Card({ label, value, accent, linkTo }: { label: string; value: number; accent?: string; linkTo?: string }) {
  const cls = accent === 'red' ? 'text-red-700 dark:text-red-300' : accent === 'blue' ? 'text-blue-700 dark:text-blue-300' : 'text-gray-900 dark:text-white'
  const content = (
    <div className={`rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950 ${linkTo ? 'hover:border-blue-300 dark:hover:border-blue-700 transition-colors cursor-pointer' : ''}`}>
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${cls}`}>{(value ?? 0).toLocaleString()}</div>
    </div>
  )
  if (linkTo) return <Link to={linkTo}>{content}</Link>
  return content
}
