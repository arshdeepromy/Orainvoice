import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { Profile } from '@/pages/settings/Profile'

interface UserRow {
  id: string
  email: string
  role: string
  is_active: boolean
  is_email_verified: boolean
  last_login_at: string | null
  created_at: string | null
  org_id: string | null
  org_name: string | null
}

const ROLE_LABELS: Record<string, string> = {
  global_admin: 'Global Admin',
  franchise_admin: 'Franchise Admin',
  org_admin: 'Org Admin',
  location_manager: 'Location Manager',
  salesperson: 'Salesperson',
  staff_member: 'Staff Member',
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
}

function ActionsMenu({
  user,
  loading,
  onToggleActive,
  onResetPassword,
  onResetMfa,
  onDelete,
}: {
  user: UserRow
  loading: boolean
  onToggleActive: () => void
  onResetPassword: () => void
  onResetMfa: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const menuItem = (label: string, onClick: () => void, danger = false) => (
    <button
      type="button"
      disabled={loading}
      onClick={() => { setOpen(false); onClick() }}
      className={`w-full text-left px-3 py-2 text-sm ${
        danger
          ? 'text-red-600 hover:bg-red-50'
          : 'text-gray-700 hover:bg-gray-100'
      } disabled:opacity-50`}
    >
      {label}
    </button>
  )

  return (
    <div className="relative" ref={ref}>
      <Button size="sm" variant="secondary" onClick={() => setOpen(!open)} aria-label="User actions">
        {loading ? <Spinner /> : '⋯'}
      </Button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-52 bg-white border border-gray-200 rounded-lg shadow-lg py-1">
          {menuItem(user.is_active ? 'Deactivate' : 'Activate', onToggleActive)}
          {menuItem('Send Reset Password', onResetPassword)}
          {menuItem('Reset MFA', onResetMfa)}
          <div className="border-t border-gray-100 my-1" />
          {menuItem('Delete Permanently', onDelete, true)}
        </div>
      )}
    </div>
  )
}

