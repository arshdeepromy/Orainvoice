/**
 * PageSettingsDrawer — slide-over drawer for editing page settings and SEO.
 *
 * Opened from the `EditorToolbar` settings (⚙) button inside
 * `PageEditorEdit`. Presents the full settings surface documented in
 * Design Gap C: title, slug, noindex, SEO (meta title/description,
 * canonical), social (OG image/type, Twitter card), and structured
 * data (JSON-LD). Hand-coded pages receive a read-only slug with an
 * explanatory tooltip and expose a "Revert to Fallback" danger button;
 * editor-created pages can freely rename their slug (which the backend
 * uses to create a 301 redirect from the old value).
 *
 * JSON-LD is accepted as either a single object or an array of
 * objects. It is validated on blur: invalid JSON paints the textarea
 * red and disables Save until the field is cleared or fixed.
 *
 * On save, `PUT /api/v2/admin/page-editor/pages/:page_key/settings` is
 * called with only the changed fields (the slug is always omitted for
 * hand-coded pages). The caller receives the updated `PageDetail` via
 * `onSaved()` so the editor can sync its local state without a full
 * refetch.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.7, 6.10
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { AxiosError } from 'axios'
import apiClient from '../../../api/client'
import { AlertBanner, Button, Input, Select } from '../../../components/ui'
import { trapFocus } from '../../../utils/accessibility'

/* --------------------------------------------------------------------
 * Types
 * ------------------------------------------------------------------ */

export type PageOrigin = 'hand-coded' | 'editor-created'

/**
 * Shape of the page detail used by this drawer — intentionally narrow
 * so callers can pass their existing PageDetail object without a cast.
 */
export interface PageSettingsPageDetail {
  page_key: string
  title: string
  page_slug: string
  page_origin: PageOrigin
  noindex: boolean
  seo: Record<string, unknown> | null
  [extra: string]: unknown
}

export interface PageSettingsDrawerProps {
  open: boolean
  onClose: () => void
  pageDetail: PageSettingsPageDetail
  /** Called after a successful save with the server's response. */
  onSaved: (updated: PageSettingsPageDetail) => void
  /**
   * Optional — only shown for hand-coded pages. When provided, renders
   * a danger-zone "Revert to Fallback" button. Clicking it closes the
   * drawer and defers the confirm flow to the parent (which owns the
   * `RevertToFallbackModal`).
   */
  onRevertToFallback?: () => void
}

/* --------------------------------------------------------------------
 * Constants
 * ------------------------------------------------------------------ */

const OG_TYPE_OPTIONS = [
  { value: 'website', label: 'Website' },
  { value: 'article', label: 'Article' },
  { value: 'product', label: 'Product' },
] as const

const TWITTER_CARD_OPTIONS = [
  { value: 'summary', label: 'Summary' },
  { value: 'summary_large_image', label: 'Summary (large image)' },
] as const

const SLUG_PATTERN = /^\/(?:[a-z0-9-]+)(?:\/[a-z0-9-]+){0,2}$/
const SLUG_MAX_LENGTH = 80
const META_TITLE_MAX = 120
const META_DESC_MAX = 320
const TITLE_MAX = 120

/* --------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------ */

/**
 * Normalise a raw SEO field value from the server into a string safe
 * for display in an `<input>` or `<textarea>`. Non-string values are
 * ignored (they should not exist for these fields but we guard anyway).
 */
function seoString(seo: Record<string, unknown> | null | undefined, key: string): string {
  if (!seo) return ''
  const v = seo[key]
  return typeof v === 'string' ? v : ''
}

/**
 * Serialise the stored `seo.json_ld` value back to a human-editable
 * textarea string. `null`/missing → empty; list with one entry → the
 * entry pretty-printed; list with many entries → the list
 * pretty-printed.
 */
