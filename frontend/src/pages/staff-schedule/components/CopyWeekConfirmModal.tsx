/**
 * CopyWeekConfirmModal — confirmation dialog for "Copy Week 1 → Week
 * 2" (Workstream B / task B11, R8.2).
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
      <div className="space-y-4 text-sm text-gray-700">
        <p>
          You are about to copy <strong>{sourceCount}</strong> source
          entries from Week 1 into Week 2.
        </p>
        {targetCount > 0 && (
          <p className="rounded border border-amber-300 bg-amber-50 p-3 text-amber-800">
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
            className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(overwrite)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Copy week
          </button>
        </div>
      </div>
    </Modal>
  )
}
