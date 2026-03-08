import { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

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

export function UserManagement() {
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchUsers = async () => {
    setLoading(true)
    setError(false)
    try {
      const params: Record<string, string> = { page: String(page), page_size: '25' }
      if (search.trim()) params.search = search.trim()
      if (roleFilter) params.role = roleFilter
      if (statusFilter) params.is_active = statusFilter
      const res = await apiClient.get('/admin/users', { params })
      setUsers(res.data.users ?? [])
      setTotal(res.data.total ?? 0)
    } catch {
      setError(true)
      addToast('error', 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchUsers() }, [page])

  const handleSearch = () => { setPage(1); fetchUsers() }

  const handleToggleActive = async (user: UserRow) => {
    try {
      await apiClient.put(`/admin/users/${user.id}/status`)
      addToast('success', `User ${user.is_active ? 'deactivated' : 'activated'}`)
      fetchUsers()
    } catch {
      addToast('error', 'Failed to update user status')
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
    {
      key: 'org_name',
      header: 'Organisation',
      render: (row) => row.org_name ?? <span className="text-gray-400">Platform</span>,
    },
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
        row.role !== 'global_admin' ? (
          <Button size="sm" variant={row.is_active ? 'danger' : 'secondary'} onClick={() => handleToggleActive(row)}>
            {row.is_active ? 'Deactivate' : 'Activate'}
          </Button>
        ) : null
      ),
    },
  ]

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
        <span className="text-sm text-gray-500">{total} users total</span>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <Input label="Search by email" placeholder="Search..." value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className="sm:w-72" />
        <Select label="Role" options={[{ value: '', label: 'All roles' }, ...Object.entries(ROLE_LABELS).map(([v, l]) => ({ value: v, label: l }))]} value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} />
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
    </div>
  )
}