function jsonLdToText(seo: Record<string, unknown> | null | undefined): string {
  if (!seo) return ''
  const value = seo.json_ld
  if (value == null) return ''
  if (Array.isArray(value)) {
    if (value.length === 0) return ''
    if (value.length === 1) return JSON.stringify(value[0], null, 2)
    return JSON.stringify(value, null, 2)
  }
  // Shouldn't happen (schema is list[dict]) but render defensively.
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return ''
  }
}

/**
 * Parse a JSON-LD textarea value. Returns `{ ok: true, value: null }`
 * for empty input, `{ ok: true, value: [...] }` for valid input
 * (single objects are wrapped in a one-element array to match the
 * backend shape), or `{ ok: false, error }` for invalid input.
 */
function parseJsonLd(
  text: string,
): { ok: true; value: Array<Record<string, unknown>> | null } | { ok: false; error: string } {
  const trimmed = text.trim()
  if (!trimmed) return { ok: true, value: null }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Invalid JSON'
    return { ok: false, error: `Invalid JSON: ${message}` }
  }
  const arr = Array.isArray(parsed) ? parsed : [parsed]
  for (const [i, item] of arr.entries()) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      return {
        ok: false,
        error: `JSON-LD entry ${i + 1} must be an object (got ${Array.isArray(item) ? 'array' : typeof item}).`,
      }
    }
  }
  return { ok: true, value: arr as Array<Record<string, unknown>> }
}

/** Pull a human-readable error detail out of an axios error. */
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

/** Client-side mirror of the backend slug validation (shape + length). */
function validateSlug(slug: string): string | null {
  if (!slug) return 'Slug is required.'
  if (slug.length > SLUG_MAX_LENGTH) {
    return `Slug must be at most ${SLUG_MAX_LENGTH} characters.`
  }
  if (!SLUG_PATTERN.test(slug)) {
    return 'Slug must start with "/" and contain only lowercase letters, numbers, and hyphens.'
  }
  return null
}

/* --------------------------------------------------------------------
 * Small presentational helpers
 * ------------------------------------------------------------------ */

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 pt-2" aria-hidden="true">
      <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
        {label}
      </span>
      <span className="h-px flex-1 bg-gray-200" />
    </div>
  )
}

interface FieldProps {
  label: string
  htmlFor: string
  error?: string | null
  helper?: string
  required?: boolean
  children: ReactNode
}

function Field({ label, htmlFor, error, helper, required, children }: FieldProps) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-sm font-medium text-gray-700">
        {label}
        {required && <span className="ml-1 text-red-500" aria-hidden="true">*</span>}
      </label>
      {children}
      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
      {helper && !error && <p className="text-xs text-gray-500">{helper}</p>}
    </div>
  )
}

/* --------------------------------------------------------------------
 * Component
 * ------------------------------------------------------------------ */

