/**
 * Staff list page — Phase 7 port of frontend/src/pages/staff/StaffList.tsx.
 *
 * ALL logic is copied VERBATIM: paginated fetch (page/page_size + role/active
 * filters), client-side name/email/employee-id search filter, the add/edit
 * modal (with inline duplicate-check, "also create as user" invite flow,
 * branch assignment, WorkSchedule), deactivate/activate, and the
 * permanent-delete confirmation (with optional user-account delete).
 *
 * Presentation is reframed onto the design-system tokens per the
 * OraInvoice_Handoff/app/Staff.html prototype: a `.page` wrapper with a
 * `.page-head` (eyebrow + title + sub), a search/filter toolbar, a
 * card-wrapped token table, and the ds.css pagination footer. The inline
 * add/edit overlay is rebuilt with the token surface language (ink/50 scrim,
 * card panel, rounded-card, shadow-pop) and the delete confirm uses the v2
 * Modal primitive. `.mono` is applied to IDs/dates per FR-2.
 */

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Modal } from '@/components/ui'
import WorkSchedule, { type WeekSchedule } from '@/components/WorkSchedule'
import { useBranch } from '@/contexts/BranchContext'
import { useModules } from '@/contexts/ModuleContext'
import StaffKpiStrip from './components/StaffKpiStrip'
import SegmentedFilter from './components/SegmentedFilter'
import DayPips from './components/DayPips'
import { staffInitials } from './components/staffInitials'
import ClockedInDrawer from './components/ClockedInDrawer'
import AuthorizedAvatar from '@/components/AuthorizedAvatar'
import { getPendingLeaveCount } from '@/api/staff'

/**
 * Coerce any API error into a human-readable string for display. Backend 409s
 * (duplicate staff, dependent-record blocks, etc.) return `detail` as an object
 * ({message, code, …}); rendering that object directly crashes React
 * ("Objects are not valid as a React child"). Always pass errors through here.
 */
function errMessage(err: any, fallback = 'Something went wrong'): string {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    return detail.message || detail.detail || detail.msg || fallback
  }
  if (typeof err?.message === 'string') return err.message
  return fallback
}

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
  employment_basis: string
  working_arrangement: string
  hourly_rate: string | null
  overtime_rate: string | null
  skills: string[]
  availability_schedule: Record<string, { start: string; end: string }>
  is_active: boolean
  on_file_photo_url: string | null
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
  employment_basis: string
  working_arrangement: string
  hourly_rate: string
  overtime_rate: string
  skills: string
  /**
   * Selected pay cycle (per-staff-pay-cycle feature). Empty string means
   * "Use organisation default" — no staff-level assignment is created so the
   * staff member resolves to the org Default_Cycle (REQ 1.4, 2.3).
   */
  pay_cycle_id: string
}

/**
 * Active pay cycle as returned by `GET /api/v2/pay-cycles/` (the endpoint
 * filters to `active == True`, so every item is an Active_Cycle). Mirrors the
 * shape consumed by the timesheets/pay-run tabs.
 */
interface PayCycle {
  id: string
  name: string
  frequency: string
  anchor_date: string
  pay_date_offset_days: number
  is_default: boolean
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
  role_type: 'employee', employment_basis: 'full_time', working_arrangement: 'rostered',
  hourly_rate: '', overtime_rate: '', skills: '', pay_cycle_id: '',
}

const modalInputCls = 'w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const modalLabelCls = 'block text-[12.5px] font-medium text-text mb-1'

