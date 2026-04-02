import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'

/* -- Types -- */

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

export interface StaffMemberFromAPI {
  id: string
  org_id: string
  user_id: string | null
  name: string
  first_name: string
  last_name: string | null
  email: string | null
  phone: string | null
  position: string | null
  role_type: string
  is_active: boolean
  location_assignments: Array<{
    id: string
    staff_id: string
    location_id: string
    assigned_at: string
  }>
}

export interface StaffAssignmentSelection {
  staffId: string
  userId: string | null
  email: string | null
  name: string
  selected: boolean
  canInvite: boolean
}

export type ModalStep = 'details' | 'staff'

const emptyForm: BranchForm = { name: '', address: '', phone: '' }

/* -- Pure helper functions (exported for property testing) -- */

export function canProceedToStaff(name: string): boolean {
  return name.trim().length > 0
}

export function getStaffBadgeInfo(userId: string | null): { text: string; variant: 'info' | 'neutral' } {
  return userId !== null
    ? { text: 'Has account', variant: 'info' }
    : { text: 'No account', variant: 'neutral' }
}

export function canInviteStaff(userId: string | null, email: string | null): boolean {
  if (userId !== null) return true
  return email !== null && email.trim().length > 0
}

export function getCheckboxLabel(userId: string | null): string {
  return userId !== null ? 'Grant branch access' : 'Invite to manage this branch'
}
/* -- Hook: fetch active staff for branch assignment -- */

