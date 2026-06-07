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
import { Button, Modal, Spinner, ToastContainer, useToast } from '../ui'
import { RecipientChips } from './RecipientChips'
import { SubjectInput } from './SubjectInput'
import { AttachmentList } from './AttachmentList'
import { StatusBanner } from './StatusBanner'
import type { BannerTone } from './StatusBanner'
import { SURFACE_REGISTRY } from './surfaceRegistry'
import type {
  BlocklistEntry,
  EmailPreviewResponse,
  OverrideSendPayload,
  SendEmailModalProps,
} from './types'

/**
 * SendEmailModal — the shared web "Send Email" composer (task 11.7).
 *
 * A single, surface-agnostic modal: it accepts ONLY
 * `{ open, onClose, templateType, entityType, entityId, onSent, surfaceLabel, logId? }`
 * (R1.1) and contains NO per-surface branching — it reads
 * `SURFACE_REGISTRY[templateType]` to learn where to POST (R1.4).
 *
 * Lifecycle:
 *   - On open it GETs `/api/v2/email-preview` in a `useEffect` guarded by an
 *     `AbortController`, aborted on unmount AND on close (R1.6, R3.1). Every
 *     response field is read with `?.` / `?? []` / `?? 0` (R1.7); the call uses a
 *     typed generic, never `as any` (R1.8). A loading skeleton appears only after
 *     a 300 ms timer (R28.2).
 *   - Renders the leaf components seeded from the preview, tracking
 *     `subjectWasEdited` / `bodyWasEdited` on first divergence from the loaded
 *     defaults (R5.4 / R6.6).
 *   - On Send it builds an `OverrideSendPayload` omitting any field unchanged from
 *     the default — critically omitting `body_html` when the body was not edited so
 *     the server falls back to its byte-equivalent default render (R3.6 / R8.1) —
 *     and POSTs to the surface's `buildSendUrl`. CSRF flows automatically through
 *     the `apiClient` interceptor (R8.10).
 *   - Edits are preserved per-entity for the session in a module-level draft store
 *     keyed by `${entityType}:${entityId}`; reopening the SAME entity restores them,
 *     opening a DIFFERENT entity starts fresh (R4.8 / R19.6).
 */

const BodyEditor = lazy(() => import('./BodyEditor'))

/** Per-entity draft of the user's edits, preserved for the browser session. */
interface DraftState {
  recipients: string[]
  cc: string[]
  bcc: string[]
  subject: string
  bodyHtml: string
  attachments: Record<string, boolean>
  subjectWasEdited: boolean
  bodyWasEdited: boolean
  overrideBlocklist: boolean
}

/**
 * Module-level (session-scoped) draft store keyed by `${entityType}:${entityId}`
 * (R4.8 / R19.6). It survives unmount/remount of the modal for the lifetime of the
 * page session; a successful send clears the entity's entry.
 */
const draftStore = new Map<string, DraftState>()

interface LoadError {
  kind: 'forbidden' | 'notfound' | 'server'
  detail: string
}

interface SendErrorState {
  tone: BannerTone
  message: string
  canRetry: boolean
  /** Non-null only for SOFT_AUTH (502) — the "Copy details" payload (R14.4). */
  copyDetails: string | null
}

/** Order-sensitive array equality (recipient order is significant — first = To). */
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

/** Look up whether an address is hard-bounced in the org blocklist. */
function isHardBounced(email: string, blocklist: BlocklistEntry[]): boolean {
  const lower = email.toLowerCase()
  return blocklist.some((b) => b.email?.toLowerCase() === lower && b.kind === 'hard')
}

