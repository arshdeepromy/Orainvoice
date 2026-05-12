/**
 * PageEditorRedirects — admin panel for managing slug redirects.
 *
 * Lists every entry in `editor_page_redirects` (active by default, with an
 * optional "Show deleted" toggle), lets a `global_admin` create new
 * redirects inline, and soft-deletes existing ones.
 *
 * Fields per row: From, To, Status, Created.
 * Create form: `from_slug`, `to_slug_or_url`, `status_code` (301/302).
 * Client-side slug validation for `from_slug` mirrors CreatePageModal
 * (regex + length + reserved-prefix check) so obvious mistakes are caught
 * before hitting the API.
 *
 * Backend errors are surfaced under the form:
 *   - 409 → slug already in use by an active page or redirect
 *   - 422 → invalid slug / self-redirect / other payload validation
 *
 * All API data accesses use `?.` and `?? []` / `?? 0` fallbacks per the
 * safe-api-consumption steering rule. Every fetch uses AbortController
 * cleanup to prevent stale state updates.
 *
 * Route: `/admin/page-editor/redirects`
 * Requirements: 11.3
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { AxiosError } from 'axios'
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
import { validateSlugClient } from './CreatePageModal'

/* --------------------------------------------------------------------
 * Types — mirror the backend `RedirectItem` schema.
 * ------------------------------------------------------------------ */

interface RedirectItem {
  id: string
  from_slug: string
  to_slug_or_url: string
  status_code: number
  created_at: string
  created_by: string | null
  deleted_at: string | null
}

interface RedirectListResponse {
  items: RedirectItem[]
  total: number
}

const PAGE_SIZE = 20

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Validate the destination value. Accepts a same-origin path starting
 * with `/` or an absolute `https://` URL. `http://` is rejected to
 * avoid insecure outbound redirects.
 */
function validateDestination(value: string): string | null {
  if (!value) return 'Destination is required.'
  if (value.length > 500) {
    return 'Destination must be at most 500 characters.'
  }
  if (value.startsWith('/')) return null
  if (value.startsWith('https://')) {
    try {
      // eslint-disable-next-line no-new
      new URL(value)
      return null
    } catch {
      return 'Destination must be a valid https:// URL.'
    }
  }
  return 'Destination must start with "/" for an internal path or "https://" for an external URL.'
}

/** Extract a human-readable error detail from an Axios error. */
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
 * Main component
 * ------------------------------------------------------------------ */

