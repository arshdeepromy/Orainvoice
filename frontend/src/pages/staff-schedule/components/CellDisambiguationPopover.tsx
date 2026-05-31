/**
 * CellDisambiguationPopover — small popover that lists every entry
 * in a multi-entry grid cell so the user can pick one to edit
 * (Workstream B / task B6, R4.3).
 *
 * The component is positionless — the parent picks where to render
 * it. Uses a fixed-position container with a backdrop click-handler
 * so the user can dismiss it by clicking outside.
 */

import { useEffect, useRef } from 'react'
import type { ScheduleEntryResponse } from '@/types/schedule'

function formatTimeRange(entry: ScheduleEntryResponse): string {
  const fmt = (iso: string) => {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    const h = String(d.getHours()).padStart(2, '0')
    const m = String(d.getMinutes()).padStart(2, '0')
    return `${h}:${m}`
  }
  return `${fmt(entry.start_time)}-${fmt(entry.end_time)}`
}

export interface CellDisambiguationPopoverProps {
  entries: ScheduleEntryResponse[]
  onPick: (entry: ScheduleEntryResponse) => void
  onClose: () => void
  /** Optional anchor coordinates in viewport pixels. */
  anchor?: { x: number; y: number }
}

export default function CellDisambiguationPopover({
  entries,
  onPick,
  onClose,
  anchor,
}: CellDisambiguationPopoverProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Click-outside dismiss.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!ref.current) return
      if (e.target instanceof Node && !ref.current.contains(e.target)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [onClose])

  const style: React.CSSProperties = anchor
    ? { position: 'fixed', top: anchor.y, left: anchor.x, zIndex: 50 }
    : { position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', zIndex: 50 }

  return (
    <div
      ref={ref}
      role="menu"
      data-testid="cell-disambiguation-popover"
      style={style}
      className="rounded-lg border border-gray-300 bg-white shadow-lg p-1 min-w-[220px]"
    >
      <ul className="max-h-64 overflow-auto">
        {entries.map((e) => (
          <li key={e.id}>
            <button
              type="button"
              role="menuitem"
              onClick={() => onPick(e)}
              className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-blue-50 focus:bg-blue-50 focus:outline-none"
            >
              <span className="font-medium">{e.title ?? e.entry_type}</span>{' '}
              <span className="text-gray-500 text-xs">
                {formatTimeRange(e)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
