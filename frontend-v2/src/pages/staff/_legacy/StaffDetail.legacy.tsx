/**
 * Legacy single-form Staff Detail page.
 *
 * Rendered when the `staff_management` module is disabled (Phase 1 module
 * gate per design §2). The new tabbed shell at `@/pages/staff/StaffDetail`
 * delegates to this file when the module is off so that orgs without the new
 * feature still see the original UX unchanged.
 *
 * Do not add features here. New work lives in the tab components.
 *
 * Logic copied verbatim from frontend/src/pages/staff/_legacy/
 * StaffDetail.legacy.tsx; presentation remapped onto the design-system tokens.
 */

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button } from '@/components/ui'
import WorkSchedule, { type WeekSchedule } from '@/components/WorkSchedule'

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

const inputCls = 'w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const readonlyCls = 'w-full rounded-ctl border border-border bg-canvas px-3 py-2 text-sm text-muted'
const labelCls = 'block text-[12.5px] font-medium text-text mb-1'

export default function LegacyStaffDetail({ staffId }: Props) {
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
        <p className="text-muted">Loading staff member...</p>
      </div>
    )
  }

  if (!staff) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted">Staff member not found.</p>
          <button onClick={() => navigate('/staff')} className="mt-2 text-sm text-accent hover:text-accent-press">
            Back to Staff List
          </button>
        </div>
      </div>
    )
  }

  const fullName = `${staff.first_name} ${staff.last_name || ''}`.trim()

  return (
    <div className="h-full" data-testid="legacy-staff-detail">
      {/* Header */}
      <div className="bg-card border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/staff')} className="text-muted-2 hover:text-text">
              &larr; Back
            </button>
            <h1 className="text-xl font-semibold text-text">{fullName}</h1>
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${staff.is_active ? 'bg-ok-soft text-ok' : 'bg-[#EEF0F4] text-muted'}`}>
              {staff.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {!editing && (
              <>
                <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
                {!staff.user_id && staff.email && staff.is_active && (
                  <button onClick={() => { setShowAccountModal(true); setAccountPassword(''); setAccountError('') }}
                    className="rounded-ctl border border-accent/40 px-4 py-2 text-sm text-accent hover:bg-accent-soft">
                    Create User Account
                  </button>
                )}
                {staff.user_id && (
                  <span className="inline-flex items-center rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
                    Has Login
                  </span>
                )}
                {staff.is_active ? (
                  <button onClick={handleDeactivate} className="rounded-ctl border border-danger/40 px-4 py-2 text-sm text-danger hover:bg-danger-soft">
                    Deactivate
                  </button>
                ) : (
                  <button onClick={handleActivate} className="rounded-ctl border border-ok/40 px-4 py-2 text-sm text-ok hover:bg-ok-soft">
                    Activate
                  </button>
                )}
              </>
            )}
            {editing && (
              <>
                <Button variant="ghost" onClick={cancelEdit}>Cancel</Button>
                <Button onClick={handleSave} loading={saving}>Save Changes</Button>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="px-6 py-6 max-w-3xl">
        {formError && (
          <div className="mb-4 rounded-ctl bg-danger-soft border border-danger/40 px-4 py-3">
            <p className="text-sm text-danger">{formError}</p>
          </div>
        )}

        <div className="bg-card rounded-card border border-border shadow-card">
          {/* Personal Info */}
          <div className="px-6 py-4 border-b border-border">
            <h2 className="text-sm font-semibold text-text uppercase tracking-wider">Personal Information</h2>
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
          <div className="px-6 py-4 border-b border-t border-border">
            <h2 className="text-sm font-semibold text-text uppercase tracking-wider">Employment Details</h2>
          </div>
          <div className="px-6 py-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Employee ID</label>
                {editing ? (
                  <input type="text" value={employeeId} onChange={e => setEmployeeId(e.target.value)} placeholder="e.g. EMP-001" className={inputCls} />
                ) : (
                  <div className={`${readonlyCls} mono`}>{staff.employee_id || '-'}</div>
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
                  <div className={`${readonlyCls} mono`}>{staff.hourly_rate ? `${parseFloat(staff.hourly_rate).toFixed(2)}` : '-'}</div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Overtime Rate ($)</label>
                {editing ? (
                  <input type="number" step="0.01" min="0" value={overtimeRate} onChange={e => setOvertimeRate(e.target.value)} className={inputCls} />
                ) : (
                  <div className={`${readonlyCls} mono`}>{staff.overtime_rate ? `${parseFloat(staff.overtime_rate).toFixed(2)}` : '-'}</div>
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
          <div className="px-6 py-4 border-b border-t border-border">
            <h2 className="text-sm font-semibold text-text uppercase tracking-wider">Work Schedule</h2>
          </div>
          <div className="px-6 py-4">
            <WorkSchedule schedule={schedule} onChange={setSchedule} readOnly={!editing} />
          </div>
        </div>

        {/* Meta info */}
        <div className="mt-4 text-xs text-muted-2">
          Created <span className="mono">{new Date(staff.created_at).toLocaleDateString()}</span> &middot; Last updated <span className="mono">{new Date(staff.updated_at).toLocaleDateString()}</span>
        </div>
      </div>

      {/* Create Account Modal */}
      {showAccountModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50">
          <div className="bg-card rounded-card shadow-pop w-full max-w-md mx-4">
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <h2 className="text-[15px] font-semibold text-text">Create User Account</h2>
              <button onClick={() => setShowAccountModal(false)} className="text-muted-2 hover:text-text" aria-label="Close">&#x2715;</button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <p className="text-sm text-muted">
                This will create an organisation login for <span className="font-medium text-text">{staff.email}</span> with org_admin access.
              </p>
              <div>
                <label className={labelCls}>Password *</label>
                <input type="password" value={accountPassword} onChange={e => setAccountPassword(e.target.value)}
                  placeholder="Minimum 8 characters"
                  className={inputCls} />
              </div>
              {accountError && <p className="text-sm text-danger">{accountError}</p>}
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4 bg-canvas rounded-b-card">
              <Button variant="ghost" onClick={() => setShowAccountModal(false)}>Cancel</Button>
              <Button onClick={handleCreateAccount} loading={creatingAccount}>Create Account</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
