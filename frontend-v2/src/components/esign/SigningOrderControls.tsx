/**
 * SigningOrderControls — the step-1 signing-order block for the Send_Flow
 * (feature: esignature-field-placement, task 19.1; Requirement 15).
 *
 * Lets an Org_Sender choose a {@link SigningOrderMode} for a send and, when
 * `sequential`, order the **signing** recipients into distinct 1-based
 * positions:
 *
 *   - **Mode toggle (R15.1, R15.2)** — a `parallel` / `sequential` radiogroup
 *     that defaults to `parallel` (the current behaviour). `parallel` lets every
 *     signer sign at once; `sequential` invites each signer only after the
 *     previous one in the order has signed.
 *   - **Reorder UI (R15.3)** — while `sequential`, every `signer`-role recipient
 *     is shown in the current Signing_Order with its 1-based position and
 *     move-up / move-down controls. Positions are always distinct and contiguous
 *     (1..N over the signers) because they are derived from the ordered key list.
 *   - **Viewers excluded (R15.6)** — `viewer`-role recipients carry no position
 *     but stay on the document; they are listed separately as "no position" so
 *     the sender can see they are still included.
 *   - **Advisory note** — order enforcement depends on the signing engine's
 *     capability; when unsupported the send degrades to parallel with the order
 *     recorded but not enforced (design: signing-order architecture, R15).
 *
 * The component is **presentational / controlled**: it owns no state. The parent
 * (the modal) supplies the recipient list, the chosen `mode`, and the ordered
 * signer-key list (`signerOrder`), and receives changes via `onModeChange` /
 * `onReorder`. Colours/keys mirror the rest of the editor (stable recipient
 * `key`).
 *
 * Accessibility: the mode toggle is a labelled `radiogroup`, every interactive
 * control meets the 44×44 CSS px minimum target, and reorder controls carry
 * accessible names naming the recipient and direction.
 *
 * _Requirements: 15.1, 15.2, 15.3, 15.6_
 */

import { AlertBanner } from '@/components/ui'
import { SIGNING_ORDER_MODES, type SigningOrderMode, type SigningRole } from '@/api/esign'

/** The minimal recipient shape the control needs (stable `key` drives order). */
export interface SigningOrderRecipient {
  /** Stable key referenced by `signerOrder` and by the field editor (R4.1). */
  key: number
  /** Display name; falls back to email then a generic label. */
  name?: string
  /** Email, shown as a secondary line / name fallback. */
  email?: string
  /** Signing role — only `signer` recipients receive a position (R15.6). */
  signing_role: SigningRole
}

const MODE_LABELS: Record<SigningOrderMode, string> = {
  parallel: 'Parallel',
  sequential: 'Sequential',
}

const MODE_DESCRIPTIONS: Record<SigningOrderMode, string> = {
  parallel: 'Everyone can sign at the same time.',
  sequential: 'Each signer is invited only after the previous one signs.',
}

/** Best-effort display name: name → email → "Recipient N". */
function displayName(recipient: SigningOrderRecipient, index: number): string {
  if (recipient.name && recipient.name.trim()) return recipient.name.trim()
  if (recipient.email && recipient.email.trim()) return recipient.email.trim()
  return `Recipient ${index + 1}`
}

/**
 * Reconcile a previous ordered signer-key list against the current recipient
 * list. Returns the keys of the current `signer`-role recipients **in order**:
 * existing entries keep their relative order, removed/now-viewer keys are
 * dropped, and newly-added signers are appended in recipient order. Pure.
 *
 * Keeping this pure and exported lets the parent re-derive a stable order each
 * time recipients change without the control owning state.
 */
export function reconcileSignerOrder(
  recipients: readonly SigningOrderRecipient[],
  prevOrder: readonly number[],
): number[] {
  const signerKeys = recipients
    .filter((r) => r.signing_role === 'signer')
    .map((r) => r.key)
  const signerKeySet = new Set(signerKeys)

  // Keep previously-ordered keys that are still signers, in their prior order.
  const kept = prevOrder.filter((key) => signerKeySet.has(key))
  const keptSet = new Set(kept)

  // Append any signer not already present, in recipient (list) order.
  const appended = signerKeys.filter((key) => !keptSet.has(key))

  return [...kept, ...appended]
}

/**
 * The 1-based Signing_Order position for each signer key, derived from the
 * ordered key list. Pure; positions are distinct and contiguous (1..N).
 */
export function signingPositionByKey(signerOrder: readonly number[]): Map<number, number> {
  const positions = new Map<number, number>()
  signerOrder.forEach((key, index) => {
    positions.set(key, index + 1)
  })
  return positions
}

export interface SigningOrderControlsProps {
  /** The Send_Flow recipient list, in order. */
  recipients: readonly SigningOrderRecipient[]
  /** The chosen Signing_Order_Mode (defaults to `parallel` in the parent). */
  mode: SigningOrderMode
  /** Called when the Org_Sender switches mode (R15.1). */
  onModeChange: (mode: SigningOrderMode) => void
  /**
   * The ordered signer keys (sequential mode). MUST contain exactly the current
   * signer recipients' keys; the parent keeps it reconciled via
   * {@link reconcileSignerOrder}. Ignored for display while `parallel`.
   */
  signerOrder: readonly number[]
  /** Called with the new ordered signer-key list after a move (R15.3). */
  onReorder: (orderedSignerKeys: number[]) => void
  /** Disable all controls. */
  disabled?: boolean
  /** Extra classes for the container. */
  className?: string
}

