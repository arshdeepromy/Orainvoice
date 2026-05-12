/**
 * EditorToolbar — top bar for the visual page editor.
 *
 * Presentational component rendered above the Puck editor in
 * `PageEditorEdit.tsx`. All network calls are delegated to handler
 * props provided by the caller — this component owns only the publish
 * confirmation modal's local state and the relative-time ticker for
 * the "Published v{N}" badge.
 *
 * Layout:
 *   ┌───────────────────────────────────────────────────────────────┐
 *   │  Title  [State badge]           [Save Draft] [Preview]        │
 *   │                                 [Publish]    [⚙]  [🕐]        │
 *   └───────────────────────────────────────────────────────────────┘
 *
 * Behavior:
 *   - Save Draft — disabled when `!isDirty`; shows "Saving…" with a
 *     spinner while `isSaving`; shows a transient "Saved" confirmation
 *     for 2s after isDirty flips false (caller clears the dirty flag
 *     on success).
 *   - Preview — delegates to `onPreview()`. The caller is responsible
 *     for POSTing to the preview endpoint and opening the tokenised
 *     URL in a new tab.
 *   - Publish — opens the inline PublishConfirmModal. Submitting the
 *     modal calls `onPublish(note)` then closes the modal on success.
 *     Errors bubble up to the caller to surface via a toast.
 *   - Settings / History — plain icon buttons delegating to their
 *     respective drawer-open callbacks.
 *
 * Requirements: 3.5, 3.6, 4.1, 4.2, 4.5
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge, Button } from '../../../components/ui'

/* --------------------------------------------------------------------
 * Types
 * ------------------------------------------------------------------ */

type PublishState = 'never-published' | 'published' | 'draft-ahead'

export interface EditorToolbarPageDetail {
  page_key: string
  title: string
  publish_state: PublishState
  published_version: number | null
  published_at: string | null
}

export interface EditorToolbarProps {
  pageDetail: EditorToolbarPageDetail
  isDirty: boolean
  isSaving: boolean
  onSaveDraft: () => Promise<void>
  onPreview: () => Promise<void>
  onPublish: (note?: string) => Promise<void>
  onOpenSettings: () => void
  onOpenHistory: () => void
}

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

/**
 * Format an ISO timestamp as a human-readable relative time
 * ("just now", "5m ago", "3h ago", "2d ago") or fall back to a
 * localized date for older timestamps.
 */
