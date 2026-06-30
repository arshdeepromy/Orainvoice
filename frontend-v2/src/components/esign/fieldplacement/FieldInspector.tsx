import { useId } from 'react'
import { recipientColor } from './lib/fieldColors'
import type { PlacedField } from './hooks/useFieldSet'

/**
 * FieldInspector — the per-field property editor for the Field_Placement_Editor
 * (feature: esignature-field-placement, task 6.3).
 *
 * When a field is selected in the editor, the inspector exposes the controls
 * that edit everything about that field other than its geometry (which is
 * driven by drag/resize in `FieldOverlay`):
 *
 *   - **Recipient re-assignment** (R4.3) — a recipient picker, colour-coded via
 *     {@link recipientColor}, that re-assigns the field to a different recipient.
 *   - **Required / optional toggle** (R5.1) — a `role="switch"` control that
 *     persists the chosen required flag on the field.
 *   - **Label + placeholder** (R5.2) — shown for `text` / `number` fields only,
 *     so the sender can label the input the recipient will fill in.
 *   - **Options editor** — shown for `radio` / `dropdown` fields only, so the
 *     sender can author the list of options (add / remove / reorder rows).
 *   - **Delete** (R3.4) — removes the field from the Field_Set.
 *
 * The component is **presentational + callback-driven**: it owns no Field_Set
 * state. The parent (`FieldPlacementEditor`, task 6.4) wires the callbacks
 * (`onAssign` / `onSetRequired` / `onSetTextMeta` / `onDelete`) to the
 * `useFieldSet` reducer. This keeps the inspector pure and trivially testable.
 *
 * Every interactive control meets the 44×44 CSS-px minimum touch target (R10.1).
 *
 * _Requirements: 4.3, 5.1, 5.2, 3.4, 10.1_
 */

/** A recipient as the inspector needs it: a stable key and a display name. */
export interface InspectorRecipient {
  /** The recipient's stable key (matches `PlacedField.recipientKey`, R4.1). */
  key: number
  /** The recipient's display name. */
  name: string
}

export interface FieldInspectorProps {
  /** The currently-selected field, or `null` when nothing is selected. */
  field: PlacedField | null
  /** The current send's recipient list (order drives each recipient's colour). */
  recipients: InspectorRecipient[]
  /** Re-assign the field to a different recipient (R4.3). */
  onAssign: (clientId: string, recipientKey: number) => void
  /** Toggle the field required/optional (R5.1). */
  onSetRequired: (clientId: string, required: boolean) => void
  /** Set a `text` / `number` field's label/placeholder (R5.2). */
  onSetTextMeta: (clientId: string, label?: string, placeholder?: string) => void
  /** Set a `radio` / `dropdown` field's sender-authored options. */
  onSetOptions: (clientId: string, options: string[]) => void
  /** Delete the field from the Field_Set (R3.4). */
  onDelete: (clientId: string) => void
  /** Optional extra classes for the container. */
  className?: string
}