export function PageEditorRedirects() {
  const navigate = useNavigate()
  const { toasts, addToast, dismissToast } = useToast()

  /* Filters */
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [page, setPage] = useState(1)

  /* Data */
  const [rows, setRows] = useState<RedirectItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create form state */
  const [fromSlug, setFromSlug] = useState('')
  const [toValue, setToValue] = useState('')
  const [statusCode, setStatusCode] = useState<string>('301')
  const [fromSlugError, setFromSlugError] = useState<string | null>(null)
  const [toValueError, setToValueError] = useState<string | null>(null)
  const [formBannerError, setFormBannerError] = useState('')
  const [creating, setCreating] = useState(false)

  /* Delete confirmation */
  const [deleteRow, setDeleteRow] = useState<RedirectItem | null>(null)
  const [actionBusy, setActionBusy] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const createAbortRef = useRef<AbortController | null>(null)

  const totalPages = Math.max(1, Math.ceil((total ?? 0) / PAGE_SIZE))

  /* ------------------------------------------------------------------
   * Fetch
   * ---------------------------------------------------------------- */
  const fetchRedirects = useCallback(
    async (signal: AbortSignal, opts: { pageNum: number }) => {
      setLoading(true)
      setError('')
      try {
        const params: Record<string, string | number | boolean> = {
          limit: PAGE_SIZE,
          offset: ((opts.pageNum ?? 1) - 1) * PAGE_SIZE,
        }
        if (includeDeleted) params.include_deleted = true

        const res = await apiClient.get<RedirectListResponse>(
          '/api/v2/admin/page-editor/redirects',
          { params, signal },
        )
        setRows(res.data?.items ?? [])
        setTotal(res.data?.total ?? 0)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        if (signal.aborted) return
        setError('Failed to load redirects. Please try again.')
      } finally {
        if (!signal.aborted) setLoading(false)
      }
    },
    [includeDeleted],
  )

  /* Reset page to 1 whenever the filter changes */
  useEffect(() => {
    setPage(1)
  }, [includeDeleted])

  /* Fetch on page / filter change */
  useEffect(() => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchRedirects(controller.signal, { pageNum: page })
    return () => controller.abort()
  }, [page, fetchRedirects])

  const reload = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    return fetchRedirects(controller.signal, { pageNum: page })
  }, [fetchRedirects, page])

  /* Abort any in-flight create request on unmount */
  useEffect(() => {
    return () => {
      if (createAbortRef.current) createAbortRef.current.abort()
    }
  }, [])

  /* ------------------------------------------------------------------
   * Create
   * ---------------------------------------------------------------- */

  const handleFromSlugChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFromSlug(e.target.value)
    if (fromSlugError) setFromSlugError(null)
    if (formBannerError) setFormBannerError('')
  }

  const handleToValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setToValue(e.target.value)
    if (toValueError) setToValueError(null)
    if (formBannerError) setFormBannerError('')
  }

  const resetForm = () => {
    setFromSlug('')
    setToValue('')
    setStatusCode('301')
    setFromSlugError(null)
    setToValueError(null)
    setFormBannerError('')
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (creating) return

    const trimmedFrom = fromSlug.trim()
    const trimmedTo = toValue.trim()

    let hasError = false
    const fromErr = validateSlugClient(trimmedFrom)
    if (fromErr) {
      setFromSlugError(fromErr)
      hasError = true
    }
    const toErr = validateDestination(trimmedTo)
    if (toErr) {
      setToValueError(toErr)
      hasError = true
    }
    if (trimmedFrom && trimmedTo && trimmedFrom === trimmedTo) {
      setToValueError('Destination must differ from the source slug.')
      hasError = true
    }

    const parsedStatus = Number(statusCode)
    if (parsedStatus !== 301 && parsedStatus !== 302) {
      setFormBannerError('Status code must be 301 or 302.')
      hasError = true
    }

    if (hasError) return

    setFormBannerError('')
    setCreating(true)

    if (createAbortRef.current) createAbortRef.current.abort()
    const controller = new AbortController()
    createAbortRef.current = controller

    try {
      await apiClient.post<RedirectItem>(
        '/api/v2/admin/page-editor/redirects',
        {
          from_slug: trimmedFrom,
          to_slug_or_url: trimmedTo,
          status_code: parsedStatus,
        },
        { signal: controller.signal },
      )
      addToast('success', `Redirect ${trimmedFrom} → ${trimmedTo} created`)
      resetForm()
      // Jump back to page 1 to see the new entry (it sorts newest-first
      // per the backend list ordering; if already on page 1 the effect
      // re-runs via reload() below).
      if (page !== 1) {
        setPage(1)
      } else {
        await reload()
      }
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      if (controller.signal.aborted) return

      const status = (err as AxiosError)?.response?.status
      if (status === 409) {
        setFromSlugError(
          extractDetail(
            err,
            `"${trimmedFrom}" is already in use by an active page or redirect.`,
          ),
        )
      } else if (status === 422) {
        const detail = extractDetail(err, 'Invalid redirect payload.')
        if (/from_slug|slug/i.test(detail)) {
          setFromSlugError(detail)
        } else if (/to_slug|destination|url/i.test(detail)) {
          setToValueError(detail)
        } else {
          setFormBannerError(detail)
        }
      } else {
        setFormBannerError(
          extractDetail(err, 'Failed to create redirect. Please try again.'),
        )
      }
    } finally {
      if (createAbortRef.current === controller) createAbortRef.current = null
      setCreating(false)
    }
  }

  /* ------------------------------------------------------------------
   * Delete
   * ---------------------------------------------------------------- */

  const confirmDelete = async () => {
    if (!deleteRow) return
    setActionBusy(true)
    try {
      await apiClient.delete(
        `/api/v2/admin/page-editor/redirects/${encodeURIComponent(deleteRow.id)}`,
      )
      addToast('success', `Deleted redirect ${deleteRow.from_slug}`)
      setDeleteRow(null)
      await reload()
    } catch (err: unknown) {
      const detail = extractDetail(err, 'Failed to delete redirect')
      addToast('error', detail)
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
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Page Redirects</h1>
          <p className="mt-1 text-sm text-gray-600">
            Forward old slugs to new pages or external URLs. Redirects are
            evaluated before page resolution.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => navigate('/admin/page-editor')}
        >
          ← Back to pages
        </Button>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Create form */}
      <section
        aria-labelledby="new-redirect-heading"
        className="mb-6 rounded-md border border-gray-200 bg-white p-4"
      >
        <h2
          id="new-redirect-heading"
          className="mb-3 text-sm font-semibold text-gray-900"
        >
          Create redirect
        </h2>
        <form onSubmit={handleCreate} noValidate className="space-y-4">
          {formBannerError && (
            <AlertBanner variant="error" title="Could not create redirect">
              {formBannerError}
            </AlertBanner>
          )}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_1fr_140px_auto] md:items-start">
            <Input
              label="From slug"
              value={fromSlug}
              onChange={handleFromSlugChange}
              placeholder="/old-path"
              maxLength={80}
              required
              error={fromSlugError ?? undefined}
              helperText={
                fromSlugError
                  ? undefined
                  : 'Must start with "/" (e.g. /old-pricing).'
              }
            />
            <Input
              label="To slug or URL"
              value={toValue}
              onChange={handleToValueChange}
              placeholder="/new-path or https://example.com"
              maxLength={500}
              required
              error={toValueError ?? undefined}
              helperText={
                toValueError
                  ? undefined
                  : 'Internal path starting with "/" or an absolute https:// URL.'
              }
            />
            <Select
              label="Status"
              value={statusCode}
              onChange={(e) => setStatusCode(e.target.value)}
              options={[
                { value: '301', label: '301 (permanent)' },
                { value: '302', label: '302 (temporary)' },
              ]}
            />
            <div className="flex items-end md:pt-6">
              <Button type="submit" loading={creating} disabled={creating}>
                Create
              </Button>
            </div>
          </div>
        </form>
      </section>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-700">
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
          <Spinner label="Loading redirects" />
        </div>
      )}

      {/* Empty */}
      {!loading && !error && (rows?.length ?? 0) === 0 && (
        <div className="rounded-md border border-gray-200 bg-gray-50 px-6 py-12 text-center text-sm text-gray-600">
          No redirects {includeDeleted ? 'found.' : 'yet. Create one above.'}
        </div>
      )}

      {/* Table */}
      {!loading && !error && (rows?.length ?? 0) > 0 && (
        <div className="overflow-x-auto rounded-md border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-600">
              <tr>
                <th scope="col" className="px-4 py-3">From</th>
                <th scope="col" className="px-4 py-3">To</th>
                <th scope="col" className="px-4 py-3">Status</th>
                <th scope="col" className="px-4 py-3">Created</th>
                <th scope="col" className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(rows ?? []).map((row) => {
                const deleted = !!row.deleted_at
                return (
                  <tr
                    key={row.id}
                    className={deleted ? 'bg-gray-50 text-gray-500' : ''}
                  >
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">
                      <div className="flex items-center gap-2">
                        <span className="truncate">{row.from_slug}</span>
                        {deleted && (
                          <Badge variant="error" className="ml-1">Deleted</Badge>
                        )}
                      </div>
                    </td>
                    <td
                      className="px-4 py-3 font-mono text-xs text-gray-700 max-w-xs truncate"
                      title={row.to_slug_or_url}
                    >
                      {row.to_slug_or_url}
                    </td>
                    <td className="px-4 py-3">
                      {row.status_code === 301 ? (
                        <Badge variant="success">301</Badge>
                      ) : (
                        <Badge variant="warning">302</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {formatDate(row.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        {!deleted && (
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => setDeleteRow(row)}
                          >
                            Delete
                          </Button>
                        )}
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

      {/* Confirm Delete */}
      <ConfirmDialog
        open={!!deleteRow}
        title="Delete redirect"
        message={
          deleteRow
            ? `Delete the redirect from "${deleteRow.from_slug}" to "${deleteRow.to_slug_or_url}"? The source slug will no longer redirect and may return 404 if no page claims it.`
            : ''
        }
        confirmLabel="Delete redirect"
        cancelLabel="Cancel"
        variant="danger"
        loading={actionBusy}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteRow(null)}
      />
    </div>
  )
}

export default PageEditorRedirects
