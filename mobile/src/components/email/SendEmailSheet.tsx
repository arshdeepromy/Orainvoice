import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useModules } from '@/contexts/ModuleContext'
import { MobileSpinner } from '@/components/ui'
import { SURFACE_REGISTRY } from './surfaceRegistry'
import type {
  BlocklistEntry,
  EmailPreviewResponse,
  OverrideSendPayload,
  SendEmailModalProps,
} from './types'

/**
 * SendEmailSheet — the mobile "Send Email" composer (task 15.2).
 *
 * Implements the SAME contract as the web `SendEmailModal` (R1.10 / R12.1):
 * `{ open, onClose, templateType, entityType, entityId, onSent, surfaceLabel,
 * logId? }`. The types and the surface registry are imported from the web module
 * (single source of truth — `./types`, `./surfaceRegistry`), never redefined.
 *
 * Mobile-optimised behaviour:
 *   - On viewports ≤ 640 px it renders full-screen with a top app-bar holding
 *     Cancel (left) and Send (right), and the body editor occupying ≥ 50 % of the
 *     viewport height (R12.2). The TipTap editor is `React.lazy`-imported so the
 *     bundle is code-split (R6.1).
 *   - All interactive elements are ≥ 44 × 44 CSS px (R12.3).
 *   - Uses `pb-safe` / `env(safe-area-inset-*)` so the Send button is never
 *     obscured by the home-indicator (R12.4).
 *   - The preview GET and every send are wrapped in an `AbortController`, aborted
 *     on unmount and on close (R12.5). Reads use `?.` / `?? []` / `?? 0` with
 *     typed generics, never `as any`.
 *   - v2 endpoints (`/api/v2/email-preview`, `POST /api/v2/...`) via the surface
 *     registry; `offset`/`limit` (not `skip`) for any pagination (R12.6).
 *   - Hidden from `global_admin` (mobile is org-users only — R12.7 / R15.3) and
 *     fails closed (renders nothing) when the surface's required module is
 *     disabled (R22.4) — the vehicle-reminder resend surfaces require `vehicles`.
 */

const MobileBodyEditor = lazy(() => import('./MobileBodyEditor'))

/** RFC-5322-minimum email check, matching the web RecipientChips regex (R4.3). */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Template types whose surface requires the `vehicles` module (R22.4). */
const VEHICLE_REMINDER_TEMPLATES = new Set([
  'wof_expiry_reminder',
  'cof_expiry_reminder',
  'registration_expiry_reminder',
  'service_due_reminder',
])

const ONE_KB = 1024
const ONE_MB = 1024 * 1024
/** Body-size estimate added to the attachment total (mirrors web R7.3). */
const ESTIMATED_BODY_BYTES = 10 * 1024

function formatBytes(sizeBytes: number): string {
  const safe = Number.isFinite(sizeBytes) && sizeBytes > 0 ? sizeBytes : 0
  if (safe < ONE_MB) return `${Math.round(safe / ONE_KB)} KB`
  return `${(safe / ONE_MB).toFixed(1)} MB`
}

/** Order-sensitive array equality (recipient order matters — first = To). */
function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  return a.every((v, i) => v === b[i])
}

/** Order-insensitive key-set equality (attachment selection order is irrelevant). */
function sameKeySet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const sortedA = [...a].sort()
  const sortedB = [...b].sort()
  return sortedA.every((v, i) => v === sortedB[i])
}

function blocklistKindFor(email: string, blocklist: BlocklistEntry[]): 'soft' | 'hard' | null {
  const lower = email.toLowerCase()
  const entry = blocklist.find((b) => b.email?.toLowerCase() === lower)
  return entry?.kind ?? null
}

function isHardBounced(email: string, blocklist: BlocklistEntry[]): boolean {
  return blocklistKindFor(email, blocklist) === 'hard'
}

