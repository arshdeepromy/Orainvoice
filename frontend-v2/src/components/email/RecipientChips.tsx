import { useId, useMemo, useState } from 'react'
import type { KeyboardEvent, ClipboardEvent } from 'react'
import { cx } from '../ui/cx'
import type { BlocklistEntry, BlocklistKind } from './types'

/**
 * RecipientChips — a To / Cc / Bcc chip input for the Send Email composer.
 *
 * A controlled, presentational field: it owns only the in-progress raw text and
 * the inline validation error; the committed chips live in `values` and every
 * mutation flows out through `onChange`. The parent (SendEmailModal) owns the
 * combined >50-recipient warning and the aggregate Send-disabled logic; this
 * component only renders the per-field chips and their blocklist treatment.
 *
 * Behaviour (design.md → "RecipientChips.tsx"):
 *   - Each entry is validated against RFC-5322-minimum
 *     `/^[^\s@]+@[^\s@]+\.[^\s@]+$/` on Enter, comma, semicolon, or Tab (R4.3).
 *     On success it becomes a chip; on failure the raw text is kept and an inline
 *     red "Invalid email address" error renders beneath the field.
 *   - Soft-bounce chips (blocklist kind 'soft') get an amber border + a
 *     warning-triangle icon + tooltip (R4.5). Hard-bounce chips (kind 'hard') get
 *     a red border + an error-octagon icon (R4.6, R13.5). The icon ALWAYS
 *     accompanies the colour so colour is never the sole signal (R27.5).
 *   - Hard-bounce chips expose an "Override once" action ONLY when
 *     `canOverrideHard` (org_admin); clicking it calls `onOverrideHard` (R13.5).
 *   - The field has a linked `<label htmlFor>` (R27.4) and 40–44px touch targets
 *     (R15.4 / R24.5). The To field is marked required (R4.2).
 */

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export interface RecipientChipsProps {
  label: 'To' | 'Cc' | 'Bcc'
  values: string[]
  onChange: (next: string[]) => void
  required?: boolean
  /** Blocklist entries (org-scoped) used to style soft/hard chips. */
  blocklist: BlocklistEntry[]
  /** org_admin only — gates the per-chip "Override once" action. */
  canOverrideHard: boolean
  onOverrideHard?: () => void
}

/** Keys that commit the current raw text to a chip. */
const COMMIT_KEYS = new Set(['Enter', ',', ';', 'Tab'])

/** Look up the blocklist kind for an address (case-insensitive). */
function blocklistKindFor(
  email: string,
  blocklist: BlocklistEntry[],
): BlocklistKind | null {
  const lower = email.toLowerCase()
  const entry = blocklist.find((b) => b.email?.toLowerCase() === lower)
  return entry?.kind ?? null
}

function WarningTriangleIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[14px] w-[14px] flex-shrink-0"
    >
      <path d="M10.3 3.9l-8 14A2 2 0 004 21h16a2 2 0 001.7-3l-8-14a2 2 0 00-3.4 0z" />
      <path d="M12 9v4m0 4h.01" />
    </svg>
  )
}

function ErrorOctagonIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[14px] w-[14px] flex-shrink-0"
    >
      <path d="M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86L7.86 2z" />
      <path d="M12 8v4m0 4h.01" />
    </svg>
  )
}

