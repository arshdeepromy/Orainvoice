/**
 * Fleet Portal — co-admin management.
 *
 * Lets a fleet_admin invite additional fleet_admin users to share
 * management of the same PortalFleetAccount. Mirrors DriversPage in
 * structure but targets `portal_user_role = 'fleet_admin'`.
 *
 * Implements: B2B Fleet Portal — Req 4.x (multi-admin per fleet).
 */
import { useEffect, useState, useCallback } from 'react'
import type { FormEvent } from 'react'

import { fleetClient } from '../api/client'

interface AdminListItem {
  portal_account_id: string
  email: string
  first_name: string | null
  last_name: string | null
  phone: string | null
  is_active: boolean
  last_login_at: string | null
}

export default function AdminsPage() {
  const [admins, setAdmins] = useState<AdminListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    try {
      // The /drivers endpoint is admin-only and returns drivers; we
      // need a list of fleet_admins. The existing /admin/accounts
      // backend endpoint lists all PortalAccount rows for the org —
      // we filter client-side to fleet_admin. (Adding a dedicated
      // GET /admins endpoint is on the backlog.)
      const res = await fleetClient.get<{ items: AdminListItem[] }>('/admins', {
        signal,
        params: { limit: 50 },
      })
      setAdmins(res.data?.items ?? [])
    } catch {
      if (!(signal?.aborted ?? false)) setAdmins([])
    } finally {
      if (!(signal?.aborted ?? false)) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const c = new AbortController()
    void fetchData(c.signal)
    return () => c.abort()
  }, [fetchData, refreshKey])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Admins</h1>
          <p className="text-xs text-gray-500">
            Add or remove people who can manage your fleet alongside you.
          </p>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700"
        >
          + Invite Admin
        </button>
      </div>

      {showInvite ? (
        <InviteAdminForm
          onClose={() => setShowInvite(false)}
          onCreated={() => {
            setShowInvite(false)
            setRefreshKey((k) => k + 1)
          }}
        />
      ) : null}

      {(admins ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No co-admins invited yet.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Name</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Email</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Phone</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Last login</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(admins ?? []).map((a) => (
                <tr key={a.portal_account_id}>
                  <td className="px-3 py-2 font-medium">
                    {[a.first_name, a.last_name].filter(Boolean).join(' ') || '—'}
                  </td>
                  <td className="px-3 py-2">{a.email}</td>
                  <td className="px-3 py-2">{a.phone ?? '—'}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        'rounded-full px-2 py-0.5 text-xs font-medium ' +
                        (a.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-600')
                      }
                    >
                      {a.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-500">
                    {a.last_login_at ? new Date(a.last_login_at).toLocaleString() : '—'}
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

function InviteAdminForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!firstName.trim() || !lastName.trim() || !email.trim()) {
      setError('Name and email are required.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await fleetClient.post('/admins/invite', {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim().toLowerCase(),
        phone: phone.trim() || null,
      })
      onCreated()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to invite admin.'
      setError(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/40 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
      <h2 className="mb-3 text-sm font-medium">Invite Co-Admin</h2>
      {error ? <p className="mb-2 text-xs text-red-600">{error}</p> : null}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <input
            type="text"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            placeholder="First name"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
          />
          <input
            type="text"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            placeholder="Last name"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
          />
        </div>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="email@company.co.nz"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
        />
        <input
          type="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="Phone (optional)"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
        />
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? 'Sending…' : 'Send Invite'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
