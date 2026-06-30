/**
 * FieldPalette — the Field_Palette control set for the Field_Placement_Editor
 * (feature: esignature-field-placement, task 6.1).
 *
 * Offers every supported Field_Type (`signature`, `initials`, `name`, `date`,
 * `email`, `text`, `number`, `radio`, `checkbox`, `dropdown`) as a source the
 * Org_Sender can add to the document (R2.1). Each source supports two
 * equivalent placement gestures so the editor is usable with a mouse, a
 * keyboard, and on touch:
 *
 *   - **drag-to-add** — the control is `draggable`; on drag start it writes the
 *     chosen {@link FieldType} onto the drag payload under
 *     {@link FIELD_TYPE_DRAG_MIME}, so the page drop target (the orchestrator,
 *     task 6.4) can read it and `add` a field at the drop point (R3.1);
 *   - **tap-to-arm** — clicking/activating a control "arms" that type; the next
 *     tap on a rendered page places a field of the armed type. Arming is a
 *     single-select toggle surfaced through `aria-pressed`, so it works by
 *     keyboard and on touch where fine-grained dragging is impractical (R10.5).
 *
 * This component is presentational: it owns no Field_Set state. The armed type
 * and the arm handler are supplied by the orchestrator, which also owns the
 * drop/tap placement and the active recipient (see RecipientLegend, R4.2).
 *
 * Accessibility: every palette control meets the 44×44 CSS px minimum target
 * size (R10.1) and carries an explicit accessible name; the group is labelled.
 *
 * _Requirements: 2.1, 10.1_
 */

import { FIELD_TYPES, type FieldType } from './hooks/useFieldSet'

/**
 * The drag-and-drop MIME type the palette writes the armed {@link FieldType}
 * onto. The page drop target reads the same key to place the field (R3.1).
 * Exported so the orchestrator and tests share one source of truth.
 */
export const FIELD_TYPE_DRAG_MIME = 'application/x-esign-field-type'

/** Human-readable label per field type (stable UI rendering). */
const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  signature: 'Signature',
  initials: 'Initials',
  name: 'Name',
  date: 'Date',
  email: 'Email',
  text: 'Text',
  number: 'Number',
  radio: 'Radio',
  checkbox: 'Checkbox',
  dropdown: 'Dropdown',
}

/** A short, leak-free description of what each field collects (for the title/aria). */
const FIELD_TYPE_HINTS: Record<FieldType, string> = {
  signature: 'A place for the recipient to sign',
  initials: 'A place for the recipient to initial',
  name: "The recipient's full name",
  date: 'The date the recipient completes the document',
  email: "The recipient's email address",
  text: 'A free-text input you can label',
  number: 'A number input you can label',
  radio: 'A set of options the recipient chooses one of',
  checkbox: 'A single box the recipient can check',
  dropdown: 'A list of options the recipient picks from',
}

/**
 * A compact, distinct glyph per field type. Inline SVG keeps the palette
 * dependency-free and crisp in both colour schemes (`currentColor`).
 */
function FieldTypeIcon({ type }: { type: FieldType }) {
  const common = {
    viewBox: '0 0 24 24',
    fill: 'none',
    'aria-hidden': true,
    className: 'h-5 w-5',
  } as const
  switch (type) {
    case 'signature':
      return (
        <svg {...common}>
          <path
            d="M3 17c3 0 4-9 6-9s2 6 4 6 3-4 5-4"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M3 20h18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      )
    case 'initials':
      return (
        <svg {...common}>
          <path
            d="M6 7v10M6 7l4 6 4-6M14 7v10"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'name':
      return (
        <svg {...common}>
          <circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M5 19c0-3.3 3.1-5 7-5s7 1.7 7 5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      )
    case 'date':
      return (
        <svg {...common}>
          <rect x="4" y="5" width="16" height="15" rx="2" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M4 9h16M8 3v4M16 3v4"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      )
    case 'email':
      return (
        <svg {...common}>
          <rect x="3" y="6" width="18" height="12" rx="2" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="m4 8 8 5 8-5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'text':
      return (
        <svg {...common}>
          <path
            d="M5 7h14M5 7V5.5M5 7v1.5M12 7v10M9.5 17h5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'number':
      return (
        <svg {...common}>
          <path
            d="M9 4 7 20M17 4l-2 16M4 9h16M3 15h16"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'radio':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="12" cy="12" r="3.2" fill="currentColor" />
        </svg>
      )
    case 'checkbox':
      return (
        <svg {...common}>
          <rect x="4" y="4" width="16" height="16" rx="3" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="m8 12 2.5 2.5L16 9"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'dropdown':
      return (
        <svg {...common}>
          <rect x="4" y="6" width="16" height="12" rx="2" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="m9 11 3 3 3-3"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    default:
      return null
  }
}

export interface FieldPaletteProps {
  /** The currently armed field type (tap-to-arm), or `null` when nothing is armed. */
  armedType: FieldType | null
  /**
   * Called when the Org_Sender arms a field type (tap/keyboard activate). The
   * orchestrator decides whether a second activation of the armed type disarms
   * it; this control simply reports each activation.
   */
  onArm: (type: FieldType) => void
  /** Disable all palette controls (e.g. while a page failed to render). */
  disabled?: boolean
  /** Extra classes for the container. */
  className?: string
}

/**
 * The Field_Palette. Renders all supported field-type sources as
 * drag-to-add / tap-to-arm controls, each a ≥44×44 px target (R2.1, R10.1).
 */
export default function FieldPalette({
  armedType,
  onArm,
  disabled = false,
  className,
}: FieldPaletteProps) {
  return (
    <div
      className={['flex flex-col gap-2', className].filter(Boolean).join(' ')}
      role="group"
      aria-label="Field types"
    >
      <span className="text-[12px] font-medium uppercase tracking-wide text-muted">
        Fields
      </span>
      <div className="grid grid-cols-2 gap-2">
        {FIELD_TYPES.map((type) => {
          const label = FIELD_TYPE_LABELS[type]
          const armed = armedType === type
          return (
            <button
              key={type}
              type="button"
              draggable={!disabled}
              disabled={disabled}
              aria-pressed={armed}
              aria-label={`${label} field — drag onto the page or tap to place`}
              title={FIELD_TYPE_HINTS[type]}
              data-field-type={type}
              data-testid={`palette-${type}`}
              onClick={() => onArm(type)}
              onDragStart={(e) => {
                // Write the chosen type onto the drag payload so the page drop
                // target can place a field of this type at the drop point (R3.1).
                e.dataTransfer.setData(FIELD_TYPE_DRAG_MIME, type)
                e.dataTransfer.setData('text/plain', label)
                e.dataTransfer.effectAllowed = 'copy'
              }}
              className={[
                'flex min-h-[44px] min-w-[44px] cursor-grab items-center gap-2 rounded-ctl border px-3 py-2 text-left text-[13px] font-medium transition-colors active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-60',
                armed
                  ? 'border-accent bg-accent-soft text-accent ring-2 ring-accent/30'
                  : 'border-border bg-canvas text-text hover:border-accent/50 hover:bg-accent-soft',
              ].join(' ')}
            >
              <span className="shrink-0 text-muted" aria-hidden="true">
                <FieldTypeIcon type={type} />
              </span>
              <span className="truncate">{label}</span>
            </button>
          )
        })}
      </div>
      <p className="text-[11.5px] leading-snug text-muted">
        Drag a field onto the page, or tap a field then tap where it should go.
      </p>
    </div>
  )
}
