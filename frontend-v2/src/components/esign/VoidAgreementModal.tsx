import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertBanner, Button, Modal } from '@/components/ui'
import { voidEnvelope as defaultVoidEnvelope } from '@/api/esign'
import type { EnvelopeOut, EsignError } from '@/api/esign'

/**
 * VoidAgreementModal — destructive-action confirmation for voiding an envelope
 * (feature: esignature-integration, Task 17.4, R7).
 *
 * Voiding cancels the document in Documenso and moves the envelope to the
 * terminal `voided` status (R7.2) — it cannot be undone. This modal is the
 * confirm-before-destroy gate the Agreements dashboard's "Void agreement"
 * action funnels through: it spells out that voiding is irreversible and
 * requires an explicit confirmation click before any call is made.
 *
 * On confirm it POSTs `voidEnvelope(id)` via the typed esign API client. While
 * the request is in flight the confirm button shows a spinner and both buttons
 * are disabled (the modal cannot be dismissed mid-request so the call is never
 * orphaned). On success it calls `onVoided` with the updated envelope and
 * closes; on error it surfaces the humanized `{ message, code }` body inline
 * (e.g. a 409 `not_voidable` when the envelope reached a terminal status first)
 * and re-enables the button so the user can dismiss or retry (R7.3 / R16.1).
 *
 * The dashboard already gates the entry point on `!isTerminal(status)` (R7.1),
 * so this modal is only ever offered for non-terminal envelopes; the backend
 * remains the source of truth and a stale terminal envelope surfaces as the
 * humanized 409.
 *
 * Controlled + testable:
 *   - open state is derived from `envelope` (non-null ⇒ open),
 *   - the API call is injectable via `voidEnvelopeFn` (defaults to the real
 *     client) so tests can drive happy / error paths without a network,
 *   - typed throughout (no `as any`), and the in-flight request is bound to an
 *     `AbortController` aborted on unmount.
 *
 * _Requirements: 7.1, 7.3, 7.4, 16.x_
 */

export interface VoidAgreementModalProps {
  /**
   * The envelope the user asked to void. The modal is open while this is
   * non-null and closed when it is null (mirrors the dashboard's
   * `voidCandidate` state).
   */
  envelope: EnvelopeOut | null
  /** Called when the user dismisses the modal (Cancel / × / after success). */
  onClose: () => void
  /**
   * Called with the updated (now `voided`) envelope on a successful void,
   * before the modal closes — so the caller can refresh its list / detail.
   */
  onVoided?: (envelope: EnvelopeOut) => void
  /** Injectable API call (defaults to the real esign client) — for testing. */
  voidEnvelopeFn?: typeof defaultVoidEnvelope
}

/** Humanize a snake_case enum value into Title Case for display. */
function humanizeToken(value: string | null | undefined): string {
  if (!value) return 'agreement'
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

/**
 * Coerce an unknown thrown value (typically an axios error) into the humanized
 * `{ message, code }` shape. The esign endpoints return `{ message, code }`
 * (optionally nested under FastAPI's `detail`); raw DB / exception text is
 * never leaked server-side (R15.5 / R16), so a generic fallback is safe.
 */
function extractEsignError(err: unknown): EsignError {
  const response = (err as { response?: { data?: unknown } })?.response
  const data = response?.data

  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>

    // Direct `{ message, code }` shape.
    if (typeof obj.message === 'string' && obj.message.trim() !== '') {
      return { message: obj.message, code: typeof obj.code === 'string' ? obj.code : null }
    }

    // FastAPI `{ detail: ... }` — detail may be the `{ message, code }` object
    // or a plain string.
    const detail = obj.detail
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>
      if (typeof d.message === 'string' && d.message.trim() !== '') {
        return { message: d.message, code: typeof d.code === 'string' ? d.code : null }
      }
    }
    if (typeof detail === 'string' && detail.trim() !== '') {
      return { message: detail, code: null }
    }
  }

  return {
    message: 'We could not void this agreement. Please try again.',
    code: null,
  }
}

/** True when the thrown value is an aborted-request signal (ignore it). */
function isAbortError(err: unknown): boolean {
  const name = (err as { name?: string })?.name
  const code = (err as { code?: string })?.code
  return name === 'AbortError' || name === 'CanceledError' || code === 'ERR_CANCELED'
}

export function VoidAgreementModal({
  envelope,
  onClose,
  onVoided,
  voidEnvelopeFn = defaultVoidEnvelope,
}: VoidAgreementModalProps) {
  const open = envelope !== null

  const [voiding, setVoiding] = useState(false)
  const [serverError, setServerError] = useState<EsignError | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  // Reset transient state whenever a new candidate opens the modal; abort any
  // in-flight request when the modal unmounts.
  useEffect(() => {
    if (open) {
      setVoiding(false)
      setServerError(null)
    }
    return () => {
      abortRef.current?.abort()
    }
  }, [open, envelope?.id])

  const handleConfirm = useCallback(async () => {
    if (!envelope?.id || voiding) return
    setServerError(null)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setVoiding(true)
    try {
      const updated = await voidEnvelopeFn(envelope.id, controller.signal)
      if (controller.signal.aborted) return
      onVoided?.(updated)
      onClose()
    } catch (err: unknown) {
      if (controller.signal.aborted || isAbortError(err)) return
      setServerError(extractEsignError(err))
    } finally {
      if (!controller.signal.aborted) setVoiding(false)
    }
  }, [envelope?.id, voiding, voidEnvelopeFn, onVoided, onClose])

  // Cancel / × are inert while the void is in flight (don't orphan the request).
  const handleClose = useCallback(() => {
    if (voiding) return
    onClose()
  }, [voiding, onClose])

  if (!open) return null

  const label = humanizeToken(envelope?.agreement_type)

  return (
    <Modal open={open} onClose={handleClose} title="Void agreement" className="max-w-md">
      <div className="space-y-4">
        {serverError && (
          <AlertBanner variant="error" onDismiss={() => setServerError(null)}>
            {serverError.message}
            {serverError.code && (
              <span className="ml-1 text-[12px] opacity-70">({serverError.code})</span>
            )}
          </AlertBanner>
        )}

        <p className="text-[13.5px] text-muted">
          You are about to void this <span className="font-medium text-text">{label}</span>.
          This cancels the document in Documenso and notifies the recipients that it is no
          longer active.
        </p>
        <p className="text-[13.5px] font-medium text-danger">
          This cannot be undone. A voided agreement is final and cannot be reactivated or
          re-sent.
        </p>

        <div className="flex justify-end gap-3 border-t border-border pt-4">
          <Button variant="ghost" size="sm" onClick={handleClose} disabled={voiding}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => void handleConfirm()}
            loading={voiding}
            disabled={voiding}
          >
            Void agreement
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export default VoidAgreementModal
