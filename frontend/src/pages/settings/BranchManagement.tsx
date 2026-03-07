import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* ── Types ── */

interface Branch {
  id: string
  name: string
  address: string | null
  phone: string | null
  is_active: boolean
  assigned_users: string[]
  [key: string]: unknown
}

interface BranchForm {
  name: string
  address: string
  phone: string
}

interface OrgUser {
  id: string
  email: string
  role: string
  branch_ids: string[]
}

const emptyForm: BranchForm = { name: '', address: '', phone: '' }

export function BranchManagement() {
  const [branches, setBranches] = useState<Branch[]>([])
  const [users, setUsers] = useState<OrgUser[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [assignModalOpen, setAssignModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [assignBranchId, setAssignBranchId] = useState<string | null>(null)
  const [form, setForm] = useState<BranchForm>(emptyForm)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [branchRes, userRes] = await Promise.all([
        apiClient.get<Branch[]>('/org/branches'),
        apiClient.get<OrgUser[]>('/org/users'),
      ])
      setBranches(branchRes.data)
      setUsers(userRes.data)
    } catch {
      addToast('error', 'Failed to load branches')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const openAdd = () => { setEditingId(null); setForm(emptyForm); setModalOpen(true) }

  const openEdit = (branch: Branch) => {
    setEditingId(branch.id)
    setForm({ name: branch.name, address: branch.address || '', phone: branch.phone || '' })
    setModalOpen(true)
  }

  const openAssign = (branchId: string) => { setAssignBranchId(branchId); setAssignModalOpen(true) }

  const saveBranch = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await apiClient.put(`/org/branches/${editingId}`, form)
      } else {
        await apiClient.post('/org/branches', form)
      }
      setModalOpen(false)
      addToast('success', editingId ? 'Branch updated' : 'Branch created')
      fetchData()
    } catch {
      addToast('error', 'Failed to save branch')
    } finally {
      setSaving(false)
    }
  }

  const toggleUserBranch = async (userId: string, branchId: string, assigned: boolean) => {
    try {
      const user = users.find((u) => u.id === userId)
      if (!user) return
      const newBranchIds = assigned
        ? user.branch_ids.filter((id) => id !== branchId)
        : [...user.branch_ids, branchId]
      await apiClient.put(`/org/users/${userId}`, { branch_ids: newBranchIds })
      fetchData()
    } catch {
      addToast('error', 'Failed to update user assignment')
    }
  }

  const columns: Column<Branch>[] = [
    { key: 'name', header: 'Branch Name', sortable: true },
    { key: 'address', header: 'Address', render: (row) => row.address || '—' },
    { key: 'phone', header: 'Phone', render: (row) => row.phone || '—' },
    {
      key: 'is_active', header: 'Status',
      render: (row) => <Badge variant={row.is_active ? 'success' : 'neutral'}>{row.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    {
      key: 'actions', header: 'Actions',
      render: (row) => (
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => openEdit(row)}>Edit</Button>
          <Button size="sm" variant="secondary" onClick={() => openAssign(row.id)}>Assign Users</Button>
        </div>
      ),
    },
  ]

  const assignedBranch = branches.find((b) => b.id === assignBranchId)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Branch Management</h1>
        <Button onClick={openAdd}>Add Branch</Button>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {loading ? (
        <p className="text-gray-500">Loading branches…</p>
      ) : (
        <DataTable columns={columns} data={branches} keyField="id" caption="Organisation branches" />
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Branch' : 'Add Branch'}>
        <div className="space-y-4">
          <Input label="Branch Name" value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} required />
          <Input label="Address" value={form.address} onChange={(e) => setForm((p) => ({ ...p, address: e.target.value }))} />
          <Input label="Phone" value={form.phone} onChange={(e) => setForm((p) => ({ ...p, phone: e.target.value }))} type="tel" />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={saveBranch} loading={saving}>{editingId ? 'Update' : 'Create'}</Button>
          </div>
        </div>
      </Modal>

      <Modal open={assignModalOpen} onClose={() => setAssignModalOpen(false)} title={`Assign Users — ${assignedBranch?.name || ''}`}>
        <div className="space-y-3">
          {users.length === 0 ? (
            <p className="text-sm text-gray-500">No users in this organisation.</p>
          ) : (
            users.map((user) => {
              const isAssigned = assignBranchId ? user.branch_ids.includes(assignBranchId) : false
              return (
                <label key={user.id} className="flex items-center gap-3 p-2 rounded hover:bg-gray-50 cursor-pointer">
                  <input type="checkbox" checked={isAssigned}
                    onChange={() => assignBranchId && toggleUserBranch(user.id, assignBranchId, isAssigned)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                  <span className="text-sm text-gray-900">{user.email}</span>
                  <Badge variant="info">{user.role}</Badge>
                </label>
              )
            })
          )}
          <div className="flex justify-end pt-2">
            <Button variant="secondary" onClick={() => setAssignModalOpen(false)}>Done</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
