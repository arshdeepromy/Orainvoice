/**
 * Fleet Portal — My Profile.
 *
 * Lets the signed-in portal user edit their own first name, last name
 * and phone number. Email is shown read-only because changing it
 * affects the login identity and goes through the workshop admin's
 * re-invite flow.
 *
 * Implements: B2B Fleet Portal — Req 3.12 (user can manage own
 * account). Backend endpoint: PATCH /fleet/api/me.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function ProfilePage() {
  const { user, refresh } = useFleetSession()
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [phone, setPhone] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  // Seed the form from the session whenever it loads/changes
  useEffect(() => {
    if (user) {
      setFirstName(user.first_name ?? '')
      setLastName(user.last_name ?? '')
    }
  }, [user])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setMsg(null)
    try {
      await fleetClient.patch('/me', {
        first_name: firstName.trim() || null,
        last_name: lastName.trim() || null,
        phone: phone.trim() || null,
      })
      setMsg({ type: 'ok', text: 'Profile updated.' })
      await refresh()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to update profile.'
      setMsg({ type: 'err', text: detail })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6 max-w-lg">
      <h1 className="text-xl font-semibold">My Profile</h1>

      {msg && (
        <p className={`rounded border p-2 text-xs ${msg.type === 'ok' ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'}`}>
          {msg.text}
        </p>
      )}

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950"
      >
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Email (read-only)</label>
          <input
            type="email"
            value={user?.email ?? ''}
            disabled
            className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm min-h-[44px] dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400"
          />
          <p className="mt-1 text-xs text-gray-400">
            Contact your workshop admin to change the email used to sign in.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">First name</label>
            <input
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Last name</label>
            <input
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
            />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Phone (optional)</label>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="e.g. 021 555 0100"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white"
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Save changes'}
        </button>
      </form>

      <p className="text-xs text-gray-400">
        Looking to change your password or set up MFA?{' '}
        <Link to="/fleet/security" className="text-indigo-600 hover:underline">
          Open Security settings
        </Link>
        .
      </p>
    </div>
  )
}
