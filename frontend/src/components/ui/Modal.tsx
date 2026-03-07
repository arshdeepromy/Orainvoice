import { useEffect, useRef, useCallback } from 'react'
import { trapFocus } from '../../utils/accessibility'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  className?: string
}

export function Modal({ open, onClose, title, children, className = '' }: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    },
    [onClose],
  )

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement
      dialog.showModal()
      document.addEventListener('keydown', handleKeyDown)
      // Trap focus within the modal
      const releaseTrap = trapFocus(dialog)
      return () => {
        document.removeEventListener('keydown', handleKeyDown)
        releaseTrap()
      }
    } else {
      dialog.close()
      previousFocusRef.current?.focus()
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <dialog
      ref={dialogRef}
      className={`rounded-lg bg-white p-0 shadow-xl backdrop:bg-black/50
        max-w-lg w-full max-h-[85vh] overflow-auto ${className}`}
      aria-labelledby="modal-title"
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose()
      }}
    >
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 id="modal-title" className="text-lg font-semibold text-gray-900">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:text-gray-600
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Close dialog"
          >
            <span aria-hidden="true" className="text-xl leading-none">×</span>
          </button>
        </div>
        {children}
      </div>
    </dialog>
  )
}
