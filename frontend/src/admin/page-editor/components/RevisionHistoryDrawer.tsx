/**
 * RevisionHistoryDrawer — slide-over drawer listing a page's revisions.
 *
 * Opened from the `EditorToolbar` history (🕐) button inside
 * `PageEditorEdit`. Presents the revision history surface documented
 * in Design Gap D: version badge, author, relative timestamp, and
 * optional note per row, with per-row "View" (read-only full-screen
 * Puck preview) and "Revert" (copy revision content into draft) actions.
 *
 * Behaviour:
 *  - Fetches `GET /pages/:page_key/revisions` when the drawer opens.
 *    The request is aborted if the drawer closes or the page changes
 *    before the response arrives.
 *  - "View" opens a full-screen read-only `<Render>` of the revision's
 *    content. The same `puckConfig` used by the editor and the public
 *    renderer is reused so the preview matches what the page looked
 *    like at that version. The full PageShell (header/footer) wrapping
 *    is skipped for now per the task brief — a plain padded container
 *    is used instead.
 *  - "Revert" calls `POST /pages/:page_key/revisions/:version/revert`
 *    which copies the revision's content into the page's draft. The
 *    returned `PageDetail` is passed to `onReverted()` so the editor
 *    can sync its local draft state without a refetch, and the drawer
 *    closes on success.
 *
 * Requirements: 5.4, 5.5, 5.6
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { AxiosError } from 'axios'
import { Render } from '@puckeditor/core'
import apiClient from '../../../api/client'
import { AlertBanner, Badge, Button } from '../../../components/ui'
import { trapFocus } from '../../../utils/accessibility'
import { puckConfig } from '../puckConfig'

/* --------------------------------------------------------------------
 * Types
 * ------------------------------------------------------------------ */

/**
 * Minimal shape of the page detail returned by the revert endpoint.
 * Intentionally narrow so callers can pass their existing PageDetail
 * object (e.g. `PageSettingsPageDetail`) without a cast.
 */
export interface PageDetail {
  page_key: string
  title: string
  page_slug: string
  draft_content?: Record<string, unknown> | null
  published_content?: Record<string, unknown> | null
  published_version?: number | null
  published_at?: string | null
  draft_updated_at?: string | null
  [extra: string]: unknown
}

/**
 * Shape of a revision summary entry. Matches the backend
 * `RevisionSummary` response — `id` and `published_by` are UUID
 * strings when serialised as JSON. `content` is the full Puck_Data
 * snapshot for the revision; it is consumed by the preview modal.
 */
interface RevisionSummary {
  id: string
  page_key?: string
  version: number
  content?: Record<string, unknown> | null
  published_at: string | null
  published_by: string | null
  note: string | null
  created_at: string
}

export interface RevisionHistoryDrawerProps {
  open: boolean
  onClose: () => void
  pageKey: string
  /** Called after a successful revert so the editor can sync its draft. */
  onReverted: (updatedPage: PageDetail) => void
  /** Optional — surfaces human-readable error messages for toasts. */
  onError?: (message: string) => void
}

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

/**
 * Format an ISO timestamp as a human-readable relative time
 * ("just now", "5m ago", "3h ago", "2d ago"). Falls back to a
 * localised date for older timestamps. Matches the formatter used
 * by `PageEditorList` and `EditorToolbar`.
 */
function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
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

/** Truncate a UUID/email to a short preview suitable for the row. */
function formatAuthor(userId: string | null | undefined): string {
  if (!userId) return '—'
  // UUIDs are 36 chars — showing the first 8 is enough to disambiguate
  // common cases. Non-UUID strings (e.g. emails) are shown as-is.
  if (userId.length > 12) return userId.slice(0, 8)
  return userId
}

/** Extract a human-readable error detail out of an axios error. */
function extractDetail(err: unknown, fallback: string): string {
  const axiosErr = err as AxiosError<{ detail?: unknown }>
  const detail = axiosErr?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string } | undefined
    if (first?.msg) return first.msg
  }
  return fallback
}

/* --------------------------------------------------------------------
 * Component
 * ------------------------------------------------------------------ */