export default function StaffList() {
  const navigate = useNavigate()
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [pendingLeaveCount, setPendingLeaveCount] = useState(0)
  const [clockedInOpen, setClockedInOpen] = useState(false)
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
  const [userRole, setUserRole] = useState<'org_admin' | 'salesperson' | 'branch_admin' | 'location_manager' | 'staff_member'>('salesperson')
  const [assignBranchId, setAssignBranchId] = useState<string>('')

  // "Send onboarding link" state — independent of the invite above (R1.5)
  const [sendOnboardingLink, setSendOnboardingLink] = useState(false)

  // Active pay cycles for the per-staff pay-cycle selector (per-staff-pay-cycle).
  // Fetched once on mount; the selector is hidden when none are configured.
  const [payCycles, setPayCycles] = useState<PayCycle[]>([])

  const { branches } = useBranch()
  const { isEnabled } = useModules()
  const isBranchModuleEnabled = isEnabled('branch_management')

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

  // Pending leave count for the header "Leave" badge (R5.2). Fetched once on
  // mount; getPendingLeaveCount returns 0 on failure so the badge stays hidden.
  useEffect(() => {
    const controller = new AbortController()
    getPendingLeaveCount(controller.signal)
      .then((count) => setPendingLeaveCount(count))
      .catch(() => setPendingLeaveCount(0))
    return () => controller.abort()
  }, [])

  // Active pay cycles for the Add-modal pay-cycle selector (REQ 1.1). The
  // endpoint returns only active cycles wrapped in `{ items, total }`; consume
  // defensively and default to an empty list so the selector simply hides when
  // none exist (REQ 1.5, 1.6). AbortController cancels the request on unmount.
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get<{ items: PayCycle[]; total: number }>('/api/v2/pay-cycles/', { signal: controller.signal })
      .then((res) => setPayCycles(res.data?.items ?? []))
      .catch(() => setPayCycles([]))
    return () => controller.abort()
  }, [])

  // Shared client-side search predicate — the SAME filter applied to render
  // table rows is reused for the CSV export so they always agree (R5.3).
  const matchesSearch = useCallback((m: StaffMember) => {
    if (!search) return true
    const q = search.toLowerCase()
    const fullName = `${m.first_name} ${m.last_name || ''}`.toLowerCase()
    return fullName.includes(q) || (m.email || '').toLowerCase().includes(q) || (m.employee_id || '').toLowerCase().includes(q)
  }, [search])

  const totalPages = Math.ceil(total / pageSize)

  const openAdd = () => {
    setEditingId(null)
    setForm({ ...emptyForm })
    setSchedule({ ...DEFAULT_SCHEDULE })
    setFormError('')
    setDupWarnings({})
    setCreateAsUser(false)
    setUserRole('salesperson')
    setAssignBranchId('')
    setSendOnboardingLink(false)
    setShowModal(true)
  }

  const openEdit = (member: StaffMember) => {
    // Editing happens on the full Staff Detail page (single source of truth).
    navigate(`/staff/${member.id}?edit=1`)
  }

  const handleSave = async () => {
    if (!form.first_name.trim()) { setFormError('First name is required'); return }
    // R1.2 — block submit when "Send onboarding link" is checked but no email
    if (!editingId && sendOnboardingLink && !form.email.trim()) {
      setFormError('An email address is required to send an onboarding link')
      return
    }
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
        availability_schedule: form.working_arrangement === 'fixed' ? schedule : {},
        role_type: form.role_type,
        employment_basis: form.employment_basis,
        working_arrangement: form.working_arrangement,
        hourly_rate: form.hourly_rate ? parseFloat(form.hourly_rate) : null,
        overtime_rate: form.overtime_rate ? parseFloat(form.overtime_rate) : null,
        skills: form.skills ? form.skills.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
      }
      if (editingId) {
        await apiClient.put(`/staff/${editingId}`, payload, { baseURL: '/api/v2' })
      } else {
        payload.send_onboarding_link = sendOnboardingLink
        // Per-staff pay cycle (REQ 2.1). A selected cycle id assigns a
        // staff-level pay cycle; an empty selection ("Use organisation
        // default") sends null so no assignment is created and the staff
        // member resolves to the org Default_Cycle (REQ 2.3).
        payload.pay_cycle_id = form.pay_cycle_id || null
        const res = await apiClient.post('/staff', payload, { baseURL: '/api/v2' })
        // R1.3/R3.6 — when the onboarding link was requested, surface a failure
        // to send the email (the staff record is still created and preserved).
        if (sendOnboardingLink && res.data?.onboarding_email_sent === false) {
          setFormError('Staff created, but the onboarding email could not be sent. You can resend it from the staff member\u2019s page.')
          setSaving(false)
          fetchStaff()
          return
        }
        // If "Also create as user" is checked, send invite via existing user invite flow
        if (createAsUser && form.email.trim()) {
          try {
            const inviteRes = await apiClient.post('/org/users/invite', { email: form.email.trim(), role: userRole })
            // If a branch is selected, assign the user to that branch
            if (assignBranchId) {
              const userId = (inviteRes.data as any)?.user_id
              if (userId) {
                try {
                  await apiClient.put(`/org/users/${userId}`, { branch_ids: [assignBranchId] })
                } catch {
                  // Branch assignment is best-effort — don't fail the whole operation
                }
              }
            }
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
      setFormError(errMessage(err, 'Failed to save'))
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
  // Preflight: which dependent records (payroll, timesheets, …) block a hard
  // delete, plus any error surfaced from the delete attempt itself.
  const [deleteBlockers, setDeleteBlockers] = useState<{ label: string; count: number }[]>([])
  const [checkingBlockers, setCheckingBlockers] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // When the delete modal opens for a member, preflight the deletion-check so
  // the admin sees exactly what blocks a permanent delete before trying.
  useEffect(() => {
    if (!deleteTarget) return
    let cancelled = false
    setDeleteBlockers([])
    setDeleteError(null)
    setCheckingBlockers(true)
    apiClient
      .get(`/staff/${deleteTarget.id}/deletion-check`, { baseURL: '/api/v2' })
      .then((res) => {
        if (cancelled) return
        const blockers = (res.data as any)?.blockers ?? []
        setDeleteBlockers(Array.isArray(blockers) ? blockers : [])
      })
      .catch(() => { if (!cancelled) setDeleteBlockers([]) })
      .finally(() => { if (!cancelled) setCheckingBlockers(false) })
    return () => { cancelled = true }
  }, [deleteTarget])

  const handleDeactivateFromModal = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await apiClient.delete(`/staff/${deleteTarget.id}`, { baseURL: '/api/v2' })
      setDeleteTarget(null)
      fetchStaff()
    } catch (err: any) {
      setDeleteError(errMessage(err, 'Failed to deactivate staff member'))
    } finally {
      setDeleting(false)
    }
  }

  const handleDeleteStaff = async () => {
    if (!deleteTarget) return
    const member = deleteTarget
    setDeleting(true)
    setDeleteError(null)
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
      // The backend returns a structured 409 ({detail:{message, blockers}}) when
      // payroll/timesheet history blocks a hard delete; show the message + list.
      const detail = err?.response?.data?.detail
      if (detail && typeof detail === 'object' && Array.isArray(detail.blockers)) {
        setDeleteBlockers(detail.blockers)
      }
      setDeleteError(errMessage(err, 'Failed to delete staff member'))
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

  // CSV export of the CURRENT filtered + searched staff set (R5.3). Uses the
  // exact same `matchesSearch` predicate the table renders with, so the export
  // mirrors the applied role/status filters (server-side) and search.
  const handleExport = () => {
    const csvEscape = (value: unknown): string => {
      const s = value == null ? '' : String(value)
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
    }
    const headers = [
      'Employee ID', 'First Name', 'Last Name', 'Position',
      'Email', 'Phone', 'Role Type', 'Status',
    ]
    const rows = staff.filter(matchesSearch).map((m) => [
      m.employee_id ?? '',
      m.first_name ?? '',
      m.last_name ?? '',
      m.position ?? '',
      m.email ?? '',
      m.phone ?? '',
      m.role_type === 'employee' ? 'Employee' : 'Contractor',
      m.is_active ? 'Active' : 'Inactive',
    ])
    const lines = [headers, ...rows].map((cols) => cols.map(csvEscape).join(','))
    const csv = lines.join('\r\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'staff.csv'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const thCls = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">People</div>
          <h1>Staff</h1>
          <p className="sub">
            <span className="mono">{total}</span> staff member{total !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="head-actions">
          <button
            type="button"
            onClick={() => setClockedInOpen(true)}
            className="relative inline-flex h-10 items-center gap-2 rounded-ctl border border-border bg-card px-3.5 text-[13.5px] font-medium text-text hover:bg-canvas dark:hover:bg-canvas"
          >
            <span
              className="relative inline-flex h-2 w-2"
              aria-hidden="true"
            >
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ok opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-ok" />
            </span>
            <svg
              className="h-4 w-4 text-muted-2"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            Clocked in
          </button>
          <button
            type="button"
            onClick={() => navigate('/leave/approvals')}
            className="relative inline-flex h-10 items-center gap-2 rounded-ctl border border-border bg-card px-3.5 text-[13.5px] font-medium text-text hover:bg-canvas dark:hover:bg-canvas"
          >
            <svg className="h-4 w-4 text-muted-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3M3 11h18M5 5h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z" />
            </svg>
            Leave
            {pendingLeaveCount > 0 && (
              <span
                aria-label={`${pendingLeaveCount} pending leave requests`}
                className="ml-0.5 inline-flex min-w-[18px] items-center justify-center rounded-full bg-danger px-1.5 py-0.5 text-[10.5px] font-semibold leading-none text-white"
              >
                {pendingLeaveCount}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={handleExport}
            className="inline-flex h-10 items-center gap-2 rounded-ctl border border-border bg-card px-3.5 text-[13.5px] font-medium text-text hover:bg-canvas dark:hover:bg-canvas"
          >
            <svg className="h-4 w-4 text-muted-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
            Export
          </button>
          <Button
            leftIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
              </svg>
            }
            onClick={openAdd}
          >
            Add Staff
          </Button>
        </div>
      </div>

      {/* KPI strip */}
      <StaffKpiStrip totalStaff={total} />

      {/* Filters */}
      <div className="mb-[22px] flex flex-wrap items-center gap-3">
        <div className="flex h-10 max-w-[300px] flex-1 items-center gap-2.5 rounded-ctl border border-border bg-card px-3 focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft)]">
          <svg className="h-4 w-4 shrink-0 text-muted-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search by name or email…"
            value={search}
            onChange={(e) => { setSearch(e.target.value) }}
            aria-label="Search staff"
            className="w-full border-none bg-transparent text-[13.5px] text-text outline-none placeholder:text-muted-2"
          />
        </div>
        <SegmentedFilter
          ariaLabel="Filter by role"
          value={roleFilter}
          onChange={(v) => { setRoleFilter(v); setPage(1) }}
          options={[
            { label: 'All roles', value: '' },
            { label: 'Employees', value: 'employee' },
            { label: 'Contractors', value: 'contractor' },
          ]}
        />
        <SegmentedFilter
          ariaLabel="Filter by status"
          value={activeFilter}
          onChange={(v) => { setActiveFilter(v); setPage(1) }}
          options={[
            { label: 'All', value: '' },
            { label: 'Active', value: 'true' },
            { label: 'Inactive', value: 'false' },
          ]}
        />
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-16 text-center text-muted">Loading staff…</div>
      ) : staff.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-muted">No staff members found.</p>
          <p className="text-sm text-muted-2 mt-1">Add your first staff member to get started.</p>
        </div>
      ) : (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className={thCls}>Employee ID</th>
                  <th className={thCls}>Name</th>
                  <th className={thCls}>Position</th>
                  <th className={thCls}>Email</th>
                  <th className={thCls}>Phone</th>
                  <th className={thCls}>Work Days</th>
                  <th className={thCls}>Reports To</th>
                  <th className={thCls}>Status</th>
                  <th className={thCls}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {staff.filter(matchesSearch).map((member) => (
                  <tr key={member.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono whitespace-nowrap px-4 py-3 text-muted">{member.employee_id || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex items-center gap-3">
                        <AuthorizedAvatar
                          src={member.on_file_photo_url}
                          initials={staffInitials(member.first_name, member.last_name) || '—'}
                          className="h-8 w-8 shrink-0 rounded-full bg-accent-soft"
                          fallbackClassName="text-[12px] font-semibold text-accent"
                          alt={`Profile photo of ${member.first_name} ${member.last_name ?? ''}`.trim()}
                        />
                        <div className="flex flex-col">
                          <button onClick={() => navigate(`/staff/${member.id}`)}
                            className="text-left text-[13.5px] font-medium text-accent hover:text-accent-press">
                            {member.first_name} {member.last_name || ''}
                          </button>
                          <span className="text-[11.5px] text-muted-2">
                            {member.role_type === 'employee' ? 'Employee' : 'Contractor'}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-text">{member.position || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">{member.email || '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-muted">{member.phone || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">
                      <DayPips schedule={member.availability_schedule} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">{member.reporting_to_name || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${member.is_active ? 'bg-ok-soft text-ok' : 'bg-[#EEF0F4] text-muted'}`}>
                        {member.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button onClick={() => openEdit(member)}
                          className="text-sm text-accent hover:text-accent-press">Edit</button>
                        {member.is_active ? (
                          <button onClick={() => handleDeactivate(member.id)}
                            className="text-sm text-danger hover:brightness-110">Deactivate</button>
                        ) : (
                          <button onClick={() => handleActivate(member.id)}
                            className="text-sm text-ok hover:brightness-110">Activate</button>
                        )}
                        <button onClick={() => { setDeleteTarget(member); setDeleteAlsoUser(!!member.email) }}
                          className="text-sm text-danger hover:brightness-110">Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-border px-4 py-3">
              <span className="text-[12.5px] text-muted">
                Showing <span className="mono text-text">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)}</span> of <span className="mono text-text">{total}</span>
              </span>
              <div className="flex items-center gap-2">
                <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                  className="rounded-ctl border border-border px-3 py-1.5 text-sm text-text disabled:opacity-50 hover:bg-canvas">
                  Previous
                </button>
                <span className="text-[12.5px] text-muted">Page <span className="mono">{page}</span> of <span className="mono">{totalPages}</span></span>
                <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}
                  className="rounded-ctl border border-border px-3 py-1.5 text-sm text-text disabled:opacity-50 hover:bg-canvas">
                  Next
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Add/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50">
          <div className="mx-4 max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-card bg-card shadow-pop">
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <h2 className="text-[15px] font-semibold text-text">
                {editingId ? 'Edit Staff Member' : 'Add Staff Member'}
              </h2>
              <button onClick={() => setShowModal(false)} className="text-muted-2 hover:text-text" aria-label="Close">✕</button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={modalLabelCls}>First Name *</label>
                  <input type="text" value={form.first_name} onChange={(e) => setForm(f => ({ ...f, first_name: e.target.value }))}
                    className={modalInputCls} />
                </div>
                <div>
                  <label className={modalLabelCls}>Last Name</label>
                  <input type="text" value={form.last_name} onChange={(e) => setForm(f => ({ ...f, last_name: e.target.value }))}
                    className={modalInputCls} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={modalLabelCls}>Email</label>
                  <input type="email" value={form.email} onChange={(e) => { setForm(f => ({ ...f, email: e.target.value })); checkDuplicate('email', e.target.value) }}
                    className={modalInputCls} />
                  {dupWarnings.email && <p className="text-xs text-danger mt-0.5">{dupWarnings.email}</p>}
                </div>
                <div>
                  <label className={modalLabelCls}>Phone</label>
                  <input type="tel" value={form.phone} onChange={(e) => { setForm(f => ({ ...f, phone: e.target.value })); checkDuplicate('phone', e.target.value) }}
                    className={modalInputCls} />
                  {dupWarnings.phone && <p className="text-xs text-danger mt-0.5">{dupWarnings.phone}</p>}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={modalLabelCls}>Employee ID</label>
                  <input type="text" value={form.employee_id} onChange={(e) => { setForm(f => ({ ...f, employee_id: e.target.value })); checkDuplicate('employee_id', e.target.value) }}
                    placeholder="e.g. EMP-001"
                    className={modalInputCls} />
                  {dupWarnings.employee_id && <p className="text-xs text-danger mt-0.5">{dupWarnings.employee_id}</p>}
                </div>
                <div>
                  <label className={modalLabelCls}>Position</label>
                  <input type="text" value={form.position} onChange={(e) => setForm(f => ({ ...f, position: e.target.value }))}
                    placeholder="e.g. Senior Mechanic"
                    className={modalInputCls} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={modalLabelCls}>Role Type</label>
                  <select value={form.role_type} onChange={(e) => setForm(f => ({ ...f, role_type: e.target.value }))}
                    className={modalInputCls}>
                    <option value="employee">Employee</option>
                    <option value="contractor">Contractor</option>
                  </select>
                </div>
                <div>
                  <label className={modalLabelCls}>Hourly Rate ($)</label>
                  <input type="number" step="0.01" min="0" value={form.hourly_rate}
                    onChange={(e) => setForm(f => ({ ...f, hourly_rate: e.target.value }))}
                    className={modalInputCls} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={modalLabelCls}>Employment Basis</label>
                  <select value={form.employment_basis} onChange={(e) => setForm(f => ({ ...f, employment_basis: e.target.value }))}
                    className={modalInputCls}>
                    <option value="full_time">Full-time employee</option>
                    <option value="part_time">Part-time employee</option>
                    <option value="casual">Casual</option>
                    <option value="contractor">Contractor</option>
                  </select>
                </div>
                <div>
                  <label className={modalLabelCls}>Working Arrangement</label>
                  <select value={form.working_arrangement} onChange={(e) => setForm(f => ({ ...f, working_arrangement: e.target.value }))}
                    className={modalInputCls}>
                    <option value="fixed">Fixed shifts (set days &amp; hours)</option>
                    <option value="rostered">Rostered / rotating shifts</option>
                    <option value="casual_on_demand">Casual — on demand</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={modalLabelCls}>Overtime Rate ($)</label>
                  <input type="number" step="0.01" min="0" value={form.overtime_rate}
                    onChange={(e) => setForm(f => ({ ...f, overtime_rate: e.target.value }))}
                    className={modalInputCls} />
                </div>
                <div>
                  <label className={modalLabelCls}>Skills (comma-separated)</label>
                  <input type="text" value={form.skills}
                    onChange={(e) => setForm(f => ({ ...f, skills: e.target.value }))}
                    placeholder="e.g. Brakes, Engine, Electrical"
                    className={modalInputCls} />
                </div>
              </div>
              <div>
                <label className={modalLabelCls}>Reports To</label>
                <select value={form.reporting_to} onChange={(e) => setForm(f => ({ ...f, reporting_to: e.target.value }))}
                  className={modalInputCls}>
                  <option value="">— None —</option>
                  {allStaff.filter(s => s.id !== editingId && s.is_active).map(s => (
                    <option key={s.id} value={s.id}>{s.first_name} {s.last_name || ''} {s.position ? `(${s.position})` : ''}</option>
                  ))}
                </select>
              </div>

              {/* Pay cycle selector (per-staff-pay-cycle). Shown only when the
                  org has at least one active cycle; otherwise hidden with a
                  hint to configure one (REQ 1.1, 1.2, 1.4, 1.5, 1.6). */}
              {payCycles.length > 0 ? (
                <div>
                  <label className={modalLabelCls}>Pay Cycle</label>
                  <select
                    value={form.pay_cycle_id}
                    onChange={(e) => setForm(f => ({ ...f, pay_cycle_id: e.target.value }))}
                    className={modalInputCls}
                  >
                    {/* "Use organisation default" — leaves no staff-level
                        assignment so the org Default_Cycle applies (REQ 1.4). */}
                    <option value="">
                      Use organisation default{(() => {
                        const def = payCycles.find(c => c.is_default)
                        return def ? ` (${def.name})` : ''
                      })()}
                    </option>
                    {payCycles.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-muted-2">
                    Choose a pay cycle for this staff member, or leave as
                    “Use organisation default” to pay them on your organisation’s
                    default cycle.
                  </p>
                </div>
              ) : (
                <div className="rounded-ctl border border-dashed border-border bg-canvas p-4">
                  <p className="text-xs text-muted-2">
                    No pay cycle configured — set one up under Timesheets →
                    Settings to assign a pay cycle to this staff member.
                  </p>
                </div>
              )}

              {/* Also create as user — only for new staff */}
              {!editingId && (
                <div className="rounded-ctl border border-border bg-canvas p-4 space-y-3">
                  <label className="flex items-center gap-2 text-[12.5px] font-medium text-text cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createAsUser}
                      onChange={(e) => setCreateAsUser(e.target.checked)}
                      className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                    />
                    Also create as a user (sends invite email)
                  </label>
                  {createAsUser && (
                    <>
                    <div>
                      <label className={modalLabelCls}>User Role</label>
                      <select
                        value={userRole}
                        onChange={(e) => setUserRole(e.target.value as typeof userRole)}
                        className={modalInputCls}
                      >
                        <option value="salesperson">Salesperson</option>
                        <option value="org_admin">Org Admin</option>
                        {isBranchModuleEnabled && <option value="branch_admin">Branch Admin</option>}
                        <option value="location_manager">Location Manager</option>
                        <option value="staff_member">Staff Member</option>
                      </select>
                      {!form.email.trim() && (
                        <p className="mt-1 text-xs text-warn">Email is required to send an invite</p>
                      )}
                    </div>
                    <div>
                      <label className={modalLabelCls}>Assign to Branch</label>
                      <select
                        value={assignBranchId}
                        onChange={(e) => setAssignBranchId(e.target.value)}
                        className={modalInputCls}
                      >
                        <option value="">— No Branch —</option>
                        {(branches ?? []).filter(b => b.is_active).map(b => (
                          <option key={b.id} value={b.id}>{b.name}</option>
                        ))}
                      </select>
                    </div>
                    </>
                  )}
                </div>
              )}

              {/* Send onboarding link — only for new staff (R1.1, R1.5) */}
              {!editingId && (
                <div className="rounded-ctl border border-border bg-canvas p-4 space-y-3">
                  <label className="flex items-center gap-2 text-[12.5px] font-medium text-text cursor-pointer">
                    <input
                      type="checkbox"
                      checked={sendOnboardingLink}
                      onChange={(e) => setSendOnboardingLink(e.target.checked)}
                      className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                    />
                    Send onboarding link (staff completes their own details)
                  </label>
                  {sendOnboardingLink && !form.email.trim() && (
                    <p className="text-xs text-warn">Email is required to send an onboarding link</p>
                  )}
                </div>
              )}

              {form.working_arrangement === 'fixed' ? (
                <div className="rounded-ctl border border-border bg-canvas p-4 space-y-2">
                  <WorkSchedule schedule={schedule} onChange={setSchedule} />
                  <p className="text-xs text-muted-2">
                    These fixed hours are the source of truth for this staff member&apos;s timesheets — they
                    generate rostered hours automatically each pay period, ready to approve and pay.
                  </p>
                </div>
              ) : (
                <div className="rounded-ctl border border-dashed border-border bg-canvas p-4">
                  <p className="text-xs text-muted-2">
                    {form.working_arrangement === 'rostered'
                      ? 'Hours come from the published roster (Schedule page) and clock-in/out activity. Set up shifts on the Schedule page.'
                      : 'Casual on-demand — hours come from actual clock-in/out activity. No fixed work days to define.'}
                  </p>
                </div>
              )}
              {formError && <p className="text-sm text-danger">{formError}</p>}
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4 bg-canvas rounded-b-card">
              <Button variant="ghost" onClick={() => setShowModal(false)}>Cancel</Button>
              <Button onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Add Staff'}</Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <Modal open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete Staff Member">
        {deleteTarget && (() => {
          const blocked = deleteBlockers.length > 0
          const fullName = `${deleteTarget.first_name} ${deleteTarget.last_name || ''}`.trim()
          return (
          <div className="space-y-4">
            {/* Blocked: payroll/timesheet history prevents a hard delete */}
            {blocked ? (
              <div className="rounded-ctl border border-warn/40 bg-warn-soft p-4">
                <p className="text-sm font-medium text-text">
                  {fullName || 'This staff member'} can’t be permanently deleted
                </p>
                <p className="mt-1 text-sm text-muted">
                  They have history that must be kept for your records:
                </p>
                <ul className="mt-2 space-y-1">
                  {deleteBlockers.map((b) => (
                    <li key={b.label} className="flex items-center justify-between rounded bg-canvas px-3 py-1.5 text-sm">
                      <span className="text-text">{b.label}</span>
                      <span className="mono font-semibold text-text">{b.count}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-sm text-muted">
                  Deactivate them instead — this removes them from active lists and
                  sign-in while preserving these records.
                </p>
              </div>
            ) : (
              <div className="rounded-ctl border border-danger/30 bg-danger-soft p-4">
                <p className="text-sm text-danger">
                  This will permanently delete <span className="font-semibold">{fullName}</span>.
                  This action cannot be undone.
                </p>
                <p className="mt-2 text-sm text-danger">
                  {checkingBlockers
                    ? 'Checking for linked records…'
                    : 'Any invoices, quotes, or other data they created will be preserved and remain accessible.'}
                </p>
              </div>
            )}

            {/* Error surfaced from the delete/deactivate attempt itself */}
            {deleteError && (
              <div role="alert" className="rounded-ctl border border-danger/40 bg-danger-soft p-3 text-sm text-danger">
                {deleteError}
              </div>
            )}

            {!blocked && deleteTarget.email && (
              <label className="flex items-start gap-3 rounded-ctl border border-border bg-canvas p-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deleteAlsoUser}
                  onChange={(e) => setDeleteAlsoUser(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border text-danger focus:ring-danger"
                />
                <div>
                  <p className="text-sm font-medium text-text">Also delete user account</p>
                  <p className="text-xs text-muted">
                    Remove the login account for {deleteTarget.email}. They will no longer be able to sign in.
                  </p>
                </div>
              </label>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>Cancel</Button>
              {blocked ? (
                deleteTarget.is_active ? (
                  <Button variant="primary" size="sm" onClick={handleDeactivateFromModal} loading={deleting}>
                    Deactivate instead
                  </Button>
                ) : (
                  <Button variant="ghost" size="sm" disabled>Already inactive</Button>
                )
              ) : (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleDeleteStaff}
                  loading={deleting}
                  disabled={checkingBlockers}
                >
                  Delete permanently
                </Button>
              )}
            </div>
          </div>
          )
        })()}
      </Modal>

      <ClockedInDrawer
        open={clockedInOpen}
        onClose={() => setClockedInOpen(false)}
      />
    </div>
  )
}
