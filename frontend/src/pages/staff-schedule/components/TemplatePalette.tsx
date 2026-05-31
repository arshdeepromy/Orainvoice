/**
 * TemplatePalette — sidebar listing the org's shift templates
 * (Workstream B / task B8).
 *
 * Renders templates from `listTemplates()`. Selecting a template
 * lifts state up to the page; re-clicking the same template clears
 * it. Empty state links to /settings/shift-templates.
 *
 * Validates: R6.1, R6.2, R6.10.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listTemplates } from '@/api/schedule'
import type { ShiftTemplateResponse } from '@/types/schedule'

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
  }, [])

  return (
    <aside
      data-testid="template-palette"
      data-no-print
      className="w-56 shrink-0 border-r border-gray-200 bg-white p-3"
      aria-label="Shift template palette"
    >
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        Shift templates
      </h2>
      {isLoading && (
        <p className="mt-3 text-xs text-gray-400">Loading…</p>
      )}
      {error && (
        <p className="mt-3 text-xs text-red-600">{error}</p>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="mt-3 text-xs text-gray-500">
          <p>No shift templates.</p>
          <Link
            to="/settings/shift-templates"
            className="mt-2 inline-block text-blue-600 hover:underline"
          >
            Create one in Settings
          </Link>
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
                  className={`w-full rounded border px-2 py-1.5 text-left text-xs ${
                    isSelected
                      ? 'border-blue-500 bg-blue-50 text-blue-800'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  } disabled:cursor-not-allowed disabled:opacity-60`}
                >
                  <div className="font-medium">{t.name}</div>
                  <div className="text-[11px] text-gray-500">
                    {t.start_time}–{t.end_time} · {t.entry_type}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}
