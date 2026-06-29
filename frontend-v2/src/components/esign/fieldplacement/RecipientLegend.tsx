/**
 * RecipientLegend — recipient colour key + active-recipient picker for the
 * Field_Placement_Editor (feature: esignature-field-placement, task 6.1).
 *
 * Two responsibilities, both driven by R4:
 *
 *   - **Colour key (R4.4)** — every recipient is shown with the distinct,
 *     high-contrast colour {@link recipientColor} assigns to that recipient's
 *     0-based position in the Send_Flow recipient list. The editor renders each
 *     placed field in its recipient's colour using the same mapping, so the
 *     legend is the visual key tying a colour to a person.
 *   - **Active-recipient picker (R4.2)** — selecting a recipient makes it the
 *     "active" recipient; the editor assigns a newly placed field to whichever
 *     recipient is active at placement time. This is a single-select control
 *     (radiogroup semantics) so exactly one recipient is active at a time.
 *
 * The component is presentational: it owns no Field_Set or recipient state. The
 * recipient list, the active key, and the selection handler are supplied by the
 * orchestrator (task 6.4). Colours are derived purely from each recipient's
 * **index** in the supplied list — the same ordering the editor and overlay use
 * — so the legend, palette, and field boxes always agree without shared state.
 *
 * Accessibility: each recipient control meets the 44×44 CSS px minimum target
 * (R10.1), the group is a labelled `radiogroup`, and each option carries an
 * accessible name conveying the recipient and their signing role.
 *
 * _Requirements: 4.2, 4.4, 10.1_
 */

import type { SigningRole } from '@/api/esign'
import { recipientColor } from './lib/fieldColors'

/**
 * The minimal recipient shape the legend needs. `key` is the stable identifier
 * a placed field references via `recipientKey` (R4.1); the recipient's colour is
 * derived from its **index** in the list passed to {@link RecipientLegend},
 * matching how the editor colours fields.
 */
export interface LegendRecipient {
  /** Stable key referenced by a field's `recipientKey` (R4.1). */
  key: number
  /** Display name; falls back to email then a generic label. */
  name?: string
  /** Email, shown as a secondary line / name fallback. */
  email?: string
  /** Signing role — surfaced as a small badge and in the accessible name. */
  signing_role: SigningRole
}

const SIGNING_ROLE_LABELS: Record<SigningRole, string> = {
  signer: 'Signer',
  viewer: 'Viewer',
}

/** Best-effort display name: name → email → "Recipient N". */
function displayName(recipient: LegendRecipient, index: number): string {
  if (recipient.name && recipient.name.trim()) return recipient.name.trim()
  if (recipient.email && recipient.email.trim()) return recipient.email.trim()
  return `Recipient ${index + 1}`
}

export interface RecipientLegendProps {
  /**
   * The Send_Flow recipient list, in order. A recipient's colour is derived
   * from its index here (R4.4), so the order MUST match the editor's.
   */
  recipients: readonly LegendRecipient[]
  /** The currently active recipient's `key`, or `null` when none is selected. */
  activeRecipientKey: number | null
  /** Called when the Org_Sender selects a recipient as the active one (R4.2). */
  onSelectRecipient: (key: number) => void
  /** Disable selection (e.g. while a page failed to render). */
  disabled?: boolean
  /** Extra classes for the container. */
  className?: string
}

/**
 * The recipient colour key + active-recipient picker. Renders one selectable
 * row per recipient with its colour swatch (R4.4) and drives which recipient a
 * newly placed field is assigned to (R4.2).
 */
export default function RecipientLegend({
  recipients,
  activeRecipientKey,
  onSelectRecipient,
  disabled = false,
  className,
}: RecipientLegendProps) {
  return (
    <div
      className={['flex flex-col gap-2', className].filter(Boolean).join(' ')}
      role="radiogroup"
      aria-label="Active recipient"
    >
      <span className="text-[12px] font-medium uppercase tracking-wide text-muted">
        Recipients
      </span>

      {recipients.length === 0 ? (
        <p className="text-[12px] text-muted">No recipients yet.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {recipients.map((recipient, index) => {
            const color = recipientColor(index)
            const active = recipient.key === activeRecipientKey
            const name = displayName(recipient, index)
            const roleLabel = SIGNING_ROLE_LABELS[recipient.signing_role]
            return (
              <li key={recipient.key}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={disabled}
                  aria-label={`Place fields for ${name} (${roleLabel})`}
                  data-recipient-key={recipient.key}
                  data-testid={`recipient-${recipient.key}`}
                  onClick={() => onSelectRecipient(recipient.key)}
                  className={[
                    'flex min-h-[44px] w-full items-center gap-3 rounded-ctl border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                    active
                      ? 'border-accent bg-accent-soft ring-2 ring-accent/30'
                      : 'border-border bg-canvas hover:border-accent/50 hover:bg-accent-soft',
                  ].join(' ')}
                >
                  {/* Colour swatch — the key tying this colour to placed fields (R4.4). */}
                  <span
                    aria-hidden="true"
                    data-testid={`recipient-swatch-${recipient.key}`}
                    className="h-5 w-5 shrink-0 rounded-full ring-1 ring-black/10 dark:ring-white/20"
                    style={{ backgroundColor: color.solid }}
                  />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-[13px] font-medium text-text">{name}</span>
                    {recipient.email && recipient.email.trim() && recipient.name?.trim() && (
                      <span className="truncate text-[11.5px] text-muted">{recipient.email}</span>
                    )}
                  </span>
                  <span
                    className="ml-auto shrink-0 rounded-chip border border-border px-1.5 py-0.5 text-[10.5px] font-medium uppercase tracking-wide text-muted"
                  >
                    {roleLabel}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
