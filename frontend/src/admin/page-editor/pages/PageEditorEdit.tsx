/**
 * PageEditorEdit — route-level page for editing a managed page via Puck.
 *
 * Route: `/admin/page-editor/:pageKey`
 *
 * Responsibilities:
 *   - Load the page detail (including the editing lock) on mount.
 *   - Render the Puck editor with the current draft content.
 *   - Present the EditorToolbar, PageSettingsDrawer, and
 *     RevisionHistoryDrawer around the Puck surface.
 *   - Show ConcurrentEditBanner (another admin has the page open) and
 *     DraftConflictBanner (auto-save received a 409 response).
 *   - Auto-save drafts every 30s via `useAutoSave`, paused during
 *     manual save and publish so the manual action always wins.
 *   - Warn on unsaved changes when the user navigates away (tab
 *     close via `beforeunload`; in-app nav via link-click interception).
 *
 * Styling note — Puck's editor CSS (`puck.css`) is imported ONLY in
 * this component. Because the route is lazy-loaded, the CSS is loaded
 * only when an admin opens the editor and never leaks into the rest of
 * AdminLayout. See design doc "Puck CSS Isolation".
 *
 * Requirements: 1.1, 3.3, 3.4, 3.5, 3.8
 */

// Scoped Puck CSS — intentionally imported here and nowhere else.
import '@puckeditor/core/puck.css'

// Side-effect import: registers the real MediaLibraryModal as the
// picker surface for every `MediaField` in `puckConfig`.
import '../components/MediaLibraryModal'

import { Puck } from '@puckeditor/core'
import type { Data as PuckData } from '@puckeditor/core'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { AxiosError } from 'axios'

import apiClient from '../../../api/client'
import {
  AlertBanner,
  Button,
  Spinner,
  ToastContainer,
  useToast,
} from '../../../components/ui'
import { useAuth } from '../../../contexts/AuthContext'
import { puckConfig } from '../puckConfig'
import { EditorToolbar } from '../components/EditorToolbar'
import { PageSettingsDrawer } from '../components/PageSettingsDrawer'
import { RevisionHistoryDrawer } from '../components/RevisionHistoryDrawer'
import { useAutoSave } from '../hooks/useAutoSave'

/* --------------------------------------------------------------------
 * Types — mirror the backend `PageDetail` schema (`schemas.py`).
 * ------------------------------------------------------------------ */

type PageOrigin = 'hand-coded' | 'editor-created'
type PublishState = 'never-published' | 'published' | 'draft-ahead'

interface EditingLock {
  user_email: string
  opened_at: string
}

interface PageDetail {
  page_key: string
  title: string
  page_slug: string
  page_origin: PageOrigin
  draft_content: Record<string, unknown> | null
  published_content: Record<string, unknown> | null
  published_version: number | null
  published_at: string | null
  published_by: string | null
  draft_updated_at: string | null
  draft_updated_by: string | null
  seo: Record<string, unknown> | null
  noindex: boolean
  deleted_at: string | null
  editing_lock: EditingLock | null
}

interface PreviewResponse {
  token: string
  preview_url: string
  expires_in_seconds: number
}

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

/** Derive the publish state display value from the page detail. */
function computePublishState(page: PageDetail): PublishState {
  if (!page.published_content) return 'never-published'
  if (
    page.draft_updated_at &&
    page.published_at &&
    new Date(page.draft_updated_at).getTime() >
      new Date(page.published_at).getTime()
  ) {
    return 'draft-ahead'
  }
  return 'published'
}

/** Extract a human-readable error detail from an axios error. */
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

/**
 * An empty Puck_Data document — used as a safe fallback when the
 * server returns null `draft_content` (e.g. a hand-coded page that has
 * never been edited via the editor).
 */
const EMPTY_PUCK_DATA: PuckData = {
  content: [],
  root: { props: {} },
} as unknown as PuckData

/* --------------------------------------------------------------------
 * Inline: ConcurrentEditBanner
 * ------------------------------------------------------------------ */

interface ConcurrentEditBannerProps {
  lock: EditingLock
  onDismiss: () => void
}

function ConcurrentEditBanner({ lock, onDismiss }: ConcurrentEditBannerProps) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-amber-900"
    >
      <div className="flex items-center gap-2 text-sm">
        <span aria-hidden="true">⚠️</span>
        <span>
          This page is currently being edited by{' '}
          <span className="font-semibold">{lock?.user_email || 'another admin'}</span>.
          Your changes may overwrite theirs.
        </span>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss concurrent edit warning"
        className="rounded p-1 text-amber-700 transition-colors hover:bg-amber-100
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
      >
        <span aria-hidden="true" className="text-lg leading-none">
          ×
        </span>
      </button>
    </div>
  )
}

