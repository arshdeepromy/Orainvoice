import { Modal } from './Modal'
import { SHORTCUT_LIST } from '../../hooks/useKeyboardShortcuts'

interface ShortcutReferenceProps {
  open: boolean
  onClose: () => void
}

/** Modal listing all available keyboard shortcuts. Triggered by Ctrl/Cmd+/. */
export function ShortcutReference({ open, onClose }: ShortcutReferenceProps) {
  return (
    <Modal open={open} onClose={onClose} title="Keyboard Shortcuts">
      <table className="w-full text-sm" role="grid" aria-label="Keyboard shortcuts">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="pb-2 font-medium">Shortcut</th>
            <th className="pb-2 font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {SHORTCUT_LIST.map((s) => (
            <tr key={s.keys} className="border-b last:border-0">
              <td className="py-2 pr-4">
                <kbd
                  className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700"
                >
                  {s.keys}
                </kbd>
              </td>
              <td className="py-2 text-gray-700">{s.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-4 text-xs text-gray-400">
        Press <kbd className="rounded bg-gray-100 px-1 font-mono text-xs">Esc</kbd> to close
      </p>
    </Modal>
  )
}
