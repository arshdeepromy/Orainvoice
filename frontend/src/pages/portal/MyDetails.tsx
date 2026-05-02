import { useState } from 'react'
import apiClient from '@/api/client'

interface MyDetailsProps {
  token: string
  email: string | null
  phone: string | null
  onUpdated: (email: string | null, phone: string | null) => void
}

interface ProfileUpdateResponse {
  email: string | null
  phone: string | null
  message: string
}

export function MyDetails({ token, email, phone, onUpdated }: MyDetailsProps) {
  const [editing, setEditing] = useState(false)
  const [emailValue, setEmailValue] = useState(email ?? '')
  const [phoneValue, setPhoneValue] = useState(phone ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleEdit = () => {
    setEmailValue(email ?? '')
    setPhoneValue(phone ?? '')
    setError('')
    setSuccess('')
    setEditing(true)
  }

  const handleCancel = () => {
    setEditing(false)
    setError('')
    setSuccess('')
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const res = await apiClient.patch<ProfileUpdateResponse>(
        `/portal/${token}/profile`,
        { email: emailValue || null, phone: phoneValue || null },
      )
      const updated = res.data
      onUpdated(updated?.email ?? null, updated?.phone ?? null)
      setSuccess(updated?.message ?? 'Profile updated successfully')
      setEditing(false)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr?.response?.data?.detail ?? 'Failed to update profile. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium text-gray-900">My Details</h2>
        {!editing && (
          <button
            type="button"
            onClick={handleEdit}
            className="text-sm font-medium text-blue-600 hover:text-blue-800"
          >
            Edit
          </button>
        )}
      </div>

      {success && (
        <p className="mt-2 text-sm text-green-600">{success}</p>
      )}
      {error && (
        <p className="mt-2 text-sm text-red-600">{error}</p>
      )}

      {editing ? (
        <div className="mt-3 space-y-3">
          <div>
            <label htmlFor="portal-email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="portal-email"
              type="email"
              value={emailValue}
              onChange={(e) => setEmailValue(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="your@email.com"
            />
          </div>
          <div>
            <label htmlFor="portal-phone" className="block text-sm font-medium text-gray-700">
              Phone
            </label>
            <input
              id="portal-phone"
              type="tel"
              value={phoneValue}
              onChange={(e) => setPhoneValue(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="+64 21 123 4567"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              disabled={saving}
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium text-gray-500">Email:</span>
            <span className="text-gray-900">{email || 'Not set'}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium text-gray-500">Phone:</span>
            <span className="text-gray-900">{phone || 'Not set'}</span>
          </div>
        </div>
      )}
    </div>
  )
}
