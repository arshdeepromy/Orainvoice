/**
 * TouchFieldOverlay — the per-page field-box layer plus the selected-field
 * nudge / resize controls for the Mobile_Field_Placement_Editor (R16).
 *
 * On a phone, fine-grained pointer dragging is impractical, so a placed field is
 * adjusted with discrete on-screen controls instead (Touch_Place, R16.5): once a
 * field is selected, a control cluster offers four nudge arrows, width/height
 * grow & shrink, and delete. Every control is a ≥44×44 px touch target
 * (R16.6 / R10.1).
 *
 * This component is purely presentational: it converts each field's stored
 * {@link NormalizedRect} to overlay px via the shared `normalizedToOverlay` so
 * boxes line up 1:1 with the rendered page, and it reports adjustments as
 * overlay-px deltas (`onNudge` / `onResize`). The editor turns those deltas back
 * into a clamped normalized rect through the **same** shared `clampToPage` +
 * mapping the web editor uses, so geometry invariants hold identically (R16.9).
 *
 * Each field box carries an accessible name conveying its type and assigned
 * recipient (R10.4) and a visible required/optional indicator (R5.5).
 *
 * _Requirements: 16.4, 16.5, 16.6_
 */

import type { FieldType, NormalizedRect, PageDims, PlacedField } from '@/lib/esign'
import { normalizedToOverlay } from '@/lib/esign'
import { recipientColor } from './fieldColors'

/** Minimal recipient shape the overlay needs to colour + label a field. */
export interface OverlayRecipient {
  /** Stable key referenced by a field's `recipientKey`. */
  key: number
  /** Display name used in the field's accessible name. */
  name: string
}

export interface TouchFieldOverlayProps {
  /** The fields placed on this page (already filtered to one page). */
  fields: PlacedField[]
  /** The send's recipients, in array order (drives colour + accessible name). */
  recipients: OverlayRecipient[]
  /** The rendered dimensions of this page (for normalized → overlay px). */
  dims: PageDims
  /** Currently-selected field's client id, or null. */
  selectedClientId: string | null
  /** Select (or toggle) a field for adjustment. */
  onSelect: (clientId: string) => void
  /** Nudge the selected field by an overlay-px delta. */
  onNudge: (clientId: string, dxPx: number, dyPx: number) => void
  /** Resize the selected field by an overlay-px width/height delta. */
  onResize: (clientId: string, dwPx: number, dhPx: number) => void
  /** Delete the selected field. */
  onDelete: (clientId: string) => void
  /** Step size (overlay px) for a single nudge. */
  nudgeStepPx?: number
  /** Step size (overlay px) for a single resize. */
  resizeStepPx?: number
}

/** Human label for a field type, used in the accessible name + box caption. */
const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  signature: 'Signature',
  initials: 'Initials',
  name: 'Name',
  date: 'Date',
  email: 'Email',
  text: 'Text',
}

const DEFAULT_NUDGE_STEP_PX = 8
const DEFAULT_RESIZE_STEP_PX = 8

/** A single ≥44×44 control button used in the adjustment cluster. */
function ControlButton({
  label,
  onTap,
  children,
  variant = 'normal',
}: {
  label: string
  onTap: () => void
  children: React.ReactNode
  variant?: 'normal' | 'danger'
}) {
  const tone =
    variant === 'danger'
      ? 'text-red-600 dark:text-red-400'
      : 'text-gray-700 dark:text-gray-200'
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      // Stop propagation so tapping a control never reaches the place surface.
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation()
        onTap()
      }}
      className={`flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md bg-white text-base font-semibold shadow-sm ring-1 ring-gray-300 active:bg-gray-100 dark:bg-gray-800 dark:ring-gray-600 dark:active:bg-gray-700 ${tone}`}
    >
      {children}
    </button>
  )
}

