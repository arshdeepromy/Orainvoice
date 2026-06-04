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
      <h1 className="text-2xl font-semibold text-text mb-6">Security Settings</h1>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="space-y-2">
        <Collapsible label="🔐 MFA Management" defaultOpen className="border border-border rounded-card">
          <MfaSettings />
        </Collapsible>

        <Collapsible label="⏱ Active Sessions" className="border border-border rounded-card">
          <div>
            {sessionsLoading && (
              <p className="text-sm text-muted py-4">Loading sessions…</p>
            )}

            {sessionsError && (
              <div className="rounded-ctl bg-danger-soft p-3 mb-4">
                <p className="text-sm text-danger">{sessionsError}</p>
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
                      className="rounded-ctl bg-danger px-3 py-2 text-sm font-medium text-white hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {revokingAll ? 'Revoking…' : 'Revoke All Other Sessions'}
                    </button>
                  </div>
                )}

                {(sessions ?? []).length === 0 ? (
                  <p className="text-sm text-muted py-4">No active sessions found.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr>
                          <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Device</th>
                          <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Browser</th>
                          <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">IP Address</th>
                          <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Created</th>
                          <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                          <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(sessions ?? []).map((session) => (
                          <tr key={session?.id ?? ''} className="border-b border-border last:border-b-0 hover:bg-canvas">
                            <td className="px-4 py-2 text-text">{session?.device_type ?? '—'}</td>
                            <td className="px-4 py-2 text-text">{session?.browser ?? '—'}</td>
                            <td className="mono px-4 py-2 text-text text-xs">{session?.ip_address ?? '—'}</td>
                            <td className="px-4 py-2 text-text">
                              {session?.created_at
                                ? new Date(session.created_at).toLocaleString()
                                : '—'}
                            </td>
                            <td className="px-4 py-2">
                              {session?.current && (
                                <span className="inline-flex items-center rounded-full bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">
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
                                  className="rounded-ctl bg-danger-soft px-2.5 py-1 text-xs font-medium text-danger hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
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

        <Collapsible label="🔑 Change Password" className="border border-border rounded-card">
          <form onSubmit={handlePasswordChange} className="space-y-4">
            <div className="space-y-3 max-w-sm">
              <div>
                <label htmlFor="currentPassword" className="block text-sm text-muted mb-1">Current password</label>
                <input
                  id="currentPassword"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  required
                  autoComplete="current-password"
                />
              </div>
              <div>
                <label htmlFor="newPassword" className="block text-sm text-muted mb-1">New password</label>
                <input
                  id="newPassword"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  required
                  autoComplete="new-password"
                />
                <PasswordRequirements password={newPassword} />
              </div>
              <div>
                <label htmlFor="confirmPassword" className="block text-sm text-muted mb-1">Confirm new password</label>
                <input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  required
                  autoComplete="new-password"
                />
                <PasswordMatch password={newPassword} confirmPassword={confirmPassword} />
              </div>
            </div>
            {passwordError && <p className="text-sm text-danger" role="alert">{passwordError}</p>}
            {passwordSuccess && <p className="text-sm text-ok">{passwordSuccess}</p>}
            <button
              type="submit"
              disabled={passwordLoading || !currentPassword || !newPassword || !confirmPassword}
              className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
            >
              {passwordLoading ? 'Changing…' : 'Change password'}
            </button>
          </form>
        </Collapsible>

        <Collapsible label="📋 Security Audit Log" className="border border-border rounded-card">
          <PlatformSecurityAuditLogSection />
        </Collapsible>
      </div>
    </div>
  )
}
