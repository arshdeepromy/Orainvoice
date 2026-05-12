/**
 * CreatePageModal — full "New Page" dialog for the visual page editor.
 *
 * Collects the fields required by Requirement 8:
 *   - title (required, 1–120 chars)
 *   - page_slug (required, auto-derived from the title until the user
 *     manually edits it, or pre-filled via `initialData` for the
 *     duplicate flow)
 *   - template (radio cards sourced from `templates.ts`)
 *   - meta_title (optional, max 120 chars)
 *   - meta_description (optional, max 320 chars)
 *
 * Client-side validation mirrors the backend:
 *   - slug must match `^/(?:[a-z0-9-]+)(?:/[a-z0-9-]+){0,2}$`
 *   - slug must be at most 80 characters
 *   - slug must not start with any entry in `RESERVED_PREFIXES`
 *
 * Submits to `POST /api/v2/admin/page-editor/pages`. On success, calls
 * `onCreated?.({ page_key, page_slug })`, closes the modal, and
 * navigates to `/admin/page-editor/{page_key}`.
 *
 * Duplicate flow: when `initialData.content` is set, it is forwarded as
 * `content` in the POST body (overrides the template on the backend).
 * When `initialData.hideTemplate` is true, the template picker is not
 * rendered. When `initialData` is passed, slug auto-derivation is
 * disabled (the user is deliberately duplicating an existing page).
 *
 * Error handling:
 *   - 409 slug conflict  → inline error under slug field
 *   - 422 validation     → inline error (slug-level detail when possible,
 *                          otherwise banner)
 *   - 500+               → banner above the form
 *
 * Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { AxiosError } from 'axios'
import apiClient from '../../../api/client'
import { AlertBanner, Button, Input, Modal } from '../../../components/ui'
import { PAGE_TEMPLATES, getTemplateByKey } from '../templates'

/* --------------------------------------------------------------------
 * Types
 * ------------------------------------------------------------------ */

export interface CreatePageInitialData {
  /** Suggested title, e.g. "{original} (Copy)". */
  title?: string
  /** Suggested slug, e.g. "/about-copy". */
  page_slug?: string
  /** Pre-filled Puck_Data for duplicate flow — sent as `content` on POST. */
  content?: Record<string, unknown>
  /** When true, hide the template picker (duplicate flow). */
  hideTemplate?: boolean
  /** Optional pre-filled SEO fields (duplicate flow). */
  meta_title?: string
  meta_description?: string
}

export interface CreatePageModalProps {
  open: boolean
  onClose: () => void
  /** Called after the page is created successfully. */
  onCreated?: (page: { page_key: string; page_slug: string }) => void
  /** Optional pre-filled data for the duplicate flow. */
  initialData?: CreatePageInitialData
}

interface CreatePageResponse {
  page_key: string
  page_slug: string
  title: string
}

/* --------------------------------------------------------------------
 * Constants — slug validation
 *
 * Mirrors `app/modules/page_editor/service.py::RESERVED_PREFIXES` and
 * `validate_slug()`. Kept client-side so obvious mistakes are caught
 * before hitting the API.
 * ------------------------------------------------------------------ */

const SLUG_PATTERN = /^\/(?:[a-z0-9-]+)(?:\/[a-z0-9-]+){0,2}$/
const SLUG_MAX_LENGTH = 80

/**
 * Reserved first-segment prefixes. Must stay in sync with the backend
 * `RESERVED_PREFIXES` set — any slug whose first path segment matches
 * one of these (plus any deeper segments) is rejected client-side.
 *
 * `/workshop`, `/trades`, `/privacy` are included here too: those are
 * hand-coded pages claimed by a known `page_key`, and the New-Page
 * flow is strictly for creating *new* editor-only pages, so we block
 * them to prevent accidents. Admins who want to replace those render
 * the existing Hand_Coded_Page via the editor directly.
 */
