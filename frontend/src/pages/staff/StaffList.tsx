/**
 * Staff list page — styled to match the rest of the app.
 * Supports search, filters, pagination, add/edit modal.
 */

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button, Modal } from '../../components/ui'
import WorkSchedule, { type WeekSchedule } from '../../components/WorkSchedule'

interface StaffMember {
  id: string
  name: string
  first_name: string
  last_name: string | null
  email: string | null
  phone: string | null
  employee_id: string | null
  position: string | null
  reporting_to: string | null
  reporting_to_name: string | null
  shift_start: string | null
  shift_end: string | null
  role_type: string
  hourly_rate: string | null
  overtime_rate: string | null
  skills: string[]
  availability_schedule: Record<string, { start: string; end: string }>
  is_active: boolean
  created_at: string
}

interface StaffFormData {
  first_name: string
  last_name: string
  email: string
  phone: string
  employee_id: string
  position: string
  reporting_to: string
  role_type: string
  hourly_rate: string
  overtime_rate: string
  skills: string
}

const DEFAULT_SCHEDULE: WeekSchedule = {
  monday: { start: '09:00', end: '17:00' },
  tuesday: { start: '09:00', end: '17:00' },
  wednesday: { start: '09:00', end: '17:00' },
  thursday: { start: '09:00', end: '17:00' },
  friday: { start: '09:00', end: '17:00' },
}

const emptyForm: StaffFormData = {
  first_name: '', last_name: '', email: '', phone: '',
  employee_id: '', position: '', reporting_to: '',
  role_type: 'employee', hourly_rate: '', overtime_rate: '', skills: '',
}

