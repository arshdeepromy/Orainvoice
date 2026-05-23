/**
 * Fleet Portal dashboard — summary cards (Property 17, Req 15.1–15.6).
 *
 * Shows different views for fleet admins vs drivers:
 * - Admin: full fleet overview with all cards + recent failures + pending counts
 * - Driver: vehicle-focused view with checklists completed + assigned vehicles
 *
 * Implements: B2B Fleet Portal task 16.5 — Requirements 15.1–15.6.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getDashboardSummary } from '../api/endpoints'
import type { DashboardSummary } from '../api/types'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function Dashboard() {
  const { user } = useFleetSession()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const data = await getDashboardSummary({ signal: controller.signal })
        setSummary(data)
      } catch {
        if (!controller.signal.aborted) {
          setError('Failed to load dashboard.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [])

  if (loading) {
    return <div className="p-4 text-sm text-gray-500">Loading…</div>
  }

  if (error) {
    return (
      <div
        className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
        role="alert"
      >
        {error}
      </div>
    )
  }

  const isDriver = user?.portal_user_role === 'driver'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-white">
          Welcome{user?.first_name ? `, ${user.first_name}` : ''}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {isDriver ? 'Driver Dashboard' : user?.email}
        </p>
      </div>

      {/* Driver-specific dashboard (Req 15.6) */}
      {isDriver ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Card
              label="Your vehicles"
              value={summary?.total_vehicles ?? 0}
              link="/fleet/vehicles"
            />
            <Card
              label="Checklists today"
              value={summary?.checklists_completed_today ?? 0}
              link="/fleet/checklists"
            />
            <Card
              label="Expiring soon"
              value={summary?.expiring_within_28 ?? 0}
              accent="amber"
              link="/fleet/vehicles"
            />
          </div>

          {/* Quick actions for drivers */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
            <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-3">Quick Actions</h2>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Link
                to="/fleet/checklists"
                className="flex items-center gap-3 rounded-lg border border-gray-200 px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 min-h-[44px]"
              >
                <span className="text-lg">📋</span>
                Start Pre-Trip Checklist
              </Link>
              <Link
                to="/fleet/bookings"
                className="flex items-center gap-3 rounded-lg border border-gray-200 px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 min-h-[44px]"
              >
                <span className="text-lg">🔧</span>
                Request Service Booking
              </Link>
            </div>
          </div>

          {/* Recent failures for driver */}
          <RecentFailuresPanel failures={summary?.recent_failures ?? []} />
        </div>
      ) : (
        /* Admin dashboard */
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card label="Total vehicles" value={summary?.total_vehicles ?? 0} link="/fleet/vehicles" />
            <Card
              label="Valid WOF & COF"
              value={summary?.valid_wof_cof ?? 0}
              accent="green"
            />
            <Card
              label="Expiring within 28 days"
              value={summary?.expiring_within_28 ?? 0}
              accent="amber"
              link="/fleet/vehicles"
            />
            <Card
              label="Service overdue"
              value={summary?.service_overdue ?? 0}
              accent="red"
              link="/fleet/vehicles"
            />
            <Card
              label="Checklists today"
              value={summary?.checklists_completed_today ?? 0}
              link="/fleet/checklists"
            />
            <Card
              label="Pending bookings"
              value={summary?.pending_booking_requests ?? 0}
              link="/fleet/bookings"
            />
            <Card
              label="Pending quotes"
              value={summary?.pending_quote_requests ?? 0}
              link="/fleet/quotes"
            />
          </div>

          {/* Recent failures panel (Req 15.3) */}
          <RecentFailuresPanel failures={summary?.recent_failures ?? []} />
        </div>
      )}
    </div>
  )
}

/** Recent checklist failures panel with clickable links (Req 15.3). */
function RecentFailuresPanel({ failures }: { failures: DashboardSummary['recent_failures'] }) {
  if ((failures ?? []).length === 0) return null

  return (
    <div className="rounded-lg border border-red-200 bg-red-50/50 p-4 dark:border-red-900 dark:bg-red-950/20">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-red-800 dark:text-red-200">
          Recent Checklist Failures
        </h2>
        <Link
          to="/fleet/checklists"
          className="text-xs text-red-600 hover:underline dark:text-red-400"
        >
          View all →
        </Link>
      </div>
      <div className="space-y-1">
        {(failures ?? []).slice(0, 5).map(f => (
          <Link
            key={f.id}
            to={`/fleet/checklists/${f.id}`}
            className="flex items-center justify-between rounded px-3 py-2 text-sm hover:bg-red-100 dark:hover:bg-red-900/30 min-h-[44px]"
          >
            <div className="flex items-center gap-2">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-red-200 text-xs font-bold text-red-800 dark:bg-red-800 dark:text-red-200">
                {f.failed_item_count ?? 0}
              </span>
              <span className="text-red-800 dark:text-red-200">
                {(f.failed_item_count ?? 0)} failed item{(f.failed_item_count ?? 0) !== 1 ? 's' : ''}
              </span>
            </div>
            <span className="text-xs text-red-600 dark:text-red-400">
              {f.completed_at ? new Date(f.completed_at).toLocaleDateString() : '—'}
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}

function Card({
  label,
  value,
  accent,
  link,
}: {
  label: string
  value: number
  accent?: 'green' | 'amber' | 'red'
  link?: string
}) {
  const accentClass =
    accent === 'red'
      ? 'text-red-700 dark:text-red-300'
      : accent === 'amber'
        ? 'text-amber-700 dark:text-amber-300'
        : accent === 'green'
          ? 'text-green-700 dark:text-green-300'
          : 'text-gray-900 dark:text-white'

  const content = (
    <>
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${accentClass}`}>
        {(value ?? 0).toLocaleString()}
      </div>
    </>
  )

  if (link) {
    return (
      <Link to={link} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:border-indigo-300 dark:border-gray-800 dark:bg-gray-950 dark:hover:border-indigo-700 transition-colors">
        {content}
      </Link>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
      {content}
    </div>
  )
}