export function PageSettingsDrawer({
  open,
  onClose,
  pageDetail,
  onSaved,
  onRevertToFallback,
}: PageSettingsDrawerProps) {
  const isHandCoded = pageDetail.page_origin === 'hand-coded'

  /* ---- Form state ------------------------------------------------- */
  const [title, setTitle] = useState(pageDetail.title)
  const [slug, setSlug] = useState(pageDetail.page_slug)
  const [noindex, setNoindex] = useState(pageDetail.noindex)
  const [metaTitle, setMetaTitle] = useState(() => seoString(pageDetail.seo, 'meta_title'))
  const [metaDescription, setMetaDescription] = useState(() =>
    seoString(pageDetail.seo, 'meta_description'),
  )
  const [canonical, setCanonical] = useState(() => seoString(pageDetail.seo, 'canonical'))
  const [ogImage, setOgImage] = useState(() => seoString(pageDetail.seo, 'og_image'))
  const [ogType, setOgType] = useState(() => seoString(pageDetail.seo, 'og_type') || 'website')
  const [twitterCard, setTwitterCard] = useState(
    () => seoString(pageDetail.seo, 'twitter_card') || 'summary_large_image',
  )
  const [jsonLd, setJsonLd] = useState(() => jsonLdToText(pageDetail.seo))

  /* ---- Validation state ------------------------------------------- */
  const [titleError, setTitleError] = useState<string | null>(null)
  const [slugError, setSlugError] = useState<string | null>(null)
  const [canonicalError, setCanonicalError] = useState<string | null>(null)
  const [jsonLdError, setJsonLdError] = useState<string | null>(null)

  /* ---- Submission state ------------------------------------------- */
  const [saving, setSaving] = useState(false)
  const [bannerError, setBannerError] = useState<string>('')
  const abortRef = useRef<AbortController | null>(null)

  /* ---- Focus + accessibility ------------------------------------- */
  const panelRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const titleId = 'page-settings-drawer-title'

  /* ---- Reset state whenever the drawer opens or the page changes */
  useEffect(() => {
    if (!open) return
    setTitle(pageDetail.title)
    setSlug(pageDetail.page_slug)
    setNoindex(pageDetail.noindex)
    setMetaTitle(seoString(pageDetail.seo, 'meta_title'))
    setMetaDescription(seoString(pageDetail.seo, 'meta_description'))
    setCanonical(seoString(pageDetail.seo, 'canonical'))
    setOgImage(seoString(pageDetail.seo, 'og_image'))
    setOgType(seoString(pageDetail.seo, 'og_type') || 'website')
    setTwitterCard(seoString(pageDetail.seo, 'twitter_card') || 'summary_large_image')
    setJsonLd(jsonLdToText(pageDetail.seo))
    setTitleError(null)
    setSlugError(null)
    setCanonicalError(null)
    setJsonLdError(null)
    setBannerError('')
  }, [open, pageDetail])

  /* ---- Escape-to-close, focus trap, body scroll lock -------------- */
  useEffect(() => {
    if (!open) return

    previousFocusRef.current = document.activeElement as HTMLElement

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (!saving) onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)

    // Lock body scroll while the drawer is open
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // Trap focus within the panel
    let releaseTrap: (() => void) | undefined
    if (panelRef.current) {
      releaseTrap = trapFocus(panelRef.current)
      // Move initial focus to the panel itself for screen readers
      panelRef.current.focus()
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = prevOverflow
      releaseTrap?.()
      previousFocusRef.current?.focus?.()
    }
  }, [open, onClose, saving])

  /* ---- Abort in-flight save on close ----------------------------- */
  useEffect(() => {
    if (!open && abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [open])

  /* ---- Field blur validators ------------------------------------- */

  const handleTitleBlur = useCallback(() => {
    const trimmed = title.trim()
    if (!trimmed) setTitleError('Title is required.')
    else if (trimmed.length > TITLE_MAX)
      setTitleError(`Title must be at most ${TITLE_MAX} characters.`)
    else setTitleError(null)
  }, [title])

  const handleSlugBlur = useCallback(() => {
    if (isHandCoded) return
    setSlugError(validateSlug(slug.trim()))
  }, [slug, isHandCoded])

  const handleCanonicalBlur = useCallback(() => {
    const trimmed = canonical.trim()
    if (!trimmed) {
      setCanonicalError(null)
      return
    }
    if (!trimmed.startsWith('https://')) {
      setCanonicalError('Canonical URL must be a fully-qualified https:// URL.')
    } else {
      setCanonicalError(null)
    }
  }, [canonical])

  const handleJsonLdBlur = useCallback(() => {
    const result = parseJsonLd(jsonLd)
    if (result.ok) setJsonLdError(null)
    else setJsonLdError(result.error)
  }, [jsonLd])

  /* ---- Derived state --------------------------------------------- */

  const hasFieldError = useMemo(
    () =>
      !!titleError ||
      !!slugError ||
      !!canonicalError ||
      !!jsonLdError,
    [titleError, slugError, canonicalError, jsonLdError],
  )

  /* ---- Save ------------------------------------------------------ */

  const handleSave = useCallback(async () => {
    if (saving) return

    // Re-run blur validators so stale errors don't block the save
    const trimmedTitle = title.trim()
    const trimmedSlug = slug.trim()
    const trimmedCanonical = canonical.trim()

    let localTitleError: string | null = null
    if (!trimmedTitle) localTitleError = 'Title is required.'
    else if (trimmedTitle.length > TITLE_MAX)
      localTitleError = `Title must be at most ${TITLE_MAX} characters.`
    setTitleError(localTitleError)

    let localSlugError: string | null = null
    if (!isHandCoded) localSlugError = validateSlug(trimmedSlug)
    setSlugError(localSlugError)

    let localCanonicalError: string | null = null
    if (trimmedCanonical && !trimmedCanonical.startsWith('https://')) {
      localCanonicalError = 'Canonical URL must be a fully-qualified https:// URL.'
    }
    setCanonicalError(localCanonicalError)

    const parsedJsonLd = parseJsonLd(jsonLd)
    const localJsonLdError = parsedJsonLd.ok ? null : parsedJsonLd.error
    setJsonLdError(localJsonLdError)

    if (
      localTitleError ||
      localSlugError ||
      localCanonicalError ||
      localJsonLdError
    ) {
      setBannerError('Please fix the highlighted fields and try again.')
      return
    }

    if (metaTitle.length > META_TITLE_MAX) {
      setBannerError(`Meta title must be at most ${META_TITLE_MAX} characters.`)
      return
    }
    if (metaDescription.length > META_DESC_MAX) {
      setBannerError(`Meta description must be at most ${META_DESC_MAX} characters.`)
      return
    }

    setBannerError('')

    // Build the request body — only include slug if it changed AND the
    // page is editor-created. All other fields are sent as-is (empty
    // strings clear the SEO field on the server).
    const body: Record<string, unknown> = {
      title: trimmedTitle,
      noindex,
      meta_title: metaTitle.trim() || null,
      meta_description: metaDescription.trim() || null,
      canonical: trimmedCanonical || null,
      og_image: ogImage.trim() || null,
      og_type: ogType || null,
      twitter_card: twitterCard || null,
      json_ld: parsedJsonLd.ok ? parsedJsonLd.value : null,
    }
    if (!isHandCoded && trimmedSlug && trimmedSlug !== pageDetail.page_slug) {
      body.page_slug = trimmedSlug
    }

    const controller = new AbortController()
    abortRef.current = controller
    setSaving(true)

    try {
      const res = await apiClient.put<PageSettingsPageDetail>(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageDetail.page_key)}/settings`,
        body,
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      const updated = res.data
      if (!updated) {
        setBannerError('Settings were saved but the server response was unexpected.')
        return
      }
      onSaved(updated)
      onClose()
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      if (controller.signal.aborted) return

      const status = (err as AxiosError)?.response?.status
      if (status === 409) {
        // Could be slug conflict or hand-coded slug change attempt
        const detail = extractDetail(err, 'Slug conflict.')
        if (/slug/i.test(detail)) setSlugError(detail)
        else setBannerError(detail)
      } else if (status === 422) {
        const detail = extractDetail(err, 'Invalid settings payload.')
        if (/slug/i.test(detail)) setSlugError(detail)
        else if (/canonical/i.test(detail)) setCanonicalError(detail)
        else if (/json.?ld/i.test(detail)) setJsonLdError(detail)
        else setBannerError(detail)
      } else if (status === 410) {
        setBannerError('This page has been deleted and cannot be edited.')
      } else {
        setBannerError(extractDetail(err, 'Failed to save settings. Please try again.'))
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setSaving(false)
    }
  }, [
    saving,
    title,
    slug,
    isHandCoded,
    canonical,
    jsonLd,
    metaTitle,
    metaDescription,
    noindex,
    ogImage,
    ogType,
    twitterCard,
    pageDetail.page_key,
    pageDetail.page_slug,
    onSaved,
    onClose,
  ])

  /* ---- Render ---------------------------------------------------- */

  if (!open) return null

  const metaTitleCount = `${metaTitle.length}/${META_TITLE_MAX}`
  const metaDescCount = `${metaDescription.length}/${META_DESC_MAX}`

  return (
    <div
      className="fixed inset-0 z-40 flex"
      role="presentation"
      onMouseDown={(e) => {
        // Close on backdrop click (not on panel click)
        if (e.target === e.currentTarget && !saving) onClose()
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
            Page settings
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded p-1 text-gray-400 transition-colors hover:text-gray-600
              disabled:opacity-50
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Close settings"
          >
            <span aria-hidden="true" className="text-2xl leading-none">×</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
          {bannerError && (
            <AlertBanner variant="error" title="Could not save settings">
              {bannerError}
            </AlertBanner>
          )}

          {/* Title */}
          <Input
            label="Title"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              if (titleError) setTitleError(null)
            }}
            onBlur={handleTitleBlur}
            maxLength={TITLE_MAX}
            required
            error={titleError ?? undefined}
            helperText={titleError ? undefined : '1–120 characters. Shown in the page list and editor header.'}
          />

          {/* Slug */}
          <Field
            label="Slug"
            htmlFor="page-settings-slug"
            error={slugError}
            helper={
              isHandCoded
                ? 'Hand-coded page slug cannot be changed.'
                : 'Changing the slug creates a 301 redirect from the old URL.'
            }
            required
          >
            <div className="relative">
              <input
                id="page-settings-slug"
                type="text"
                value={slug}
                onChange={(e) => {
                  setSlug(e.target.value)
                  if (slugError) setSlugError(null)
                }}
                onBlur={handleSlugBlur}
                readOnly={isHandCoded}
                maxLength={SLUG_MAX_LENGTH}
                aria-invalid={slugError ? 'true' : undefined}
                title={isHandCoded ? 'Hand-coded page slug cannot be changed' : undefined}
                className={`h-[42px] w-full rounded-md border px-3 py-2 pr-10 text-gray-900 shadow-sm transition-colors
                  placeholder:text-gray-400
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                  focus-visible:ring-offset-2 focus-visible:border-blue-500
                  ${slugError ? 'border-red-500 focus-visible:ring-red-500 focus-visible:border-red-500' : 'border-gray-300'}
                  ${isHandCoded ? 'cursor-not-allowed bg-gray-50 text-gray-600' : ''}`}
              />
              {isHandCoded && (
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-gray-400"
                  title="Hand-coded page slug cannot be changed"
                >
                  🔒
                </span>
              )}
            </div>
          </Field>

          {/* Noindex toggle */}
          <div className="flex items-start justify-between gap-4 rounded-md border border-gray-200 bg-gray-50 px-3 py-3">
            <div className="flex-1">
              <label htmlFor="page-settings-noindex" className="text-sm font-medium text-gray-700">
                Hide from search engines
              </label>
              <p className="text-xs text-gray-500">
                Adds <code className="rounded bg-white px-1">noindex, nofollow</code> and excludes this
                page from the sitemap.
              </p>
            </div>
            <button
              id="page-settings-noindex"
              type="button"
              role="switch"
              aria-checked={noindex}
              onClick={() => setNoindex((v) => !v)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full
                transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                focus-visible:ring-offset-2
                ${noindex ? 'bg-blue-600' : 'bg-gray-300'}`}
            >
              <span className="sr-only">Hide from search engines</span>
              <span
                aria-hidden="true"
                className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform
                  ${noindex ? 'translate-x-5' : 'translate-x-0.5'}`}
              />
            </button>
          </div>

          {/* --- SEO --- */}
          <SectionDivider label="SEO" />

          <Input
            label="Meta title"
            value={metaTitle}
            onChange={(e) => setMetaTitle(e.target.value)}
            maxLength={META_TITLE_MAX}
            placeholder="Defaults to the page title"
            helperText={metaTitleCount}
          />

          <Field
            label="Meta description"
            htmlFor="page-settings-meta-desc"
            helper={metaDescCount}
          >
            <textarea
              id="page-settings-meta-desc"
              value={metaDescription}
              onChange={(e) => setMetaDescription(e.target.value)}
              maxLength={META_DESC_MAX}
              rows={3}
              placeholder="Short summary shown by search engines and social previews."
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm transition-colors
                placeholder:text-gray-400
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
          </Field>

          <Input
            label="Canonical URL"
            value={canonical}
            onChange={(e) => {
              setCanonical(e.target.value)
              if (canonicalError) setCanonicalError(null)
            }}
            onBlur={handleCanonicalBlur}
            placeholder="https://example.com/path"
            error={canonicalError ?? undefined}
            helperText={
              canonicalError
                ? undefined
                : 'Optional. Must be a fully-qualified https:// URL.'
            }
          />

          {/* --- Social --- */}
          <SectionDivider label="Social" />

          <Input
            label="Open Graph image URL"
            value={ogImage}
            onChange={(e) => setOgImage(e.target.value)}
            placeholder="https://example.com/og-image.jpg"
            helperText="Shown on Facebook, LinkedIn, and other social previews."
          />

          <Select
            label="Open Graph type"
            value={ogType}
            onChange={(e) => setOgType(e.target.value)}
            options={[...OG_TYPE_OPTIONS]}
          />

          <Select
            label="Twitter card"
            value={twitterCard}
            onChange={(e) => setTwitterCard(e.target.value)}
            options={[...TWITTER_CARD_OPTIONS]}
          />

          {/* --- Structured Data --- */}
          <SectionDivider label="Structured Data" />

          <Field
            label="JSON-LD"
            htmlFor="page-settings-jsonld"
            error={jsonLdError}
            helper={
              jsonLdError
                ? undefined
                : 'Paste one JSON object or an array of objects. Validated on blur.'
            }
          >
            <textarea
              id="page-settings-jsonld"
              value={jsonLd}
              onChange={(e) => {
                setJsonLd(e.target.value)
                if (jsonLdError) setJsonLdError(null)
              }}
              onBlur={handleJsonLdBlur}
              rows={8}
              spellCheck={false}
              aria-invalid={jsonLdError ? 'true' : undefined}
              placeholder={`{\n  "@context": "https://schema.org",\n  "@type": "Organization",\n  "name": "..."\n}`}
              className={`w-full rounded-md border px-3 py-2 font-mono text-xs text-gray-900 shadow-sm transition-colors
                placeholder:text-gray-400
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
                ${
                  jsonLdError
                    ? 'border-red-500 focus-visible:ring-red-500 focus-visible:border-red-500'
                    : 'border-gray-300 focus-visible:ring-blue-500 focus-visible:border-blue-500'
                }`}
            />
          </Field>

          {/* --- Danger zone (hand-coded pages only) --- */}
          {isHandCoded && onRevertToFallback && (
            <div className="mt-6 rounded-md border border-red-200 bg-red-50 p-4">
              <p className="text-sm font-semibold text-red-900">Danger zone</p>
              <p className="mt-1 text-xs text-red-800">
                Remove all editor content and revert to the original hand-coded page.
                This cannot be undone.
              </p>
              <div className="mt-3">
                <Button
                  type="button"
                  variant="danger"
                  size="sm"
                  onClick={() => {
                    onClose()
                    onRevertToFallback()
                  }}
                  disabled={saving}
                >
                  Revert to fallback
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            loading={saving}
            disabled={saving || hasFieldError}
          >
            Save settings
          </Button>
        </div>
      </div>
    </div>
  )
}

export default PageSettingsDrawer
