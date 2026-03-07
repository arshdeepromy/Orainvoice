import { useEffect, useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

export interface ShortcutConfig {
  /** Callback for Ctrl/Cmd+S (save draft). If omitted, shortcut is a no-op. */
  onSave?: () => void
  /** Override default Ctrl/Cmd+N navigation target. Defaults to '/invoices/new'. */
  newInvoicePath?: string
  /** Additional custom shortcuts. Key = lowercase letter, handler receives the event. */
  custom?: Record<string, (e: KeyboardEvent) => void>
  /** Disable all shortcuts (e.g. when another modal is open). */
  disabled?: boolean
}

export interface ShortcutEntry {
  keys: string
  label: string
}

/** Canonical list of global shortcuts for the reference modal. */
export const SHORTCUT_LIST: ShortcutEntry[] = [
  { keys: 'Ctrl/⌘ + N', label: 'New invoice' },
  { keys: 'Ctrl/⌘ + K', label: 'Search' },
  { keys: 'Ctrl/⌘ + S', label: 'Save draft' },
  { keys: 'Ctrl/⌘ + /', label: 'Shortcut reference' },
]

/**
 * Global keyboard shortcut handler.
 *
 * Registers:
 *  - Ctrl/Cmd+N → navigate to new invoice
 *  - Ctrl/Cmd+K → search (handled by GlobalSearchBar — not intercepted here)
 *  - Ctrl/Cmd+S → save draft callback
 *  - Ctrl/Cmd+/ → toggle shortcut reference modal
 *
 * Returns `{ referenceOpen, setReferenceOpen }` so the caller can render
 * the ShortcutReference modal.
 */
export function useKeyboardShortcuts(config: ShortcutConfig = {}) {
  const { onSave, newInvoicePath = '/invoices/new', custom, disabled } = config
  const navigate = useNavigate()
  const [referenceOpen, setReferenceOpen] = useState(false)

  // Keep callbacks in refs so the listener always sees latest values
  const onSaveRef = useRef(onSave)
  onSaveRef.current = onSave

  const customRef = useRef(custom)
  customRef.current = custom

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (disabled) return

      const mod = e.metaKey || e.ctrlKey
      if (!mod) return

      switch (e.key.toLowerCase()) {
        case 'n':
          e.preventDefault()
          navigate(newInvoicePath)
          break

        case 'k':
          // Handled by GlobalSearchBar — we intentionally skip preventDefault
          // so the existing handler in GlobalSearchBar picks it up.
          break

        case 's':
          e.preventDefault()
          onSaveRef.current?.()
          break

        case '/':
          e.preventDefault()
          setReferenceOpen((prev) => !prev)
          break

        default: {
          const handler = customRef.current?.[e.key.toLowerCase()]
          if (handler) {
            e.preventDefault()
            handler(e)
          }
        }
      }
    },
    [disabled, navigate, newInvoicePath, setReferenceOpen],
  )

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  return { referenceOpen, setReferenceOpen } as const
}
