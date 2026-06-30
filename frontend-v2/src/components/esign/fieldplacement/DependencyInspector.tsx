import { useId, useMemo, useState } from 'react'
import {
  addDependency,
  type DependencyCondition,
  type DependencyEffect,
  type FieldDependency,
} from '../lib/dependencyGraph'
import type { PlacedField } from './hooks/useFieldSet'

/**
 * DependencyInspector — the conditional / dependent-fields editor for the
 * Field_Placement_Editor (feature: esignature-field-placement, task 17.5).
 *
 * For the selected field this panel lets the Org_Sender define a
 * Field_Dependency (R14.1): pick a Trigger_Field (any *other* field in the same
 * Field_Set, R14.2), a Dependency_Condition (R14.3), and an `effect` of `show`
 * or `require`. Every add is routed through the pure {@link addDependency} so a
 * self-loop (`reason: 'self'`, R14.2) or an edge that closes a cycle
 * (`reason: 'cycle'`, R14.4) is rejected inline with a human-readable message
 * and never recorded.
 *
 * Because the Documenso signing engine has no cross-field conditional
 * primitive, the dependency model is **advisory** only: it is recorded for the
 * sender's reference but is NOT enforced during signing — every field is shown
 * to the recipient unconditionally, and a `require`-effect dependency degrades
 * to optional (R14.6–R14.8). The panel surfaces this prominently as an
 * **advisory notice** (R14.7).
 *
 * The component is **presentational + callback-driven**: it owns no Field_Set or
 * dependency state beyond the in-progress form. The parent
 * (`FieldPlacementEditor`, task 17.8) holds the `FieldDependency[]` and wires
 * `onAddDependency` / `onRemoveDependency`. The cycle/self-loop check runs
 * against the `dependencies` prop so the panel stays pure and trivially
 * testable.
 *
 * Every interactive control meets the 44×44 CSS-px minimum touch target (R10.1).
 *
 * _Requirements: 14.1, 14.2, 14.3, 14.4, 14.7_
 */

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

/** The Dependency_Condition set (R14.3), in display order, with labels. */
const CONDITION_OPTIONS: ReadonlyArray<{ value: DependencyCondition; label: string }> = [
  { value: 'is_checked', label: 'is checked' },
  { value: 'is_not_checked', label: 'is not checked' },
  { value: 'equals', label: 'equals…' },
  { value: 'not_equals', label: 'does not equal…' },
  { value: 'is_filled', label: 'is filled' },
  { value: 'is_empty', label: 'is empty' },
]

/** The effect set (R14.1), in display order, with labels. */
const EFFECT_OPTIONS: ReadonlyArray<{ value: DependencyEffect; label: string }> = [
  { value: 'show', label: 'Show this field' },
  { value: 'require', label: 'Require this field' },
]

/** Whether the condition takes a comparison value (`equals` / `not_equals`). */
function conditionTakesValue(condition: DependencyCondition): boolean {
  return condition === 'equals' || condition === 'not_equals'
}

/** Shared field-label styling, matching the v2 `Input`/`Select` primitives. */
const LABEL_CLASS = 'text-[12.5px] font-medium text-text'

/** Min touch-target sizing applied to every interactive control (R10.1). */
const TOUCH_TARGET = 'min-h-[44px] min-w-[44px]'

/** Shared `<select>` styling (caret chevron + focus ring), copied from FieldInspector. */
const SELECT_CLASS = `${TOUCH_TARGET} w-full appearance-none rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
  bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%23687283%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')]
  bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10
  focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]`

/** Shared `<input>` styling, copied from FieldInspector. */
const INPUT_CLASS = `${TOUCH_TARGET} w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text transition-[border-color,box-shadow] duration-150
  placeholder:text-muted-2
  focus:outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]`

/**
 * A short, stable label for a field as it appears in the trigger picker and the
 * dependency list — its type, plus its label for `text` fields, plus its 1-based
 * position within the set so two same-type fields stay distinguishable.
 */
function describeField(field: PlacedField, position: number): string {
  const base = FIELD_TYPE_LABELS[field.type]
  if (field.type === 'text' && field.label) return `${base} “${field.label}” (#${position})`
  return `${base} (#${position})`
}