/**
 * The signing-order block: mode toggle + (for sequential) the signer reorder
 * list, an advisory note, and a "no position" list of viewers.
 */
export default function SigningOrderControls({
  recipients,
  mode,
  onModeChange,
  signerOrder,
  onReorder,
  disabled = false,
  className,
}: SigningOrderControlsProps) {
  const byKey = new Map(recipients.map((r) => [r.key, r] as const))
  const indexByKey = new Map(recipients.map((r, i) => [r.key, i] as const))

  // The signers in the current Signing_Order (defensive: only existing signers).
  const orderedSigners = signerOrder
    .map((key) => byKey.get(key))
    .filter((r): r is SigningOrderRecipient => r != null && r.signing_role === 'signer')

  const viewers = recipients.filter((r) => r.signing_role === 'viewer')

  const move = (fromIndex: number, toIndex: number) => {
    if (toIndex < 0 || toIndex >= orderedSigners.length) return
    const keys = orderedSigners.map((r) => r.key)
    const [moved] = keys.splice(fromIndex, 1)
    keys.splice(toIndex, 0, moved)
    onReorder(keys)
  }

  return (
    <div
      className={['flex flex-col gap-3', className].filter(Boolean).join(' ')}
      data-testid="signing-order-controls"
    >
      <span className="text-[12.5px] font-medium text-text">Signing order</span>

      {/* ── Mode toggle (R15.1, R15.2) ─────────────────────────────────── */}
      <div role="radiogroup" aria-label="Signing order mode" className="flex flex-col gap-2">
        {SIGNING_ORDER_MODES.map((m) => {
          const selected = m === mode
          return (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              data-testid={`signing-order-mode-${m}`}
              onClick={() => onModeChange(m)}
              className={[
                'flex min-h-[44px] w-full items-start gap-3 rounded-ctl border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                selected
                  ? 'border-accent bg-accent-soft ring-2 ring-accent/30'
                  : 'border-border bg-canvas hover:border-accent/50 hover:bg-accent-soft',
              ].join(' ')}
            >
              <span
                aria-hidden="true"
                className={[
                  'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                  selected ? 'border-accent' : 'border-border',
                ].join(' ')}
              >
                {selected && <span className="h-2 w-2 rounded-full bg-accent" />}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="text-[13px] font-medium text-text">{MODE_LABELS[m]}</span>
                <span className="text-[11.5px] text-muted">{MODE_DESCRIPTIONS[m]}</span>
              </span>
            </button>
          )
        })}
      </div>

      {/* ── Sequential: reorder signers + advisory note (R15.3, R15.6) ──── */}
      {mode === 'sequential' && (
        <div className="flex flex-col gap-3">
          <AlertBanner variant="info">
            Order enforcement depends on the signing engine. If it isn't supported, the document
            still goes out but every signer can sign at once (parallel) — the order is recorded for
            your reference, not enforced.
          </AlertBanner>

          {orderedSigners.length === 0 ? (
            <p className="text-[12px] text-muted">
              Add at least one signer recipient to set a signing order.
            </p>
          ) : (
            <ol className="flex flex-col gap-1.5" data-testid="signing-order-list">
              {orderedSigners.map((recipient, position) => {
                const name = displayName(recipient, indexByKey.get(recipient.key) ?? position)
                const isFirst = position === 0
                const isLast = position === orderedSigners.length - 1
                return (
                  <li
                    key={recipient.key}
                    data-testid={`signing-order-item-${recipient.key}`}
                    data-position={position + 1}
                    className="flex items-center gap-3 rounded-ctl border border-border bg-canvas px-3 py-2"
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
                    >
                      {position + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">
                      <span className="sr-only">Position {position + 1}: </span>
                      {name}
                    </span>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        disabled={disabled || isFirst}
                        aria-label={`Move ${name} earlier in the signing order`}
                        data-testid={`signing-order-up-${recipient.key}`}
                        onClick={() => move(position, position - 1)}
                        className="flex h-11 w-11 items-center justify-center rounded-ctl border border-border text-muted transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <span aria-hidden="true">↑</span>
                      </button>
                      <button
                        type="button"
                        disabled={disabled || isLast}
                        aria-label={`Move ${name} later in the signing order`}
                        data-testid={`signing-order-down-${recipient.key}`}
                        onClick={() => move(position, position + 1)}
                        className="flex h-11 w-11 items-center justify-center rounded-ctl border border-border text-muted transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <span aria-hidden="true">↓</span>
                      </button>
                    </div>
                  </li>
                )
              })}
            </ol>
          )}

          {/* Viewers stay on the document but carry no position (R15.6). */}
          {viewers.length > 0 && (
            <div className="flex flex-col gap-1" data-testid="signing-order-viewers">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted">
                Viewers (no signing position)
              </span>
              <ul className="flex flex-col gap-1">
                {viewers.map((recipient) => {
                  const name = displayName(recipient, indexByKey.get(recipient.key) ?? 0)
                  return (
                    <li
                      key={recipient.key}
                      data-testid={`signing-order-viewer-${recipient.key}`}
                      className="truncate rounded-ctl border border-dashed border-border bg-canvas px-3 py-1.5 text-[12px] text-muted"
                    >
                      {name}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