function useStaffForBranch() {
  const [staff, setStaff] = useState<StaffMemberFromAPI[]>([])
  const [staffLoading, setStaffLoading] = useState(false)
  const [staffError, setStaffError] = useState<string | null>(null)

  const fetchStaff = useCallback((signal?: AbortSignal) => {
    setStaffLoading(true)
    setStaffError(null)
    apiClient
      .get<{ staff: StaffMemberFromAPI[] }>('/api/v2/staff', {
        params: { is_active: true },
        signal,
      })
      .then((res) => {
        setStaff(res.data?.staff ?? [])
      })
      .catch(() => {
        if (signal?.aborted) return
        setStaffError('Failed to load staff')
        setStaff([])
      })
      .finally(() => {
        if (!signal?.aborted) setStaffLoading(false)
      })
  }, [])

  const retry = useCallback(() => {
    fetchStaff()
  }, [fetchStaff])

  return { staff, staffLoading, staffError, retry, fetchStaff }
}

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
  const [modalStep, setModalStep] = useState<ModalStep>('details')
  const { toasts, addToast, dismissToast } = useToast()
  const { staff, staffLoading, staffError, retry: retryStaff, fetchStaff } = useStaffForBranch()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [branchRes, userRes] = await Promise.all([
        apiClient.get('/org/branches'),
        apiClient.get('/org/users'),
      ])
      const branchData = Array.isArray(branchRes.data) ? branchRes.data : (branchRes.data?.branches || [])
      const userData = Array.isArray(userRes.data) ? userRes.data : (userRes.data?.users || [])
      setBranches(branchData)
      setUsers(userData)
    } catch {
      addToast('error', 'Failed to load branches')
      setBranches([])
      setUsers([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const closeModal = () => {
    setModalOpen(false)
    setModalStep('details')
  }

  const openAdd = () => {
    setEditingId(null)
    setForm(emptyForm)
    setModalStep('details')
    setModalOpen(true)
  }

  const openEdit = (branch: Branch) => {
    setEditingId(branch.id)
    setForm({ name: branch.name, address: branch.address || '', phone: branch.phone || '' })
    setModalOpen(true)
  }

  const openAssign = (branchId: string) => {
    setAssignBranchId(branchId)
    setAssignModalOpen(true)
  }

  const handleNextStep = () => {
    if (!canProceedToStaff(form.name)) return
    setModalStep('staff')
    fetchStaff()
  }

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
      setModalStep('details')
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
    { key: 'address', header: 'Address', render: (row) => row.address || '\u2014' },
    { key: 'phone', header: 'Phone', render: (row) => row.phone || '\u2014' },
    {
      key: 'is_active', header: 'Status',
      render: (row) => (
        <Badge variant={row.is_active ? 'success' : 'neutral'}>
          {row.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
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

  const assignedBranch = assignBranchId ? branches.find((b) => b.id === assignBranchId) : null
  const isAddMode = editingId === null

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Branch Management</h1>
        <Button onClick={openAdd}>Add Branch</Button>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {loading ? (
        <p className="text-gray-500">Loading branches&hellip;</p>
      ) : (
        <DataTable columns={columns} data={branches} keyField="id" caption="Organisation branches" />
      )}

      {/* Add / Edit Branch Modal */}
      <Modal
        open={modalOpen}
        onClose={closeModal}
        title={isAddMode ? (modalStep === 'details' ? 'Add Branch \u2014 Details' : 'Add Branch \u2014 Staff Assignment') : 'Edit Branch'}
        className={modalStep === 'staff' && isAddMode ? 'max-w-2xl' : 'max-w-lg'}
      >
        {/* Step 1: Branch details */}
        {(modalStep === 'details' || !isAddMode) && (
          <div className="space-y-4">
            <Input
              label="Branch Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Main Street Workshop"
              required
            />
            <Input
              label="Address"
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              placeholder="123 Main St"
            />
            <Input
              label="Phone"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="+61 400 000 000"
            />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={closeModal}>Cancel</Button>
              {isAddMode && (
                <>
                  <Button variant="secondary" onClick={saveBranch} disabled={!form.name.trim() || saving} loading={saving}>
                    Create
                  </Button>
                  <Button onClick={handleNextStep} disabled={!canProceedToStaff(form.name)}>
                    Next
                  </Button>
                </>
              )}
              {!isAddMode && (
                <Button onClick={saveBranch} disabled={!form.name.trim() || saving} loading={saving}>
                  Save
                </Button>
              )}
            </div>
          </div>
        )}
        {/* Step 2: Staff assignment (only in add mode) */}
        {modalStep === 'staff' && isAddMode && (
          <div className="space-y-4">
            {staffLoading && (
              <p className="text-gray-500 text-sm">Loading staff&hellip;</p>
            )}

            {staffError && !staffLoading && (
              <div className="rounded-md bg-red-50 border border-red-200 p-4">
                <p className="text-sm text-red-700 mb-3">{staffError}</p>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={retryStaff}>Retry</Button>
                  <Button size="sm" variant="secondary" onClick={saveBranch} disabled={saving} loading={saving}>Skip</Button>
                </div>
              </div>
            )}

            {!staffLoading && !staffError && staff.length === 0 && (
              <p className="text-gray-500 text-sm">No staff members found</p>
            )}

            {!staffLoading && !staffError && staff.length > 0 && (
              <ul className="divide-y divide-gray-100" role="list" aria-label="Staff members">
                {staff.map((member) => {
                  const badge = getStaffBadgeInfo(member.user_id)
                  const invitable = canInviteStaff(member.user_id, member.email)
                  const label = getCheckboxLabel(member.user_id)
                  return (
                    <li key={member.id} className="flex items-center justify-between py-3 gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900 text-sm truncate">{member.name}</span>
                          <Badge variant={badge.variant}>{badge.text}</Badge>
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          {member.position ?? 'No position'} &middot; {member.email ?? 'No email'}
                        </div>
                      </div>
                      <div className="flex-shrink-0">
                        {invitable ? (
                          <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                            <input type="checkbox" className="rounded border-gray-300" />
                            <span>{label}</span>
                          </label>
                        ) : (
                          <div className="relative group">
                            <label className="flex items-center gap-2 text-sm text-gray-400 cursor-not-allowed">
                              <input type="checkbox" disabled className="rounded border-gray-200 opacity-50" />
                              <span>{label}</span>
                            </label>
                            <div className="absolute bottom-full right-0 mb-1 hidden group-hover:block bg-gray-800 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10">
                              Email address required to create account
                            </div>
                          </div>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}

            <div className="flex justify-between pt-2 border-t border-gray-100">
              <Button variant="secondary" onClick={() => setModalStep('details')}>Back</Button>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={saveBranch} disabled={saving} loading={saving}>Skip</Button>
                <Button onClick={saveBranch} disabled={saving} loading={saving}>Create</Button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Assign Users Modal */}
      <Modal open={assignModalOpen} onClose={() => setAssignModalOpen(false)} title={`Assign Users \u2014 ${assignedBranch?.name ?? ''}`}>
        {assignedBranch && (
          <div className="space-y-2">
            {users.length === 0 && <p className="text-gray-500 text-sm">No users found</p>}
            {users.map((user) => {
              const assigned = (user.branch_ids ?? []).includes(assignedBranch.id)
              return (
                <label key={user.id} className="flex items-center gap-2 py-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={assigned}
                    onChange={() => toggleUserBranch(user.id, assignedBranch.id, assigned)}
                    className="rounded border-gray-300"
                  />
                  <span className="text-sm text-gray-700">{user.email}</span>
                  <Badge variant="neutral">{user.role}</Badge>
                </label>
              )
            })}
            <div className="flex justify-end pt-2">
              <Button variant="secondary" onClick={() => setAssignModalOpen(false)}>Close</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}