export function RecipientChips({
  label,
  values,
  onChange,
  required = false,
  blocklist,
  canOverrideHard,
  onOverrideHard,
}: RecipientChipsProps) {
  const reactId = useId()
  const inputId = `recipient-${label.toLowerCase()}-${reactId}`
  const errorId = `${inputId}-error`

  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)

  const hasHardBounce = useMemo(
    () => values.some((v) => blocklistKindFor(v, blocklist) === 'hard'),
    [values, blocklist],
  )

  function removeAt(index: number) {
    onChange(values.filter((_, i) => i !== index))
  }

  /** Validate + commit the current draft. Returns true when a chip was added. */
  function commitDraft(): boolean {
    const trimmed = draft.trim().replace(/[,;]+$/, '').trim()
    if (trimmed === '') {
      setDraft('')
      return false
    }
    if (!EMAIL_RE.test(trimmed)) {
      setError('Invalid email address')
      return false
    }
    // De-duplicate (case-insensitive) — silently drop an exact repeat.
    const exists = values.some((v) => v.toLowerCase() === trimmed.toLowerCase())
    if (!exists) onChange([...values, trimmed])
    setDraft('')
    setError(null)
    return true
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (COMMIT_KEYS.has(e.key)) {
      // Tab only commits when there is pending text; otherwise let focus move on.
      if (e.key === 'Tab' && draft.trim() === '') return
      e.preventDefault()
      commitDraft()
      return
    }
    // Backspace on an empty draft removes the last chip.
    if (e.key === 'Backspace' && draft === '' && values.length > 0) {
      e.preventDefault()
      removeAt(values.length - 1)
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData('text')
    if (!/[,;\s]/.test(text)) return // single token — let the input handle it
    e.preventDefault()
    const tokens = text.split(/[,;\s]+/).map((t) => t.trim()).filter(Boolean)
    const next = [...values]
    let anyInvalid = false
    for (const token of tokens) {
      if (!EMAIL_RE.test(token)) {
        anyInvalid = true
        continue
      }
      if (!next.some((v) => v.toLowerCase() === token.toLowerCase())) next.push(token)
    }
    onChange(next)
    setError(anyInvalid ? 'Invalid email address' : null)
  }

  return (
    <div className="flex flex-col gap-[7px]">
      <label htmlFor={inputId} className="text-[12.5px] font-medium text-text">
        {label}
        {required && <span className="ml-1 text-danger" aria-hidden="true">*</span>}
        {required && <span className="sr-only"> (required)</span>}
      </label>

      <div
        className={cx(
          'flex min-h-[42px] w-full flex-wrap items-center gap-[6px] rounded-ctl border bg-card px-[8px] py-[6px]',
          'transition-[border-color,box-shadow] duration-150 focus-within:shadow-[0_0_0_3px_var(--accent-soft)]',
          error ? 'border-danger focus-within:border-danger' : 'border-border focus-within:border-accent',
        )}
      >
        {values.map((email, index) => {
          const kind = blocklistKindFor(email, blocklist)
          const isHard = kind === 'hard'
          const isSoft = kind === 'soft'
          const tooltip = isHard
            ? `${email} hard-bounced and is blocked from delivery.`
            : isSoft
              ? 'Recently soft-bounced — may not deliver. Continue at your own discretion.'
              : undefined
          return (
            <span
              key={`${email}-${index}`}
              title={tooltip}
              className={cx(
                'inline-flex max-w-full items-center gap-[5px] rounded-chip border px-[8px] py-[3px] text-[12.5px]',
                isHard && 'border-danger bg-danger-soft text-danger',
                isSoft && 'border-warn bg-warn-soft text-warn',
                !kind && 'border-border bg-canvas text-text',
              )}
            >
              {isHard && <ErrorOctagonIcon />}
              {isSoft && <WarningTriangleIcon />}
              <span className="truncate">{email}</span>
              {isHard && canOverrideHard && (
                <button
                  type="button"
                  onClick={onOverrideHard}
                  className="ml-[2px] rounded px-[4px] text-[11px] font-medium underline underline-offset-2 hover:bg-black/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
                >
                  Override once
                </button>
              )}
              <button
                type="button"
                onClick={() => removeAt(index)}
                aria-label={`Remove ${email}`}
                className="grid h-[18px] w-[18px] flex-shrink-0 place-items-center rounded-full leading-none hover:bg-black/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
              >
                <span aria-hidden="true">×</span>
              </button>
            </span>
          )
        })}

        <input
          id={inputId}
          type="text"
          inputMode="email"
          autoComplete="off"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            if (error) setError(null)
          }}
          onKeyDown={handleKeyDown}
          onBlur={() => commitDraft()}
          onPaste={handlePaste}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? errorId : undefined}
          aria-required={required ? 'true' : undefined}
          className="h-[30px] min-w-[120px] flex-1 bg-transparent px-[5px] text-[13.5px] text-text outline-none placeholder:text-muted-2"
        />
      </div>

      {error && (
        <p id={errorId} className="text-[12.5px] text-danger" role="alert">
          {error}
        </p>
      )}

      {hasHardBounce && !canOverrideHard && (
        <p className="text-[12px] text-muted">
          A hard-bounced recipient is present. Remove it to enable sending.
        </p>
      )}
    </div>
  )
}

export default RecipientChips
