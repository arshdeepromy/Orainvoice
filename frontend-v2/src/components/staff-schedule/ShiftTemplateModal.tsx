/**
 * ShiftTemplateModal — small create-template dialog used from the
 * staff-schedule TemplatePalette empty state and the standalone Shift
 * Templates settings page.
 *
 * Posts to `/api/v2/schedule/templates`. On success calls `onCreated()` so
 * the caller can refresh its list.
 */

import { useEffect, useRef, useState } from 'react'
import apiClient from '@/api/client'
import { Modal } from '@/components/ui'

interface ShiftTemplateModalProps {
  open: boolean
  onClose: () => void
  onCreated?: () => void
}

const ENTRY_TYPES = [
  { value: 'job', label: 'Job' },
  { value: 'booking', label: 'Booking' },
  { value: 'break', label: 'Break' },
  { value: 'leave', label: 'Leave' },
  { value: 'other', label: 'Other' },
] as const

const fieldCls =
  'block w-full rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

export default function ShiftTemplateModal({
  open,
  onClose,
  onCreated,
}: ShiftTemplateModalProps) {
  const [name, setName] = useState('')
  const [startTime, setStartTime] = useState('08:00')
  const [endTime, setEndTime] = useState('17:00')
  const [entryType, setEntryType] = useState<string>('job')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const submittingRef = useRef(false)

  // Reset form whenever the modal opens.
  useEffect(() => {
    if (open) {
      setName('')
      setStartTime('08:00')
      setEndTime('17:00')
      setEntryType('job')
      setError('')
      setSubmitting(false)
      submittingRef.current = false
    }
  }, [open])

  const handleSave = async () => {
    if (submittingRef.current) return
    if (!name.trim()) {
      setError('Name is required')
      return
    }
    submittingRef.current = true
    setSubmitting(true)
    setError('')
    try {
      await apiClient.post('/api/v2/schedule/templates', {
        name: name.trim(),
        start_time: startTime,
        end_time: endTime,
        entry_type: entryType,
      })
      onCreated?.()
      onClose()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to create template.'
      setError(detail)
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const handleCancel = () => {
    if (submittingRef.current) return
    onClose()
  }

  return (
    <Modal open={open} onClose={handleCancel} title="New Shift Template">
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs text-muted">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Morning Shift"
            className={fieldCls}
            autoFocus
          />
        </div>
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-muted">Start</label>
            <input
              type="time"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className={fieldCls}
            />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-xs text-muted">End</label>
            <input
              type="time"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className={fieldCls}
            />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-xs text-muted">Type</label>
            <select
              value={entryType}
              onChange={(e) => setEntryType(e.target.value)}
              className={fieldCls}
            >
              {ENTRY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {error && (
          <p className="text-xs text-danger" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={handleCancel}
          disabled={submitting}
          className="rounded-ctl border border-border bg-card px-3 py-1.5 text-xs font-medium text-text hover:bg-canvas disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={submitting}
          className="rounded-ctl bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-press disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Save Template'}
        </button>
      </div>
    </Modal>
  )
}
