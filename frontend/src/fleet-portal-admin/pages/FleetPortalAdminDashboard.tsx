/**
 * Fleet Portal Admin Dashboard — workshop-staff view of fleet portal activity.
 *
 * Shows summary cards and links to the booking queue, quote queue,
 * fleet account list, checklist failures feed, and security settings.
 *
 * Implements: B2B Fleet Portal — Req 16.1–16.7.
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
        Manage fleet portal access for your business customers. Customers with fleet portal access
        log in at <code className="rounded bg-gray-100 px-1 py-0.5 text-xs dark:bg-gray-800">/fleet/login</code>.
      </p>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="Fleet Accounts" value={data?.fleet_accounts ?? 0} linkTo="/fleet-portal-admin/accounts" />
        <Card
          label="Pending Bookings"
          value={data?.pending_bookings ?? 0}
          linkTo="/fleet-portal-admin/bookings"
          accent={(data?.pending_bookings ?? 0) > 0 ? 'blue' : undefined}
        />
        <Card
          label="Pending Quotes"
          value={data?.pending_quotes ?? 0}
          linkTo="/fleet-portal-admin/quotes"
          accent={(data?.pending_quotes ?? 0) > 0 ? 'blue' : undefined}
        />
        <Card
          label="Recent Failures (7d)"
          value={data?.recent_failures ?? 0}
          linkTo="/fleet-portal-admin/checklist-failures"
          accent={(data?.recent_failures ?? 0) > 0 ? 'red' : undefined}
        />
      </div>

      {/* Manage links */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-base font-medium mb-3">Queues</h2>
          <div className="space-y-2">
            <NavRow
              to="/fleet-portal-admin/bookings"
              label="Booking Requests"
              count={data?.pending_bookings ?? 0}
            />
            <NavRow
              to="/fleet-portal-admin/quotes"
              label="Quote Requests"
              count={data?.pending_quotes ?? 0}
            />
            <NavRow
              to="/fleet-portal-admin/checklist-failures"
              label="Checklist Failures"
              count={data?.recent_failures ?? 0}
              accent="red"
            />
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-800 dark:bg-gray-950">
          <h2 className="text-base font-medium mb-3">Manage</h2>
          <div className="space-y-2">
            <NavRow to="/fleet-portal-admin/accounts" label="Fleet Accounts" count={data?.fleet_accounts ?? 0} />
            <NavRow to="/fleet-portal-admin/settings" label="Security Policy" />
          </div>
          <p className="mt-4 text-xs text-gray-500">
            To invite a new fleet customer, go to their customer profile and use “Invite to Fleet Portal”.
          </p>
        </div>
      </div>
    </div>
  )
}

function Card({
  label,
  value,
  accent,
  linkTo,
}: {
  label: string
  value: number
  accent?: string
  linkTo?: string
}) {
  const cls =
    accent === 'red'
      ? 'text-red-700 dark:text-red-300'
      : accent === 'blue'
        ? 'text-blue-700 dark:text-blue-300'
        : 'text-gray-900 dark:text-white'
  const content = (
    <div
      className={
        'rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950 ' +
        (linkTo
          ? 'hover:border-blue-300 dark:hover:border-blue-700 transition-colors cursor-pointer'
          : '')
      }
    >
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${cls}`}>{(value ?? 0).toLocaleString()}</div>
    </div>
  )
  if (linkTo) return <Link to={linkTo}>{content}</Link>
  return content
}

function NavRow({
  to,
  label,
  count,
  accent,
}: {
  to: string
  label: string
  count?: number
  accent?: 'red' | 'blue'
}) {
  const badgeCls =
    accent === 'red'
      ? 'bg-red-100 text-red-800'
      : 'bg-blue-100 text-blue-800'
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-md border border-gray-200 px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 min-h-[44px]"
    >
      <span>{label}</span>
      {count !== undefined && count > 0 ? (
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badgeCls}`}>{count}</span>
      ) : null}
    </Link>
  )
}
