/**
 * Schedule Entry Modal — create or edit a schedule entry.
 *
 * Create mode: POST /api/v2/schedule
 * Edit mode:   PUT  /api/v2/schedule/{id} (pre-populated)
 * After submit: GET  /api/v2/schedule/{id}/conflicts → display warning if any
 *
 * Requirements: 36.1, 36.2, 36.3, 36.4, 36.5, 36.6
 */

import { useState, useEffect, useCallback } from 'react'
import { Modal } from '@/components/ui/Modal'
import apiClient from '@/api/client'
import type { ScheduleEntry } from './ScheduleCalendar'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StaffOption {
  id: string
  name: string
  position: string | null
}

interface ConflictItem {
  entry_id: string
  title: string | null
  start_time: string
  end_time: string
  entry_type: string
}

interface ScheduleEntryModalProps {
  open: boolean
  onClose: () => void
  onSave: () => void
  /** When provided the modal opens in edit mode with pre-populated fields */
  entry?: ScheduleEntry | null
  /** Pre-select entry type (e.g. 'leave' for Add Leave button) */
  defaultEntryType?: string
}

interface ShiftTemplate {
  id: string
  name: string
  start_time: string
  end_time: string
  entry_type: string
}

const ENTRY_TYPES = [
  { value: 'job', label: 'Job' },
  { value: 'booking', label: 'Booking' },
  { value: 'break', label: 'Break' },
  { value: 'leave', label: 'Leave' },
  { value: 'other', label: 'Other' },
] as const

const RECURRENCE_OPTIONS = [
  { value: 'none', label: 'Does not repeat' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'fortnightly', label: 'Fortnightly' },
] as const

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Convert an ISO datetime string to a local datetime-local input value */
function toDatetimeLocal(iso: string): string {
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return ''
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return ''
  }
}