/** Human-readable labels for each field type (stable rendering). */
const FIELD_TYPE_LABELS: Record<PlacedField['type'], string> = {
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

/** Shared field-label styling, matching the v2 `Input`/`Select` primitives. */
const LABEL_CLASS = 'text-[12.5px] font-medium text-text'

/** Min touch-target sizing applied to every interactive control (R10.1). */
const TOUCH_TARGET = 'min-h-[44px] min-w-[44px]'

export function FieldInspector({
  field,
  recipients,
  onAssign,
  onSetRequired,
  onSetTextMeta,
  onSetOptions,
  onDelete,
  className,
}: FieldInspectorProps) {
  const baseId = useId()

  // Nothing selected — show a quiet prompt so the panel never renders empty.
  if (!field) {
    return (
      <div
        className={`flex flex-col gap-3 rounded-ctl border border-border bg-card p-3 ${className ?? ''}`}
        data-testid="field-inspector-empty"
      >
        <p className="text-[13px] text-muted">Select a field to edit its properties.</p>
      </div>
    )
  }

  const isText = field.type === 'text' || field.type === 'number'
  const hasOptions = field.type === 'radio' || field.type === 'dropdown'
  const recipientSelectId = `${baseId}-recipient`
  const labelInputId = `${baseId}-label`
  const placeholderInputId = `${baseId}-placeholder`
  const options = field.options ?? []

  // ── Options editor helpers (radio / dropdown) ──────────────────────────
  // Each mutation rebuilds the whole options array and pushes it through
  // onSetOptions so the reducer owns the field's options state.
  const addOption = () => onSetOptions(field.clientId, [...options, ''])
  const updateOption = (index: number, value: string) =>
    onSetOptions(
      field.clientId,
      options.map((opt, i) => (i === index ? value : opt)),
    )
  const removeOption = (index: number) =>
    onSetOptions(
      field.clientId,
      options.filter((_, i) => i !== index),
    )
  const moveOption = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= options.length) return
    const next = [...options]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    onSetOptions(field.clientId, next)
  }

  // The colour of the field's currently-assigned recipient (R4.4) — shown as a
  // swatch next to the picker so the assignment is visible at a glance.
  const assignedIndex = recipients.findIndex((r) => r.key === field.recipientKey)
  const assignedColor = recipientColor(assignedIndex >= 0 ? assignedIndex : 0)

  return (
    <div
      className={`flex flex-col gap-4 rounded-ctl border border-border bg-card p-3 ${className ?? ''}`}
      data-testid="field-inspector"
      aria-label={`${FIELD_TYPE_LABELS[field.type]} field properties`}
    >
      {/* ── Heading: the field's type ─────────────────────────────────── */}
      <div className="flex items-center gap-2">
        <span
          className="inline-block h-3 w-3 flex-shrink-0 rounded-full"
          style={{ backgroundColor: assignedColor.solid }}
          aria-hidden="true"
        />
        <h3 className="text-[13.5px] font-semibold text-text">
          {FIELD_TYPE_LABELS[field.type]} field
        </h3>
      </div>

      {/* ── Recipient re-assignment (R4.3) ────────────────────────────── */}
      <div className="flex flex-col gap-[7px]">
        <label htmlFor={recipientSelectId} className={LABEL_CLASS}>
          Assigned to
        </label>
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-4 w-4 flex-shrink-0 rounded-sm border border-border"
            style={{ backgroundColor: assignedColor.solid }}
            aria-hidden="true"
          />
          <select
            id={recipientSelectId}
            value={String(field.recipientKey)}
            onChange={(e) => onAssign(field.clientId, Number(e.target.value))}
            className={`${TOUCH_TARGET} w-full appearance-none rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
              bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%23687283%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')]
              bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10
              focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]`}
          >
            {recipients.map((r) => (
              <option key={r.key} value={String(r.key)}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Required / optional toggle (R5.1) ─────────────────────────── */}
      <div className="flex items-center justify-between gap-3">
        <span className={LABEL_CLASS}>Required</span>
        <button
          type="button"
          role="switch"
          aria-checked={field.required}
          aria-label={`Mark this ${FIELD_TYPE_LABELS[field.type]} field ${field.required ? 'optional' : 'required'}`}
          onClick={() => onSetRequired(field.clientId, !field.required)}
          className={`${TOUCH_TARGET} relative inline-flex items-center rounded-full px-1 transition-colors duration-150
            focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card
            ${field.required ? 'bg-accent' : 'bg-border-strong'}`}
        >
          {/* A fixed-width track inside the 44px hit target. */}
          <span className="relative block h-6 w-11">
            <span
              className={`absolute top-1/2 h-5 w-5 -translate-y-1/2 rounded-full bg-white shadow transition-[left] duration-150 ${
                field.required ? 'left-[22px]' : 'left-[2px]'
              }`}
            />
          </span>
        </button>
      </div>

      {/* ── Text label + placeholder (R5.2) — text fields only ────────── */}
      {isText && (
        <div className="flex flex-col gap-3 border-t border-border pt-3">
          <div className="flex flex-col gap-[7px]">
            <label htmlFor={labelInputId} className={LABEL_CLASS}>
              Label
            </label>
            <input
              id={labelInputId}
              type="text"
              value={field.label ?? ''}
              placeholder="e.g. Job reference"
              onChange={(e) =>
                onSetTextMeta(field.clientId, e.target.value || undefined, field.placeholder)
              }
              className={`${TOUCH_TARGET} w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
                placeholder:text-muted-2
                focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]`}
            />
          </div>
          <div className="flex flex-col gap-[7px]">
            <label htmlFor={placeholderInputId} className={LABEL_CLASS}>
              Placeholder
            </label>
            <input
              id={placeholderInputId}
              type="text"
              value={field.placeholder ?? ''}
              placeholder="e.g. Enter the job number"
              onChange={(e) =>
                onSetTextMeta(field.clientId, field.label, e.target.value || undefined)
              }
              className={`${TOUCH_TARGET} w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
                placeholder:text-muted-2
                focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]`}
            />
          </div>
        </div>
      )}

      {/* ── Options editor — radio / dropdown only ────────────────────── */}
      {hasOptions && (
        <div
          className="flex flex-col gap-3 border-t border-border pt-3"
          data-testid="field-options-editor"
        >
          <div className="flex items-center justify-between gap-2">
            <span className={LABEL_CLASS}>Options</span>
            <button
              type="button"
              onClick={addOption}
              aria-label="Add an option"
              data-testid="field-option-add"
              className={`${TOUCH_TARGET} flex items-center justify-center gap-1 rounded-ctl border border-border bg-card px-3 text-[13px] font-medium text-text transition-colors hover:border-accent/50 hover:bg-accent-soft
                focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card`}
            >
              + Add option
            </button>
          </div>

          {options.length === 0 ? (
            <p className="text-[12.5px] text-muted" data-testid="field-options-empty">
              Add at least one option for this {FIELD_TYPE_LABELS[field.type].toLowerCase()} field.
            </p>
          ) : (
            <ul className="flex flex-col gap-2" data-testid="field-options-list">
              {options.map((option, index) => {
                const optionInputId = `${baseId}-option-${index}`
                return (
                  <li key={index} className="flex items-center gap-1.5">
                    <label htmlFor={optionInputId} className="sr-only">
                      Option {index + 1}
                    </label>
                    <input
                      id={optionInputId}
                      type="text"
                      value={option}
                      placeholder={`Option ${index + 1}`}
                      data-testid={`field-option-input-${index}`}
                      onChange={(e) => updateOption(index, e.target.value)}
                      className={`${TOUCH_TARGET} w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
                        placeholder:text-muted-2
                        focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]`}
                    />
                    <button
                      type="button"
                      onClick={() => moveOption(index, -1)}
                      disabled={index === 0}
                      aria-label={`Move option ${index + 1} up`}
                      data-testid={`field-option-up-${index}`}
                      className={`${TOUCH_TARGET} flex items-center justify-center rounded-ctl border border-border bg-card px-2 text-text transition-colors hover:border-accent/50 disabled:cursor-not-allowed disabled:opacity-40
                        focus:outline-none focus-visible:ring-2 focus-visible:ring-accent`}
                    >
                      <span aria-hidden="true">↑</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => moveOption(index, 1)}
                      disabled={index === options.length - 1}
                      aria-label={`Move option ${index + 1} down`}
                      data-testid={`field-option-down-${index}`}
                      className={`${TOUCH_TARGET} flex items-center justify-center rounded-ctl border border-border bg-card px-2 text-text transition-colors hover:border-accent/50 disabled:cursor-not-allowed disabled:opacity-40
                        focus:outline-none focus-visible:ring-2 focus-visible:ring-accent`}
                    >
                      <span aria-hidden="true">↓</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => removeOption(index)}
                      aria-label={`Remove option ${index + 1}`}
                      data-testid={`field-option-remove-${index}`}
                      className={`${TOUCH_TARGET} flex items-center justify-center rounded-ctl border border-transparent bg-danger px-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 hover:brightness-95 active:translate-y-px
                        focus:outline-none focus-visible:ring-2 focus-visible:ring-danger focus-visible:ring-offset-1 focus-visible:ring-offset-card`}
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}

      {/* ── Delete (R3.4) ─────────────────────────────────────────────── */}
      <div className="border-t border-border pt-3">
        <button
          type="button"
          onClick={() => onDelete(field.clientId)}
          aria-label={`Delete this ${FIELD_TYPE_LABELS[field.type]} field`}
          className={`${TOUCH_TARGET} flex w-full items-center justify-center gap-2 rounded-ctl border border-transparent bg-danger px-3 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 hover:brightness-95 active:translate-y-px
            focus:outline-none focus-visible:ring-2 focus-visible:ring-danger focus-visible:ring-offset-1 focus-visible:ring-offset-card`}
        >
          Delete field
        </button>
      </div>
    </div>
  )
}

export default FieldInspector
