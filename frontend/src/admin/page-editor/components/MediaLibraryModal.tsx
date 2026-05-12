/**
 * MediaLibraryModal — Task 7.8.
 *
 * Full-featured media library picker used both as a standalone admin
 * tool and as the picker surface behind the custom `MediaField` Puck
 * field (Task 6.6). Presents a grid of uploaded images with filename,
 * dimensions, and size, a debounced search, inline upload + drag-and-
 * drop, per-row delete with reference-check error handling, and
 * "Load more" pagination.
 *
 * Behaviour:
 *  - Fetches `GET /api/v2/admin/page-editor/media?search=&offset=&limit=`
 *    on open and whenever the debounced search changes.
 *  - Uploads via `POST /api/v2/admin/page-editor/media` (multipart).
 *    Client-side checks: MIME in the accepted set and size ≤ 10 MB so
 *    obvious mistakes are caught before hitting the API.
 *  - Deletes via `DELETE /api/v2/admin/page-editor/media/:id`. A 409
 *    response means the asset is referenced by a page's draft or
 *    published content — surfaced as an error toast so the editor
 *    knows which pages still use it.
 *  - Clicking an asset calls `onSelect(displayUrl)` + `onClose()`.
 *    `displayUrl` is derived from the asset ID + filename so the
 *    surrounding `MediaField` preview and the public `<img>` render
 *    can both load it through nginx without a separate lookup.
 *
 * Wiring: this module registers itself as the modal used by the
 * custom `MediaField` via `registerMediaLibraryModal()` so every
 * `mediaField()` field automatically gets the real library once this
 * file is imported anywhere (e.g. from `PageEditorEdit.tsx`).
 *
 * Requirements: 12.2, 12.3, 12.4
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ChangeEvent, DragEvent, ReactElement } from 'react'
import type { AxiosError } from 'axios'
import apiClient from '../../../api/client'
import {
  AlertBanner,
  Button,
  Spinner,
  ToastContainer,
  useToast,
} from '../../../components/ui'
import { trapFocus } from '../../../utils/accessibility'
import {
  registerMediaLibraryModal,
  type MediaLibraryModalProps as FieldModalProps,
} from '../fields/MediaField'

/* --------------------------------------------------------------------
 * Types
 * ------------------------------------------------------------------ */

/**
 * Shape of a single media asset returned by the backend listing
 * endpoint. Mirrors `app/modules/page_editor/schemas.py::MediaAsset`.
 */
interface MediaAsset {
  id: string
  filename: string
  original_path: string
  content_type: string
  size_bytes: number
  width: number | null
  height: number | null
  variants: Record<string, string>
  uploaded_at: string
}

interface MediaListResponse {
  items: MediaAsset[]
  total: number
}

/**
 * Public props for the standalone modal. Adds an `open` flag on top
 * of the `MediaField` contract so the modal can be mounted
 * persistently (e.g. from `PageEditorEdit`) and toggled. The
 * registered wrapper used by `MediaField` (which already gates
 * mounting on its own `showLibrary` state) adapts this to the
 * `{ onSelect, onClose }`-only `FieldModalProps` shape.
 */
export interface MediaLibraryModalProps {
  open: boolean
  onClose: () => void
  /** Called with the selected asset's public display URL. */
  onSelect: (url: string) => void
}

/* --------------------------------------------------------------------
 * Constants
 * ------------------------------------------------------------------ */

const PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 300

// Matches backend media_service.ALLOWED_MIME_TYPES.
const ACCEPTED_MIME_TYPES = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/svg+xml',
  'image/gif',
] as const

// 10 MB — matches backend MAX_UPLOAD_SIZE.
const MAX_UPLOAD_SIZE = 10_485_760

const ACCEPT_ATTR = ACCEPTED_MIME_TYPES.join(',')

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

/**
 * Build the public URL for an asset. The backend stores
 * `original_path` as a server-side filesystem path (e.g.
 * `/app/uploads/page-editor/{uuid}/{filename}`). The frontend-facing
 * URL strips the container-internal `/app/uploads` prefix and relies
 * on nginx to serve files from `/uploads/...`.
 */
function assetDisplayUrl(asset: MediaAsset): string {
  const byPath = asset.original_path
    ? asset.original_path.replace(/^\/?app\/uploads/, '/uploads')
    : ''
  if (byPath.startsWith('/uploads/')) return byPath

  // Fallback: construct from id + filename. Matches the upload layout
  // `app_uploads/page-editor/{uuid}/{filename}`.
  return `/uploads/page-editor/${asset.id}/${encodeURIComponent(asset.filename)}`
}