/** Format a conflict time range for display */
function formatConflictTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat('en-NZ', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ScheduleEntryModal({
  open,
  onClose,
  onSave,
  entry,
  defaultEntryType,
}: ScheduleEntryModalProps) {
  const isEdit = !!entry

  // Form fields
  const [staffId, setStaffId] = useState('')
  const [title, setTitle] = useState('')
  const [entryType, setEntryType] = useState('job')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [notes, setNotes] = useState('')
  const [recurrence, setRecurrence] = useState('none')

  // Staff options for dropdown
  const [staffOptions, setStaffOptions] = useState<StaffOption[]>([])
  const [loadingStaff, setLoadingStaff] = useState(false)

  // Shift templates
  const [templates, setTemplates] = useState<ShiftTemplate[]>([])

  // Form state
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Conflict warning after save
  const [conflicts, setConflicts] = useState<ConflictItem[]>([])
  const [showConflictWarning, setShowConflictWarning] = useState(false)

  /* ---------------------------------------------------------------- */
  /*  Fetch staff options                                              */
  /* ---------------------------------------------------------------- */

  const fetchStaff = useCallback(async (signal: AbortSignal) => {
    setLoadingStaff(true)
    try {
      const res = await apiClient.get<{ staff: StaffOption[] }>('/api/v2/staff', {
        params: { is_active: true, page_size: 100 },
        signal,
      })
      setStaffOptions(res.data?.staff ?? [])
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setStaffOptions([])
      }
    } finally {
      setLoadingStaff(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    fetchStaff(controller.signal)
    // Fetch shift templates
    const fetchTemplates = async () => {
      try {
        const res = await apiClient.get<{ templates: ShiftTemplate[] }>(
          '/api/v2/schedule/templates',
          { signal: controller.signal },
        )
        setTemplates(res.data?.templates ?? [])
      } catch (err: unknown) {
        if (!(err instanceof Error && err.name === 'CanceledError')) {
          setTemplates([])
        }
      }
    }
    fetchTemplates()
    return () => controller.abort()
  }, [open, fetchStaff])

  /* ---------------------------------------------------------------- */
  /*  Populate form when entry changes (edit mode)                     */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    if (open && entry) {
      setStaffId(entry.staff_id ?? '')
      setTitle(entry.title ?? '')
      setEntryType(entry.entry_type ?? 'job')
      setStartTime(toDatetimeLocal(entry.start_time))
      setEndTime(toDatetimeLocal(entry.end_time))
      setNotes(entry.description ?? '')
      setRecurrence('none') // Recurrence not editable on existing entries
    } else if (open && !entry) {
      // Reset for create mode
      setStaffId('')
      setTitle('')
      setEntryType(defaultEntryType ?? 'job')
      setStartTime('')
      setEndTime('')
      setNotes('')
      setRecurrence('none')
    }
    // Reset state when opening
    if (open) {
      setErrors({})
      setConflicts([])
      setShowConflictWarning(false)
    }
  }, [open, entry])

  /* ---------------------------------------------------------------- */
  /*  Validation                                                       */
  /* ---------------------------------------------------------------- */

  const validate = (): boolean => {
    const errs: Record<string, string> = {}

    if (!startTime) errs.start_time = 'Start time is required'
    if (!endTime) errs.end_time = 'End time is required'

    if (startTime && endTime) {
      const s = new Date(startTime)
      const e = new Date(endTime)
      if (e <= s) errs.end_time = 'End time must be after start time'
    }

    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  /* ---------------------------------------------------------------- */
  /*  Submit                                                           */
  /* ---------------------------------------------------------------- */

  const handleSubmit = async () => {
    if (!validate()) return

    setSubmitting(true)
    setErrors({})

    try {
      const payload = {
        staff_id: staffId || null,
        title: title.trim() || null,
        entry_type: entryType,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
        notes: notes.trim() || null,
        description: notes.trim() || null,
        ...(isEdit ? {} : { recurrence }),
      }

      let savedEntryId: string

      if (isEdit && entry) {
        // Edit mode — PUT /api/v2/schedule/{id}
        const res = await apiClient.put<{ id: string }>(
          `/api/v2/schedule/${entry.id}`,
          payload,
        )
        savedEntryId = res.data?.id ?? entry.id
      } else {
        // Create mode — POST /api/v2/schedule
        const res = await apiClient.post<{ id: string }>(
          '/api/v2/schedule',
          payload,
        )
        savedEntryId = res.data?.id ?? ''
      }

      // Check for conflicts after save (Req 36.6)
      if (savedEntryId) {
        try {
          const conflictRes = await apiClient.get<{
            has_conflicts: boolean
            conflicts: ConflictItem[]
          }>(`/api/v2/schedule/${savedEntryId}/conflicts`)

          if (conflictRes.data?.has_conflicts) {
            setConflicts(conflictRes.data?.conflicts ?? [])
            setShowConflictWarning(true)
            // Notify parent to refresh even though we show a warning
            onSave()
            return // Keep modal open to show conflict warning
          }
        } catch {
          // Conflict check failed — not critical, proceed normally
        }
      }

      onSave()
      onClose()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to save schedule entry. Please try again.'
      setErrors({ submit: detail })
    } finally {
      setSubmitting(false)
    }
  }

  /* ---------------------------------------------------------------- */
  /*  Dismiss conflict warning and close                               */
  /* ---------------------------------------------------------------- */

  const handleDismissConflicts = () => {
    setShowConflictWarning(false)
    setConflicts([])
    onClose()
  }

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <Modal
      open={open}
      onClose={showConflictWarning ? handleDismissConflicts : onClose}
      title={isEdit ? 'Edit Schedule Entry' : 'New Schedule Entry'}
      className="max-w-md"
    >
      {/* Conflict warning banner */}
      {showConflictWarning && conflicts.length > 0 && (
        <div className="mb-4 rounded border border-amber-300 bg-amber-50 p-3">
          <p className="text-sm font-medium text-amber-800">
            ⚠ Scheduling conflict detected
          </p>
          <ul className="mt-1 space-y-1">
            {conflicts.map((c) => (
              <li key={c.entry_id} className="text-xs text-amber-700">
                {c.title ?? c.entry_type} — {formatConflictTime(c.start_time)} to{' '}
                {formatConflictTime(c.end_time)}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-amber-600">
            The entry was saved, but it overlaps with existing entries.
          </p>
          <button
            onClick={handleDismissConflicts}
            className="mt-2 rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500"
          >
            OK, close
          </button>
        </div>
      )}

      {/* Form */}
      {!showConflictWarning && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            handleSubmit()
          }}
          className="space-y-4"
        >
          {/* Staff member dropdown */}
          <div>
            <label htmlFor="se-staff" className="block text-sm font-medium text-gray-700">
              Staff Member
            </label>
            <select
              id="se-staff"
              value={staffId}
              onChange={(e) => setStaffId(e.target.value)}
              disabled={loadingStaff}
              className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">— Select staff —</option>
              {staffOptions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.position ? ` — ${s.position}` : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Use Template dropdown (create mode only) */}
          {!isEdit && templates.length > 0 && (
            <div>
              <label htmlFor="se-template" className="block text-sm font-medium text-gray-700">
                Use Template
              </label>
              <select
                id="se-template"
                defaultValue=""
                onChange={(e) => {
                  const tpl = templates.find((t) => t.id === e.target.value)
                  if (tpl) {
                    setTitle(tpl.name)
                    setEntryType(tpl.entry_type)
                    // Pre-fill start/end times using today's date + template times
                    const today = new Date()
                    const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
                    setStartTime(`${dateStr}T${tpl.start_time}`)
                    setEndTime(`${dateStr}T${tpl.end_time}`)
                  }
                }}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">— Select template —</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.start_time}–{t.end_time})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Title */}
          <div>
            <label htmlFor="se-title" className="block text-sm font-medium text-gray-700">
              Title
            </label>
            <input
              id="se-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Oil change — Toyota Hilux"
              className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* Entry type */}
          <div>
            <label htmlFor="se-type" className="block text-sm font-medium text-gray-700">
              Entry Type
            </label>
            <select
              id="se-type"
              value={entryType}
              onChange={(e) => setEntryType(e.target.value)}
              className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {ENTRY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* Repeat / Recurrence (create mode only) */}
          {!isEdit && (
            <div>
              <label htmlFor="se-recurrence" className="block text-sm font-medium text-gray-700">
                Repeat
              </label>
              <select
                id="se-recurrence"
                value={recurrence}
                onChange={(e) => setRecurrence(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {RECURRENCE_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
              {recurrence !== 'none' && (
                <p className="mt-1 text-xs text-gray-500">
                  Entries will be created for up to 4 weeks ahead.
                </p>
              )}
            </div>
          )}

          {/* Start time */}
          <div>
            <label htmlFor="se-start" className="block text-sm font-medium text-gray-700">
              Start Time
            </label>
            <input
              id="se-start"
              type="datetime-local"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className={`mt-1 block w-full rounded border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 ${
                errors.start_time
                  ? 'border-red-400 focus:border-red-500 focus:ring-red-500'
                  : 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
              }`}
            />
            {errors.start_time && (
              <p className="mt-1 text-xs text-red-600">{errors.start_time}</p>
            )}
          </div>

          {/* End time */}
          <div>
            <label htmlFor="se-end" className="block text-sm font-medium text-gray-700">
              End Time
            </label>
            <input
              id="se-end"
              type="datetime-local"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className={`mt-1 block w-full rounded border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 ${
                errors.end_time
                  ? 'border-red-400 focus:border-red-500 focus:ring-red-500'
                  : 'border-gray-300 focus:border-blue-500 focus:ring-blue-500'
              }`}
            />
            {errors.end_time && (
              <p className="mt-1 text-xs text-red-600">{errors.end_time}</p>
            )}
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="se-notes" className="block text-sm font-medium text-gray-700">
              Notes
            </label>
            <textarea
              id="se-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Optional notes…"
              className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* Submit error */}
          {errors.submit && (
            <div className="rounded border border-red-300 bg-red-50 p-2">
              <p className="text-sm text-red-700">{errors.submit}</p>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {submitting ? 'Saving…' : isEdit ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