export function SendEmailModal({
  open,
  onClose,
  templateType,
  entityType,
  entityId,
  onSent,
  surfaceLabel,
  logId,
}: SendEmailModalProps) {
  const { isOrgAdmin } = useAuth()
  const { toasts, addToast, dismissToast } = useToast()

  const entityKey = `${entityType}:${entityId}`

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
  const [overSize, setOverSize] = useState(false)

  // ── Send state ────────────────────────────────────────────────────────
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<SendErrorState | null>(null)

  // Loaded defaults, used to compute the edited flags + the omit-unchanged payload.
  const defaultSubjectRef = useRef('')
  const defaultBodyRef = useRef('')
  const sendTimedOutRef = useRef(false)

  const blocklist = preview?.blocklisted ?? []

  // ── Preview fetch (abort on unmount + close, R1.6) ─────────────────────
  useEffect(() => {
    if (!open) return

    const controller = new AbortController()
    const skeletonTimer = setTimeout(() => setShowSkeleton(true), 300)
    setLoading(true)
    setLoadError(null)
    setSendError(null)

    void (async () => {
      try {
        const res = await apiClient.get<EmailPreviewResponse>('/api/v2/email-preview', {
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
        if (status === 403) {
          setLoadError({ kind: 'forbidden', detail })
        } else if (status === 404) {
          setLoadError({ kind: 'notfound', detail })
        } else {
          setLoadError({ kind: 'server', detail })
        }
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
    // hydrateFromPreview is stable for the render; entityKey derives from the deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateType, entityType, entityId, logId, reloadKey])

  /** Seed editable state from the preview, restoring any saved per-entity draft. */
  const hydrateFromPreview = useCallback(
    (data: EmailPreviewResponse) => {
      setPreview(data)
      defaultSubjectRef.current = data.subject ?? ''
      defaultBodyRef.current = data.body_editable_html ?? ''

      const defaultAttachments: Record<string, boolean> = {}
      for (const spec of data.attachments ?? []) {
        defaultAttachments[spec.key] = spec.default_attached ?? false
      }

      const draft = draftStore.get(entityKey)
      if (draft) {
        setRecipients(draft.recipients)
        setCc(draft.cc)
        setBcc(draft.bcc)
        setSubject(draft.subject)
        setBodyHtml(draft.bodyHtml)
        setAttachments(draft.attachments)
        setSubjectWasEdited(draft.subjectWasEdited)
        setBodyWasEdited(draft.bodyWasEdited)
        setOverrideBlocklist(draft.overrideBlocklist)
      } else {
        setRecipients(data.recipients ?? [])
        setCc(data.cc ?? [])
        setBcc(data.bcc ?? [])
        setSubject(data.subject ?? '')
        setBodyHtml(data.body_editable_html ?? '')
        setAttachments(defaultAttachments)
        setSubjectWasEdited(false)
        setBodyWasEdited(false)
        setOverrideBlocklist(false)
      }
    },
    [entityKey],
  )

  // ── Persist the draft per-entity whenever an edit happens (R4.8 / R19.6) ──
  useEffect(() => {
    if (!preview) return
    draftStore.set(entityKey, {
      recipients,
      cc,
      bcc,
      subject,
      bodyHtml,
      attachments,
      subjectWasEdited,
      bodyWasEdited,
      overrideBlocklist,
    })
  }, [
    preview,
    entityKey,
    recipients,
    cc,
    bcc,
    subject,
    bodyHtml,
    attachments,
    subjectWasEdited,
    bodyWasEdited,
    overrideBlocklist,
  ])

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

  // ── Send-disabled aggregation ─────────────────────────────────────────
  const hasHardBounce = useMemo(
    () =>
      [...recipients, ...cc, ...bcc].some((addr) => isHardBounced(addr, blocklist)),
    [recipients, cc, bcc, blocklist],
  )
  const blockedByHardBounce = hasHardBounce && !overrideBlocklist

  const sendDisabled =
    !preview ||
    !!loadError ||
    sending ||
    recipients.length === 0 || // To required (R4.2)
    subject.trim() === '' || // subject required (R5.3)
    overSize || // over-size (R7.3)
    blockedByHardBounce // hard-bounce unless org_admin override (R4.6)

  /** Build the override payload, omitting fields unchanged from the default. */
  const buildPayload = useCallback((): OverrideSendPayload => {
    const payload: OverrideSendPayload = {}
    const specs = preview?.attachments ?? []

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
    subjectWasEdited,
    bodyWasEdited,
    overrideBlocklist,
  ])

  /** Map a failed override-send response → banner tone/message/actions (R8.5–8.9). */
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
        message:
          detail || 'Email provider authentication failed. Contact your platform admin.',
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

  /** Compose the SOFT_AUTH "Copy details" string — no credentials, ever (R14.4). */
  function buildCopyDetails(data: Record<string, unknown>): string {
    const parts: string[] = []
    if (typeof data.provider_key === 'string') parts.push(`provider_key=${data.provider_key}`)
    if (typeof data.attempts === 'number') parts.push(`attempts=${data.attempts}`)
    parts.push(`timestamp=${new Date().toISOString()}`)
    return parts.join(' ')
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
      const url = surface.buildSendUrl(entityId, { logId })
      await apiClient.request({
        method: surface.method,
        url,
        data: buildPayload(),
        signal: controller.signal,
      })

      // Success — clear the draft, toast, refresh the surface, and close (R8.4).
      draftStore.delete(entityKey)
      const primary = recipients[0] ?? preview.recipients?.[0] ?? 'recipient'
      addToast('success', `Email sent to ${primary}`)
      onSent()
      onClose()
    } catch (err: unknown) {
      // Keep user-edited fields intact for retry (R8.9).
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
    // mapSendError/buildCopyDetails are pure render-local closures.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    preview,
    sendDisabled,
    templateType,
    entityId,
    logId,
    entityKey,
    recipients,
    buildPayload,
    addToast,
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

  // ── Close guard — Cancel/× are inert while a send is in flight (R8.2) ──
  const handleClose = useCallback(() => {
    if (sending) return
    onClose()
  }, [sending, onClose])

  // ── Render helpers ─────────────────────────────────────────────────────
  function renderLoadErrorBanner(error: LoadError) {
    if (error.kind === 'server') {
      return (
        <StatusBanner
          tone="red"
          message={error.detail || 'Could not load defaults.'}
          onDismiss={() => setLoadError(null)}
          onRetry={() => {
            setLoadError(null)
            setReloadKey((k) => k + 1)
          }}
        />
      )
    }
    const message =
      error.kind === 'forbidden'
        ? error.detail || "You don't have permission to send this email."
        : error.detail || "We couldn't find this record. It may have been removed."
    return (
      <StatusBanner tone="red" message={message} onDismiss={() => setLoadError(null)} />
    )
  }

  function renderBody() {
    if (loading && showSkeleton) {
      return (
        <div className="flex min-h-[280px] items-center justify-center">
          <Spinner size="lg" label="Loading email preview" />
        </div>
      )
    }
    if (loadError) {
      return <div className="py-2">{renderLoadErrorBanner(loadError)}</div>
    }
    if (!preview) {
      // Fast (<300 ms) load — render nothing until the preview arrives.
      return <div className="min-h-[120px]" aria-hidden="true" />
    }

    return (
      <div className="flex flex-col gap-[15px]">
        {sendError && (
          <StatusBanner
            tone={sendError.tone}
            message={sendError.message}
            onDismiss={() => setSendError(null)}
            onRetry={sendError.canRetry ? handleRetrySend : undefined}
            onCopyDetails={sendError.copyDetails ? handleCopyDetails : undefined}
          />
        )}

        <RecipientChips
          label="To"
          values={recipients}
          onChange={setRecipients}
          required
          blocklist={blocklist}
          canOverrideHard={isOrgAdmin}
          onOverrideHard={() => setOverrideBlocklist(true)}
        />
        <RecipientChips
          label="Cc"
          values={cc}
          onChange={setCc}
          blocklist={blocklist}
          canOverrideHard={isOrgAdmin}
          onOverrideHard={() => setOverrideBlocklist(true)}
        />
        <RecipientChips
          label="Bcc"
          values={bcc}
          onChange={setBcc}
          blocklist={blocklist}
          canOverrideHard={isOrgAdmin}
          onOverrideHard={() => setOverrideBlocklist(true)}
        />

        <SubjectInput value={subject} onChange={handleSubjectChange} />

        <Suspense
          fallback={
            <div className="flex min-h-[180px] items-center justify-center rounded-ctl border border-border bg-card">
              <Spinner size="md" label="Loading editor" />
            </div>
          }
        >
          <BodyEditor
            valueHtml={bodyHtml}
            defaultHtml={defaultBodyRef.current}
            onChange={handleBodyChange}
            onResetToDefault={handleResetBody}
            senderPreview={preview.sender_preview}
            locale={preview.locale ?? 'en'}
          />
        </Suspense>

        <AttachmentList
          attachments={preview.attachments ?? []}
          selected={attachments}
          onToggle={handleToggleAttachment}
          emailSizeLimitBytes={preview.email_size_limit_bytes ?? 0}
          onOverSizeChange={setOverSize}
        />
      </div>
    )
  }

  return (
    <>
      <Modal open={open} onClose={handleClose} title={surfaceLabel} className="max-w-2xl">
        {renderBody()}

        <div className="mt-5 flex items-center justify-end gap-3 border-t border-border pt-4">
          <Button variant="ghost" onClick={handleClose} disabled={sending}>
            Cancel
          </Button>
          <Button onClick={() => void handleSend()} loading={sending} disabled={sendDisabled}>
            Send
          </Button>
        </div>
      </Modal>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}

export default SendEmailModal
