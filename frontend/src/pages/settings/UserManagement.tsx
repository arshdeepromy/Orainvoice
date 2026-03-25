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

interface PlanInfo { user_seats: number }
interface InviteForm { email: string; role: string }

const ROLE_OPTIONS = [
  { value: 'org_admin', label: 'Org Admin' },
  { value: 'salesperson', label: 'Salesperson' },
]

export function UserManagement() {
  const [users, setUsers] = useState<OrgUser[]>([])
  const [plan, setPlan] = useState<PlanInfo | null>(null)
  const [mfaPolicy, setMfaPolicy] = useState<'optional' | 'mandatory'>('optional')
  const [loading, setLoading] = useState(true)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteForm, setInviteForm] = useState<InviteForm>({ email: '', role: 'salesperson' })
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [userRes, settingsRes] = await Promise.all([
        apiClient.get('/org/users'),
        apiClient.get('/org/settings'),
      ])
      // Handle both array and wrapped response formats
      const userData = Array.isArray(userRes.data) ? userRes.data : (userRes.data?.users || [])
      setUsers(userData)
      setMfaPolicy(settingsRes.data.mfa_policy || 'optional')
      if (settingsRes.data.plan) {
        setPlan({ user_seats: settingsRes.data.plan.user_seats })
      }
    } catch {
      addToast('error', 'Failed to load users')
      setUsers([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const activeCount = users.filter((u) => u.is_active).length
  const seatLimit = plan?.user_seats ?? 0
  const atLimit = seatLimit > 0 && activeCount >= seatLimit

  const inviteUser = async () => {
    if (!inviteForm.email.trim()) return
    if (atLimit) {
      addToast('error', 'Seat limit reached. Upgrade your plan to invite more users.')
      return
    }
    setSaving(true)
    try {
      await apiClient.post('/org/users/invite', inviteForm)
      setInviteOpen(false)
      setInviteForm({ email: '', role: 'salesperson' })
      addToast('success', 'Invitation sent')
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

  const columns: Column<OrgUser>[] = [
    { key: 'email', header: 'Email', sortable: true },
    {
      key: 'role', header: 'Role',
      render: (row) => <Badge variant="info">{row.role === 'org_admin' ? 'Org Admin' : 'Salesperson'}</Badge>,
    },
    {
      key: 'is_active', header: 'Status',
      render: (row) => (
        <Badge variant={row.is_active ? 'success' : 'neutral'}>
          {row.is_active ? (row.is_email_verified ? 'Active' : 'Pending') : 'Inactive'}
        </Badge>
      ),
    },
    { key: 'last_login_at', header: 'Last Login', render: (row) => formatDate(row.last_login_at) },
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

      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite User">
        <div className="space-y-4">
          <Input label="Email Address" type="email" value={inviteForm.email}
            onChange={(e) => setInviteForm((p) => ({ ...p, email: e.target.value }))} required />
          <Select label="Role" options={ROLE_OPTIONS} value={inviteForm.role}
            onChange={(e) => setInviteForm((p) => ({ ...p, role: e.target.value }))} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setInviteOpen(false)}>Cancel</Button>
            <Button onClick={inviteUser} loading={saving}>Send Invitation</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
