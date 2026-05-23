/**
 * Fleet Portal drivers management page (admin-only).
 *
 * Implements: B2B Fleet Portal — Requirements 5.1–5.9.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { listDrivers } from '../api/endpoints'
import type { DriverListItem, PaginatedResponse } from '../api/types'

export default function DriversPage() {
  const [drivers, setDrivers] = useState<DriverListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)

  const fetchDrivers = async () => {
    try {
      const res = await listDrivers()
      setDrivers(res.items ?? [])
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchDrivers() }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Drivers</h1>
        <button onClick={() => setShowInvite(true)} className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700">
          + Invite Driver
        </button>
      </div>

      {showInvite && <InviteDriverForm onClose={() => setShowInvite(false)} onInvited={() => { setShowInvite(false); fetchDrivers() }} />}

      {(drivers ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No drivers yet. Invite drivers so they can log hours, run checklists, and manage their assigned vehicles.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Name</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Email</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Vehicles</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">Last Login</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
              {(drivers ?? []).map(d => (
                <tr key={d.portal_account_id}>
                  <td className="px-3 py-2 font-medium">
                    <Link to={`/fleet/drivers/${d.portal_account_id}`} className="text-indigo-600 hover:underline">
                      {[d.first_name, d.last_name].filter(Boolean).join(' ') || '—'}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-gray-500">{d.email}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${d.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                      {d.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular-nums">{(d.assigned_vehicle_count ?? 0)}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs">{d.last_login_at ? new Date(d.last_login_at).toLocaleDateString() : '—'}</td>
                  <td className="px-3 py-2">
                    {d.is_active ? (
                      <button onClick={() => deactivateDriver(d.portal_account_id, fetchDrivers)} className="text-xs text-red-600 hover:underline min-h-[44px]">
                        Deactivate
                      </button>
                    ) : (
                      <button onClick={() => reactivateDriver(d.portal_account_id, fetchDrivers)} className="text-xs text-green-700 hover:underline min-h-[44px]">
                        Reactivate
                      </button>
                    )}
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

async function deactivateDriver(id: string, refresh: () => void) {
  if (!confirm('Deactivate this driver? They will lose portal access.')) return
  try { await fleetClient.post(`/drivers/${id}/deactivate`); refresh() } catch {}
}

async function reactivateDriver(id: string, refresh: () => void) {
  if (!confirm('Reactivate this driver and let them sign in again?')) return
  try { await fleetClient.post(`/drivers/${id}/reactivate`); refresh() } catch {}
}

function InviteDriverForm({ onClose, onInvited }: { onClose: () => void; onInvited: () => void }) {
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!firstName.trim() || !lastName.trim() || !email.trim()) { setError('First name, last name, and email are required.'); return }
    setSubmitting(true); setError(null)
    try {
      await fleetClient.post('/drivers/invite', {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim().toLowerCase(),
        phone: phone.trim() || null,
      })
      onInvited()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to invite driver.')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
      <h2 className="text-sm font-medium mb-3">Invite a Driver</h2>
      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <input type="text" value={firstName} onChange={e => setFirstName(e.target.value)} placeholder="First name *"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          <input type="text" value={lastName} onChange={e => setLastName(e.target.value)} placeholder="Last name *"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        </div>
        <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Email address *"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <input type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="Phone (optional)"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <div className="flex gap-2">
          <button type="submit" disabled={submitting} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700">
            {submitting ? 'Sending…' : 'Send Invite'}
          </button>
          <button type="button" onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm min-h-[44px] hover:bg-gray-50 dark:border-gray-700">Cancel</button>
        </div>
      </form>
    </div>
  )
}
