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
        // Prevent native dialog close on Escape — modals should only
        // close via explicit Cancel / Save / X buttons.
        e.preventDefault()
      }
    },
    [],
  )

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    // Prevent native dialog cancel (Escape key) from closing the modal
    const handleCancel = (e: Event) => { e.preventDefault() }

    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement
      dialog.showModal()
      dialog.addEventListener('cancel', handleCancel)
      document.addEventListener('keydown', handleKeyDown)
      // Trap focus within the modal
      const releaseTrap = trapFocus(dialog)
      return () => {
        dialog.removeEventListener('cancel', handleCancel)
        document.removeEventListener('keydown', handleKeyDown)
        releaseTrap()
      }
    } else {
      dialog.close()
      previousFocusRef.current?.focus()
    }

    return () => {
      dialog.removeEventListener('cancel', handleCancel)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <dialog
      ref={dialogRef}
      className={`fixed top-[5vh] left-1/2 -translate-x-1/2 bg-white p-0 shadow-2xl backdrop:bg-black/50 backdrop:backdrop-blur-sm
        w-full max-h-[90vh] overflow-hidden animate-fadeIn ${className || 'max-w-lg'}`}
      style={{ borderRadius: 'var(--modal-radius)', boxShadow: 'var(--modal-shadow)' }}
      aria-labelledby="modal-title"
      onClick={(e) => {
        // Prevent closing when clicking the backdrop — modals should only
        // close via explicit Cancel / Save / X buttons.
        e.stopPropagation()
      }}
    >
      <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-white">
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
      <div className="px-6 py-4 overflow-y-auto max-h-[calc(90vh-72px)] bg-white">
        {children}
      </div>
    </dialog>
  )
}
