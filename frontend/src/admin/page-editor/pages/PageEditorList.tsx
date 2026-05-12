/**
 * PageEditorList — admin page list for the visual page editor.
 *
 * Columns: Title (+ dirty dot), Slug, Origin badge, State badge,
 * Noindex icon, Last Published, Actions.
 *
 * Filters: search (title/slug substring, debounced 300ms), origin
 * (all/hand-coded/editor-created), state (all/published/never-published/
 * draft-ahead), and a "Show deleted" toggle.
 *
 * Pagination: 20 per page.
 *
 * Row actions:
 *   - Edit                → /admin/page-editor/:pageKey
 *   - Duplicate           → opens CreatePageModal pre-filled (wired in 7.2)
 *   - Delete              → editor-created only, soft-delete via DELETE endpoint
 *   - Revert to Fallback  → hand-coded only, POST revert-to-fallback
 *   - Undelete            → shown when "Show deleted" is on and row is soft-deleted
 *   - Audit Log           → /admin/audit-log?filter=page_editor&page_key=...
 *
 * All API data accesses use `?.` and `?? []` / `?? 0` fallbacks per the
 * safe-api-consumption steering rule.
 *
 * Requirements: 3.1, 3.2, 3.9, 3.10, 3.11, 10.2
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '../../../api/client'
import {
  AlertBanner,
  Badge,
  Button,
  ConfirmDialog,
  Input,
  Pagination,
  Select,
  Spinner,
  ToastContainer,
  useToast,
} from '../../../components/ui'
import { CreatePageModal } from './CreatePageModal'
import type { CreatePageInitialData } from './CreatePageModal'

/* --------------------------------------------------------------------
 * Types — mirror the backend `PageSummary` schema.
 * ------------------------------------------------------------------ */

type PageOrigin = 'hand-coded' | 'editor-created'
type PublishState = 'never-published' | 'published' | 'draft-ahead'

interface PageSummary {
  page_key: string
  title: string
  page_slug: string
  page_origin: PageOrigin
  publish_state: PublishState
  noindex: boolean
  published_at: string | null
  draft_updated_at: string | null
  published_version: number | null
  deleted_at: string | null
}

interface PageListResponse {
  items: PageSummary[]
  total: number
}

const PAGE_SIZE = 20

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diffSec = Math.floor((Date.now() - then) / 1000)
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

/** True when the draft is newer than the last publish. */
function isDirty(row: PageSummary): boolean {
  if (!row.draft_updated_at) return false
  if (!row.published_at) return true
  return (
    new Date(row.draft_updated_at).getTime() >
    new Date(row.published_at).getTime()
  )
}

function originBadge(origin: PageOrigin) {
  if (origin === 'hand-coded') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-blue-300 bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
        Hand-coded
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-purple-300 bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-800">
      Editor
    </span>
  )
}

function stateBadge(row: PageSummary) {
  if (row.publish_state === 'published') {
    const version = row.published_version ?? 0
    return <Badge variant="success">{`Published v${version}`}</Badge>
  }
  if (row.publish_state === 'draft-ahead') {
    return <Badge variant="warning">Draft ahead</Badge>
  }
  return <Badge variant="neutral">Never published</Badge>
}

/* --------------------------------------------------------------------
 * Main component
 * ------------------------------------------------------------------ */