export default function TouchFieldOverlay({
  fields,
  recipients,
  dims,
  selectedClientId,
  onSelect,
  onNudge,
  onResize,
  onDelete,
  nudgeStepPx = DEFAULT_NUDGE_STEP_PX,
  resizeStepPx = DEFAULT_RESIZE_STEP_PX,
}: TouchFieldOverlayProps) {
  const recipientIndex = (key: number) => recipients.findIndex((r) => r.key === key)
  const recipientName = (key: number) => recipients.find((r) => r.key === key)?.name ?? 'recipient'

  return (
    <>
      {fields.map((field) => {
        const overlay = normalizedToOverlay(field.rect as NormalizedRect, dims)
        const idx = recipientIndex(field.recipientKey)
        const color = recipientColor(idx >= 0 ? idx : 0)
        const isSelected = field.clientId === selectedClientId
        const typeLabel = FIELD_TYPE_LABELS[field.type]
        const name = recipientName(field.recipientKey)
        const requiredLabel = field.required ? 'required' : 'optional'

        // Position the adjustment cluster above the field, or below it when the
        // field sits near the top of the page so the cluster stays on-screen.
        const clusterAbove = overlay.yPx > 60
        const clusterTop = clusterAbove ? overlay.yPx - 52 : overlay.yPx + overlay.hPx + 8

        return (
          <div key={field.clientId}>
            {/* The field box itself. A tap selects it (and stops propagation so
                the underlying place surface doesn't also fire). */}
            <button
              type="button"
              data-testid={`field-box-${field.clientId}`}
              aria-label={`${typeLabel} field for ${name} (${requiredLabel})`}
              aria-pressed={isSelected}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation()
                onSelect(field.clientId)
              }}
              className="absolute flex items-center justify-center overflow-hidden rounded-sm text-[11px] font-medium"
              style={{
                left: overlay.xPx,
                top: overlay.yPx,
                width: overlay.wPx,
                height: overlay.hPx,
                backgroundColor: color.fill,
                border: `2px ${isSelected ? 'solid' : 'dashed'} ${color.solid}`,
                color: color.solid,
                outline: isSelected ? `2px solid ${color.solid}` : undefined,
              }}
            >
              <span className="truncate px-1">
                {typeLabel}
                {field.required ? ' *' : ''}
              </span>
            </button>

            {/* Adjustment controls for the selected field (R16.5). */}
            {isSelected && (
              <div
                data-testid={`field-controls-${field.clientId}`}
                className="absolute z-10 flex flex-wrap items-center gap-1 rounded-lg bg-white/95 p-1 shadow-lg ring-1 ring-gray-300 dark:bg-gray-900/95 dark:ring-gray-600"
                style={{
                  left: Math.max(0, Math.min(overlay.xPx, dims.cssWidth - 320)),
                  top: Math.max(0, clusterTop),
                }}
              >
                <ControlButton label="Move left" onTap={() => onNudge(field.clientId, -nudgeStepPx, 0)}>
                  ←
                </ControlButton>
                <ControlButton label="Move up" onTap={() => onNudge(field.clientId, 0, -nudgeStepPx)}>
                  ↑
                </ControlButton>
                <ControlButton label="Move down" onTap={() => onNudge(field.clientId, 0, nudgeStepPx)}>
                  ↓
                </ControlButton>
                <ControlButton
                  label="Move right"
                  onTap={() => onNudge(field.clientId, nudgeStepPx, 0)}
                >
                  →
                </ControlButton>
                <ControlButton
                  label="Narrower"
                  onTap={() => onResize(field.clientId, -resizeStepPx, 0)}
                >
                  W−
                </ControlButton>
                <ControlButton
                  label="Wider"
                  onTap={() => onResize(field.clientId, resizeStepPx, 0)}
                >
                  W+
                </ControlButton>
                <ControlButton
                  label="Shorter"
                  onTap={() => onResize(field.clientId, 0, -resizeStepPx)}
                >
                  H−
                </ControlButton>
                <ControlButton
                  label="Taller"
                  onTap={() => onResize(field.clientId, 0, resizeStepPx)}
                >
                  H+
                </ControlButton>
                <ControlButton
                  label="Delete field"
                  variant="danger"
                  onTap={() => onDelete(field.clientId)}
                >
                  ✕
                </ControlButton>
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