export function UserManagement() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tab: 'org' | 'global' = tabParam === 'global' ? 'global' : 'org'
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [createForm, setCreateForm] = useState({ email: '', first_name: '', last_name: '', password: '' })
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState('')
  const { toasts, addToast, dismissToast } = useToast()

  const ORG_ROLES = ['org_admin', 'franchise_admin', 'location_manager', 'salesperson', 'staff_member']
  const GLOBAL_ROLES = ['global_admin']

  const fetchUsers = async () => {
    setLoading(true)
    setError(false)
    try {
      const params: Record<string, string> = { page: String(page), page_size: '25' }
      if (search.trim()) params.search = search.trim()
      if (statusFilter) params.is_active = statusFilter

      if (tab === 'global') {
        // Global Admin tab — always filter to global_admin role
        params.role = 'global_admin'
      } else {
        // Org Users tab — use selected role filter, or no role filter (backend returns all)
        if (roleFilter) params.role = roleFilter
      }

      const res = await apiClient.get('/admin/users', { params })
      let fetched: UserRow[] = res.data.users ?? []

      // Client-side filter: if org tab with no role filter, exclude global_admin users
      if (tab === 'org' && !roleFilter) {
        fetched = fetched.filter((u) => u.role !== 'global_admin')
      }

      setUsers(fetched)
      setTotal(tab === 'org' && !roleFilter ? fetched.length : (res.data.total ?? 0))
    } catch {
      setError(true)
      addToast('error', 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchUsers() }, [page, tab])

  const handleSearch = () => { setPage(1); fetchUsers() }

  const handleTabChange = (newTab: 'org' | 'global') => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('tab', newTab)
      return next
    }, { replace: true })
    setSearch('')
    setRoleFilter('')
    setStatusFilter('')
    setPage(1)
  }

  const [deleteConfirm, setDeleteConfirm] = useState<UserRow | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const handleToggleActive = async (user: UserRow) => {
    setActionLoading(user.id)
    try {
      await apiClient.put(`/admin/users/${user.id}/status`)
      addToast('success', `User ${user.is_active ? 'deactivated' : 'activated'}`)
      fetchUsers()
    } catch {
      addToast('error', 'Failed to update user status')
    } finally {
      setActionLoading(null)
    }
  }

  const handleDeleteUser = async (user: UserRow) => {
    setActionLoading(user.id)
    try {
      await apiClient.delete(`/admin/users/${user.id}`)
      addToast('success', `User ${user.email} permanently deleted`)
      setDeleteConfirm(null)
      fetchUsers()
    } catch (err: any) {
      addToast('error', err?.response?.data?.detail || 'Failed to delete user')
    } finally {
      setActionLoading(null)
    }
  }

  const handleResetPassword = async (user: UserRow) => {
    setActionLoading(user.id)
    try {
      await apiClient.post(`/admin/users/${user.id}/reset-password`)
      addToast('success', `Password reset link sent to ${user.email}`)
    } catch (err: any) {
      addToast('error', err?.response?.data?.detail || 'Failed to send reset link')
    } finally {
      setActionLoading(null)
    }
  }

  const handleResetMfa = async (user: UserRow) => {
    setActionLoading(user.id)
    try {
      await apiClient.post(`/admin/users/${user.id}/reset-mfa`)
      addToast('success', `MFA reset for ${user.email}`)
    } catch (err: any) {
      addToast('error', err?.response?.data?.detail || 'Failed to reset MFA')
    } finally {
      setActionLoading(null)
    }
  }

  const handleCreateGlobalAdmin = async () => {
    if (!createForm.email || !createForm.password) {
      setCreateError('Email and password are required')
      return
    }
    if (createForm.password.length < 8) {
      setCreateError('Password must be at least 8 characters')
      return
    }
    setCreateSaving(true)
    setCreateError('')
    try {
      await apiClient.post('/admin/users/global-admin', createForm)
      addToast('success', `Global admin ${createForm.email} created`)
      setCreateModalOpen(false)
      setCreateForm({ email: '', first_name: '', last_name: '', password: '' })
      fetchUsers()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to create global admin'
      setCreateError(msg)
    } finally {
      setCreateSaving(false)
    }
  }

  const columns: Column<UserRow>[] = [
    { key: 'email', header: 'Email', sortable: true },
    {
      key: 'role',
      header: 'Role',
      sortable: true,
      render: (row) => <Badge variant="neutral">{ROLE_LABELS[row.role] ?? row.role}</Badge>,
    },
    ...(tab === 'org' ? [{
      key: 'org_name' as keyof UserRow,
      header: 'Organisation',
      render: (row: UserRow) => row.org_name ?? <span className="text-gray-400">Platform</span>,
    }] : []),
    {
      key: 'is_active',
      header: 'Status',
      render: (row) => (
        <Badge variant={row.is_active ? 'success' : 'error'}>
          {row.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    {
      key: 'is_email_verified',
      header: 'Verified',
      render: (row) => (
        <Badge variant={row.is_email_verified ? 'success' : 'warning'}>
          {row.is_email_verified ? 'Yes' : 'No'}
        </Badge>
      ),
    },
    { key: 'last_login_at', header: 'Last login', render: (row) => formatDate(row.last_login_at) },
    { key: 'created_at', header: 'Created', render: (row) => formatDate(row.created_at) },
    {
      key: 'id',
      header: 'Actions',
      render: (row) => (
        <ActionsMenu
          user={row}
          loading={actionLoading === row.id}
          onToggleActive={() => handleToggleActive(row)}
          onResetPassword={() => handleResetPassword(row)}
          onResetMfa={() => handleResetMfa(row)}
          onDelete={() => setDeleteConfirm(row)}
        />
      ),
    },
  ]

  const roleOptions = tab === 'org'
    ? ORG_ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] ?? r }))
    : GLOBAL_ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] ?? r }))

  if (loading && users.length === 0) {
    return <div className="flex items-center justify-center py-20"><Spinner label="Loading users" /></div>
  }

  if (error && users.length === 0) {
    return <AlertBanner variant="error" title="Something went wrong">Could not load users. Please try again.</AlertBanner>
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">User Management</h1>
        <div className="flex items-center gap-3">
          {tab === 'global' && (
            <Button onClick={() => { setCreateError(''); setCreateModalOpen(true) }}>+ Add Global Admin</Button>
          )}
          <span className="text-sm text-gray-500">{total} users total</span>
        </div>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-4">
        <button
          type="button"
          onClick={() => handleTabChange('org')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'org'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          Organisation Users
        </button>
        <button
          type="button"
          onClick={() => handleTabChange('global')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'global'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          Global Admin Users
        </button>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <Input label="Search by email" placeholder="Search..." value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className="sm:w-72" />
        {tab === 'org' && (
          <Select label="Role" options={[{ value: '', label: 'All roles' }, ...roleOptions]} value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} />
        )}
        <Select label="Status" options={[{ value: '', label: 'All' }, { value: 'true', label: 'Active' }, { value: 'false', label: 'Inactive' }]} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} />
        <div className="flex items-end"><Button onClick={handleSearch}>Search</Button></div>
      </div>
      <DataTable columns={columns} data={users} keyField="id" caption="User management table" />
      {total > 25 && (
        <div className="flex justify-center gap-2 mt-4">
          <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
          <span className="text-sm text-gray-600 self-center">Page {page} of {Math.ceil(total / 25)}</span>
          <Button size="sm" variant="secondary" disabled={page >= Math.ceil(total / 25)} onClick={() => setPage(p => p + 1)}>Next</Button>
        </div>
      )}

      {/* Edit Profile Modal for Global Admin */}
      {editModalOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8">
          <div className="bg-gray-50 rounded-xl shadow-2xl w-full max-w-2xl mx-4 relative">
            <div className="sticky top-0 bg-white rounded-t-xl border-b border-gray-200 px-6 py-4 flex items-center justify-between z-10">
              <h2 className="text-lg font-semibold text-gray-900">Edit Profile</h2>
              <button
                type="button"
                onClick={() => setEditModalOpen(false)}
                className="rounded-md p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                aria-label="Close"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-6">
              <Profile />
            </div>
          </div>
        </div>
      )}

      {/* Create Global Admin Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 relative">
            <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Create Global Admin</h2>
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                className="rounded-md p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                aria-label="Close"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-6 space-y-4">
              <Input label="Email *" type="email" value={createForm.email} onChange={(e) => setCreateForm(f => ({ ...f, email: e.target.value }))} placeholder="admin@example.com" />
              <div className="grid grid-cols-2 gap-3">
                <Input label="First name" value={createForm.first_name} onChange={(e) => setCreateForm(f => ({ ...f, first_name: e.target.value }))} />
                <Input label="Last name" value={createForm.last_name} onChange={(e) => setCreateForm(f => ({ ...f, last_name: e.target.value }))} />
              </div>
              <Input label="Password *" type="password" value={createForm.password} onChange={(e) => setCreateForm(f => ({ ...f, password: e.target.value }))} placeholder="Min 8 characters" />
              {createError && <p className="text-sm text-red-600">{createError}</p>}
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="secondary" onClick={() => setCreateModalOpen(false)}>Cancel</Button>
                <Button onClick={handleCreateGlobalAdmin} loading={createSaving}>Create</Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm mx-4 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Delete User Permanently</h2>
            <p className="text-sm text-gray-600 mb-1">
              This will permanently delete <span className="font-medium">{deleteConfirm.email}</span> and all associated data including MFA, sessions, and audit records.
            </p>
            <p className="text-sm text-red-600 font-medium mb-4">This action cannot be undone.</p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setDeleteConfirm(null)}>Cancel</Button>
              <Button variant="danger" loading={actionLoading === deleteConfirm.id} onClick={() => handleDeleteUser(deleteConfirm)}>
                Delete Permanently
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
