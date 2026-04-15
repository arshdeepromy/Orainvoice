import { useState, useEffect, useCallback } from 'react'
import { Collapsible } from '@/components/ui/Collapsible'
import { useToast, ToastContainer } from '@/components/ui/Toast'
import { MfaSettings } from '@/pages/settings/MfaSettings'
import { PasswordRequirements, PasswordMatch, allPasswordRulesMet } from '@/components/auth/PasswordRequirements'
import apiClient from '@/api/client'
import { PlatformSecurityAuditLogSection } from '@/components/admin/PlatformSecurityAuditLogSection'

interface SessionInfo {
  id: string
  device_type: string | null
  browser: string | null
  ip_address: string | null
  last_activity_at: string | null
  created_at: string | null
  current: boolean
}

interface SessionListResponse {
  sessions: SessionInfo[]
}

interface InvalidateAllResponse {
  sessions_revoked: number
  message: string
}

export function AdminSecurityPage() {
  const { toasts, addToast, dismissToast } = useToast()

  // --- Session Management State ---
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokingAll, setRevokingAll] = useState(false)

  // --- Password Change State ---
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordLoading, setPasswordLoading] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [passwordSuccess, setPasswordSuccess] = useState('')

  const fetchSessions = useCallback((signal?: AbortSignal) => {
    const load = async () => {
      setSessionsLoading(true)
      setSessionsError(null)
      try {
        const res = await apiClient.get<SessionListResponse>('/auth/sessions', { signal })
        setSessions(res.data?.sessions ?? [])
      } catch (err: unknown) {
        if (signal && signal.aborted) return
        setSessionsError('Failed to load sessions')
      } finally {
        setSessionsLoading(false)
      }
    }
    load()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchSessions(controller.signal)
    return () => controller.abort()
  }, [fetchSessions])

  const revokeSession = async (sessionId: string) => {
    setRevokingId(sessionId)
    try {
      await apiClient.delete<{ message: string }>(`/auth/sessions/${sessionId}`)
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
      addToast('success', 'Session revoked successfully')
    } catch {
      addToast('error', 'Failed to revoke session')
    } finally {
      setRevokingId(null)
    }
  }

  const revokeAllOtherSessions = async () => {
    setRevokingAll(true)
    try {
      const res = await apiClient.post<InvalidateAllResponse>('/auth/sessions/invalidate-all')
      const count = res.data?.sessions_revoked ?? 0
      addToast('success', `Revoked ${count} other session(s)`)
      fetchSessions()
    } catch {
      addToast('error', 'Failed to revoke all sessions')
    } finally {
      setRevokingAll(false)
    }
  }

  const otherSessionCount = (sessions ?? []).filter((s) => !s?.current).length

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError('')
    setPasswordSuccess('')

    if (newPassword !== confirmPassword) {
      setPasswordError('Passwords do not match')
      return
    }
    if (!allPasswordRulesMet(newPassword)) {
      setPasswordError('Password does not meet requirements')
      return
    }

    setPasswordLoading(true)
    try {
      await apiClient.post<{ message: string }>('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setPasswordSuccess('Password changed successfully')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setTimeout(() => setPasswordSuccess(''), 3000)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPasswordError(detail ?? 'Failed to change password')
    } finally {
      setPasswordLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Security Settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-2">
        <Collapsible label="🔐 MFA Management" defaultOpen className="border rounded-lg">
          <MfaSettings />
        </Collapsible>

        <Collapsible label="⏱ Active Sessions" className="border rounded-lg">
          <div>
            {sessionsLoading && (
              <p className="text-sm text-gray-500 py-4">Loading sessions…</p>
            )}

            {sessionsError && (
              <div className="rounded-md bg-red-50 p-3 mb-4">
                <p className="text-sm text-red-700">{sessionsError}</p>
              </div>
            )}

            {!sessionsLoading && !sessionsError && (
              <>
                {otherSessionCount > 0 && (
                  <div className="mb-4">
                    <button
                      type="button"
                      onClick={revokeAllOtherSessions}
                      disabled={revokingAll}
                      className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {revokingAll ? 'Revoking…' : 'Revoke All Other Sessions'}
                    </button>
                  </div>
                )}

                {(sessions ?? []).length === 0 ? (
                  <p className="text-sm text-gray-500 py-4">No active sessions found.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-2 text-left font-medium text-gray-500">Device</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-500">Browser</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-500">IP Address</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-500">Created</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-500">Status</th>
                          <th className="px-4 py-2 text-right font-medium text-gray-500">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {(sessions ?? []).map((session) => (
                          <tr key={session?.id ?? ''} className="hover:bg-gray-50">
                            <td className="px-4 py-2 text-gray-700">{session?.device_type ?? '—'}</td>
                            <td className="px-4 py-2 text-gray-700">{session?.browser ?? '—'}</td>
                            <td className="px-4 py-2 text-gray-700 font-mono text-xs">{session?.ip_address ?? '—'}</td>
                            <td className="px-4 py-2 text-gray-700">
                              {session?.created_at
                                ? new Date(session.created_at).toLocaleString()
                                : '—'}
                            </td>
                            <td className="px-4 py-2">
                              {session?.current && (
                                <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                                  Current
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-right">
                              {!session?.current && (
                                <button
                                  type="button"
                                  onClick={() => revokeSession(session?.id ?? '')}
                                  disabled={revokingId === session?.id}
                                  className="rounded-md bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                  {revokingId === session?.id ? 'Revoking…' : 'Revoke'}
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </Collapsible>

        <Collapsible label="🔑 Change Password" className="border rounded-lg">
          <form onSubmit={handlePasswordChange} className="space-y-4">
            <div className="space-y-3 max-w-sm">
              <div>
                <label htmlFor="currentPassword" className="block text-sm text-gray-600 mb-1">Current password</label>
                <input
                  id="currentPassword"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
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
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
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
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                  required
                  autoComplete="new-password"
                />
                <PasswordMatch password={newPassword} confirmPassword={confirmPassword} />
              </div>
            </div>
            {passwordError && <p className="text-sm text-red-600" role="alert">{passwordError}</p>}
            {passwordSuccess && <p className="text-sm text-green-600">{passwordSuccess}</p>}
            <button
              type="submit"
              disabled={passwordLoading || !currentPassword || !newPassword || !confirmPassword}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
            >
              {passwordLoading ? 'Changing…' : 'Change password'}
            </button>
          </form>
        </Collapsible>

        <Collapsible label="📋 Security Audit Log" className="border rounded-lg">
          <PlatformSecurityAuditLogSection />
        </Collapsible>
      </div>
    </div>
  )
}