/** Format byte count as "1.2 MB" / "245 KB" / "512 B". */
function formatSize(bytes: number): string {
  if (!bytes || bytes < 1024) return `${bytes ?? 0} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Format dimensions as "1920×1080" or "—" if unknown. */
function formatDims(w: number | null, h: number | null): string {
  if (!w || !h) return '—'
  return `${w}×${h}`
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

export function MediaLibraryModal({
  open,
  onClose,
  onSelect,
}: MediaLibraryModalProps): ReactElement | null {
  /* ---- Search state --------------------------------------------- */
  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  /* ---- Listing state -------------------------------------------- */
  const [items, setItems] = useState<MediaAsset[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [listError, setListError] = useState('')

  /* ---- Upload / delete state ------------------------------------ */
  const [uploading, setUploading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)

  /* ---- Refs ----------------------------------------------------- */
  const listAbortRef = useRef<AbortController | null>(null)
  const uploadAbortRef = useRef<AbortController | null>(null)
  const deleteAbortRef = useRef<AbortController | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const dragCounterRef = useRef(0)

  /* ---- Toasts --------------------------------------------------- */
  const { toasts, addToast, dismissToast } = useToast()

  const titleId = 'media-library-modal-title'

  /* ---- Debounce search ----------------------------------------- */

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [searchInput])

  /* ---- Reset on open/close ------------------------------------- */

  useEffect(() => {
    if (!open) {
      setItems([])
      setTotal(0)
      setOffset(0)
      setSearchInput('')
      setDebouncedSearch('')
      setListError('')
      setDragActive(false)
      dragCounterRef.current = 0
      listAbortRef.current?.abort()
      uploadAbortRef.current?.abort()
      deleteAbortRef.current?.abort()
      listAbortRef.current = null
      uploadAbortRef.current = null
      deleteAbortRef.current = null
    }
  }, [open])

  /* ---- Fetch list ---------------------------------------------- */

  const fetchPage = useCallback(
    async (startOffset: number, search: string, append: boolean) => {
      const controller = new AbortController()
      listAbortRef.current?.abort()
      listAbortRef.current = controller

      if (append) setLoadingMore(true)
      else setLoading(true)
      if (!append) setListError('')

      try {
        const params: Record<string, string | number> = {
          offset: startOffset,
          limit: PAGE_SIZE,
        }
        if (search) params.search = search

        const res = await apiClient.get<MediaListResponse>(
          '/api/v2/admin/page-editor/media',
          { params, signal: controller.signal },
        )
        if (controller.signal.aborted) return

        const next = res.data?.items ?? []
        const nextTotal = res.data?.total ?? 0
        setItems((prev) => (append ? [...prev, ...next] : next))
        setTotal(nextTotal)
        setOffset(startOffset + next.length)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if ((err as { name?: string })?.name === 'CanceledError') return
        const msg = extractDetail(err, 'Failed to load media library.')
        if (append) addToast('error', msg)
        else setListError(msg)
      } finally {
        if (controller.signal.aborted) return
        if (listAbortRef.current === controller) listAbortRef.current = null
        if (append) setLoadingMore(false)
        else setLoading(false)
      }
    },
    [addToast],
  )

  // Initial load and reload on search change while open.
  useEffect(() => {
    if (!open) return
    void fetchPage(0, debouncedSearch, false)
  }, [open, debouncedSearch, fetchPage])

  const handleLoadMore = useCallback(() => {
    if (loadingMore || loading) return
    if (items.length >= total) return
    void fetchPage(offset, debouncedSearch, true)
  }, [fetchPage, offset, debouncedSearch, items.length, total, loadingMore, loading])

  const hasMore = useMemo(() => items.length < total, [items.length, total])

  /* ---- Upload -------------------------------------------------- */

  const uploadFile = useCallback(
    async (file: File) => {
      if (!ACCEPTED_MIME_TYPES.includes(file.type as (typeof ACCEPTED_MIME_TYPES)[number])) {
        addToast(
          'error',
          `Unsupported file type (${file.type || 'unknown'}). Accepted: JPEG, PNG, WebP, SVG, GIF.`,
        )
        return
      }
      if (file.size > MAX_UPLOAD_SIZE) {
        addToast('error', `File is too large (max 10 MB).`)
        return
      }

      const controller = new AbortController()
      uploadAbortRef.current?.abort()
      uploadAbortRef.current = controller

      setUploading(true)
      try {
        const form = new FormData()
        form.append('file', file)
        const res = await apiClient.post<MediaAsset>(
          '/api/v2/admin/page-editor/media',
          form,
          {
            signal: controller.signal,
            headers: { 'Content-Type': 'multipart/form-data' },
          },
        )
        if (controller.signal.aborted) return
        const asset = res.data
        if (asset) {
          // Prepend so the newly-uploaded image is visible immediately.
          setItems((prev) => [asset, ...prev])
          setTotal((prev) => prev + 1)
          setOffset((prev) => prev + 1)
          addToast('success', `Uploaded "${asset.filename}".`)
        }
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if ((err as { name?: string })?.name === 'CanceledError') return
        addToast('error', extractDetail(err, `Failed to upload "${file.name}".`))
      } finally {
        if (uploadAbortRef.current === controller) uploadAbortRef.current = null
        setUploading(false)
      }
    },
    [addToast],
  )

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files)
      for (const file of list) {
        // Sequential so the toast order is predictable and we don't
        // overwhelm the backend with a huge batch at once.
        // eslint-disable-next-line no-await-in-loop
        await uploadFile(file)
      }
    },
    [uploadFile],
  )

  /* ---- File input & drag-and-drop handlers --------------------- */

  const handleFileInputChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files
      if (files && files.length > 0) {
        void uploadFiles(files)
      }
      // Reset so selecting the same file again re-triggers change.
      e.target.value = ''
    },
    [uploadFiles],
  )

  const openFilePicker = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleDragEnter = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounterRef.current += 1
    if (e.dataTransfer?.types?.includes('Files')) {
      setDragActive(true)
    }
  }, [])

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy'
    }
  }, [])

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1)
    if (dragCounterRef.current === 0) setDragActive(false)
  }, [])

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      e.stopPropagation()
      dragCounterRef.current = 0
      setDragActive(false)
      const files = e.dataTransfer?.files
      if (files && files.length > 0) {
        void uploadFiles(files)
      }
    },
    [uploadFiles],
  )

  /* ---- Delete -------------------------------------------------- */

  const handleDelete = useCallback(
    async (asset: MediaAsset) => {
      if (deletingId) return
      const confirmed = window.confirm(
        `Delete "${asset.filename}"? This cannot be undone.`,
      )
      if (!confirmed) return

      const controller = new AbortController()
      deleteAbortRef.current?.abort()
      deleteAbortRef.current = controller

      setDeletingId(asset.id)
      try {
        await apiClient.delete(
          `/api/v2/admin/page-editor/media/${encodeURIComponent(asset.id)}`,
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setItems((prev) => prev.filter((a) => a.id !== asset.id))
        setTotal((prev) => Math.max(0, prev - 1))
        setOffset((prev) => Math.max(0, prev - 1))
        addToast('success', `Deleted "${asset.filename}".`)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if ((err as { name?: string })?.name === 'CanceledError') return
        const status = (err as AxiosError)?.response?.status
        if (status === 409) {
          const detail = extractDetail(
            err,
            'Cannot delete: image is referenced by one or more pages.',
          )
          addToast('error', `Cannot delete: image is used by ${detail}`)
        } else {
          addToast('error', extractDetail(err, `Failed to delete "${asset.filename}".`))
        }
      } finally {
        if (deleteAbortRef.current === controller) deleteAbortRef.current = null
        setDeletingId(null)
      }
    },
    [deletingId, addToast],
  )

  /* ---- Select -------------------------------------------------- */

  const handleSelect = useCallback(
    (asset: MediaAsset) => {
      onSelect(assetDisplayUrl(asset))
      onClose()
    },
    [onSelect, onClose],
  )

  /* ---- Escape-to-close, focus trap, body scroll lock ----------- */

  useEffect(() => {
    if (!open) return

    previousFocusRef.current = document.activeElement as HTMLElement

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (uploading || deletingId) return
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    let releaseTrap: (() => void) | undefined
    const dialog = dialogRef.current
    if (dialog) {
      releaseTrap = trapFocus(dialog)
      dialog.focus()
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = prevOverflow
      releaseTrap?.()
      previousFocusRef.current?.focus?.()
    }
  }, [open, uploading, deletingId, onClose])

  if (!open) return null

  /* ---- Render --------------------------------------------------- */

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        // Click outside dialog = close (match existing drawer behaviour).
        if (e.target === e.currentTarget && !uploading && !deletingId) {
          onClose()
        }
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="flex max-h-[80vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-white shadow-xl focus:outline-none"
        onClick={(e) => e.stopPropagation()}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            Media Library
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={uploading || !!deletingId}
            className="rounded p-1 text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
            aria-label="Close media library"
          >
            <span aria-hidden="true" className="text-xl leading-none">×</span>
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex flex-col gap-3 border-b border-gray-200 bg-gray-50 px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex-1 sm:max-w-md">
            <label htmlFor="media-library-search" className="sr-only">
              Search by filename
            </label>
            <input
              id="media-library-search"
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by filename..."
              className="h-10 w-full rounded-md border border-gray-300 bg-white px-3 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_ATTR}
              multiple
              className="hidden"
              onChange={handleFileInputChange}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={openFilePicker}
              loading={uploading}
              disabled={uploading}
            >
              {uploading ? 'Uploading…' : 'Upload'}
            </Button>
          </div>
        </div>

        {/* Body */}
        <div className="relative flex-1 overflow-y-auto px-6 py-4">
          {dragActive ? (
            <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-blue-500 bg-blue-50/90 text-blue-700">
              <p className="text-sm font-medium">
                Drop images here to upload (JPEG, PNG, WebP, SVG, GIF — max 10 MB)
              </p>
            </div>
          ) : null}

          {listError ? (
            <AlertBanner variant="error" className="mb-4">
              {listError}
            </AlertBanner>
          ) : null}

          {loading && items.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <Spinner />
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-sm text-gray-600">
                {debouncedSearch
                  ? `No images match "${debouncedSearch}".`
                  : 'No images uploaded yet.'}
              </p>
              {!debouncedSearch ? (
                <p className="mt-1 text-xs text-gray-500">
                  Drop images into this modal or click Upload to get started.
                </p>
              ) : null}
            </div>
          ) : (
            <>
              <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                {items.map((asset) => {
                  const url = assetDisplayUrl(asset)
                  const isDeleting = deletingId === asset.id
                  return (
                    <li
                      key={asset.id}
                      className="group relative overflow-hidden rounded-md border border-gray-200 bg-white shadow-sm transition hover:border-blue-400 hover:shadow-md"
                    >
                      <button
                        type="button"
                        onClick={() => handleSelect(asset)}
                        disabled={isDeleting}
                        className="block w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
                        aria-label={`Select ${asset.filename}`}
                      >
                        <div className="aspect-square w-full bg-gray-100">
                          <img
                            src={url}
                            alt=""
                            loading="lazy"
                            className="h-full w-full object-contain"
                            onError={(e) => {
                              ;(e.target as HTMLImageElement).style.visibility =
                                'hidden'
                            }}
                          />
                        </div>
                        <div className="px-2 py-1.5">
                          <p
                            className="truncate text-xs font-medium text-gray-900"
                            title={asset.filename}
                          >
                            {asset.filename}
                          </p>
                          <p className="text-[11px] text-gray-500">
                            {formatDims(asset.width, asset.height)} ·{' '}
                            {formatSize(asset.size_bytes)}
                          </p>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          void handleDelete(asset)
                        }}
                        disabled={isDeleting || uploading}
                        className="absolute right-1.5 top-1.5 rounded-md bg-white/90 p-1.5 text-gray-600 opacity-0 shadow-sm transition hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-50"
                        aria-label={`Delete ${asset.filename}`}
                        title="Delete"
                      >
                        {isDeleting ? (
                          <span className="block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
                        ) : (
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            className="h-4 w-4"
                            aria-hidden="true"
                          >
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                            <path d="M10 11v6" />
                            <path d="M14 11v6" />
                            <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
                          </svg>
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>

              {/* Pagination */}
              {hasMore ? (
                <div className="mt-6 flex justify-center">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleLoadMore}
                    loading={loadingMore}
                    disabled={loadingMore}
                  >
                    {loadingMore
                      ? 'Loading…'
                      : `Load more (${items.length} of ${total})`}
                  </Button>
                </div>
              ) : items.length > 0 ? (
                <p className="mt-6 text-center text-xs text-gray-500">
                  Showing all {items.length}{' '}
                  {items.length === 1 ? 'image' : 'images'}.
                </p>
              ) : null}
            </>
          )}
        </div>

        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------
 * Register with MediaField so the custom Puck field picks up this
 * real modal instead of the placeholder. `MediaField` already gates
 * the modal's mounting on its own `showLibrary` state and hands us
 * `{ onSelect, onClose }` only, so we wrap the standalone modal and
 * force `open={true}` — MediaField unmounts us when the user
 * finishes or cancels.
 * ------------------------------------------------------------------ */

function MediaLibraryModalForField({
  onSelect,
  onClose,
}: FieldModalProps): ReactElement {
  return (
    <MediaLibraryModal open onSelect={onSelect} onClose={onClose} />
  )
}

registerMediaLibraryModal(MediaLibraryModalForField)

export default MediaLibraryModal
