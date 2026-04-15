import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Modal } from '@/components/ui/Modal'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

interface OrgUser {
  id: string
  email: string
  role: string
  is_active: boolean
  last_login_at: string | null
  is_email_verified: boolean
  [key: string]: unknown
}

interface RoleOption {
  slug: string
  name: string
  is_system: boolean
}

interface PlanInfo { user_seats: number }
interface InviteForm { email: string; role: string; password: string }

// Roles that should not appear in the invite dropdown
const HIDDEN_ROLE_SLUGS = new Set(['global_admin'])

export function UserManagement() {
  const [users, setUsers] = useState<OrgUser[]>([])
  const [roles, setRoles] = useState<RoleOption[]>([])
  const [plan, setPlan] = useState<PlanInfo | null>(null)
  const [mfaPolicy, setMfaPolicy] = useState<'optional' | 'mandatory'>('optional')
  const [loading, setLoading] = useState(true)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteForm, setInviteForm] = useState<InviteForm>({ email: '', role: 'salesperson', password: '' })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const [userRes, settingsRes, rolesRes] = await Promise.all([
        apiClient.get('/org/users', { signal }),
        apiClient.get('/org/settings', { signal }),
        apiClient.get<RoleOption[]>('/org/roles', { signal }),
      ])
      // Handle both array and wrapped response formats
      const userData = Array.isArray(userRes.data) ? userRes.data : (userRes.data?.users ?? [])
      setUsers(userData)
      setMfaPolicy(settingsRes.data?.mfa_policy ?? 'optional')
      if (settingsRes.data?.plan) {
        setPlan({ user_seats: settingsRes.data?.plan?.user_seats ?? 0 })
      }
      // Filter out global_admin from assignable roles
      const allRoles = Array.isArray(rolesRes.data) ? rolesRes.data : []
      setRoles(allRoles.filter((r) => !HIDDEN_ROLE_SLUGS.has(r?.slug)))
    } catch (err) {
      if (signal && signal.aborted) return
      addToast('error', 'Failed to load users')
      setUsers([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [])

  const activeCount = users.filter((u) => u.is_active).length
  const seatLimit = plan?.user_seats ?? 0
  const atLimit = seatLimit > 0 && activeCount >= seatLimit

  const inviteUser = async () => {
    if (!inviteForm.email.trim()) return
    if (inviteForm.role === 'kiosk' && inviteForm.password.length < 8) {
      addToast('error', 'Password must be at least 8 characters')
      return
    }
    if (atLimit) {
      addToast('error', 'Seat limit reached. Upgrade your plan to invite more users.')
      return
    }
    setSaving(true)
    try {
      const payload: Record<string, string | null> = {
        email: inviteForm.email,
        role: inviteForm.role,
      }
      if (inviteForm.role === 'kiosk' && inviteForm.password) {
        payload.password = inviteForm.password
      }
      await apiClient.post('/org/users/invite', payload)
      setInviteOpen(false)
      setInviteForm({ email: '', role: 'salesperson', password: '' })
      addToast('success', inviteForm.role === 'kiosk' && inviteForm.password ? 'Kiosk account created' : 'Invitation sent')
      fetchData()
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Failed to send invitation'
      addToast('error', detail)
    } finally {
      setSaving(false)
    }
  }

  const deactivateUser = async (userId: string) => {
    if (!confirm('Deactivate this user? All their active sessions will be terminated.')) return
    try {
      await apiClient.delete(`/org/users/${userId}`)
      addToast('success', 'User deactivated')
      fetchData()
    } catch {
      addToast('error', 'Failed to deactivate user')
    }
  }

  const revokeUserSessions = async (userId: string) => {
    if (!confirm('Revoke all active sessions for this kiosk user? The tablet will need to re-authenticate.')) return
    try {
      await apiClient.post(`/org/users/${userId}/revoke-sessions`)
      addToast('success', 'Sessions revoked')
      fetchData()
    } catch {
      addToast('error', 'Failed to revoke sessions')
    }
  }

  const [resendingEmail, setResendingEmail] = useState<string | null>(null)
  const [resendCooldowns, setResendCooldowns] = useState<Record<string, number>>({})

  const resendInvite = async (email: string) => {
    setResendingEmail(email)
    try {
      await apiClient.post('/auth/resend-invite', { email })
      addToast('success', `Invitation resent to ${email}`)
      setResendCooldowns(prev => ({ ...prev, [email]: 60 }))
    } catch {
      addToast('error', 'Failed to resend invitation')
    } finally {
      setResendingEmail(null)
    }
  }

  // Countdown timer for resend cooldowns
  useEffect(() => {
    const hasActive = Object.values(resendCooldowns).some(v => v > 0)
    if (!hasActive) return
    const timer = setInterval(() => {
      setResendCooldowns(prev => {
        const next: Record<string, number> = {}
        for (const [k, v] of Object.entries(prev)) {
          if (v > 1) next[k] = v - 1
        }
        return next
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [resendCooldowns])

  const deleteUserPermanently = async (userId: string, email: string) => {
    if (!confirm(`PERMANENTLY delete ${email}? This cannot be undone. Their invoices will be reassigned to you.`)) return
    try {
      await apiClient.delete(`/org/users/${userId}/permanent`)
      addToast('success', `User ${email} permanently deleted`)
      fetchData()
    } catch (err: any) {
      addToast('error', err?.response?.data?.detail || 'Failed to delete user')
    }
  }

  const toggleMfaPolicy = async () => {
    const newPolicy = mfaPolicy === 'optional' ? 'mandatory' : 'optional'
    try {
      await apiClient.put('/org/settings', { mfa_policy: newPolicy })
      setMfaPolicy(newPolicy)
      addToast('success', `MFA set to ${newPolicy}`)
    } catch {
      addToast('error', 'Failed to update MFA policy')
    }
  }

  const formatDate = (iso: string | null) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleDateString('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' })
  }

  const roleLabel = (slug: string) => {
    const found = roles.find((r) => r?.slug === slug)
    return found?.name ?? slug
  }

  const roleOptions = (roles ?? []).map((r) => ({
    value: r?.slug ?? '',
    label: r?.name ?? r?.slug ?? '',
  }))

  const columns: Column<OrgUser>[] = [
    { key: 'email', header: 'Email', sortable: true },
    {
      key: 'role', header: 'Role',
      render: (row) => (
        <Badge variant={row.role === 'kiosk' ? 'warning' : 'info'}>
          {roleLabel(row.role)}
        </Badge>
      ),
    },
    {
      key: 'is_active', header: 'Status',
      render: (row) => (
        <Badge variant={row.is_active ? 'success' : 'neutral'}>
          {row.is_active ? (row.is_email_verified ? 'Active' : 'Pending') : 'Inactive'}
        </Badge>
      ),
    },
    { key: 'last_login_at', header: 'Last Activity', render: (row) => {
      const dateStr = formatDate(row.last_login_at)
      if (row.role === 'kiosk' && row.last_login_at) {
        return <span className="text-sm font-medium">{dateStr}</span>
      }
      return dateStr
    }},
    {
      key: 'actions', header: 'Actions',
      render: (row) => {
        if (!row.is_active) return (
          <div className="flex gap-2">
            <span className="text-sm text-gray-400">Deactivated</span>
            <Button size="sm" variant="danger" onClick={() => deleteUserPermanently(row.id, row.email)}>Delete</Button>
          </div>
        )
        return (
          <div className="flex gap-2">
            {row.is_active && !row.is_email_verified && (
              resendCooldowns[row.email] > 0
                ? <span className="text-xs text-gray-500 tabular-nums">Resend in {resendCooldowns[row.email]}s</span>
                : <Button size="sm" variant="secondary" loading={resendingEmail === row.email} onClick={() => resendInvite(row.email)}>Resend Invite</Button>
            )}
            {row.role === 'kiosk' && row.is_active && (
              <Button size="sm" variant="secondary" onClick={() => revokeUserSessions(row.id)}>Revoke Sessions</Button>
            )}
            <Button size="sm" variant="danger" onClick={() => deactivateUser(row.id)}>Deactivate</Button>
            <Button size="sm" variant="danger" onClick={() => deleteUserPermanently(row.id, row.email)}>Delete</Button>
          </div>
        )
      },
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">User Management</h1>
        <Button onClick={() => setInviteOpen(true)} disabled={atLimit}>
          {atLimit ? 'Seat Limit Reached' : 'Invite User'}
        </Button>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Seat usage & MFA policy */}
      <div className="flex flex-wrap items-center gap-6 mb-6 p-4 bg-gray-50 rounded-lg">
        <div className="text-sm text-gray-700">
          <span className="font-medium">Seats:</span> {activeCount} / {seatLimit || '∞'}
          {atLimit && (
            <span className="ml-2 text-red-600 font-medium">
              — <a href="/settings/billing" className="underline">Upgrade plan</a> to add more users
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-700">MFA Policy:</span>
          <button role="switch" aria-checked={mfaPolicy === 'mandatory'} aria-label="MFA policy toggle"
            onClick={toggleMfaPolicy}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${mfaPolicy === 'mandatory' ? 'bg-blue-600' : 'bg-gray-300'}`}>
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${mfaPolicy === 'mandatory' ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
          <span className="text-sm text-gray-600">{mfaPolicy === 'mandatory' ? 'Mandatory' : 'Optional'}</span>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-500">Loading users…</p>
      ) : (
        <DataTable columns={columns} data={users} keyField="id" caption="Organisation users" />
      )}

      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title={inviteForm.role === 'kiosk' ? 'Create Kiosk Account' : 'Invite User'}>
        <div className="space-y-4">
          <Input label="Email Address" type="email" value={inviteForm.email}
            onChange={(e) => setInviteForm((p) => ({ ...p, email: e.target.value }))} required />
          <Select label="Role" options={roleOptions} value={inviteForm.role}
            onChange={(e) => setInviteForm((p) => ({ ...p, role: e.target.value, password: '' }))} />
          {inviteForm.role === 'kiosk' && (
            <>
              <Input
                label="Password"
                type="password"
                value={inviteForm.password}
                onChange={(e) => setInviteForm((p) => ({ ...p, password: e.target.value }))}
                required
                placeholder="Min 8 characters"
              />
              <p className="text-sm text-gray-500">
                Set the password now so you can log in directly on the tablet. No invite email will be sent.
              </p>
            </>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setInviteOpen(false)}>Cancel</Button>
            <Button onClick={inviteUser} loading={saving}>
              {inviteForm.role === 'kiosk' ? 'Create Account' : 'Send Invitation'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
