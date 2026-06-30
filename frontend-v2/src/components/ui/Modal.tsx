import { useEffect, useRef, useCallback } from 'react'
import type { ReactNode } from 'react'
import { cx } from './cx'

/**
 * Modal — accessible centred dialog primitive.
 *
 * Design-on-the-fly (FR-2b): the redesign prototype has no standalone "View
 * All" modal for the dashboard widgets, so this is built from scratch on the
 * design-system tokens. It mirrors the ORIGINAL
 * frontend/src/components/ui/Modal.tsx contract and behaviour 1:1 so the ported
 * widgets (RecentInvoicesWidget) drop in unchanged (FR-1):
 *   • Same props: { open, onClose, title, children, className }.
 *   • Modals close ONLY via explicit Cancel / Save / × buttons — clicking the
 *     backdrop and pressing Escape are intentionally suppressed (matching the
 *     original's native <dialog> cancel/backdrop suppression).
 *   • Focus is moved into the dialog on open and restored to the previously
 *     focused element on close; a focus trap keeps Tab within the dialog.
 *
 * Presentation uses the prototype's surface language: shadow-pop card, the
 * `.card-head` header row (bottom border, 15px/600 title), an `.icon-btn`-style
 * close button, and an ink/50 scrim.
 */

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  className?: string
  /**
   * Optional override for the scrollable body wrapper. Defaults to the standard
   * padded, vertically-scrolling body. Pass a full-height flex layout (e.g.
   * `flex min-h-0 flex-1 ... overflow-hidden`) when the content manages its own
   * internal scroll regions (such as the field-placement editor).
   */
  bodyClassName?: string
}

/** Keep Tab focus cycling within `container`; returns a cleanup function. */
function trapFocus(container: HTMLElement): () => void {
  const SELECTOR =
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key !== 'Tab') return
    const focusable = Array.from(container.querySelectorAll<HTMLElement>(SELECTOR)).filter(
      (el) => el.offsetParent !== null,
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  container.addEventListener('keydown', handleKeyDown)
  return () => container.removeEventListener('keydown', handleKeyDown)
}

export function Modal({ open, onClose, title, children, className = '', bodyClassName = '' }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      // Modals should only close via explicit Cancel / Save / × buttons.
      e.preventDefault()
    }
  }, [])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!open || !dialog) return

    previousFocusRef.current = document.activeElement as HTMLElement
    document.addEventListener('keydown', handleKeyDown)
    dialog.focus()
    const releaseTrap = trapFocus(dialog)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      releaseTrap()
      previousFocusRef.current?.focus()
    }
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 px-4 py-[5vh]"
      onClick={(e) => {
        // Suppress backdrop-click close (matches the original).
        e.stopPropagation()
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className={cx(
          'flex max-h-[90vh] w-full flex-col overflow-hidden rounded-card bg-card shadow-pop outline-none',
          className || 'max-w-lg',
        )}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-card px-6 py-4">
          <h2 id="modal-title" className="text-[15px] font-semibold text-text">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="rounded-ctl p-1 text-muted-2 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Close dialog"
          >
            <span aria-hidden="true" className="text-xl leading-none">×</span>
          </button>
        </div>
        <div className={bodyClassName || 'overflow-y-auto px-6 py-4'}>{children}</div>
      </div>
    </div>
  )
}

export default Modal