export interface DependencyInspectorProps {
  /** The currently-selected field (the dependent), or `null` when none selected. */
  field: PlacedField | null
  /** The full Field_Set — used to populate the Trigger_Field picker (R14.2). */
  fields: PlacedField[]
  /** The current dependency set — the cycle/self-loop check runs against this (R14.4). */
  dependencies: FieldDependency[]
  /** Record a new Field_Dependency (already validated via {@link addDependency}). */
  onAddDependency: (dependency: FieldDependency) => void
  /** Remove the Field_Dependency at `index` from the set. */
  onRemoveDependency: (index: number) => void
  /** Optional extra classes for the container. */
  className?: string
}

export function DependencyInspector({
  field,
  fields,
  dependencies,
  onAddDependency,
  onRemoveDependency,
  className,
}: DependencyInspectorProps) {
  const baseId = useId()
  const triggerSelectId = `${baseId}-trigger`
  const conditionSelectId = `${baseId}-condition`
  const valueInputId = `${baseId}-value`
  const effectSelectId = `${baseId}-effect`

  // In-progress form state (the only state the panel owns).
  const [triggerClientId, setTriggerClientId] = useState('')
  const [condition, setCondition] = useState<DependencyCondition>('is_checked')
  const [value, setValue] = useState('')
  const [effect, setEffect] = useState<DependencyEffect>('show')
  const [error, setError] = useState<string | null>(null)

  // A stable 1-based position for every field, by its order in the set, so the
  // labels in the picker and the list line up regardless of selection.
  const positionByClientId = useMemo(() => {
    const map = new Map<string, number>()
    fields.forEach((f, i) => map.set(f.clientId, i + 1))
    return map
  }, [fields])

  const labelFor = (clientId: string): string => {
    const target = fields.find((f) => f.clientId === clientId)
    if (!target) return 'Unknown field'
    return describeField(target, positionByClientId.get(clientId) ?? 0)
  }

  // Nothing selected — quiet prompt so the panel never renders empty.
  if (!field) {
    return (
      <div
        className={`flex flex-col gap-3 rounded-ctl border border-border bg-card p-3 ${className ?? ''}`}
        data-testid="dependency-inspector-empty"
      >
        <p className="text-[13px] text-muted">Select a field to add a conditional rule.</p>
      </div>
    )
  }

  // Candidate triggers: every OTHER field in the set (R14.2).
  const triggerCandidates = fields.filter((f) => f.clientId !== field.clientId)

  // Dependencies whose dependent is the selected field (what this field's rules are).
  const fieldDependencies = dependencies
    .map((dep, index) => ({ dep, index }))
    .filter(({ dep }) => dep.dependentClientId === field.clientId)

  const handleAdd = () => {
    setError(null)

    if (!triggerClientId) {
      setError('Choose a trigger field first.')
      return
    }

    const edge: FieldDependency = {
      dependentClientId: field.clientId,
      triggerClientId,
      condition,
      effect,
      ...(conditionTakesValue(condition) ? { value } : {}),
    }

    // Route every add through the pure graph core so self-loops (R14.2) and
    // cycles (R14.4) are rejected inline and never recorded.
    const result = addDependency(dependencies, edge)
    if (!result.ok) {
      setError(
        result.reason === 'self'
          ? 'A field can’t depend on itself. Choose a different trigger field.'
          : 'That rule would create a circular dependency, so it can’t be added.',
      )
      return
    }

    onAddDependency(edge)
    // Reset the in-progress value but keep trigger/condition/effect for fast repeat.
    setValue('')
  }

  const showValueInput = conditionTakesValue(condition)
  const noTriggers = triggerCandidates.length === 0

  return (
    <div
      className={`flex flex-col gap-4 rounded-ctl border border-border bg-card p-3 ${className ?? ''}`}
      data-testid="dependency-inspector"
      aria-label={`Conditional rules for this ${FIELD_TYPE_LABELS[field.type]} field`}
    >
      {/* ── Heading ───────────────────────────────────────────────────── */}
      <h3 className="text-[13.5px] font-semibold text-text">Conditional rules</h3>

      {/* ── Advisory notice (R14.7) — prominent, always visible ───────── */}
      <div
        role="note"
        data-testid="dependency-advisory-notice"
        className="flex flex-col gap-1 rounded-ctl border border-warn/30 bg-warn-soft p-3 text-[12.5px] leading-snug text-text"
      >
        <span className="font-semibold text-warn">Recorded for your reference only</span>
        <span className="text-muted">
          Conditional rules are saved with the document but are <strong>not enforced</strong> during
          signing. Every field is shown to the recipient, and a “require” rule is treated as
          optional so an unmet condition can’t block them from finishing.
        </span>
      </div>

      {noTriggers ? (
        <p className="text-[13px] text-muted">
          Add at least one other field to this document to create a conditional rule.
        </p>
      ) : (
        <>
          {/* ── Trigger field (R14.2) ─────────────────────────────────── */}
          <div className="flex flex-col gap-[7px]">
            <label htmlFor={triggerSelectId} className={LABEL_CLASS}>
              When this field
            </label>
            <select
              id={triggerSelectId}
              value={triggerClientId}
              onChange={(e) => {
                setTriggerClientId(e.target.value)
                setError(null)
              }}
              className={SELECT_CLASS}
            >
              <option value="">Select a trigger field…</option>
              {triggerCandidates.map((f) => (
                <option key={f.clientId} value={f.clientId}>
                  {describeField(f, positionByClientId.get(f.clientId) ?? 0)}
                </option>
              ))}
            </select>
          </div>

          {/* ── Condition (R14.3) ─────────────────────────────────────── */}
          <div className="flex flex-col gap-[7px]">
            <label htmlFor={conditionSelectId} className={LABEL_CLASS}>
              Condition
            </label>
            <select
              id={conditionSelectId}
              value={condition}
              onChange={(e) => {
                setCondition(e.target.value as DependencyCondition)
                setError(null)
              }}
              className={SELECT_CLASS}
            >
              {CONDITION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* ── Comparison value (equals / not_equals only) ───────────── */}
          {showValueInput && (
            <div className="flex flex-col gap-[7px]">
              <label htmlFor={valueInputId} className={LABEL_CLASS}>
                Value
              </label>
              <input
                id={valueInputId}
                type="text"
                value={value}
                placeholder="e.g. Yes"
                onChange={(e) => {
                  setValue(e.target.value)
                  setError(null)
                }}
                className={INPUT_CLASS}
              />
            </div>
          )}

          {/* ── Effect (R14.1) ────────────────────────────────────────── */}
          <div className="flex flex-col gap-[7px]">
            <label htmlFor={effectSelectId} className={LABEL_CLASS}>
              Then
            </label>
            <select
              id={effectSelectId}
              value={effect}
              onChange={(e) => {
                setEffect(e.target.value as DependencyEffect)
                setError(null)
              }}
              className={SELECT_CLASS}
            >
              {EFFECT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* ── Inline rejection message (R14.2 / R14.4) ──────────────── */}
          {error && (
            <p role="alert" data-testid="dependency-error" className="text-[12.5px] text-danger">
              {error}
            </p>
          )}

          {/* ── Add ───────────────────────────────────────────────────── */}
          <button
            type="button"
            onClick={handleAdd}
            className={`${TOUCH_TARGET} flex w-full items-center justify-center gap-2 rounded-ctl border border-transparent bg-accent px-3 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 hover:brightness-95 active:translate-y-px
              focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card`}
          >
            Add rule
          </button>
        </>
      )}

      {/* ── Existing rules for this field ─────────────────────────────── */}
      {fieldDependencies.length > 0 && (
        <ul className="flex flex-col gap-2 border-t border-border pt-3" aria-label="Current rules">
          {fieldDependencies.map(({ dep, index }) => {
            const conditionLabel =
              CONDITION_OPTIONS.find((o) => o.value === dep.condition)?.label ?? dep.condition
            const effectLabel = dep.effect === 'require' ? 'require' : 'show'
            return (
              <li
                key={index}
                data-testid="dependency-row"
                className="flex items-start justify-between gap-2 rounded-ctl border border-border bg-canvas p-2"
              >
                <span className="text-[12.5px] leading-snug text-text">
                  When <strong>{labelFor(dep.triggerClientId)}</strong> {conditionLabel}
                  {conditionTakesValue(dep.condition) ? ` “${dep.value ?? ''}”` : ''}, {effectLabel}{' '}
                  this field.
                </span>
                <button
                  type="button"
                  onClick={() => onRemoveDependency(index)}
                  aria-label={`Remove rule: when ${labelFor(dep.triggerClientId)} ${conditionLabel}, ${effectLabel} this field`}
                  className={`${TOUCH_TARGET} flex flex-shrink-0 items-center justify-center rounded-ctl border border-border bg-card px-2 text-[12.5px] font-medium text-danger transition-colors duration-150 hover:bg-danger/10
                    focus:outline-none focus-visible:ring-2 focus-visible:ring-danger focus-visible:ring-offset-1 focus-visible:ring-offset-card`}
                >
                  Remove
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default DependencyInspector