const RESERVED_PREFIXES: ReadonlySet<string> = new Set([
  '/admin',
  '/api',
  '/auth',
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
  '/verify-email',
  '/mfa',
  '/dashboard',
  '/invoices',
  '/quotes',
  '/customers',
  '/inventory',
  '/jobs',
  '/reports',
  '/settings',
  '/billing',
  '/staff',
  '/schedule',
  '/expenses',
  '/purchase-orders',
  '/compliance',
  '/franchise',
  '/accounting',
  '/banking',
  '/tax',
  '/pos',
  '/kiosk',
  '/workshop',
  '/trades',
  '/privacy',
  '/assets',
  '/static',
  '/uploads',
  '/health',
  '/ws',
  '/_',
  '/mechanics',
  '/garage',
])

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

/**
 * Derive a URL slug from a title.
 *
 * Mirrors `app/modules/page_editor/service.py::title_to_slug`:
 *   1. Unicode-normalize (NFKD) and strip combining diacritics
 *   2. Lowercase and ASCII-fold
 *   3. Replace whitespace/underscores with hyphens
 *   4. Drop any character outside [a-z0-9-]
 *   5. Collapse repeated hyphens and trim leading/trailing hyphens
 *   6. Prefix with `/`, falling back to `/untitled` when empty.
 */
export function deriveSlug(title: string): string {
  const normalized = title.normalize('NFKD')
  const ascii = normalized.replace(/[\u0300-\u036f]/g, '').toLowerCase()
  const kebab = ascii
    .replace(/[\s_]+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
  return kebab ? `/${kebab}` : '/untitled'
}

/**
 * Validate a slug client-side. Returns null when valid, or a
 * user-facing error message when invalid. Checks pattern, length and
 * reserved prefixes.
 */
export function validateSlugClient(slug: string): string | null {
  if (!slug) return 'Slug is required.'
  if (slug.length > SLUG_MAX_LENGTH) {
    return `Slug must be at most ${SLUG_MAX_LENGTH} characters.`
  }
  if (!SLUG_PATTERN.test(slug)) {
    return 'Slug must start with "/" and contain only lowercase letters, numbers, and hyphens (e.g. /about or /services/pricing).'
  }
  const firstSegment = `/${slug.slice(1).split('/')[0]}`
  if (RESERVED_PREFIXES.has(firstSegment)) {
    return `Slug prefix "${firstSegment}" is reserved and cannot be used for a public page.`
  }
  return null
}

/** Extract a human-readable error detail from an Axios error. */
function extractDetail(err: unknown, fallback: string): string {
  const axiosErr = err as AxiosError<{ detail?: unknown }>
  const detail = axiosErr?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors are a list of { loc, msg, type }
    const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined
    if (first?.msg) return first.msg
  }
  return fallback
}

/* --------------------------------------------------------------------
 * Component
 * ------------------------------------------------------------------ */