export function PageEditorList() {
  const navigate = useNavigate()
  const { toasts, addToast, dismissToast } = useToast()

  /* Filters */
  const [search, setSearch] = useState('')
  const [originFilter, setOriginFilter] = useState<string>('')
  const [stateFilter, setStateFilter] = useState<string>('')
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [page, setPage] = useState(1)

  /* Data */
  const [rows, setRows] = useState<PageSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Modals */
  const [createOpen, setCreateOpen] = useState(false)
  const [createInitial, setCreateInitial] = useState<
    CreatePageInitialData | undefined
  >(undefined)

  const [deleteRow, setDeleteRow] = useState<PageSummary | null>(null)
  const [revertRow, setRevertRow] = useState<PageSummary | null>(null)
  const [undeleteRow, setUndeleteRow] = useState<PageSummary | null>(null)
  const [actionBusy, setActionBusy] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const totalPages = Math.max(1, Math.ceil((total ?? 0) / PAGE_SIZE))

  /* ------------------------------------------------------------------
   * Fetch
   * ---------------------------------------------------------------- */
  const fetchPages = useCallback(
    async (signal: AbortSignal, opts: { pageNum: number; searchTerm: string }) => {
      setLoading(true)
      setError('')
      try {
        const params: Record<string, string | number | boolean> = {
          limit: PAGE_SIZE,
          offset: ((opts.pageNum ?? 1) - 1) * PAGE_SIZE,
        }
        if (opts.searchTerm.trim()) params.search = opts.searchTerm.trim()
        if (originFilter) params.origin = originFilter
        if (stateFilter) params.state = stateFilter
        if (includeDeleted) params.include_deleted = true

        const res = await apiClient.get<PageListResponse>(
          '/api/v2/admin/page-editor/pages',
          { params, signal },
        )
        setRows(res.data?.items ?? [])
        setTotal(res.data?.total ?? 0)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        if (signal.aborted) return
        setError('Failed to load pages. Please try again.')
      } finally {
        if (!signal.aborted) setLoading(false)
      }
    },
    [originFilter, stateFilter, includeDeleted],
  )

  /* Debounced search — resets to page 1 */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
    // `search` is the value we want to debounce
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  /* Reset page to 1 whenever non-search filters change */
  useEffect(() => {
    setPage(1)
  }, [originFilter, stateFilter, includeDeleted])

  /* Fetch when page / filters change */
  useEffect(() => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchPages(controller.signal, { pageNum: page, searchTerm: search })
    return () => controller.abort()
    // `search` changes trigger via the debounce → setPage(1) path, which
    // re-runs this effect. We include it here so the first load uses the
    // current search term.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, originFilter, stateFilter, includeDeleted, fetchPages])

  const reload = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    return fetchPages(controller.signal, { pageNum: page, searchTerm: search })
  }, [fetchPages, page, search])

  /* ------------------------------------------------------------------
   * Row actions
   * ---------------------------------------------------------------- */

  const handleEdit = (row: PageSummary) => {
    navigate(`/admin/page-editor/${encodeURIComponent(row.page_key)}`)
  }

  const handleDuplicate = (row: PageSummary) => {
    // Full pre-fill from draft/published content happens in 7.2 when
    // CreatePageModal is wired up. For now open the modal with a
    // suggested title and slug; log the intent for dev visibility.
    const suggestedSlug = `${row.page_slug}-copy`
    const initial: CreatePageInitialData = {
      title: `${row.title} (Copy)`,
      page_slug: suggestedSlug,
      hideTemplate: true,
    }
    // eslint-disable-next-line no-console
    console.log('[page-editor] duplicate requested', {
      source_page_key: row.page_key,
      suggested: initial,
    })
    setCreateInitial(initial)
    setCreateOpen(true)
  }

  const handleAuditLog = (row: PageSummary) => {
    const params = new URLSearchParams({
      filter: 'page_editor',
      page_key: row.page_key,
    })
    navigate(`/admin/audit-log?${params.toString()}`)
  }

  const confirmDelete = async () => {
    if (!deleteRow) return
    setActionBusy(true)
    try {
      await apiClient.delete(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(deleteRow.page_key)}`,
      )
      addToast('success', `Deleted "${deleteRow.title}"`)
      setDeleteRow(null)
      await reload()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to delete page'
      addToast('error', typeof detail === 'string' ? detail : 'Failed to delete page')
    } finally {
      setActionBusy(false)
    }
  }

  const confirmRevert = async () => {
    if (!revertRow) return
    setActionBusy(true)
    try {
      await apiClient.post(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(revertRow.page_key)}/revert-to-fallback`,
      )
      addToast('success', `Reverted "${revertRow.title}" to fallback`)
      setRevertRow(null)
      await reload()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to revert page'
      addToast('error', typeof detail === 'string' ? detail : 'Failed to revert page')
    } finally {
      setActionBusy(false)
    }
  }

  const confirmUndelete = async () => {
    if (!undeleteRow) return
    setActionBusy(true)
    try {
      await apiClient.post(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(undeleteRow.page_key)}/undelete`,
      )
      addToast('success', `Restored "${undeleteRow.title}"`)
      setUndeleteRow(null)
      await reload()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to restore page'
      addToast('error', typeof detail === 'string' ? detail : 'Failed to restore page')
    } finally {
      setActionBusy(false)
    }
  }

  /* ------------------------------------------------------------------
   * Render
   * ---------------------------------------------------------------- */

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Page Editor</h1>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => navigate('/admin/page-editor/redirects')}
          >
            Redirects
          </Button>
          <Button
            onClick={() => {
              setCreateInitial(undefined)
              setCreateOpen(true)
            }}
          >
            New Page
          </Button>
        </div>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <div className="w-full sm:w-72">
          <Input
            label="Search"
            placeholder="Filter by title or slug"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-full sm:w-56">
          <Select
            label="Origin"
            value={originFilter}
            onChange={(e) => setOriginFilter(e.target.value)}
            options={[
              { value: '', label: 'All origins' },
              { value: 'hand-coded', label: 'Hand-coded' },
              { value: 'editor-created', label: 'Editor-created' },
            ]}
          />
        </div>
        <div className="w-full sm:w-56">
          <Select
            label="State"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            options={[
              { value: '', label: 'All states' },
              { value: 'published', label: 'Published' },
              { value: 'never-published', label: 'Never published' },
              { value: 'draft-ahead', label: 'Draft ahead' },
            ]}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700 pb-3">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
          />
          Show deleted
        </label>
      </div>

      {/* Error banner */}
      {error && !loading && (
        <AlertBanner variant="error" title="Failed to load">
          {error}
        </AlertBanner>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <Spinner label="Loading pages" />
        </div>
      )}

      {/* Empty */}
      {!loading && !error && (rows?.length ?? 0) === 0 && (
        <div className="rounded-md border border-gray-200 bg-gray-50 px-6 py-12 text-center text-sm text-gray-600">
          No pages match the current filters.
        </div>
      )}

      {/* Table */}
      {!loading && !error && (rows?.length ?? 0) > 0 && (
        <div className="overflow-x-auto rounded-md border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-600">
              <tr>
                <th scope="col" className="px-4 py-3">Title</th>
                <th scope="col" className="px-4 py-3">Slug</th>
                <th scope="col" className="px-4 py-3">Origin</th>
                <th scope="col" className="px-4 py-3">State</th>
                <th scope="col" className="px-4 py-3">Noindex</th>
                <th scope="col" className="px-4 py-3">Last Published</th>
                <th scope="col" className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(rows ?? []).map((row) => {
                const dirty = isDirty(row)
                const deleted = !!row.deleted_at
                return (
                  <tr
                    key={row.page_key}
                    className={deleted ? 'bg-gray-50 text-gray-500' : ''}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {dirty && (
                          <span
                            aria-label="Has unpublished draft changes"
                            title="Draft ahead of published"
                            className="h-2 w-2 rounded-full bg-amber-500"
                          />
                        )}
                        <span className="font-medium text-gray-900">
                          {row.title || '(untitled)'}
                        </span>
                        {deleted && (
                          <Badge variant="error" className="ml-1">Deleted</Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">
                      {row.page_slug}
                    </td>
                    <td className="px-4 py-3">{originBadge(row.page_origin)}</td>
                    <td className="px-4 py-3">{stateBadge(row)}</td>
                    <td className="px-4 py-3 text-center">
                      {row.noindex ? (
                        <span
                          aria-label="Noindex enabled"
                          title="Excluded from search engines"
                        >
                          🚫
                        </span>
                      ) : (
                        <span className="text-gray-300" aria-hidden="true">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {formatRelative(row.published_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        {!deleted && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleEdit(row)}
                          >
                            Edit
                          </Button>
                        )}
                        {!deleted && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleDuplicate(row)}
                          >
                            Duplicate
                          </Button>
                        )}
                        {!deleted && row.page_origin === 'editor-created' && (
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => setDeleteRow(row)}
                          >
                            Delete
                          </Button>
                        )}
                        {!deleted && row.page_origin === 'hand-coded' && (
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => setRevertRow(row)}
                          >
                            Revert to Fallback
                          </Button>
                        )}
                        {deleted && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setUndeleteRow(row)}
                          >
                            Undelete
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleAuditLog(row)}
                        >
                          Audit Log
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && !error && totalPages > 1 && (
        <div className="mt-6 flex items-center justify-between gap-3">
          <p className="text-sm text-gray-600">
            Showing page {page} of {totalPages} ({(total ?? 0).toLocaleString()} total)
          </p>
          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={(p) => setPage(p)}
          />
        </div>
      )}

      {/* Create modal */}
      <CreatePageModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          reload()
        }}
        initialData={createInitial}
      />

      {/* Confirm Delete (editor-created) */}
      <ConfirmDialog
        open={!!deleteRow}
        title="Delete page"
        message={
          deleteRow
            ? `Delete "${deleteRow.title}" (${deleteRow.page_slug})? The page will be soft-deleted and the public URL will return 404. You can restore it from the Show deleted view.`
            : ''
        }
        confirmLabel="Delete page"
        cancelLabel="Cancel"
        variant="danger"
        loading={actionBusy}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteRow(null)}
      />

      {/* Confirm Revert to Fallback (hand-coded) */}
      <ConfirmDialog
        open={!!revertRow}
        title="Revert to fallback"
        message={
          revertRow
            ? `Revert "${revertRow.title}" to its hand-coded fallback? Published Puck content will be cleared and the original React page will render at ${revertRow.page_slug}. Revisions and draft content are retained.`
            : ''
        }
        confirmLabel="Revert to fallback"
        cancelLabel="Cancel"
        variant="danger"
        loading={actionBusy}
        onConfirm={confirmRevert}
        onCancel={() => setRevertRow(null)}
      />

      {/* Confirm Undelete */}
      <ConfirmDialog
        open={!!undeleteRow}
        title="Restore page"
        message={
          undeleteRow
            ? `Restore "${undeleteRow.title}" (${undeleteRow.page_slug})? It will become visible at its original slug again. If the slug is already in use by another active page, the restore will fail.`
            : ''
        }
        confirmLabel="Restore page"
        cancelLabel="Cancel"
        variant="primary"
        loading={actionBusy}
        onConfirm={confirmUndelete}
        onCancel={() => setUndeleteRow(null)}
      />
    </div>
  )
}

export default PageEditorList
