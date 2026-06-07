/**
 * TemplatePalette — sidebar listing the org's shift templates
 * (Workstream B / task B8).
 *
 * Renders templates from `listTemplates()`. Selecting a template
 * lifts state up to the page; re-clicking the same template clears
 * it. Empty state links to /settings/shift-templates.
 *
 * Validates: R6.1, R6.2, R6.10.
 *
 * Logic copied verbatim from
 * frontend/src/pages/staff-schedule/components/TemplatePalette.tsx;
 * presentation remapped onto the design-system tokens.
 */

import { useEffect, useState } from 'react'
import { listTemplates } from '@/api/schedule'
import type { ShiftTemplateResponse } from '@/types/schedule'
import ShiftTemplateModal from '@/components/staff-schedule/ShiftTemplateModal'

export interface TemplatePaletteProps {
  selectedTemplate: ShiftTemplateResponse | null
  onSelect: (template: ShiftTemplateResponse | null) => void
  /** When true, palette controls are disabled (in-flight bulk submit). */
  disabled?: boolean
}

export default function TemplatePalette({
  selectedTemplate,
  onSelect,
  disabled,
}: TemplatePaletteProps) {
  const [templates, setTemplates] = useState<ShiftTemplateResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setIsLoading(true)
      try {
        const res = await listTemplates({ signal: controller.signal })
        const list = (res.templates ?? [])
          .slice()
          .sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
        setTemplates(list)
        setError(null)
      } catch (err: unknown) {
        const e = err as
          | { code?: string; name?: string; message?: string }
          | undefined
        const isAbort =
          controller.signal.aborted ||
          e?.code === 'ERR_CANCELED' ||
          e?.name === 'CanceledError' ||
          e?.name === 'AbortError'
        if (isAbort) return
        setError('Failed to load templates')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [reloadKey])

  return (
    <aside
      data-testid="template-palette"
      data-no-print
      className="w-56 shrink-0 border-r border-border bg-card p-3"
      aria-label="Shift template palette"
    >
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
        Shift templates
      </h2>
      {isLoading && (
        <p className="mt-3 text-xs text-muted-2">Loading…</p>
      )}
      {error && (
        <p className="mt-3 text-xs text-danger">{error}</p>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="mt-3 text-xs text-muted">
          <p>No shift templates.</p>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="mt-2 inline-block text-accent hover:underline"
          >
            Create one
          </button>
        </div>
      )}
      {!isLoading && !error && templates.length > 0 && (
        <ul className="mt-3 space-y-1">
          {templates.map((t) => {
            const isSelected = selectedTemplate?.id === t.id
            return (
              <li key={t.id}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  disabled={disabled}
                  onClick={() => onSelect(isSelected ? null : t)}
                  className={`w-full rounded-ctl border px-2 py-1.5 text-left text-xs ${
                    isSelected
                      ? 'border-accent bg-accent-soft text-accent'
                      : 'border-border bg-card text-text hover:bg-canvas'
                  } disabled:cursor-not-allowed disabled:opacity-60`}
                >
                  <div className="font-medium">{t.name}</div>
                  <div className="mono text-[11px] text-muted">
                    {t.start_time}–{t.end_time} · {t.entry_type}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {!isLoading && !error && templates.length > 0 && (
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          disabled={disabled}
          className="mt-3 w-full rounded-ctl border border-dashed border-border bg-card px-2 py-1.5 text-left text-xs text-accent hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-60"
        >
          + New template
        </button>
      )}
      <ShiftTemplateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => setReloadKey((k) => k + 1)}
      />
    </aside>
  )
}
