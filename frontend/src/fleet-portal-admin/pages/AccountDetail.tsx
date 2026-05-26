/**
 * Workshop Admin — Fleet portal account detail page.
 * Shows account info with admin actions: unlock, force MFA re-enrol, reset password.
 *
 * Implements: B2B Fleet Portal — Requirements 21.17, 21.18, 21.19, 21.20.
 */
import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'

import apiClient from '../../api/client'

interface AccountInfo {
  portal_account_id: string
  email: string
  first_name: string | null
  last_name: string | null
  portal_user_role: string
  is_active: boolean
  is_locked_permanently: boolean
  failed_login_attempts: number
  last_login_at: string | null
  mfa_methods: Array<{ id: string; method: string; verified: boolean }>
  created_at: string
}

export default function AccountDetail() {
  const { accountId } = useParams<{ accountId: string }>()
  const [account, setAccount] = useState<AccountInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionMsg, setActionMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const fetchAccount = async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<AccountInfo>(
        `/api/v2/fleet-portal/admin/accounts/${accountId}`,
        { signal },
      )
      setAccount(res.data ?? null)
    } catch {
      setAccount(null)
    } finally { setLoading(false) }
  }

  useEffect(() => {
    const controller = new AbortController()
    fetchAccount(controller.signal)
    return () => controller.abort()
  }, [accountId])

  const adminAction = async (action: string, confirmMsg: string) => {
    if (!confirm(confirmMsg)) return
    setActionMsg(null)
    try {
      await apiClient.post(`/api/v2/fleet-portal/admin/accounts/${accountId}/${action}`)
      setActionMsg({ type: 'ok', text: `Action "${action}" completed successfully.` })
      await fetchAccount()
    } catch (err: unknown) {
      setActionMsg({ type: 'err', text: (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `Failed to ${action}.` })
    }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>
  if (!account) return (
    <div className="space-y-4">
      <Link to="/fleet-portal-admin" className="text-sm text-indigo-600 hover:underline">← Back</Link>
      <p className="text-sm text-gray-500">Account not found.</p>
    </div>
  )

  return (
    <div className="space-y-6">
      <div>
        <Link to="/fleet-portal-admin" className="text-sm text-indigo-600 hover:underline">← Back to Fleet Portal</Link>
        <h1 className="mt-2 text-xl font-semibold text-gray-900 dark:text-white">
          {[account.first_name, account.last_name].filter(Boolean).join(' ') || account.email}
        </h1>
      </div>

      {actionMsg && (
        <div className={`rounded border p-3 text-sm ${actionMsg.type === 'ok' ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'}`}>
          {actionMsg.text}
        </div>
      )}

      {/* Account info */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium mb-3">Account Information</h2>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-sm">
          <div><dt className="text-xs text-gray-500">Email</dt><dd>{account.email}</dd></div>
          <div><dt className="text-xs text-gray-500">Role</dt><dd className="capitalize">{account.portal_user_role?.replace('_', ' ')}</dd></div>
          <div><dt className="text-xs text-gray-500">Status</dt><dd>
            {account.is_locked_permanently ? <span className="text-red-600 font-medium">Permanently Locked</span> :
             !account.is_active ? <span className="text-red-600">Revoked</span> :
             (account.failed_login_attempts ?? 0) >= 5 ? <span className="text-orange-600">Temporarily Locked</span> :
             <span className="text-green-600">Active</span>}
          </dd></div>
          <div><dt className="text-xs text-gray-500">Failed Attempts</dt><dd>{account.failed_login_attempts ?? 0}</dd></div>
          <div><dt className="text-xs text-gray-500">Last Login</dt><dd>{account.last_login_at ? new Date(account.last_login_at).toLocaleString() : 'Never'}</dd></div>
          <div><dt className="text-xs text-gray-500">Created</dt><dd>{new Date(account.created_at).toLocaleDateString()}</dd></div>
        </dl>
      </div>

      {/* MFA methods */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium mb-3">MFA Methods</h2>
        {(account.mfa_methods ?? []).length === 0 ? (
          <p className="text-xs text-gray-500">No MFA methods enrolled.</p>
        ) : (
          <div className="space-y-2">
            {(account.mfa_methods ?? []).map(m => (
              <div key={m.id} className="flex items-center justify-between rounded border border-gray-200 px-3 py-2 dark:border-gray-700">
                <span className="text-sm capitalize">{m.method === 'totp' ? '🔐 Authenticator' : m.method}</span>
                {m.verified && <span className="text-xs bg-green-100 text-green-800 px-1.5 py-0.5 rounded">Verified</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Admin actions */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium mb-3">Admin Actions</h2>
        <div className="flex flex-wrap gap-2">
          {(account.is_locked_permanently || (account.failed_login_attempts ?? 0) >= 5) && (
            <button
              onClick={() => adminAction('unlock', 'Unlock this account? They will be able to log in again.')}
              className="rounded-md border border-green-300 px-3 py-2 text-sm font-medium text-green-700 min-h-[44px] hover:bg-green-50"
            >
              Unlock Account
            </button>
          )}
          <button
            onClick={() => adminAction('force-mfa-reset', 'Force MFA re-enrolment? Their existing MFA methods will be removed and they will need to set up MFA again.')}
            className="rounded-md border border-orange-300 px-3 py-2 text-sm font-medium text-orange-700 min-h-[44px] hover:bg-orange-50"
          >
            Force MFA Re-enrol
          </button>
          <button
            onClick={() => adminAction('reset-password', 'Send a password reset email to this account?')}
            className="rounded-md border border-blue-300 px-3 py-2 text-sm font-medium text-blue-700 min-h-[44px] hover:bg-blue-50"
          >
            Reset Password
          </button>
          <button
            onClick={async () => {
              if (!confirm('Impersonate this user? You will be logged in as them in a new tab.')) return
              setActionMsg(null)
              try {
                const res = await apiClient.post<{ session_token: string; csrf_token: string }>(`/api/v2/fleet-portal/admin/accounts/${accountId}/impersonate`)
                const { session_token, csrf_token } = res.data ?? {}
                if (session_token && csrf_token) {
                  // Set cookies and open fleet portal in new tab
                  document.cookie = `fleet_portal_session=${session_token}; path=/fleet; SameSite=Lax`
                  document.cookie = `fleet_portal_csrf=${csrf_token}; path=/fleet; SameSite=Lax`
                  window.open('/fleet/dashboard', '_blank')
                  setActionMsg({ type: 'ok', text: 'Impersonation session created. Check the new tab.' })
                }
              } catch (err: unknown) {
                setActionMsg({ type: 'err', text: (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to impersonate.' })
              }
            }}
            className="rounded-md border border-purple-300 px-3 py-2 text-sm font-medium text-purple-700 min-h-[44px] hover:bg-purple-50"
          >
            Impersonate
          </button>
          {account.is_active && (
            <button
              onClick={() => adminAction('revoke', 'Revoke portal access? They will no longer be able to log in.')}
              className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 min-h-[44px] hover:bg-red-50"
            >
              Revoke Access
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
