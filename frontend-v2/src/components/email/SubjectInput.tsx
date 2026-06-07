import { Input } from '../ui/Input'

/**
 * SubjectInput — the single-line Subject field for the Send Email composer.
 *
 * A thin, controlled wrapper around the `Input` primitive (R5.1). It owns no
 * edit-tracking state of its own: the parent (SendEmailModal) diffs the reported
 * value against the loaded default to drive the `subject_was_edited` audit flag
 * (R5.4) — this component just surfaces value changes through `onChange`.
 *
 * Behaviour (design.md → "SubjectInput.tsx"):
 *   - Pre-populated with the rendered default subject, capped at `maxLength`
 *     (255) characters (R5.2).
 *   - Shows a live character count once the value exceeds 200 characters (R5.2).
 *   - Renders the inline error "Subject is required." when the value is empty
 *     (R5.3). The error is wired to the input via `aria-describedby` +
 *     `role="alert"` by the `Input` primitive for accessibility.
 */

export const SUBJECT_MAX_LENGTH = 255

/** Threshold above which the character count becomes visible (R5.2). */
const COUNT_VISIBLE_AT = 200

export interface SubjectInputProps {
  value: string
  onChange: (v: string) => void
  /** Hard character cap (defaults to 255, R5.2). */
  maxLength?: number
}

export function SubjectInput({
  value,
  onChange,
  maxLength = SUBJECT_MAX_LENGTH,
}: SubjectInputProps) {
  const isEmpty = value.trim() === ''
  const showCount = value.length > COUNT_VISIBLE_AT

  return (
    <Input
      id="email-subject"
      label="Subject"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      maxLength={maxLength}
      required
      aria-required="true"
      placeholder="Email subject"
      error={isEmpty ? 'Subject is required.' : undefined}
      helperText={showCount ? `${value.length} / ${maxLength}` : undefined}
    />
  )
}

export default SubjectInput