export function CreatePageModal({
  open,
  onClose,
  onCreated,
  initialData,
}: CreatePageModalProps) {
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [templateKey, setTemplateKey] = useState<string>('blank')
  const [metaTitle, setMetaTitle] = useState('')
  const [metaDescription, setMetaDescription] = useState('')

  /**
   * True once the user has manually edited the slug, in which case we
   * stop auto-deriving it from the title. Also true from the start in
   * the duplicate flow (the caller is providing the slug deliberately).
   */
  const [slugDirty, setSlugDirty] = useState(false)

  const [saving, setSaving] = useState(false)
  const [slugError, setSlugError] = useState<string | null>(null)
  const [titleError, setTitleError] = useState<string | null>(null)
  const [bannerError, setBannerError] = useState<string>('')

  const abortRef = useRef<AbortController | null>(null)

  const isDuplicate = useMemo(
    () => !!initialData?.content || !!initialData?.hideTemplate,
    [initialData],
  )
  const showTemplate = !initialData?.hideTemplate

  /* ---- Reset state every time the modal opens --------------------- */
  useEffect(() => {
    if (!open) return
    setTitle(initialData?.title ?? '')
    setSlug(initialData?.page_slug ?? '')
    setTemplateKey('blank')
    setMetaTitle(initialData?.meta_title ?? '')
    setMetaDescription(initialData?.meta_description ?? '')
    // In the duplicate flow, the slug is user-authored from the start;
    // also treat any pre-filled slug as already-dirty so the title
    // doesn't silently overwrite it.
    setSlugDirty(!!initialData?.page_slug || !!initialData)
    setSlugError(null)
    setTitleError(null)
    setBannerError('')
  }, [open, initialData])

  /* ---- Abort any in-flight create when the modal closes ---------- */
  useEffect(() => {
    if (!open && abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [open])

  /* ---- Title change handler — auto-derive slug until dirty -------- */
  const handleTitleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const next = e.target.value
      setTitle(next)
      if (titleError) setTitleError(null)
      if (!slugDirty) {
        setSlug(deriveSlug(next))
        setSlugError(null)
      }
    },
    [slugDirty, titleError],
  )

  /* ---- Slug change handler — mark as user-edited ------------------ */
  const handleSlugChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSlug(e.target.value)
      setSlugDirty(true)
      if (slugError) setSlugError(null)
    },
    [slugError],
  )

  /* ---- Submit ----------------------------------------------------- */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (saving) return

      const trimmedTitle = title.trim()
      const trimmedSlug = slug.trim()

      // Client-side validation mirroring the backend rules
      let hasError = false
      if (!trimmedTitle) {
        setTitleError('Title is required.')
        hasError = true
      } else if (trimmedTitle.length > 120) {
        setTitleError('Title must be at most 120 characters.')
        hasError = true
      }

      const slugValidationError = validateSlugClient(trimmedSlug)
      if (slugValidationError) {
        setSlugError(slugValidationError)
        hasError = true
      }

      if (metaTitle.length > 120) {
        setBannerError('Meta title must be at most 120 characters.')
        hasError = true
      } else if (metaDescription.length > 320) {
        setBannerError('Meta description must be at most 320 characters.')
        hasError = true
      }

      if (hasError) return

      setBannerError('')
      setSaving(true)

      const controller = new AbortController()
      abortRef.current = controller

      const body: Record<string, unknown> = {
        title: trimmedTitle,
        page_slug: trimmedSlug,
        template: templateKey,
      }
      if (metaTitle.trim()) body.meta_title = metaTitle.trim()
      if (metaDescription.trim()) body.meta_description = metaDescription.trim()
      // Duplicate flow: forward pre-filled content (overrides template on server)
      if (initialData?.content) {
        body.content = initialData.content
      }

      try {
        const res = await apiClient.post<CreatePageResponse>(
          '/api/v2/admin/page-editor/pages',
          body,
          { signal: controller.signal },
        )
        const created = res.data
        if (!created?.page_key) {
          setBannerError('Page was created but the server response was unexpected.')
          return
        }
        onCreated?.({
          page_key: created.page_key,
          page_slug: created.page_slug,
        })
        onClose()
        navigate(`/admin/page-editor/${encodeURIComponent(created.page_key)}`)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        if (controller.signal.aborted) return

        const status = (err as AxiosError)?.response?.status
        if (status === 409) {
          setSlugError(
            extractDetail(
              err,
              `The slug "${trimmedSlug}" is already in use by another page or redirect.`,
            ),
          )
        } else if (status === 422) {
          const detail = extractDetail(err, 'Invalid slug or payload.')
          // Route slug-related messages to the slug field, otherwise banner
          if (/slug/i.test(detail)) {
            setSlugError(detail)
          } else {
            setBannerError(detail)
          }
        } else {
          setBannerError(extractDetail(err, 'Failed to create page. Please try again.'))
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null
        setSaving(false)
      }
    },
    [
      saving,
      title,
      slug,
      templateKey,
      metaTitle,
      metaDescription,
      initialData,
      onCreated,
      onClose,
      navigate,
    ],
  )

  /* ---- Render ----------------------------------------------------- */

  const metaTitleHelper = `${metaTitle.length}/120 characters`
  const metaDescHelper = `${metaDescription.length}/320 characters`
  const chosenTemplate = getTemplateByKey(templateKey)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isDuplicate ? 'Duplicate page' : 'New page'}
      className="max-w-2xl"
    >
      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        {bannerError && (
          <AlertBanner variant="error" title="Could not create page">
            {bannerError}
          </AlertBanner>
        )}

        <Input
          label="Page title"
          value={title}
          onChange={handleTitleChange}
          placeholder="About us"
          maxLength={120}
          autoFocus
          required
          error={titleError ?? undefined}
          helperText={
            titleError ? undefined : '1–120 characters. Shown as the page heading and in browser tabs.'
          }
        />

        <Input
          label="Slug"
          value={slug}
          onChange={handleSlugChange}
          placeholder="/about"
          maxLength={SLUG_MAX_LENGTH}
          required
          error={slugError ?? undefined}
          helperText={
            slugError
              ? undefined
              : isDuplicate
                ? 'Must start with / and differ from the source page.'
                : 'Auto-derived from the title. Edit to customise. Lowercase letters, numbers and hyphens only.'
          }
        />

        {showTemplate && (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-gray-700">Template</legend>
            <p className="text-xs text-gray-500">
              Choose a starting point. You can fully edit the content after creation.
            </p>
            <div
              role="radiogroup"
              aria-label="Page template"
              className="grid grid-cols-1 gap-2 sm:grid-cols-2"
            >
              {PAGE_TEMPLATES.map((tpl) => {
                const selected = templateKey === tpl.key
                const inputId = `template-${tpl.key}`
                return (
                  <label
                    key={tpl.key}
                    htmlFor={inputId}
                    className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-3 transition-colors
                      ${
                        selected
                          ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                          : 'border-gray-300 bg-white hover:bg-gray-50'
                      }`}
                  >
                    <input
                      id={inputId}
                      type="radio"
                      name="page-template"
                      value={tpl.key}
                      checked={selected}
                      onChange={() => setTemplateKey(tpl.key)}
                      className="mt-1 h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="flex flex-col">
                      <span className="text-sm font-medium text-gray-900">
                        {tpl.name}
                      </span>
                      <span className="text-xs text-gray-600">
                        {tpl.description}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
            <p className="sr-only" aria-live="polite">
              Selected template: {chosenTemplate.name}
            </p>
          </fieldset>
        )}

        <div className="space-y-4 rounded-md border border-gray-200 bg-gray-50 p-4">
          <p className="text-sm font-medium text-gray-700">
            SEO (optional)
          </p>
          <Input
            label="Meta title"
            value={metaTitle}
            onChange={(e) => setMetaTitle(e.target.value)}
            placeholder="Leave blank to use the page title"
            maxLength={120}
            helperText={metaTitleHelper}
          />
          <div className="flex flex-col gap-1">
            <label
              htmlFor="create-page-meta-description"
              className="text-sm font-medium text-gray-700"
            >
              Meta description
            </label>
            <textarea
              id="create-page-meta-description"
              value={metaDescription}
              onChange={(e) => setMetaDescription(e.target.value)}
              placeholder="Short summary shown by search engines and social previews."
              maxLength={320}
              rows={3}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm transition-colors
                placeholder:text-gray-400
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
            <p className="text-sm text-gray-500">{metaDescHelper}</p>
          </div>
        </div>

        <p className="text-xs text-gray-500">
          The page will be created as a draft and will <strong>not</strong> be
          publicly visible until you publish it.
        </p>

        <div className="flex justify-end gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button type="submit" loading={saving} disabled={saving}>
            {isDuplicate ? 'Duplicate page' : 'Create page'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

export default CreatePageModal
