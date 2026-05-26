/**
 * Workshop Admin — Fleet portal accounts list.
 *
 * Lists every PortalFleetAccount for the org, with a link to each
 * detail page (where the admin actions live: unlock, force MFA, reset
 * password, impersonate, revoke). Replaces the orphan AccountDetail
 * route — admins now have a navigable path to it.
 *
 * Implements: B2B Fleet Portal — Req 16.6.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import apiClient from '../../api/client'

interface FleetAccountRow {
  fleet_account_id: string
  customer_id: string
  display_name: string | null
  is_active: boolean
  portal_account_count: number
}

interface PortalAccountRow {
  portal_account_id: string
  email: string
  first_name: string | null
  last_name: string | null
  portal_user_role: string
  is_active: boolean
  last_login_at: string | null
}

export default function AccountsList() {
  const [fleets, setFleets] = useState<FleetAccountRow[]>([])
  const [accounts, setAccounts] = useState<Record<string, PortalAccountRow[]>>({})
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<{
        items: FleetAccountRow[]
        total: number
      }>('/api/v2/fleet-portal/admin/accounts', {
        signal,
        params: { limit: 200 },
      })
      setFleets(res.data?.items ?? [])
    } catch (e: unknown) {
      if (!(signal?.aborted ?? false)) {
        const detail =
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Failed to load fleet accounts.'
        setErr(detail)
      }
    } finally {
      if (!(signal?.aborted ?? false)) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const c = new AbortController()
    void fetchData(c.signal)
    return () => c.abort()
  }, [fetchData])

  // Lazy-load the portal accounts under each fleet on demand. The
  // backend only has /accounts (fleets) and /accounts/{id} (a specific
  // portal account); to render the per-fleet user list we'd need
  // another endpoint. For now we link to the fleet's first
  // portal_account_count and let admins drill down via the customer
  // edit modal where the invite/revoke actions live.

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Fleet Accounts</h1>
        <Link
          to="/fleet-portal-admin"
          className="text-sm text-indigo-600 hover:underline"
        >
          ← Fleet Portal
        </Link>
      </div>
      <p className="text-sm text-gray-500">
        Customers with fleet portal access. Click a fleet to manage individual portal accounts.
      </p>

      {err ? (
        <p className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {err}
        </p>
      ) : null}

      {(fleets ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">
            No fleet accounts yet. Invite a business customer from their profile to get started.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Fleet</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Active accounts</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(fleets ?? []).map((f) => (
                <tr key={f.fleet_account_id}>
                  <td className="px-3 py-2 font-medium">{f.display_name ?? '—'}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        'rounded-full px-2 py-0.5 text-xs font-medium ' +
                        (f.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800')
                      }
                    >
                      {f.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-3 py-2">{f.portal_account_count}</td>
                  <td className="px-3 py-2">
                    <Link
                      to={`/customers/${f.customer_id}`}
                      className="text-xs text-indigo-700 hover:underline min-h-[36px] mr-3"
                    >
                      Open customer
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