interface LoadError {
  kind: 'forbidden' | 'notfound' | 'server'
  detail: string
}

type BannerTone = 'red' | 'amber'

interface SendErrorState {
  tone: BannerTone
  message: string
  canRetry: boolean
  copyDetails: string | null
}

// ── Recipient field (mobile) ────────────────────────────────────────────────
interface RecipientFieldProps {
  label: 'To' | 'Cc' | 'Bcc'
  values: string[]
  onChange: (next: string[]) => void
  required?: boolean
  blocklist: BlocklistEntry[]
  canOverrideHard: boolean
  onOverrideHard: () => void
}

function RecipientField({
  label,
  values,
  onChange,
  required = false,
  blocklist,
  canOverrideHard,
  onOverrideHard,
}: RecipientFieldProps) {
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)

  const commitDraft = useCallback(() => {
    const trimmed = draft.trim().replace(/[,;]+$/, '').trim()
    if (trimmed === '') {
      setDraft('')
      return
    }
    if (!EMAIL_RE.test(trimmed)) {
      setError('Invalid email address')
      return
    }
    const exists = values.some((v) => v.toLowerCase() === trimmed.toLowerCase())
    if (!exists) onChange([...values, trimmed])
    setDraft('')
    setError(null)
  }, [draft, values, onChange])

  function removeAt(index: number) {
    onChange(values.filter((_, i) => i !== index))
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}
        {required && (
          <span className="ml-0.5 text-red-500" aria-hidden="true">
            *
          </span>
        )}
      </span>

      <div
        className={`flex min-h-[44px] flex-wrap items-center gap-1.5 rounded-lg border bg-white px-2 py-1.5 dark:bg-gray-800 ${
          error
            ? 'border-red-500 dark:border-red-400'
            : 'border-gray-300 dark:border-gray-600'
        }`}
      >
        {values.map((email, index) => {
          const kind = blocklistKindFor(email, blocklist)
          const isHard = kind === 'hard'
          const isSoft = kind === 'soft'
          return (
            <span
              key={`${email}-${index}`}
              className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-1 text-xs ${
                isHard
                  ? 'border-red-500 bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                  : isSoft
                    ? 'border-amber-500 bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                    : 'border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200'
              }`}
            >
              {(isHard || isSoft) && (
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  className="h-3.5 w-3.5 flex-shrink-0"
                >
                  <path d="M10.3 3.9l-8 14A2 2 0 004 21h16a2 2 0 001.7-3l-8-14a2 2 0 00-3.4 0z" />
                  <path d="M12 9v4m0 4h.01" />
                </svg>
              )}
              <span className="truncate">{email}</span>
              {isHard && canOverrideHard && (
                <button
                  type="button"
                  onClick={onOverrideHard}
                  className="ml-0.5 rounded px-1 text-[11px] font-medium underline"
                >
                  Override once
                </button>
              )}
              <button
                type="button"
                onClick={() => removeAt(index)}
                aria-label={`Remove ${email}`}
                className="grid h-6 w-6 flex-shrink-0 place-items-center rounded-full leading-none active:bg-black/10"
              >
                <span aria-hidden="true">×</span>
              </button>
            </span>
          )
        })}

        <input
          type="text"
          inputMode="email"
          autoComplete="off"
          autoCapitalize="none"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            if (error) setError(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',' || e.key === ';') {
              e.preventDefault()
              commitDraft()
            } else if (e.key === 'Backspace' && draft === '' && values.length > 0) {
              e.preventDefault()
              removeAt(values.length - 1)
            }
          }}
          onBlur={commitDraft}
          aria-invalid={error ? 'true' : undefined}
          aria-required={required ? 'true' : undefined}
          aria-label={label}
          className="h-9 min-w-[120px] flex-1 bg-transparent px-1 text-base text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100"
          placeholder={values.length === 0 ? 'name@example.com' : ''}
        />
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

// ── Status banner (mobile) ──────────────────────────────────────────────────
interface StatusBannerProps {
  tone: BannerTone
  message: string
  onDismiss: () => void
  onRetry?: () => void
  onCopyDetails?: () => void
}

function StatusBanner({ tone, message, onDismiss, onRetry, onCopyDetails }: StatusBannerProps) {
  const toneClass =
    tone === 'red'
      ? 'bg-red-50 text-red-800 dark:bg-red-900/30 dark:text-red-200'
      : 'bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200'
  const iconPath =
    tone === 'red'
      ? 'M12 9v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
      : 'M12 9v4m0 4h.01M10.3 3.9l-8 14A2 2 0 004 21h16a2 2 0 001.7-3l-8-14a2 2 0 00-3.4 0z'

  return (
    <div role="alert" className={`flex items-start gap-3 rounded-xl px-3 py-3 text-sm ${toneClass}`}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className="mt-0.5 h-[18px] w-[18px] flex-shrink-0"
      >
        <path d={iconPath} />
      </svg>

      <div className="flex flex-1 flex-col gap-2">
        <p>{message}</p>
        {(onRetry || onCopyDetails) && (
          <div className="flex flex-wrap items-center gap-3">
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="min-h-[44px] rounded-lg border border-current px-3 text-sm font-medium"
              >
                Retry
              </button>
            )}
            {onCopyDetails && (
              <button
                type="button"
                onClick={onCopyDetails}
                className="min-h-[44px] text-sm font-medium underline underline-offset-2"
              >
                Copy details
              </button>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="grid h-8 w-8 flex-shrink-0 place-items-center rounded leading-none active:bg-black/10"
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  )
}

export function SendEmailSheet({
  open,
  onClose,
  templateType,
  entityType,
  entityId,
  onSent,
  surfaceLabel,
  logId,
}: SendEmailModalProps) {
  const { isOrgAdmin, isGlobalAdmin } = useAuth()
  const { isModuleEnabled } = useModules()

  // ── Preview / load state ──────────────────────────────────────────────
  const [loading, setLoading] = useState(false)
  const [showSkeleton, setShowSkeleton] = useState(false)
  const [preview, setPreview] = useState<EmailPreviewResponse | null>(null)
  const [loadError, setLoadError] = useState<LoadError | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  // ── Editable fields ───────────────────────────────────────────────────
  const [recipients, setRecipients] = useState<string[]>([])
  const [cc, setCc] = useState<string[]>([])
  const [bcc, setBcc] = useState<string[]>([])
  const [subject, setSubject] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [attachments, setAttachments] = useState<Record<string, boolean>>({})
  const [subjectWasEdited, setSubjectWasEdited] = useState(false)
  const [bodyWasEdited, setBodyWasEdited] = useState(false)
  const [overrideBlocklist, setOverrideBlocklist] = useState(false)

  // ── Send state ────────────────────────────────────────────────────────
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<SendErrorState | null>(null)

  const defaultSubjectRef = useRef('')
  const defaultBodyRef = useRef('')
  const sendTimedOutRef = useRef(false)

  const blocklist = preview?.blocklisted ?? []

  // Surface fails closed when its required module is disabled (R22.4).
  const moduleAvailable =
    !VEHICLE_REMINDER_TEMPLATES.has(templateType) || isModuleEnabled('vehicles')

  // global_admin must never see the sheet (R12.7 / R15.3).
  const visible = open && !isGlobalAdmin && moduleAvailable

  const hydrateFromPreview = useCallback((data: EmailPreviewResponse) => {
    setPreview(data)
    defaultSubjectRef.current = data.subject ?? ''
    defaultBodyRef.current = data.body_editable_html ?? ''

    const defaultAttachments: Record<string, boolean> = {}
    for (const spec of data.attachments ?? []) {
      defaultAttachments[spec.key] = spec.default_attached ?? false
    }

    setRecipients(data.recipients ?? [])
    setCc(data.cc ?? [])
    setBcc(data.bcc ?? [])
    setSubject(data.subject ?? '')
    setBodyHtml(data.body_editable_html ?? '')
    setAttachments(defaultAttachments)
    setSubjectWasEdited(false)
    setBodyWasEdited(false)
    setOverrideBlocklist(false)
  }, [])

  // ── Preview fetch (AbortController aborted on unmount + close, R12.5) ───
  useEffect(() => {
    if (!visible) return

    const controller = new AbortController()
    const skeletonTimer = setTimeout(() => setShowSkeleton(true), 300)
    setLoading(true)
    setLoadError(null)
    setSendError(null)

    void (async () => {
      try {
        const res = await apiClient.get<EmailPreviewResponse>('/email-preview', {
          baseURL: '/api/v2',
          params: {
            template_type: templateType,
            entity_type: entityType,
            entity_id: entityId,
          },
          signal: controller.signal,
        })
        if (controller.signal.aborted) return
        hydrateFromPreview(res.data)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        const status = (err as { response?: { status?: number } })?.response?.status
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? ''
        if (status === 403) setLoadError({ kind: 'forbidden', detail })
        else if (status === 404) setLoadError({ kind: 'notfound', detail })
        else setLoadError({ kind: 'server', detail })
      } finally {
        if (!controller.signal.aborted) {
          clearTimeout(skeletonTimer)
          setLoading(false)
          setShowSkeleton(false)
        }
      }
    })()

    return () => {
      controller.abort()
      clearTimeout(skeletonTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, templateType, entityType, entityId, logId, reloadKey])

  // ── Edit handlers ─────────────────────────────────────────────────────
  const handleSubjectChange = useCallback((v: string) => {
    setSubject(v)
    if (v !== defaultSubjectRef.current) setSubjectWasEdited(true)
  }, [])

  const handleBodyChange = useCallback((html: string) => {
    setBodyHtml(html)
    if (html !== defaultBodyRef.current) setBodyWasEdited(true)
  }, [])

  const handleResetBody = useCallback(() => {
    setBodyHtml(defaultBodyRef.current)
    setBodyWasEdited(false)
  }, [])

  const handleToggleAttachment = useCallback((key: string, checked: boolean) => {
    setAttachments((prev) => ({ ...prev, [key]: checked }))
  }, [])

  // ── Over-size computation (R12.x mirrors web R7.3) ─────────────────────
  const specs = preview?.attachments ?? []
  const isChecked = useCallback(
    (key: string, required: boolean) => required || attachments[key] === true,
    [attachments],
  )
  const selectedBytes = useMemo(
    () =>
      specs.reduce(
        (sum, spec) => (isChecked(spec.key, spec.required) ? sum + (spec.size_bytes ?? 0) : sum),
        0,
      ),
    [specs, isChecked],
  )
  const sizeLimit = preview?.email_size_limit_bytes ?? 0
  const overSize = sizeLimit > 0 && selectedBytes + ESTIMATED_BODY_BYTES > sizeLimit

  // ── Send-disabled aggregation ─────────────────────────────────────────
  const hasHardBounce = useMemo(
    () => [...recipients, ...cc, ...bcc].some((addr) => isHardBounced(addr, blocklist)),
    [recipients, cc, bcc, blocklist],
  )
  const blockedByHardBounce = hasHardBounce && !overrideBlocklist

  const sendDisabled =
    !preview ||
    !!loadError ||
    sending ||
    recipients.length === 0 ||
    subject.trim() === '' ||
    overSize ||
    blockedByHardBounce

  // ── Override payload (omit fields unchanged from the default) ──────────
  const buildPayload = useCallback((): OverrideSendPayload => {
    const payload: OverrideSendPayload = {}

    if (!arraysEqual(recipients, preview?.recipients ?? [])) payload.recipients = recipients
    if (!arraysEqual(cc, preview?.cc ?? [])) payload.cc = cc
    if (!arraysEqual(bcc, preview?.bcc ?? [])) payload.bcc = bcc

    // body_html MUST be omitted when not edited so the server renders the
    // byte-equivalent default (R3.6 / R8.1 / Property P1).
    if (subjectWasEdited) payload.subject = subject
    if (bodyWasEdited) payload.body_html = bodyHtml

    const checkedKeys = specs
      .filter((spec) => spec.required || attachments[spec.key] === true)
      .map((spec) => spec.key)
    const defaultKeys = specs
      .filter((spec) => spec.required || spec.default_attached === true)
      .map((spec) => spec.key)
    if (!sameKeySet(checkedKeys, defaultKeys)) payload.attachments = checkedKeys

    payload.subject_was_edited = subjectWasEdited
    payload.body_was_edited = bodyWasEdited
    if (overrideBlocklist) payload.override_blocklist = true

    return payload
  }, [
    preview,
    recipients,
    cc,
    bcc,
    subject,
    bodyHtml,
    attachments,
    specs,
    subjectWasEdited,
    bodyWasEdited,
    overrideBlocklist,
  ])

  function buildCopyDetails(data: Record<string, unknown>): string {
    const parts: string[] = []
    if (typeof data.provider_key === 'string') parts.push(`provider_key=${data.provider_key}`)
    if (typeof data.attempts === 'number') parts.push(`attempts=${data.attempts}`)
    parts.push(`timestamp=${new Date().toISOString()}`)
    return parts.join(' ')
  }

  /** Map a failed override-send response → banner tone/message/actions (R14). */
  function mapSendError(err: unknown): SendErrorState {
    const response = (err as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const status = response?.status
    const data = response?.data ?? {}
    const detail = typeof data.detail === 'string' ? data.detail : ''

    if (status === 400) {
      return {
        tone: 'red',
        message: detail || 'Recipient address rejected. Fix the To list and try again.',
        canRetry: false,
        copyDetails: null,
      }
    }
    if (status === 413) {
      return {
        tone: 'red',
        message: detail || 'Email too large. Uncheck some attachments and try again.',
        canRetry: false,
        copyDetails: null,
      }
    }
    if (status === 502) {
      return {
        tone: 'red',
        message: detail || 'Email provider authentication failed. Contact your platform admin.',
        canRetry: false,
        copyDetails: buildCopyDetails(data),
      }
    }
    if (status === 503) {
      return {
        tone: 'amber',
        message:
          detail ||
          'Delivery temporarily failed across all providers. Please try again in a few minutes.',
        canRetry: true,
        copyDetails: null,
      }
    }
    return {
      tone: 'amber',
      message: detail || 'Something went wrong sending the email. Please try again.',
      canRetry: true,
      copyDetails: null,
    }
  }

  // ── Send ──────────────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    if (!preview || sendDisabled) return

    const surface = SURFACE_REGISTRY[templateType]
    if (!surface) {
      setSendError({
        tone: 'red',
        message: 'This email surface is not configured.',
        canRetry: false,
        copyDetails: null,
      })
      return
    }

    setSending(true)
    setSendError(null)
    sendTimedOutRef.current = false

    // Bound the in-flight wait to the server's delivery budget (R28.3).
    const budgetMs = (preview.total_budget_seconds ?? 45) * 1000
    const controller = new AbortController()
    const budgetTimer = setTimeout(() => {
      sendTimedOutRef.current = true
      controller.abort()
    }, budgetMs)

    try {
      // The surface registry's v2 URLs are absolute (`/api/v2/...`); the mobile
      // apiClient request interceptor strips the `/api/v1` baseURL for any
      // `/api/`-prefixed path, so v2 and v1 surfaces both resolve correctly.
      const url = surface.buildSendUrl(entityId, { logId })
      await apiClient.request({
        method: surface.method,
        url,
        data: buildPayload(),
        signal: controller.signal,
      })

      // Success — refresh the surface and close. The trigger (task 15.3) owns
      // any success toast via its `onSent` callback.
      onSent()
      onClose()
    } catch (err: unknown) {
      if (sendTimedOutRef.current) {
        setSendError({
          tone: 'amber',
          message: 'Delivery timed out. Please try again in a few minutes.',
          canRetry: true,
          copyDetails: null,
        })
      } else {
        setSendError(mapSendError(err))
      }
    } finally {
      clearTimeout(budgetTimer)
      setSending(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    preview,
    sendDisabled,
    templateType,
    entityId,
    logId,
    recipients,
    buildPayload,
    onSent,
    onClose,
  ])

  const handleRetrySend = useCallback(() => {
    setSendError(null)
    void handleSend()
  }, [handleSend])

  const handleCopyDetails = useCallback(() => {
    const details = sendError?.copyDetails
    if (details && typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(details)
    }
  }, [sendError])

  const handleClose = useCallback(() => {
    if (sending) return
    onClose()
  }, [sending, onClose])

  if (!visible) return null

  const subjectEmpty = subject.trim() === ''

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={surfaceLabel}
      data-testid="send-email-sheet"
      className="fixed inset-0 z-50 flex flex-col bg-white dark:bg-gray-900"
    >
      {/* Top app-bar: Cancel (left) / title / Send (right) (R12.2) */}
      <div
        className="flex items-center justify-between border-b border-gray-200 px-2 dark:border-gray-700"
        style={{ paddingTop: 'env(safe-area-inset-top)' }}
      >
        <button
          type="button"
          onClick={handleClose}
          disabled={sending}
          className="min-h-[44px] min-w-[44px] px-2 text-base font-medium text-blue-600 disabled:opacity-50 dark:text-blue-400"
        >
          Cancel
        </button>
        <h1 className="truncate px-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          {surfaceLabel}
        </h1>
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={sendDisabled}
          aria-busy={sending || undefined}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center gap-2 px-2 text-base font-semibold text-blue-600 disabled:opacity-40 dark:text-blue-400"
        >
          {sending && <MobileSpinner size="sm" />}
          Send
        </button>
      </div>

      {/* Scrollable body — fills remaining space, body editor ≥ 50 % vh */}
      <div
        className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 pt-4 pb-safe"
        style={{ paddingBottom: 'max(1.5rem, env(safe-area-inset-bottom))' }}
      >
        {loading && showSkeleton && (
          <div className="flex min-h-[200px] items-center justify-center">
            <MobileSpinner size="lg" />
          </div>
        )}

        {loadError && (
          <StatusBanner
            tone="red"
            message={
              loadError.kind === 'forbidden'
                ? loadError.detail || "You don't have permission to send this email."
                : loadError.kind === 'notfound'
                  ? loadError.detail || "We couldn't find this record. It may have been removed."
                  : loadError.detail || 'Could not load defaults.'
            }
            onDismiss={() => setLoadError(null)}
            onRetry={
              loadError.kind === 'server'
                ? () => {
                    setLoadError(null)
                    setReloadKey((k) => k + 1)
                  }
                : undefined
            }
          />
        )}

        {preview && !loadError && (
          <>
            {sendError && (
              <StatusBanner
                tone={sendError.tone}
                message={sendError.message}
                onDismiss={() => setSendError(null)}
                onRetry={sendError.canRetry ? handleRetrySend : undefined}
                onCopyDetails={sendError.copyDetails ? handleCopyDetails : undefined}
              />
            )}

            <RecipientField
              label="To"
              values={recipients}
              onChange={setRecipients}
              required
              blocklist={blocklist}
              canOverrideHard={isOrgAdmin}
              onOverrideHard={() => setOverrideBlocklist(true)}
            />
            <RecipientField
              label="Cc"
              values={cc}
              onChange={setCc}
              blocklist={blocklist}
              canOverrideHard={isOrgAdmin}
              onOverrideHard={() => setOverrideBlocklist(true)}
            />
            <RecipientField
              label="Bcc"
              values={bcc}
              onChange={setBcc}
              blocklist={blocklist}
              canOverrideHard={isOrgAdmin}
              onOverrideHard={() => setOverrideBlocklist(true)}
            />

            {/* Subject */}
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="mobile-email-subject"
                className="text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Subject
                <span className="ml-0.5 text-red-500" aria-hidden="true">
                  *
                </span>
              </label>
              <input
                id="mobile-email-subject"
                type="text"
                value={subject}
                onChange={(e) => handleSubjectChange(e.target.value)}
                maxLength={255}
                required
                aria-required="true"
                aria-invalid={subjectEmpty ? 'true' : undefined}
                placeholder="Email subject"
                className={`min-h-[44px] w-full rounded-lg border bg-white px-3 text-base text-gray-900 outline-none dark:bg-gray-800 dark:text-gray-100 ${
                  subjectEmpty
                    ? 'border-red-500 dark:border-red-400'
                    : 'border-gray-300 dark:border-gray-600'
                }`}
              />
              {subjectEmpty ? (
                <p className="text-xs text-red-600 dark:text-red-400" role="alert">
                  Subject is required.
                </p>
              ) : (
                subject.length > 200 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {subject.length} / 255
                  </p>
                )
              )}
            </div>

            {/* Body editor (lazy TipTap) — occupies ≥ 50 % vh (R12.2) */}
            <Suspense
              fallback={
                <div className="flex min-h-[50vh] items-center justify-center rounded-xl border border-gray-200 dark:border-gray-700">
                  <MobileSpinner size="md" />
                </div>
              }
            >
              <MobileBodyEditor
                valueHtml={bodyHtml}
                defaultHtml={defaultBodyRef.current}
                onChange={handleBodyChange}
                onResetToDefault={handleResetBody}
                senderPreview={preview.sender_preview}
                locale={preview.locale ?? 'en'}
              />
            </Suspense>

            {/* Attachments */}
            {specs.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <h2 className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Attachments
                </h2>
                <ul className="flex flex-col">
                  {specs.map((spec) => {
                    const checked = isChecked(spec.key, spec.required)
                    const checkboxId = `mobile-attachment-${spec.key}`
                    return (
                      <li key={spec.key}>
                        <label
                          htmlFor={checkboxId}
                          className={`flex min-h-[44px] w-full items-center gap-3 rounded-lg px-2 ${
                            spec.required ? '' : 'active:bg-gray-50 dark:active:bg-gray-800'
                          }`}
                        >
                          <input
                            id={checkboxId}
                            type="checkbox"
                            checked={checked}
                            disabled={spec.required}
                            aria-disabled={spec.required ? 'true' : undefined}
                            onChange={(e) => {
                              if (spec.required) return
                              handleToggleAttachment(spec.key, e.target.checked)
                            }}
                            className="h-5 w-5 flex-shrink-0 accent-blue-600 disabled:opacity-60"
                          />
                          <span className="flex-1 truncate text-base text-gray-900 dark:text-gray-100">
                            {spec.label}
                          </span>
                          {spec.required && (
                            <span className="flex-shrink-0 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300">
                              Required
                            </span>
                          )}
                          <span className="flex-shrink-0 font-mono text-xs tabular-nums text-gray-500 dark:text-gray-400">
                            {formatBytes(spec.size_bytes)}
                          </span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
                {overSize && (
                  <p className="text-xs text-red-600 dark:text-red-400" role="alert">
                    Total attachment size {formatBytes(selectedBytes)} exceeds the{' '}
                    {formatBytes(sizeLimit)} limit. Uncheck attachments to continue.
                  </p>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default SendEmailSheet
