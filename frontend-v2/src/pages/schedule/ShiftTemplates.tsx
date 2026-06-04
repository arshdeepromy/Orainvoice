/**
 * Shift Templates management panel — create, view, and delete shift templates.
 *
 * Requirements: 57.1, 57.2, 57.3
 *
 * Logic copied verbatim from frontend/src/pages/schedule/ShiftTemplates.tsx;
 * presentation remapped onto the design-system tokens.
 */

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

interface ShiftTemplate {
  id: string
  name: string
  start_time: string
  end_time: string
  entry_type: string
  created_at: string
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

export default function ShiftTemplates() {
  const [templates, setTemplates] = useState<ShiftTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)

  // Form fields
  const [name, setName] = useState('')
  const [startTime, setStartTime] = useState('08:00')
  const [endTime, setEndTime] = useState('17:00')
  const [entryType, setEntryType] = useState('job')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ templates: ShiftTemplate[]; total: number }>(
        '/api/v2/schedule/templates',
      )
      setTemplates(res.data?.templates ?? [])
    } catch {
      setTemplates([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchTemplates()
    return () => controller.abort()
  }, [fetchTemplates])

  const handleCreate = async () => {
    if (!name.trim()) {
      setError('Name is required')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await apiClient.post('/api/v2/schedule/templates', {
        name: name.trim(),
        start_time: startTime,
        end_time: endTime,
        entry_type: entryType,
      })
      setName('')
      setStartTime('08:00')
      setEndTime('17:00')
      setEntryType('job')
      setShowForm(false)
      fetchTemplates()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to create template.'
      setError(detail)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/api/v2/schedule/templates/${id}`)
      fetchTemplates()
    } catch {
      // Silently fail — template may already be deleted
    }
  }

  return (
    <div className="rounded-card border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text">Shift Templates</h3>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-xs font-medium text-accent hover:text-accent-press"
        >
          {showForm ? 'Cancel' : '+ New Template'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="mb-4 space-y-2 border-b border-border pb-4">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Template name (e.g. Morning Shift)"
            className={fieldCls}
          />
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="mb-0.5 block text-xs text-muted">Start</label>
              <input
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                className={fieldCls}
              />
            </div>
            <div className="flex-1">
              <label className="mb-0.5 block text-xs text-muted">End</label>
              <input
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                className={fieldCls}
              />
            </div>
            <div className="flex-1">
              <label className="mb-0.5 block text-xs text-muted">Type</label>
              <select
                value={entryType}
                onChange={(e) => setEntryType(e.target.value)}
                className={fieldCls}
              >
                {ENTRY_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <button
            onClick={handleCreate}
            disabled={submitting}
            className="rounded-ctl bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-press disabled:opacity-50"
          >
            {submitting ? 'Saving…' : 'Save Template'}
          </button>
        </div>
      )}

      {/* Template list */}
      {loading ? (
        <p className="text-xs text-muted-2">Loading templates…</p>
      ) : templates.length === 0 ? (
        <p className="text-xs text-muted-2">No templates yet. Create one to speed up scheduling.</p>
      ) : (
        <ul className="space-y-1.5">
          {templates.map((t) => (
            <li
              key={t.id}
              className="flex items-center justify-between rounded-ctl bg-canvas px-2 py-1.5 text-sm"
            >
              <div>
                <span className="font-medium text-text">{t.name}</span>
                <span className="mono ml-2 text-xs text-muted">
                  {t.start_time}–{t.end_time} · {t.entry_type}
                </span>
              </div>
              <button
                onClick={() => handleDelete(t.id)}
                className="text-xs text-danger hover:brightness-110"
                aria-label={`Delete template ${t.name}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