/* --------------------------------------------------------------------
 * Inline: DraftConflictBanner
 * ------------------------------------------------------------------ */

interface DraftConflictBannerProps {
  reloading: boolean
  onReload: () => void
  onIgnore: () => void
}

function DraftConflictBanner({
  reloading,
  onReload,
  onIgnore,
}: DraftConflictBannerProps) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-red-900"
    >
      <div className="flex items-center gap-2 text-sm">
        <span aria-hidden="true">⚠️</span>
        <span>
          This draft was updated by another session. Reload to see the latest
          version — saving now will overwrite their changes.
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={onReload}
          loading={reloading}
          disabled={reloading}
        >
          Reload
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={onIgnore}
          disabled={reloading}
        >
          Ignore
        </Button>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------
 * Main component
 * ------------------------------------------------------------------ */

export function PageEditorEdit() {
  const { pageKey: pageKeyParam } = useParams<{ pageKey: string }>()
  const pageKey = pageKeyParam ?? ''
  const navigate = useNavigate()
  const { user } = useAuth()
  const { toasts, addToast, dismissToast } = useToast()

  /* ---- Page state ------------------------------------------------- */
  const [pageDetail, setPageDetail] = useState<PageDetail | null>(null)
  const [draftContent, setDraftContent] = useState<PuckData | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string>('')

  /* ---- Editor state ---------------------------------------------- */
  const [isDirty, setIsDirty] = useState(false)
  const [manualSaving, setManualSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)

  /* ---- Drawers / banners ---------------------------------------- */
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [concurrentLock, setConcurrentLock] = useState<EditingLock | null>(null)
  const [concurrentDismissed, setConcurrentDismissed] = useState(false)
  const [conflictVisible, setConflictVisible] = useState(false)
  const [reloading, setReloading] = useState(false)

  /* ---- Refs ------------------------------------------------------ */
  const fetchAbortRef = useRef<AbortController | null>(null)
  const isDirtyRef = useRef(false)

  useEffect(() => {
    isDirtyRef.current = isDirty
  }, [isDirty])

  /* ------------------------------------------------------------------
   * Fetch page detail
   * ---------------------------------------------------------------- */
  const loadPage = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true)
      setLoadError('')
      try {
        const res = await apiClient.get<PageDetail>(
          `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageKey)}`,
          { signal },
        )
        if (signal.aborted) return
        const data = res.data
        if (!data) {
          setLoadError('Page response was empty.')
          return
        }
        setPageDetail(data)
        const nextContent =
          (data.draft_content as PuckData | null) ??
          (data.published_content as PuckData | null) ??
          EMPTY_PUCK_DATA
        setDraftContent(nextContent)
        setIsDirty(false)
        // Only show the concurrent-edit banner when the lock is held
        // by a different admin than the current session.
        const lock = data.editing_lock ?? null
        if (lock && user?.email && lock.user_email !== user.email) {
          setConcurrentLock(lock)
          setConcurrentDismissed(false)
        } else {
          setConcurrentLock(null)
        }
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        if (signal.aborted) return
        const status = (err as AxiosError)?.response?.status
        if (status === 404) {
          setLoadError('This page no longer exists.')
        } else {
          setLoadError(extractDetail(err, 'Failed to load page.'))
        }
      } finally {
        if (!signal.aborted) setLoading(false)
      }
    },
    [pageKey, user?.email],
  )

  useEffect(() => {
    if (!pageKey) {
      setLoadError('Missing page identifier in URL.')
      setLoading(false)
      return
    }
    fetchAbortRef.current?.abort()
    const controller = new AbortController()
    fetchAbortRef.current = controller
    void loadPage(controller.signal)
    return () => {
      controller.abort()
    }
  }, [pageKey, loadPage])

  /* ------------------------------------------------------------------
   * Auto-save wiring
   * ---------------------------------------------------------------- */

  const handleAutoSaveError = useCallback(
    (err: unknown) => {
      const status = (err as AxiosError)?.response?.status
      if (status === 410) {
        addToast('error', 'This page has been deleted. Your changes will not be saved.')
        return
      }
      if (status === 413) {
        addToast('error', 'Draft exceeds 1 MB and cannot be saved.')
        return
      }
      addToast('error', 'Auto-save failed. We will retry on the next tick.')
    },
    [addToast],
  )

  const { autoSaving, saveNow } = useAutoSave({
    pageKey,
    content: (draftContent as unknown as Record<string, unknown> | null) ?? null,
    isDirty,
    paused: manualSaving || publishing,
    onSaved: () => {
      setIsDirty(false)
    },
    onConflict: () => {
      setConflictVisible(true)
    },
    onError: handleAutoSaveError,
  })

  const anySaving = autoSaving || manualSaving

  /* ------------------------------------------------------------------
   * Puck onChange — mark dirty and update local content
   * ---------------------------------------------------------------- */

  const handleChange = useCallback((next: PuckData) => {
    setDraftContent(next)
    setIsDirty(true)
  }, [])

  /* ------------------------------------------------------------------
   * Handlers — toolbar actions
   * ---------------------------------------------------------------- */

  const handleSaveDraft = useCallback(async () => {
    if (manualSaving || publishing) return
    setManualSaving(true)
    try {
      await saveNow()
    } finally {
      setManualSaving(false)
    }
  }, [manualSaving, publishing, saveNow])

  const handlePreview = useCallback(async () => {
    try {
      // Save pending changes first so the preview reflects them.
      if (isDirtyRef.current && !manualSaving) {
        setManualSaving(true)
        try {
          await saveNow()
        } finally {
          setManualSaving(false)
        }
      }
      const res = await apiClient.post<PreviewResponse>(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageKey)}/preview`,
      )
      const url = res.data?.preview_url
      if (!url) {
        addToast('error', 'Preview URL was missing from the server response.')
        return
      }
      // Open in a new tab; noopener prevents the new window from
      // accessing `window.opener` in the editor context.
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      addToast('error', extractDetail(err, 'Failed to generate preview.'))
    }
  }, [pageKey, manualSaving, saveNow, addToast])

  const handlePublish = useCallback(
    async (note?: string) => {
      if (publishing) return
      setPublishing(true)
      try {
        // Save pending edits before publishing so the published
        // version includes them. (The backend publishes from
        // `draft_content`, so it must be up to date.)
        if (isDirtyRef.current) {
          await saveNow()
        }
        const res = await apiClient.post<PageDetail>(
          `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageKey)}/publish`,
          { note: note ?? null },
        )
        const updated = res.data
        if (!updated) {
          addToast('error', 'Publish succeeded but the server response was unexpected.')
          return
        }
        setPageDetail(updated)
        setDraftContent(
          (updated.draft_content as PuckData | null) ??
            (updated.published_content as PuckData | null) ??
            EMPTY_PUCK_DATA,
        )
        setIsDirty(false)
        addToast('success', `Published v${updated.published_version ?? 0}.`)
      } catch (err) {
        addToast('error', extractDetail(err, 'Failed to publish the page.'))
        // Re-throw so EditorToolbar's PublishConfirmModal can surface
        // the error inline and keep itself open.
        throw err
      } finally {
        setPublishing(false)
      }
    },
    [pageKey, publishing, saveNow, addToast],
  )

  /* ------------------------------------------------------------------
   * Handlers — drawers
   * ---------------------------------------------------------------- */

  const handleOpenSettings = useCallback(() => setSettingsOpen(true), [])
  const handleCloseSettings = useCallback(() => setSettingsOpen(false), [])

  const handleSettingsSaved = useCallback(
    (updated: PageDetail) => {
      setPageDetail((prev) => ({ ...(prev ?? updated), ...updated }))
      // If the slug changed, keep the URL in sync with the new slug.
      // The page_key is stable so we don't navigate, but users will
      // see the new slug reflected in the toolbar and settings.
      addToast('success', 'Settings saved.')
    },
    [addToast],
  )

  const handleOpenHistory = useCallback(() => setHistoryOpen(true), [])
  const handleCloseHistory = useCallback(() => setHistoryOpen(false), [])

  const handleReverted = useCallback(
    (updated: PageDetail) => {
      setPageDetail((prev) => ({ ...(prev ?? updated), ...updated }))
      const nextContent =
        (updated.draft_content as PuckData | null) ??
        (updated.published_content as PuckData | null) ??
        EMPTY_PUCK_DATA
      setDraftContent(nextContent)
      // The revert endpoint writes the revision content into
      // `draft_content` without publishing, so the draft is now
      // ahead of published — mark dirty so the toolbar reflects
      // the unsaved state.
      setIsDirty(true)
      addToast('success', `Reverted draft to v${updated.published_version ?? 0}.`)
    },
    [addToast],
  )

  const handleHistoryError = useCallback(
    (message: string) => {
      addToast('error', message)
    },
    [addToast],
  )

  /* ------------------------------------------------------------------
   * Conflict banner — Reload / Ignore
   * ---------------------------------------------------------------- */

  const handleConflictReload = useCallback(async () => {
    setReloading(true)
    const controller = new AbortController()
    try {
      await loadPage(controller.signal)
      setConflictVisible(false)
    } finally {
      setReloading(false)
    }
  }, [loadPage])

  const handleConflictIgnore = useCallback(() => {
    setConflictVisible(false)
  }, [])

  /* ------------------------------------------------------------------
   * Unsaved-changes guard
   *
   * 1. `beforeunload` — browser-level confirmation on tab close or
   *    external navigation while dirty or a save is in flight.
   * 2. Link-click interception — intercepts same-origin anchor clicks
   *    routed through the SPA (react-router's <Link>) to present a
   *    window.confirm dialog before navigation proceeds.
   * ---------------------------------------------------------------- */

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!isDirtyRef.current && !manualSaving && !publishing) return
      // Chrome/Firefox require both preventDefault and returnValue.
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [manualSaving, publishing])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (e.defaultPrevented) return
      if (e.button !== 0) return
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      if (!isDirtyRef.current) return

      const target = (e.target as Element | null)?.closest('a[href]')
      if (!(target instanceof HTMLAnchorElement)) return
      if (target.target && target.target !== '_self') return
      if (target.hasAttribute('download')) return

      let destination: URL
      try {
        destination = new URL(target.href, window.location.href)
      } catch {
        return
      }
      if (destination.origin !== window.location.origin) return
      // Same page (hash-only change) — allow.
      if (
        destination.pathname === window.location.pathname &&
        destination.search === window.location.search
      ) {
        return
      }

      // eslint-disable-next-line no-alert
      const proceed = window.confirm(
        'You have unsaved changes to this page. Leave without saving?',
      )
      if (!proceed) {
        e.preventDefault()
        e.stopPropagation()
      }
    }
    // Capture phase so we run before react-router's link handler.
    document.addEventListener('click', handler, true)
    return () => document.removeEventListener('click', handler, true)
  }, [])

  /* ------------------------------------------------------------------
   * Derived props for the toolbar
   * ---------------------------------------------------------------- */

  const toolbarPageDetail = useMemo(() => {
    if (!pageDetail) return null
    return {
      page_key: pageDetail.page_key,
      title: pageDetail.title,
      publish_state: computePublishState(pageDetail),
      published_version: pageDetail.published_version,
      published_at: pageDetail.published_at,
    }
  }, [pageDetail])

  /* ------------------------------------------------------------------
   * Render
   * ---------------------------------------------------------------- */

  if (loading && !pageDetail) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner size="lg" label="Loading editor" />
      </div>
    )
  }

  if (loadError && !pageDetail) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <AlertBanner variant="error" title="Failed to load page">
          {loadError}
        </AlertBanner>
        <div className="mt-4 flex gap-2">
          <Button
            variant="secondary"
            onClick={() => navigate('/admin/page-editor')}
          >
            Back to pages
          </Button>
          <Button
            onClick={() => {
              const controller = new AbortController()
              fetchAbortRef.current = controller
              void loadPage(controller.signal)
            }}
          >
            Retry
          </Button>
        </div>
      </div>
    )
  }

  if (!pageDetail || !toolbarPageDetail) {
    return null
  }

  const showConcurrentBanner = concurrentLock && !concurrentDismissed

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {showConcurrentBanner && (
        <ConcurrentEditBanner
          lock={concurrentLock}
          onDismiss={() => setConcurrentDismissed(true)}
        />
      )}

      {conflictVisible && (
        <DraftConflictBanner
          reloading={reloading}
          onReload={handleConflictReload}
          onIgnore={handleConflictIgnore}
        />
      )}

      <EditorToolbar
        pageDetail={toolbarPageDetail}
        isDirty={isDirty}
        isSaving={anySaving}
        onSaveDraft={handleSaveDraft}
        onPreview={handlePreview}
        onPublish={handlePublish}
        onOpenSettings={handleOpenSettings}
        onOpenHistory={handleOpenHistory}
      />

      <div className="flex-1 min-h-0">
        <Puck
          config={puckConfig}
          data={draftContent ?? EMPTY_PUCK_DATA}
          onChange={handleChange}
          onPublish={handlePublish}
        />
      </div>

      <PageSettingsDrawer
        open={settingsOpen}
        onClose={handleCloseSettings}
        pageDetail={pageDetail}
        onSaved={handleSettingsSaved}
      />

      <RevisionHistoryDrawer
        open={historyOpen}
        onClose={handleCloseHistory}
        pageKey={pageKey}
        onReverted={handleReverted}
        onError={handleHistoryError}
      />
    </div>
  )
}

export default PageEditorEdit