function formatRelative(iso: string | null | undefined): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diffSec = Math.floor((Date.now() - then) / 1000)
  if (diffSec < 0) return 'just now'
  if (diffSec < 60) return 'just now'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`
  return new Date(iso).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/* --------------------------------------------------------------------
 * Inline PublishConfirmModal
 *
 * Small, tightly coupled to this toolbar — kept inline per the task
 * brief rather than promoted to its own file.
 * ------------------------------------------------------------------ */

interface PublishConfirmModalProps {
  open: boolean
  publishing: boolean
  error: string | null
  onCancel: () => void
  onConfirm: (note?: string) => Promise<void> | void
}

function PublishConfirmModal({
  open,
  publishing,
  error,
  onCancel,
  onConfirm,
}: PublishConfirmModalProps) {
  const [note, setNote] = useState('')
  const dialogRef = useRef<HTMLDialogElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  // Open/close the native <dialog> in sync with `open`.
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    // Prevent the backdrop Escape cancel flow — explicit buttons only.
    const handleCancel = (e: Event) => {
      e.preventDefault()
    }

    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement
      if (!dialog.open) dialog.showModal()
      dialog.addEventListener('cancel', handleCancel)
      return () => {
        dialog.removeEventListener('cancel', handleCancel)
      }
    }

    if (dialog.open) dialog.close()
    previousFocusRef.current?.focus()
    return () => {
      dialog.removeEventListener('cancel', handleCancel)
    }
  }, [open])

  // Reset the note field whenever the modal opens.
  useEffect(() => {
    if (open) setNote('')
  }, [open])

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (publishing) return
      const trimmed = note.trim()
      await onConfirm(trimmed || undefined)
    },
    [note, publishing, onConfirm],
  )

  if (!open) return null

  return (
    <dialog
      ref={dialogRef}
      className="fixed top-[10vh] left-1/2 w-full max-w-md -translate-x-1/2 bg-white p-0 shadow-2xl
        backdrop:bg-black/50 backdrop:backdrop-blur-sm
        max-h-[85vh] overflow-hidden animate-fadeIn"
      style={{ borderRadius: 'var(--modal-radius)', boxShadow: 'var(--modal-shadow)' }}
      aria-labelledby="publish-confirm-title"
      onClick={(e) => e.stopPropagation()}
    >
      <form onSubmit={handleSubmit}>
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <h2
            id="publish-confirm-title"
            className="text-lg font-semibold text-gray-900"
          >
            Publish this page?
          </h2>
          <button
            type="button"
            onClick={onCancel}
            disabled={publishing}
            className="rounded p-1 text-gray-400 hover:text-gray-600 disabled:opacity-50
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Close dialog"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </div>
        <div className="space-y-4 px-5 py-4">
          <p className="text-sm text-gray-700">
            It will be live immediately.
          </p>
          <div className="flex flex-col gap-1">
            <label
              htmlFor="publish-note"
              className="text-sm font-medium text-gray-700"
            >
              Note <span className="text-gray-400">(optional)</span>
            </label>
            <textarea
              id="publish-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What changed? Recorded in the revision history."
              maxLength={500}
              rows={3}
              disabled={publishing}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
                transition-colors placeholder:text-gray-400 disabled:bg-gray-50 disabled:text-gray-500
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
            <p className="text-xs text-gray-500">{note.length}/500</p>
          </div>
          {error && (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
              role="alert"
            >
              {error}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
          <Button
            type="button"
            variant="secondary"
            onClick={onCancel}
            disabled={publishing}
          >
            Cancel
          </Button>
          <Button type="submit" loading={publishing} disabled={publishing}>
            Publish Now
          </Button>
        </div>
      </form>
    </dialog>
  )
}

/* --------------------------------------------------------------------
 * Main component
 * ------------------------------------------------------------------ */

export function EditorToolbar({
  pageDetail,
  isDirty,
  isSaving,
  onSaveDraft,
  onPreview,
  onPublish,
  onOpenSettings,
  onOpenHistory,
}: EditorToolbarProps) {
  /* Local state -------------------------------------------------- */
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState<string | null>(null)

  const [previewing, setPreviewing] = useState(false)
  const [showSaved, setShowSaved] = useState(false)

  /**
   * Refresh the "Published v2 · 5m ago" relative timestamp every 30s
   * so it stays accurate while an admin has the editor open.
   */
  const [, setTick] = useState(0)
  useEffect(() => {
    if (pageDetail.publish_state !== 'published') return
    const id = setInterval(() => setTick((n) => n + 1), 30000)
    return () => clearInterval(id)
  }, [pageDetail.publish_state])

  /**
   * Transient "Saved" confirmation — fires whenever isDirty flips from
   * true to false while no save is in flight. Cleared after 2 seconds.
   */
  const prevDirtyRef = useRef(isDirty)
  useEffect(() => {
    if (prevDirtyRef.current && !isDirty && !isSaving) {
      setShowSaved(true)
      const id = setTimeout(() => setShowSaved(false), 2000)
      return () => clearTimeout(id)
    }
    prevDirtyRef.current = isDirty
  }, [isDirty, isSaving])

  /* Handlers ----------------------------------------------------- */

  const handleSaveDraft = useCallback(async () => {
    if (isSaving || !isDirty) return
    try {
      await onSaveDraft()
    } catch {
      // Caller surfaces the error via a toast; nothing to do here.
    }
  }, [isSaving, isDirty, onSaveDraft])

  const handlePreview = useCallback(async () => {
    if (previewing) return
    setPreviewing(true)
    try {
      await onPreview()
    } catch {
      // Caller handles error surfacing.
    } finally {
      setPreviewing(false)
    }
  }, [previewing, onPreview])

  const openPublishModal = useCallback(() => {
    setPublishError(null)
    setPublishOpen(true)
  }, [])

  const closePublishModal = useCallback(() => {
    if (publishing) return
    setPublishOpen(false)
    setPublishError(null)
  }, [publishing])

  const handleConfirmPublish = useCallback(
    async (note?: string) => {
      if (publishing) return
      setPublishing(true)
      setPublishError(null)
      try {
        await onPublish(note)
        setPublishOpen(false)
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } }; message?: string })
            ?.response?.data?.detail ??
          (err as { message?: string })?.message ??
          'Failed to publish. Please try again.'
        setPublishError(typeof message === 'string' ? message : 'Failed to publish.')
      } finally {
        setPublishing(false)
      }
    },
    [publishing, onPublish],
  )

  /* Publish state badge ----------------------------------------- */

  const publishedRelative = formatRelative(pageDetail.published_at)

  let stateBadge: React.ReactNode
  if (pageDetail.publish_state === 'published') {
    const version = pageDetail.published_version ?? 0
    stateBadge = (
      <div className="flex items-center gap-2">
        <Badge variant="success">{`Published v${version}`}</Badge>
        {publishedRelative && (
          <span className="text-xs text-gray-500">{publishedRelative}</span>
        )}
      </div>
    )
  } else if (pageDetail.publish_state === 'draft-ahead') {
    stateBadge = <Badge variant="warning">Draft ahead</Badge>
  } else {
    stateBadge = <Badge variant="neutral">Never published</Badge>
  }

  /* Save-draft button label ------------------------------------- */

  let saveLabel: React.ReactNode = 'Save Draft'
  if (isSaving) saveLabel = 'Saving…'
  else if (showSaved) saveLabel = 'Saved'

  /* Render ------------------------------------------------------ */

  return (
    <div className="sticky top-0 z-20 border-b border-gray-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-lg font-semibold text-gray-900">
            {pageDetail.title || '(untitled)'}
          </h1>
          {stateBadge}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            loading={isSaving}
            disabled={isSaving || (!isDirty && !showSaved)}
            onClick={handleSaveDraft}
            aria-label="Save draft"
          >
            {saveLabel}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            loading={previewing}
            disabled={previewing}
            onClick={handlePreview}
            aria-label="Preview draft in new tab"
          >
            Preview
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={openPublishModal}
            aria-label="Publish page"
          >
            Publish
          </Button>

          <button
            type="button"
            onClick={onOpenSettings}
            aria-label="Open page settings"
            title="Page settings"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-300
              bg-white text-gray-700 transition-colors hover:bg-gray-50
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              focus-visible:ring-offset-2"
          >
            <span aria-hidden="true" className="text-lg leading-none">⚙️</span>
          </button>

          <button
            type="button"
            onClick={onOpenHistory}
            aria-label="Open revision history"
            title="Revision history"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-300
              bg-white text-gray-700 transition-colors hover:bg-gray-50
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              focus-visible:ring-offset-2"
          >
            <span aria-hidden="true" className="text-lg leading-none">🕐</span>
          </button>
        </div>
      </div>

      <PublishConfirmModal
        open={publishOpen}
        publishing={publishing}
        error={publishError}
        onCancel={closePublishModal}
        onConfirm={handleConfirmPublish}
      />
    </div>
  )
}

export default EditorToolbar
