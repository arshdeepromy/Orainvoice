import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { PasswordRequirements, PasswordMatch, allPasswordRulesMet } from '@/components/auth/PasswordRequirements'

import { MfaSettings } from '@/pages/settings/MfaSettings'
interface UserProfile {
  id: string
  email: string
  first_name: string | null
  last_name: string | null
  role: string
  mfa_methods: string[]
  has_password: boolean
}

export function Profile() {
  const { refreshProfile } = useAuth()
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Name form
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [nameSaving, setNameSaving] = useState(false)
  const [nameMsg, setNameMsg] = useState('')

  // Password form
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMsg, setPwMsg] = useState('')
  const [pwError, setPwError] = useState('')

  const fetchProfile = useCallback(async () => {
    try {
      const res = await apiClient.get('/auth/me')
      setProfile(res.data)
      setFirstName(res.data.first_name ?? '')
      setLastName(res.data.last_name ?? '')
    } catch {
      setError('Failed to load profile')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchProfile() }, [fetchProfile])

  const handleNameSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setNameSaving(true)
    setNameMsg('')
    try {
      const res = await apiClient.put('/auth/me', {
        first_name: firstName || null,
        last_name: lastName || null,
      })
      setProfile(res.data)
      setNameMsg('Name updated')
      await refreshProfile()
      setTimeout(() => setNameMsg(''), 3000)
    } catch {
      setNameMsg('Failed to update name')
    } finally {
      setNameSaving(false)
    }
  }

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPwError('')
    setPwMsg('')

    if (newPassword !== confirmPassword) {
      setPwError('Passwords do not match')
      return
    }
    if (!allPasswordRulesMet(newPassword)) {
      setPwError('Password does not meet requirements')
      return
    }

    setPwSaving(true)
    try {
      await apiClient.post('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setPwMsg('Password changed successfully')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setTimeout(() => setPwMsg(''), 3000)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPwError(detail ?? 'Failed to change password')
    } finally {
      setPwSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" role="status" aria-label="Loading profile" />
      </div>
    )
  }

  if (error || !profile) {
    return <div className="text-red-600 py-4" role="alert">{error || 'Profile not found'}</div>
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Profile</h2>
        <p className="text-sm text-gray-500 mt-1">{profile.email}</p>
      </div>

      {/* Name section */}
      <form onSubmit={handleNameSave} className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
        <h3 className="text-sm font-medium text-gray-900">Personal Information</h3>

        <div>
          <label className="block text-sm text-gray-600 mb-1">Email</label>
          <p className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
            {profile.email}
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="firstName" className="block text-sm text-gray-600 mb-1">First name</label>
            <input
              id="firstName"
              type="text"
              value={firstName}
              onChange={e => setFirstName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              maxLength={100}
            />
          </div>
          <div>
            <label htmlFor="lastName" className="block text-sm text-gray-600 mb-1">Last name</label>
            <input
              id="lastName"
              type="text"
              value={lastName}
              onChange={e => setLastName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              maxLength={100}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={nameSaving}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 min-h-[44px]"
          >
            {nameSaving ? 'Saving…' : 'Save name'}
          </button>
          {nameMsg && <span className="text-sm text-green-600">{nameMsg}</span>}
        </div>
      </form>

      {/* Password section */}
      {profile.has_password && (
        <form onSubmit={handlePasswordChange} className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
          <h3 className="text-sm font-medium text-gray-900">Change Password</h3>
          <div className="space-y-3 max-w-sm">
            <div>
              <label htmlFor="currentPassword" className="block text-sm text-gray-600 mb-1">Current password</label>
              <input
                id="currentPassword"
                type="password"
                value={currentPassword}
                onChange={e => setCurrentPassword(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
                autoComplete="current-password"
              />
            </div>
            <div>
              <label htmlFor="newPassword" className="block text-sm text-gray-600 mb-1">New password</label>
              <input
                id="newPassword"
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
                autoComplete="new-password"
              />
              <PasswordRequirements password={newPassword} />
            </div>
            <div>
              <label htmlFor="confirmPassword" className="block text-sm text-gray-600 mb-1">Confirm new password</label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
                autoComplete="new-password"
              />
              <PasswordMatch password={newPassword} confirmPassword={confirmPassword} />
            </div>
          </div>
          {pwError && <p className="text-sm text-red-600" role="alert">{pwError}</p>}
          {pwMsg && <p className="text-sm text-green-600">{pwMsg}</p>}
          <button
            type="submit"
            disabled={pwSaving || !currentPassword || !newPassword || !confirmPassword}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 min-h-[44px]"
          >
            {pwSaving ? 'Changing…' : 'Change password'}
          </button>
        </form>
      )}

      {/* MFA section */}
      <MfaSettings />
    </div>
  )
}
