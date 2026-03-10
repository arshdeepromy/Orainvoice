/**
 * Staff detail page — view/edit a single staff member.
 * Uses the new schema: first_name, last_name, employee_id, position,
 * reporting_to, shift_start, shift_end, overtime_rate, skills.
 */

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '../../api/client'
import { Button } from '../../components/ui'
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
  user_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

interface AllStaffItem {
  id: string
  first_name: string
  last_name: string | null
  position: string | null
  is_active: boolean
}

interface Props {
  staffId: string
}

export default function StaffDetail({ staffId }: Props) {
  const navigate = useNavigate()
  const [staff, setStaff] = useState<StaffMember | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [allStaff, setAllStaff] = useState<AllStaffItem[]>([])

  // Form fields
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [position, setPosition] = useState('')
  const [reportingTo, setReportingTo] = useState('')
  const [roleType, setRoleType] = useState('employee')
  const [hourlyRate, setHourlyRate] = useState('')
  const [overtimeRate, setOvertimeRate] = useState('')
  const [skills, setSkills] = useState('')
  const [schedule, setSchedule] = useState<WeekSchedule>({})

  // Create account modal
  const [showAccountModal, setShowAccountModal] = useState(false)
  const [accountPassword, setAccountPassword] = useState('')
  const [creatingAccount, setCreatingAccount] = useState(false)
  const [accountError, setAccountError] = useState('')

  const populateForm = (data: StaffMember) => {
    setFirstName(data.first_name || '')
    setLastName(data.last_name || '')
    setEmail(data.email || '')
    setPhone(data.phone || '')
    setEmployeeId(data.employee_id || '')
    setPosition(data.position || '')
    setReportingTo(data.reporting_to || '')
    setRoleType(data.role_type || 'employee')
    setHourlyRate(data.hourly_rate || '')
    setOvertimeRate(data.overtime_rate || '')
    setSkills((data.skills || []).join(', '))
    setSchedule(data.availability_schedule && Object.keys(data.availability_schedule).length > 0
      ? { ...data.availability_schedule }
      : {})
  }

  const fetchStaff = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(`/staff/${staffId}`, { baseURL: '/api/v2' })
      const data: StaffMember = res.data
      setStaff(data)
      populateForm(data)
    } catch {
      setStaff(null)
    } finally {
      setLoading(false)
    }
  }, [staffId])

  useEffect(() => { fetchStaff() }, [fetchStaff])

  // Load all staff for "Reports To" dropdown
  useEffect(() => {
    async function loadAll() {
      try {
        const res = await apiClient.get('/staff', { baseURL: '/api/v2', params: { page_size: '200' } })
        setAllStaff((res.data as any)?.staff ?? [])
      } catch { /* non-blocking */ }
    }
    loadAll()
  }, [])

  const handleSave = async () => {
    if (!firstName.trim()) { setFormError('First name is required'); return }
    setSaving(true)
    setFormError('')
    try {
      const payload: any = {
        first_name: firstName.trim(),
        last_name: lastName.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        employee_id: employeeId.trim() || null,
        position: position.trim() || null,
        reporting_to: reportingTo || null,
        role_type: roleType,
        hourly_rate: hourlyRate ? parseFloat(hourlyRate) : null,
        overtime_rate: overtimeRate ? parseFloat(overtimeRate) : null,
        skills: skills ? skills.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
        availability_schedule: schedule,
      }
      await apiClient.put(`/staff/${staffId}`, payload, { baseURL: '/api/v2' })
      setEditing(false)
      fetchStaff()
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleDeactivate = async () => {
    if (!confirm('Deactivate this staff member?')) return
    try {
      await apiClient.delete(`/staff/${staffId}`, { baseURL: '/api/v2' })
      fetchStaff()
    } catch { /* non-blocking */ }
  }

  const handleActivate = async () => {
    try {
      await apiClient.post(`/staff/${staffId}/activate`, {}, { baseURL: '/api/v2' })
      fetchStaff()
    } catch { /* non-blocking */ }
  }

  const handleCreateAccount = async () => {
    if (accountPassword.length < 8) { setAccountError('Password must be at least 8 characters'); return }
    setCreatingAccount(true)
    setAccountError('')
    try {
      await apiClient.post(`/staff/${staffId}/create-account`, { password: accountPassword }, { baseURL: '/api/v2' })
      setShowAccountModal(false)
      setAccountPassword('')
      fetchStaff()
    } catch (err: any) {
      setAccountError(err?.response?.data?.detail || 'Failed to create account')
    } finally {
      setCreatingAccount(false)
    }
  }

  const cancelEdit = () => {
    if (staff) populateForm(staff)
    setEditing(false)
    setFormError('')
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-gray-500">Loading staff member...</p>
      </div>
    )
  }

  if (!staff) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-500">Staff member not found.</p>
          <button onClick={() => navigate('/staff')} className="mt-2 text-sm text-blue-600 hover:text-blue-800">
            Back to Staff List
          </button>
        </div>
      </div>
    )
  }

  const fullName = `${staff.first_name} ${staff.last_name || ''}`.trim()
  const inputCls = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
  const readonlyCls = 'w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700'
  const labelCls = 'block text-sm font-medium text-gray-700 mb-1'

  return (
    <div className="h-full">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/staff')} className="text-gray-400 hover:text-gray-600">
              &larr; Back
            </button>
            <h1 className="text-xl font-semibold text-gray-900">{fullName}</h1>
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${staff.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
              {staff.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {!editing && (
              <>
                <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>
                {!staff.user_id && staff.email && staff.is_active && (
                  <button onClick={() => { setShowAccountModal(true); setAccountPassword(''); setAccountError('') }}
                    className="rounded-md border border-indigo-300 px-4 py-2 text-sm text-indigo-600 hover:bg-indigo-50">
                    Create User Account
                  </button>
                )}
                {staff.user_id && (
                  <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700">
                    Has Login
                  </span>
                )}
                {staff.is_active ? (
                  <button onClick={handleDeactivate} className="rounded-md border border-red-300 px-4 py-2 text-sm text-red-600 hover:bg-red-50">
                    Deactivate
                  </button>
                ) : (
                  <button onClick={handleActivate} className="rounded-md border border-emerald-300 px-4 py-2 text-sm text-emerald-600 hover:bg-emerald-50">
                    Activate
                  </button>
                )}
              </>
            )}
            {editing && (
              <>
                <Button variant="secondary" onClick={cancelEdit}>Cancel</Button>
                <Button onClick={handleSave} loading={saving}>Save Changes</Button>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="px-6 py-6 max-w-3xl">
        {formError && (
          <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-3">
            <p className="text-sm text-red-700">{formError}</p>
          </div>
        )}

        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          {/* Personal Info */}
          <div className="px-6 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wider">Personal Information</h2>
          </div>
          <div className="px-6 py-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>First Name {editing && '*'}</label>
                {editing ? (
                  <input type="text" value={firstName} onChange={e => setFirstName(e.target.value)} className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.first_name || '-'}</div>
                )}
              </div>
              <div>
                <label className={labelCls}>Last Name</label>
                {editing ? (
                  <input type="text" value={lastName} onChange={e => setLastName(e.target.value)} className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.last_name || '-'}</div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Email</label>
                {editing ? (
                  <input type="email" value={email} onChange={e => setEmail(e.target.value)} className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.email || '-'}</div>
                )}
              </div>
              <div>
                <label className={labelCls}>Phone</label>
                {editing ? (
                  <input type="tel" value={phone} onChange={e => setPhone(e.target.value)} className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.phone || '-'}</div>
                )}
              </div>
            </div>
          </div>

          {/* Employment Info */}
          <div className="px-6 py-4 border-b border-t border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wider">Employment Details</h2>
          </div>
          <div className="px-6 py-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Employee ID</label>
                {editing ? (
                  <input type="text" value={employeeId} onChange={e => setEmployeeId(e.target.value)} placeholder="e.g. EMP-001" className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.employee_id || '-'}</div>
                )}
              </div>
              <div>
                <label className={labelCls}>Position</label>
                {editing ? (
                  <input type="text" value={position} onChange={e => setPosition(e.target.value)} placeholder="e.g. Senior Mechanic" className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.position || '-'}</div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Role Type</label>
                {editing ? (
                  <select value={roleType} onChange={e => setRoleType(e.target.value)} className={inputCls}>
                    <option value="employee">Employee</option>
                    <option value="contractor">Contractor</option>
                  </select>
                ) : (
                  <div className={readonlyCls}>{staff.role_type === 'contractor' ? 'Contractor' : 'Employee'}</div>
                )}
              </div>
              <div>
                <label className={labelCls}>Hourly Rate ($)</label>
                {editing ? (
                  <input type="number" step="0.01" min="0" value={hourlyRate} onChange={e => setHourlyRate(e.target.value)} className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.hourly_rate ? `$${parseFloat(staff.hourly_rate).toFixed(2)}` : '-'}</div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Overtime Rate ($)</label>
                {editing ? (
                  <input type="number" step="0.01" min="0" value={overtimeRate} onChange={e => setOvertimeRate(e.target.value)} className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.overtime_rate ? `$${parseFloat(staff.overtime_rate).toFixed(2)}` : '-'}</div>
                )}
              </div>
              <div>
                <label className={labelCls}>Skills (comma-separated)</label>
                {editing ? (
                  <input type="text" value={skills} onChange={e => setSkills(e.target.value)} placeholder="e.g. Brakes, Engine, Electrical" className={inputCls} />
                ) : (
                  <div className={readonlyCls}>{staff.skills && staff.skills.length > 0 ? staff.skills.join(', ') : '-'}</div>
                )}
              </div>
            </div>
            <div>
              <label className={labelCls}>Reports To</label>
              {editing ? (
                <select value={reportingTo} onChange={e => setReportingTo(e.target.value)} className={inputCls}>
                  <option value="">-- None --</option>
                  {allStaff.filter(s => s.id !== staffId && s.is_active).map(s => (
                    <option key={s.id} value={s.id}>
                      {s.first_name} {s.last_name || ''} {s.position ? `(${s.position})` : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <div className={readonlyCls}>{staff.reporting_to_name || '-'}</div>
              )}
            </div>
          </div>

          {/* Work Schedule */}
          <div className="px-6 py-4 border-b border-t border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wider">Work Schedule</h2>
          </div>
          <div className="px-6 py-4">
            <WorkSchedule schedule={schedule} onChange={setSchedule} readOnly={!editing} />
          </div>
        </div>

        {/* Meta info */}
        <div className="mt-4 text-xs text-gray-400">
          Created {new Date(staff.created_at).toLocaleDateString()} &middot; Last updated {new Date(staff.updated_at).toLocaleDateString()}
        </div>
      </div>

      {/* Create Account Modal */}
      {showAccountModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">Create User Account</h2>
              <button onClick={() => setShowAccountModal(false)} className="text-gray-400 hover:text-gray-600" aria-label="Close">&#x2715;</button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <p className="text-sm text-gray-600">
                This will create an organisation login for <span className="font-medium">{staff.email}</span> with org_admin access.
              </p>
              <div>
                <label className={labelCls}>Password *</label>
                <input type="password" value={accountPassword} onChange={e => setAccountPassword(e.target.value)}
                  placeholder="Minimum 8 characters"
                  className={inputCls} />
              </div>
              {accountError && <p className="text-sm text-red-600">{accountError}</p>}
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4 bg-gray-50 rounded-b-lg">
              <Button variant="secondary" onClick={() => setShowAccountModal(false)}>Cancel</Button>
              <Button onClick={handleCreateAccount} loading={creatingAccount}>Create Account</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
