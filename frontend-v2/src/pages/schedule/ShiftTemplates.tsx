/**
 * Shift Templates management panel — list and delete shift templates.
 * Creation happens via `ShiftTemplateModal`.
 *
 * Mounted both standalone at `/settings/shift-templates` (see App.tsx) and
 * inline inside `ScheduleCalendar` when the "Templates" toggle is on.
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import ShiftTemplateModal from '@/components/staff-schedule/ShiftTemplateModal'

interface ShiftTemplate {
  id: string
  name: string
  start_time: string
  end_time: string
  entry_type: string
  created_at: string
}

export default function ShiftTemplates() {
  const [templates, setTemplates] = useState<ShiftTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)

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
    fetchTemplates()
  }, [fetchTemplates])

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
          type="button"
          onClick={() => setCreateOpen(true)}
          className="text-xs font-medium text-accent hover:text-accent-press"
        >
          + New Template
        </button>
      </div>

      {loading ? (
        <p className="text-xs text-muted-2">Loading templates…</p>
      ) : templates.length === 0 ? (
        <p className="text-xs text-muted-2">
          No templates yet. Create one to speed up scheduling.
        </p>
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
                type="button"
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

      <ShiftTemplateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={fetchTemplates}
      />
    </div>
  )
}