export function RevisionHistoryDrawer({
  open,
  onClose,
  pageKey,
  onReverted,
  onError,
}: RevisionHistoryDrawerProps) {
  /* ---- Data state ------------------------------------------------ */
  const [revisions, setRevisions] = useState<RevisionSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState<string>('')

  /* ---- Action state --------------------------------------------- */
  const [revertingVersion, setRevertingVersion] = useState<number | null>(null)
  const [previewRevision, setPreviewRevision] = useState<RevisionSummary | null>(null)

  /* ---- Refs ------------------------------------------------------ */
  const fetchAbortRef = useRef<AbortController | null>(null)
  const revertAbortRef = useRef<AbortController | null>(null)

  const panelRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const titleId = 'revision-history-drawer-title'

  /* ---- Fetch revisions on open ----------------------------------- */

  useEffect(() => {
    if (!open) {
      // Reset state so the next open starts clean.
      setRevisions([])
      setListError('')
      setRevertingVersion(null)
      setPreviewRevision(null)
      return
    }

    const controller = new AbortController()
    fetchAbortRef.current?.abort()
    fetchAbortRef.current = controller

    setLoading(true)
    setListError('')

    apiClient
      .get<{ items: RevisionSummary[]; total: number }>(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageKey)}/revisions`,
        {
          params: { offset: 0, limit: 50 },
          signal: controller.signal,
        },
      )
      .then((res) => {
        if (controller.signal.aborted) return
        setRevisions(res.data?.items ?? [])
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if ((err as { name?: string })?.name === 'CanceledError') return
        setListError(extractDetail(err, 'Failed to load revision history.'))
      })
      .finally(() => {
        if (controller.signal.aborted) return
        if (fetchAbortRef.current === controller) fetchAbortRef.current = null
        setLoading(false)
      })

    return () => {
      controller.abort()
    }
  }, [open, pageKey])

  /* ---- Escape-to-close, focus trap, body scroll lock -------------- */

  useEffect(() => {
    if (!open) return
    // If a preview modal is open, let that own the keyboard / focus
    // trap instead of the drawer.
    if (previewRevision) return

    previousFocusRef.current = document.activeElement as HTMLElement

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (revertingVersion === null) onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    let releaseTrap: (() => void) | undefined
    if (panelRef.current) {
      releaseTrap = trapFocus(panelRef.current)
      panelRef.current.focus()
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = prevOverflow
      releaseTrap?.()
      previousFocusRef.current?.focus?.()
    }
  }, [open, onClose, revertingVersion, previewRevision])

  /* ---- Abort in-flight requests on close ------------------------- */

  useEffect(() => {
    if (open) return
    fetchAbortRef.current?.abort()
    revertAbortRef.current?.abort()
    fetchAbortRef.current = null
    revertAbortRef.current = null
  }, [open])

  /* ---- View revision -------------------------------------------- */

  const handleView = useCallback(
    (revision: RevisionSummary) => {
      // Content ships with the list response per the documented
      // RevisionSummary contract. If it's missing (older backend), we
      // can't render a preview — surface a friendly error instead of
      // opening an empty modal.
      const content = revision?.content ?? null
      if (!content) {
        onError?.(
          'Unable to preview this revision — its content is not available.',
        )
        return
      }
      setPreviewRevision(revision)
    },
    [onError],
  )

  const closePreview = useCallback(() => {
    setPreviewRevision(null)
  }, [])

  /* ---- Revert --------------------------------------------------- */

  const handleRevert = useCallback(
    async (revision: RevisionSummary) => {
      if (revertingVersion !== null) return

      const controller = new AbortController()
      revertAbortRef.current?.abort()
      revertAbortRef.current = controller

      setRevertingVersion(revision.version)

      try {
        const res = await apiClient.post<PageDetail>(
          `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageKey)}/revisions/${revision.version}/revert`,
          {},
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        const updated = res.data
        if (!updated) {
          onError?.('Revert succeeded but the server response was unexpected.')
          return
        }
        onReverted(updated)
        onClose()
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if ((err as { name?: string })?.name === 'CanceledError') return
        onError?.(
          extractDetail(err, `Failed to revert to v${revision.version}. Please try again.`),
        )
      } finally {
        if (revertAbortRef.current === controller) revertAbortRef.current = null
        setRevertingVersion(null)
      }
    },
    [pageKey, revertingVersion, onReverted, onClose, onError],
  )

  /* ---- Derived -------------------------------------------------- */

  // List endpoint already returns newest-first, but sort defensively in
  // case a future change alters the server order.
  const sortedRevisions = useMemo(
    () =>
      [...(revisions ?? [])].sort(
        (a, b) => (b?.version ?? 0) - (a?.version ?? 0),
      ),
    [revisions],
  )

  /* ---- Render --------------------------------------------------- */

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-40 flex"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && revertingVersion === null) onClose()
      }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-sm animate-fadeIn"
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative ml-auto flex h-full w-full max-w-md flex-col bg-white shadow-2xl
          focus:outline-none"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            Revision history
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={revertingVersion !== null}
            className="rounded p-1 text-gray-400 transition-colors hover:text-gray-600
              disabled:opacity-50
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Close revision history"
          >
            <span aria-hidden="true" className="text-2xl leading-none">×</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-5">
          {listError && (
            <div className="mb-4">
              <AlertBanner variant="error" title="Could not load revisions">
                {listError}
              </AlertBanner>
            </div>
          )}

          {loading && (
            <div className="space-y-3" aria-label="Loading revisions">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-24 animate-pulse rounded-md border border-gray-200 bg-gray-50"
                  aria-hidden="true"
                />
              ))}
            </div>
          )}

          {!loading && !listError && sortedRevisions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <span aria-hidden="true" className="mb-3 text-4xl">🕐</span>
              <p className="text-sm font-medium text-gray-700">No revisions yet</p>
              <p className="mt-1 text-xs text-gray-500">
                Publish the page to create the first revision.
              </p>
            </div>
          )}

          {!loading && sortedRevisions.length > 0 && (
            <ul className="space-y-3">
              {sortedRevisions.map((rev) => {
                const isReverting = revertingVersion === rev?.version
                const disableActions = revertingVersion !== null && !isReverting
                const fullTimestamp = rev?.published_at
                  ? new Date(rev.published_at).toLocaleString('en-NZ')
                  : rev?.created_at
                    ? new Date(rev.created_at).toLocaleString('en-NZ')
                    : ''
                return (
                  <li
                    key={rev?.id ?? rev?.version}
                    className="rounded-md border border-gray-200 bg-white p-3 shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Badge variant="info">{`v${rev?.version ?? 0}`}</Badge>
                        <span className="text-sm text-gray-700">
                          {formatAuthor(rev?.published_by)}
                        </span>
                      </div>
                      <span
                        className="text-xs text-gray-500"
                        title={fullTimestamp || undefined}
                      >
                        {formatRelative(rev?.published_at ?? rev?.created_at)}
                      </span>
                    </div>

                    {rev?.note && (
                      <p className="mt-2 text-sm italic text-gray-600">
                        {rev.note}
                      </p>
                    )}

                    <div className="mt-3 flex items-center gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => handleView(rev)}
                        disabled={disableActions}
                        aria-label={`View content of revision v${rev?.version ?? 0}`}
                      >
                        View
                      </Button>
                      <Button
                        type="button"
                        variant="primary"
                        size="sm"
                        onClick={() => handleRevert(rev)}
                        loading={isReverting}
                        disabled={disableActions}
                        aria-label={`Revert draft to revision v${rev?.version ?? 0}`}
                      >
                        {isReverting ? 'Reverting…' : 'Revert'}
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>

      {/* Full-screen read-only preview modal */}
      {previewRevision && (
        <RevisionPreviewModal
          revision={previewRevision}
          onClose={closePreview}
        />
      )}
    </div>
  )
}

/* --------------------------------------------------------------------
 * RevisionPreviewModal
 *
 * Full-screen read-only preview of a revision's content. Reuses the
 * same `puckConfig` as the editor and the public renderer so the
 * preview matches what the page looked like at that version.
 *
 * Page shell (LandingHeader + LandingFooter) integration is deferred
 * per the task brief — a plain padded container is used instead.
 * ------------------------------------------------------------------ */

interface RevisionPreviewModalProps {
  revision: RevisionSummary
  onClose: () => void
}

function RevisionPreviewModal({ revision, onClose }: RevisionPreviewModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  // Escape-to-close + focus trap + body-scroll-lock.
  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    let releaseTrap: (() => void) | undefined
    if (panelRef.current) {
      releaseTrap = trapFocus(panelRef.current)
      panelRef.current.focus()
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = prevOverflow
      releaseTrap?.()
      previousFocusRef.current?.focus?.()
    }
  }, [onClose])

  const titleId = 'revision-preview-modal-title'

  // Puck's `Render` component expects a `Data` object. The revision
  // content may be missing if a caller reaches this modal without the
  // list endpoint returning a content payload — guard and fall back
  // to an empty state in that case.
  const content = revision?.content ?? null
  const data = content as unknown as Parameters<typeof Render>[0]['data']

  return (
    <div
      className="fixed inset-0 z-50 bg-white animate-fadeIn"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      ref={panelRef}
      tabIndex={-1}
    >
      {/* Sticky header */}
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-white px-5 py-3">
        <div className="flex items-center gap-3">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            Preview revision
          </h2>
          <Badge variant="info">{`v${revision?.version ?? 0}`}</Badge>
          <span className="text-xs text-gray-500">read-only</span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onClose}
          >
            Close preview
          </Button>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="h-[calc(100vh-57px)] overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 py-6">
          {data ? (
            <Render config={puckConfig} data={data} />
          ) : (
            <div className="flex items-center justify-center py-16 text-sm text-gray-500">
              <span>Revision content is not available.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default RevisionHistoryDrawer
