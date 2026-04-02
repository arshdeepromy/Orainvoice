/**
 * Staff scheduling page — calendar/table view of schedule entries filtered by branch.
 * Includes "Add Shift" form with overlap error handling.
 *
 * Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5
 */
import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { useBranch } from '@/contexts/BranchContext'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { ToastContainer, useToast } from '@/components/ui/Toast'

interface ScheduleEntry {
  id: string
  branch_name: string
  user_name: string
  shift_date: string
  start_time: string
  end_time: string
  notes: string | null
}

interface StaffOption {
  id: string
  name: string
  first_name?: string
  last_name?: string | null
  user_id: string | null
  shift_start: string | null
  shift_end: string | null
  availability_schedule: Record<string, { start: string; end: string }> | null
}

export default function StaffSchedule() {
  const { selectedBranchId, branches } = useBranch()
  const { toasts, addToast, dismissToast } = useToast()
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [staff, setStaff] = useState<StaffOption[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Form state
  const [selectedStaffId, setSelectedStaffId] = useState('')
  const [branchId, setBranchId] = useState('')
  const [shiftDate, setShiftDate] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [notes, setNotes] = useState('')

  const fetchEntries = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ entries: ScheduleEntry[] }>('/scheduling')
      setEntries(res.data?.entries ?? [])
    } catch {
      addToast('error', 'Failed to load schedule')
    } finally {
      setLoading(false)
    }
  }, [addToast])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      try {
        const [schedRes, staffRes] = await Promise.all([
          apiClient.get<{ entries: ScheduleEntry[] }>('/scheduling', { signal: controller.signal }),
          apiClient.get<{ staff: StaffOption[]; total: number }>('/staff', {
            baseURL: '/api/v2',
            params: { page_size: '200', is_active: 'true' },
            signal: controller.signal,
          }),
        ])
        setEntries(schedRes.data?.entries ?? [])
        // Map staff members — only include those with a linked user account
        const allStaff = (staffRes.data?.staff ?? []).map((s) => ({
          id: s.id,
          name: s.name ?? `${s.first_name ?? ''} ${s.last_name ?? ''}`.trim(),
          user_id: s.user_id ?? null,
          shift_start: s.shift_start ?? null,
          shift_end: s.shift_end ?? null,
          availability_schedule: s.availability_schedule ?? null,
        }))
        setStaff(allStaff)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          addToast('error', 'Failed to load schedule')
        }
      } finally {
        setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [addToast, selectedBranchId])

  // Pre-fill shift times from staff member's default work hours when selected
  const handleStaffSelect = (staffId: string) => {
    setSelectedStaffId(staffId)
    const member = staff.find((s) => s.id === staffId)
    if (!member) return

    // Get day name for the selected date to look up availability_schedule
    if (shiftDate && member.availability_schedule) {
      const dayName = new Date(shiftDate).toLocaleDateString('en-US', { weekday: 'long' }).toLowerCase()
      const dayHours = member.availability_schedule[dayName]
      if (dayHours) {
        if (!startTime) setStartTime(dayHours.start)
        if (!endTime) setEndTime(dayHours.end)
        return
      }
    }

    // Fallback to legacy shift_start/shift_end
    if (!startTime && member.shift_start) setStartTime(member.shift_start)
    if (!endTime && member.shift_end) setEndTime(member.shift_end)
  }

  // Also pre-fill times when date changes (for availability_schedule lookup)
  const handleDateChange = (date: string) => {
    setShiftDate(date)
    if (!selectedStaffId || !date) return
    const member = staff.find((s) => s.id === selectedStaffId)
    if (!member?.availability_schedule) return
    const dayName = new Date(date).toLocaleDateString('en-US', { weekday: 'long' }).toLowerCase()
    const dayHours = member.availability_schedule[dayName]
    if (dayHours) {
      setStartTime(dayHours.start)
      setEndTime(dayHours.end)
    }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()

    // Resolve the user_id from the selected staff member
    const selectedMember = staff.find((s) => s.id === selectedStaffId)
    if (!selectedMember) {
      addToast('error', 'Please select a staff member')
      return
    }
    if (!selectedMember.user_id) {
      addToast('error', 'This staff member does not have a user account. Create one from the Staff page first.')
      return
    }

    const effectiveBranchId = branchId || selectedBranchId
    if (!effectiveBranchId) {
      addToast('error', 'Please select a branch')
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post('/scheduling', {
        user_id: selectedMember.user_id,
        branch_id: effectiveBranchId,
        shift_date: shiftDate,
        start_time: startTime,
        end_time: endTime,
        notes: notes || null,
      })
      addToast('success', 'Shift added')
      setShowForm(false)
      setSelectedStaffId('')
      setBranchId('')
      setShiftDate('')
      setStartTime('')
      setEndTime('')
      setNotes('')
      fetchEntries()
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create shift'
      if (status === 409) {
        addToast('warning', msg)
      } else {
        addToast('error', msg)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (entryId: string) => {
    try {
      await apiClient.delete(`/scheduling/${entryId}`)
      addToast('success', 'Shift deleted')
      fetchEntries()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to delete shift'
      addToast('error', msg)
    }
  }

  // Group entries by branch when "All Branches"
  const grouped = !selectedBranchId
    ? (entries ?? []).reduce<Record<string, ScheduleEntry[]>>((acc, e) => {
        const key = e.branch_name ?? 'Unknown'
        if (!acc[key]) acc[key] = []
        acc[key].push(e)
        return acc
      }, {})
    : null

  if (loading && entries.length === 0) {
    return <div className="py-16"><Spinner label="Loading schedule" /></div>
  }

  return (
    <div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">Staff schedule{selectedBranchId ? '' : ' across all branches'}.</p>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : 'Add Shift'}
        </Button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 rounded-lg border border-gray-200 bg-white p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <div>
              <label htmlFor="sched-user" className="block text-sm font-medium text-gray-700 mb-1">Staff Member</label>
              <select id="sched-user" value={selectedStaffId} onChange={(e) => handleStaffSelect(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
                <option value="">Select staff</option>
                {(staff ?? []).map((s) => (
                  <option key={s.id} value={s.id} disabled={!s.user_id}>
                    {s.name}{!s.user_id ? ' (no account)' : ''}
                  </option>
                ))}
              </select>
            </div>
            {!selectedBranchId && (
              <div>
                <label htmlFor="sched-branch" className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
                <select id="sched-branch" value={branchId} onChange={(e) => setBranchId(e.target.value)} required
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
                  <option value="">Select branch</option>
                  {(branches ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label htmlFor="sched-date" className="block text-sm font-medium text-gray-700 mb-1">Date</label>
              <input id="sched-date" type="date" value={shiftDate} onChange={(e) => handleDateChange(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label htmlFor="sched-start" className="block text-sm font-medium text-gray-700 mb-1">Start Time</label>
              <input id="sched-start" type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label htmlFor="sched-end" className="block text-sm font-medium text-gray-700 mb-1">End Time</label>
              <input id="sched-end" type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="sched-notes" className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
              <input id="sched-notes" type="text" value={notes} onChange={(e) => setNotes(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" placeholder="Optional notes" />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button size="sm" type="submit" loading={submitting} disabled={submitting}>Add Shift</Button>
          </div>
        </form>
      )}

      {grouped ? (
        Object.entries(grouped).map(([branchName, branchEntries]) => (
          <div key={branchName} className="mb-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-2">{branchName}</h3>
            <ScheduleTable entries={branchEntries} showBranch={false} onDelete={handleDelete} />
          </div>
        ))
      ) : (
        <ScheduleTable entries={entries} showBranch={false} onDelete={handleDelete} />
      )}

      {entries.length === 0 && !loading && (
        <p className="text-center text-sm text-gray-500 py-12">No schedule entries found.</p>
      )}
    </div>
  )
}

function ScheduleTable({
  entries,
  showBranch,
  onDelete,
}: {
  entries: ScheduleEntry[]
  showBranch: boolean
  onDelete: (id: string) => void
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200" role="grid">
        <caption className="sr-only">Staff schedule</caption>
        <thead className="bg-gray-50">
          <tr>
            {showBranch && <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Branch</th>}
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Staff</th>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Start</th>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">End</th>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Notes</th>
            <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {entries.map((e) => (
            <tr key={e.id} className="hover:bg-gray-50">
              {showBranch && <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{e.branch_name ?? '—'}</td>}
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{e.user_name ?? '—'}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{e.shift_date}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{e.start_time}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{e.end_time}</td>
              <td className="px-4 py-3 text-sm text-gray-500 max-w-xs truncate">{e.notes ?? '—'}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                <Button size="sm" variant="danger" onClick={() => onDelete(e.id)}>Delete</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