export default function StaffList() {
  const navigate = useNavigate()
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const pageSize = 20

  // Modal state
  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<StaffFormData>({ ...emptyForm })
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  // All staff for "reporting to" dropdown
  const [allStaff, setAllStaff] = useState<StaffMember[]>([])

  // Work schedule for modal
  const [schedule, setSchedule] = useState<WeekSchedule>({ ...DEFAULT_SCHEDULE })

  // "Also create as user" state
  const [createAsUser, setCreateAsUser] = useState(false)
  const [userRole, setUserRole] = useState<'org_admin' | 'salesperson'>('salesperson')

  // Inline duplicate warnings
  const [dupWarnings, setDupWarnings] = useState<Record<string, string | undefined>>({})
  const dupTimers = useState<Record<string, ReturnType<typeof setTimeout>>>({})[0]

  const checkDuplicate = (field: 'email' | 'phone' | 'employee_id', value: string) => {
    if (dupTimers[field]) clearTimeout(dupTimers[field])
    if (!value.trim()) { setDupWarnings((w: Record<string, string | undefined>) => ({ ...w, [field]: undefined })); return }
    dupTimers[field] = setTimeout(async () => {
      try {
        const params: Record<string, string> = { field, value: value.trim() }
        if (editingId) params.exclude_id = editingId
        const res = await apiClient.get('/staff/check-duplicate', { baseURL: '/api/v2', params })
        const data = res.data as any
        setDupWarnings((w: Record<string, string | undefined>) => ({ ...w, [field]: data.duplicate ? data.message : undefined }))
      } catch { /* non-blocking */ }
    }, 400)
  }
  const fetchStaff = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), page_size: String(pageSize) }
      if (roleFilter) params.role_type = roleFilter
      if (activeFilter) params.is_active = activeFilter
      const res = await apiClient.get('/staff', { baseURL: '/api/v2', params })
      const data = res.data as any
      setStaff(data?.staff ?? [])
      setTotal(data?.total ?? 0)
    } catch {
      setStaff([])
    } finally {
      setLoading(false)
    }
  }, [page, roleFilter, activeFilter])

  useEffect(() => { fetchStaff() }, [fetchStaff])

  // Load all staff for reporting_to dropdown
  useEffect(() => {
    async function loadAll() {
      try {
        const res = await apiClient.get('/staff', { baseURL: '/api/v2', params: { page_size: '200' } })
        setAllStaff((res.data as any)?.staff ?? [])
      } catch { /* non-blocking */ }
    }
    loadAll()
  }, [])

  const totalPages = Math.ceil(total / pageSize)

  const openAdd = () => {
    setEditingId(null)
    setForm({ ...emptyForm })
    setSchedule({ ...DEFAULT_SCHEDULE })
    setFormError('')
    setDupWarnings({})
    setCreateAsUser(false)
    setUserRole('salesperson')
    setShowModal(true)
  }

  const openEdit = (member: StaffMember) => {
    setEditingId(member.id)
    setForm({
      first_name: member.first_name || '',
      last_name: member.last_name || '',
      email: member.email || '',
      phone: member.phone || '',
      employee_id: member.employee_id || '',
      position: member.position || '',
      reporting_to: member.reporting_to || '',
      role_type: member.role_type || 'employee',
      hourly_rate: member.hourly_rate || '',
      overtime_rate: member.overtime_rate || '',
      skills: (member.skills || []).join(', '),
    })
    setSchedule(member.availability_schedule && Object.keys(member.availability_schedule).length > 0
      ? { ...member.availability_schedule }
      : { ...DEFAULT_SCHEDULE })
    setFormError('')
    setDupWarnings({})
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.first_name.trim()) { setFormError('First name is required'); return }
    setSaving(true)
    setFormError('')
    try {
      const payload: any = {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        employee_id: form.employee_id.trim() || null,
        position: form.position.trim() || null,
        reporting_to: form.reporting_to || null,
        availability_schedule: schedule,
        role_type: form.role_type,
        hourly_rate: form.hourly_rate ? parseFloat(form.hourly_rate) : null,
        overtime_rate: form.overtime_rate ? parseFloat(form.overtime_rate) : null,
        skills: form.skills ? form.skills.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
      }
      if (editingId) {
        await apiClient.put(`/staff/${editingId}`, payload, { baseURL: '/api/v2' })
      } else {
        await apiClient.post('/staff', payload, { baseURL: '/api/v2' })
        // If "Also create as user" is checked, send invite via existing user invite flow
        if (createAsUser && form.email.trim()) {
          try {
            await apiClient.post('/org/users/invite', { email: form.email.trim(), role: userRole })
          } catch (inviteErr: any) {
            const detail = inviteErr?.response?.data?.detail || ''
            // Don't fail the whole operation if invite fails — staff was already created
            if (detail.includes('already exists')) {
              setFormError('Staff created, but user invite skipped — email already has an account.')
            } else {
              setFormError('Staff created, but failed to send user invite. You can invite them from Settings > Users.')
            }
            setSaving(false)
            fetchStaff()
            return
          }
        }
      }
      setShowModal(false)
      fetchStaff()
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleDeactivate = async (id: string) => {
    if (!confirm('Deactivate this staff member?')) return
    try {
      await apiClient.delete(`/staff/${id}`, { baseURL: '/api/v2' })
      fetchStaff()
    } catch { /* non-blocking */ }
  }

  // Delete confirmation modal state
  const [deleteTarget, setDeleteTarget] = useState<StaffMember | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteAlsoUser, setDeleteAlsoUser] = useState(true)

  const handleDeleteStaff = async () => {
    if (!deleteTarget) return
    const member = deleteTarget
    setDeleting(true)
    try {
      await apiClient.delete(`/staff/${member.id}/permanent`, { baseURL: '/api/v2' })
      if (deleteAlsoUser && member.email) {
        try {
          const usersRes = await apiClient.get('/org/users')
          const users = (usersRes.data as any)?.users || usersRes.data || []
          const matchedUser = Array.isArray(users) ? users.find((u: any) => u.email === member.email) : null
          if (matchedUser) {
            await apiClient.delete(`/org/users/${matchedUser.id}/permanent`)
          }
        } catch { /* user delete is best-effort */ }
      }
      setDeleteTarget(null)
      fetchStaff()
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || 'Failed to delete staff member')
    } finally {
      setDeleting(false)
    }
  }

  const handleActivate = async (id: string) => {
    try {
      await apiClient.post(`/staff/${id}/activate`, {}, { baseURL: '/api/v2' })
      fetchStaff()
    } catch { /* non-blocking */ }
  }

  return (
    <div className="h-full">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">Staff</h1>
          <Button onClick={openAdd}>+ Add Staff</Button>
        </div>
      </div>

      <div className="px-6 py-4 space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <input type="text" placeholder="Search by name or email…" value={search}
            onChange={(e) => { setSearch(e.target.value) }}
            className="w-64 rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Roles</option>
            <option value="employee">Employee</option>
            <option value="contractor">Contractor</option>
          </select>
          <select value={activeFilter} onChange={(e) => { setActiveFilter(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Status</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </div>

        {/* Table */}
        {loading ? (
          <div className="py-16 text-center text-gray-500">Loading staff…</div>
        ) : staff.length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-gray-500">No staff members found.</p>
            <p className="text-sm text-gray-400 mt-1">Add your first staff member to get started.</p>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <th className="py-3 px-4">Employee ID</th>
                    <th className="py-3 px-4">Name</th>
                    <th className="py-3 px-4">Position</th>
                    <th className="py-3 px-4">Email</th>
                    <th className="py-3 px-4">Phone</th>
                    <th className="py-3 px-4">Work Days</th>
                    <th className="py-3 px-4">Reports To</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {staff.filter(m => {
                    if (!search) return true
                    const q = search.toLowerCase()
                    const fullName = `${m.first_name} ${m.last_name || ''}`.toLowerCase()
                    return fullName.includes(q) || (m.email || '').toLowerCase().includes(q) || (m.employee_id || '').toLowerCase().includes(q)
                  }).map((member) => (
                    <tr key={member.id} className="hover:bg-gray-50">
                      <td className="py-3 px-4 text-gray-500">{member.employee_id || '—'}</td>
                      <td className="py-3 px-4">
                        <button onClick={() => navigate(`/staff/${member.id}`)}
                          className="font-medium text-blue-600 hover:text-blue-800">
                          {member.first_name} {member.last_name || ''}
                        </button>
                      </td>
                      <td className="py-3 px-4 text-gray-700">{member.position || '—'}</td>
                      <td className="py-3 px-4 text-gray-600">{member.email || '—'}</td>
                      <td className="py-3 px-4 text-gray-600">{member.phone || '—'}</td>
                      <td className="py-3 px-4 text-gray-600">
                        {member.availability_schedule && Object.keys(member.availability_schedule).length > 0
                          ? ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
                              .filter(d => member.availability_schedule[d])
                              .map(d => d.slice(0, 3).charAt(0).toUpperCase() + d.slice(1, 3))
                              .join(', ')
                          : (member.shift_start && member.shift_end ? `${member.shift_start} - ${member.shift_end}` : '-')}
                      </td>
                      <td className="py-3 px-4 text-gray-600">{member.reporting_to_name || '—'}</td>
                      <td className="py-3 px-4">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${member.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
                          {member.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <button onClick={() => openEdit(member)}
                            className="text-sm text-blue-600 hover:text-blue-800">Edit</button>
                          {member.is_active ? (
                            <button onClick={() => handleDeactivate(member.id)}
                              className="text-sm text-red-600 hover:text-red-800">Deactivate</button>
                          ) : (
                            <button onClick={() => handleActivate(member.id)}
                              className="text-sm text-emerald-600 hover:text-emerald-800">Activate</button>
                          )}
                          <button onClick={() => { setDeleteTarget(member); setDeleteAlsoUser(!!member.email) }}
                            className="text-sm text-red-600 hover:text-red-800">Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 bg-gray-50">
                <span className="text-sm text-gray-600">
                  Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
                </span>
                <div className="flex items-center gap-2">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50 hover:bg-gray-100">
                    Previous
                  </button>
                  <span className="text-sm text-gray-600">Page {page} of {totalPages}</span>
                  <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50 hover:bg-gray-100">
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Add/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">
                {editingId ? 'Edit Staff Member' : 'Add Staff Member'}
              </h2>
              <button onClick={() => setShowModal(false)} className="text-gray-400 hover:text-gray-600" aria-label="Close">✕</button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">First Name *</label>
                  <input type="text" value={form.first_name} onChange={(e) => setForm(f => ({ ...f, first_name: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
                  <input type="text" value={form.last_name} onChange={(e) => setForm(f => ({ ...f, last_name: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                  <input type="email" value={form.email} onChange={(e) => { setForm(f => ({ ...f, email: e.target.value })); checkDuplicate('email', e.target.value) }}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  {dupWarnings.email && <p className="text-xs text-red-500 mt-0.5">{dupWarnings.email}</p>}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
                  <input type="tel" value={form.phone} onChange={(e) => { setForm(f => ({ ...f, phone: e.target.value })); checkDuplicate('phone', e.target.value) }}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  {dupWarnings.phone && <p className="text-xs text-red-500 mt-0.5">{dupWarnings.phone}</p>}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Employee ID</label>
                  <input type="text" value={form.employee_id} onChange={(e) => { setForm(f => ({ ...f, employee_id: e.target.value })); checkDuplicate('employee_id', e.target.value) }}
                    placeholder="e.g. EMP-001"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  {dupWarnings.employee_id && <p className="text-xs text-red-500 mt-0.5">{dupWarnings.employee_id}</p>}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Position</label>
                  <input type="text" value={form.position} onChange={(e) => setForm(f => ({ ...f, position: e.target.value }))}
                    placeholder="e.g. Senior Mechanic"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Role Type</label>
                  <select value={form.role_type} onChange={(e) => setForm(f => ({ ...f, role_type: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="employee">Employee</option>
                    <option value="contractor">Contractor</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Hourly Rate ($)</label>
                  <input type="number" step="0.01" min="0" value={form.hourly_rate}
                    onChange={(e) => setForm(f => ({ ...f, hourly_rate: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Overtime Rate ($)</label>
                  <input type="number" step="0.01" min="0" value={form.overtime_rate}
                    onChange={(e) => setForm(f => ({ ...f, overtime_rate: e.target.value }))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Skills (comma-separated)</label>
                  <input type="text" value={form.skills}
                    onChange={(e) => setForm(f => ({ ...f, skills: e.target.value }))}
                    placeholder="e.g. Brakes, Engine, Electrical"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Reports To</label>
                <select value={form.reporting_to} onChange={(e) => setForm(f => ({ ...f, reporting_to: e.target.value }))}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">— None —</option>
                  {allStaff.filter(s => s.id !== editingId && s.is_active).map(s => (
                    <option key={s.id} value={s.id}>{s.first_name} {s.last_name || ''} {s.position ? `(${s.position})` : ''}</option>
                  ))}
                </select>
              </div>

              {/* Also create as user — only for new staff */}
              {!editingId && (
                <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createAsUser}
                      onChange={(e) => setCreateAsUser(e.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    Also create as a user (sends invite email)
                  </label>
                  {createAsUser && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">User Role</label>
                      <select
                        value={userRole}
                        onChange={(e) => setUserRole(e.target.value as 'org_admin' | 'salesperson')}
                        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="salesperson">Salesperson</option>
                        <option value="org_admin">Org Admin</option>
                      </select>
                      {!form.email.trim() && (
                        <p className="mt-1 text-xs text-amber-600">Email is required to send an invite</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              <WorkSchedule schedule={schedule} onChange={setSchedule} />
              {formError && <p className="text-sm text-red-600">{formError}</p>}
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4 bg-gray-50 rounded-b-lg">
              <Button variant="secondary" onClick={() => setShowModal(false)}>Cancel</Button>
              <Button onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Add Staff'}</Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <Modal open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Staff Member">
        {deleteTarget && (
          <div className="space-y-4">
            <div className="rounded-md border border-red-200 bg-red-50 p-4">
              <p className="text-sm text-red-800">
                This will permanently delete <span className="font-semibold">{deleteTarget.first_name} {deleteTarget.last_name || ''}</span>.
                This action cannot be undone.
              </p>
              <p className="mt-2 text-sm text-red-700">
                Any invoices, quotes, or other data they created will be preserved and remain accessible.
              </p>
            </div>

            {deleteTarget.email && (
              <label className="flex items-start gap-3 rounded-md border border-gray-200 bg-gray-50 p-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deleteAlsoUser}
                  onChange={(e) => setDeleteAlsoUser(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-500"
                />
                <div>
                  <p className="text-sm font-medium text-gray-900">Also delete user account</p>
                  <p className="text-xs text-gray-500">
                    Remove the login account for {deleteTarget.email}. They will no longer be able to sign in.
                  </p>
                </div>
              </label>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)}>Cancel</Button>
              <Button variant="danger" size="sm" onClick={handleDeleteStaff} loading={deleting}>
                Delete permanently
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
