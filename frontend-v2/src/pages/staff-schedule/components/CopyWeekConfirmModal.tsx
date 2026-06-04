/**
 * CopyWeekConfirmModal — confirmation dialog for "Copy Week 1 → Week
 * 2" (Workstream B / task B11, R8.2).
 *
 * Logic copied verbatim from
 * frontend/src/pages/staff-schedule/components/CopyWeekConfirmModal.tsx;
 * presentation remapped onto the design-system tokens.
 */

import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'

export interface CopyWeekConfirmModalProps {
  open: boolean
  sourceCount: number
  targetCount: number
  onConfirm: (overwrite: boolean) => void
  onClose: () => void
}

export default function CopyWeekConfirmModal({
  open,
  sourceCount,
  targetCount,
  onConfirm,
  onClose,
}: CopyWeekConfirmModalProps) {
  const [overwrite, setOverwrite] = useState(false)
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Copy Week 1 → Week 2"
      className="max-w-md"
    >
      <div className="space-y-4 text-sm text-text">
        <p>
          You are about to copy <strong>{sourceCount}</strong> source
          entries from Week 1 into Week 2.
        </p>
        {targetCount > 0 && (
          <p className="rounded-ctl border border-warn/40 bg-warn-soft p-3 text-warn">
            Week 2 already contains <strong>{targetCount}</strong>{' '}
            entr{targetCount === 1 ? 'y' : 'ies'}.
          </p>
        )}
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
          />
          <span>Overwrite existing entries in Week 2</span>
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas hover:border-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(overwrite)}
            className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Copy week
          </button>
        </div>
      </div>
    </Modal>
  )
}
