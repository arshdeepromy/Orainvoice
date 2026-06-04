import { forwardRef } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

/**
 * Badge — the status pill used across tables, detail headers and lists.
 *
 * Matches the prototype's `.badge` family from OraInvoice_Handoff/app/ds.css and
 * the variants shown in OraInvoice_Handoff/app/Components.html (Paid / Sent /
 * Overdue / Pending / Draft, each with a leading `.b-dot`):
 *
 *   .badge        inline-flex, gap 6, 11.5px / 500, padding 3px 10px,
 *                 rounded 20px, no-wrap; `.b-dot` is a 6×6 circle.
 *
 * ds.css colour mappings (soft bg + matching solid text + dot), preserved 1:1:
 *   paid / active / completed / success     → ok-soft  / ok
 *   sent / info / inprogress                → accent-soft / accent
 *   overdue / danger / failed               → danger-soft / danger
 *   draft / neutral                         → #EEF0F4 / muted   (dot muted-2)
 *   pending / warn                          → warn-soft / warn
 *
 * The `variant` union exposes the status names Task 11 calls for
 * (paid|sent|overdue|draft) plus the generic tone names
 * (ok|warn|danger|neutral|info) and the other prototype aliases.
 *
 * The draft/neutral background (#EEF0F4) is the one value ds.css writes as a raw
 * hex with no corresponding token, so it's matched here as an arbitrary value to
 * keep the pill pixel-identical to the prototype; every other colour uses a
 * design token.
 */
export type BadgeVariant =
  // status names (Task 11)
  | 'paid'
  | 'sent'
  | 'overdue'
  | 'draft'
  // generic tones
  | 'ok'
  | 'warn'
  | 'danger'
  | 'neutral'
  | 'info'
  // other prototype aliases
  | 'active'
  | 'completed'
  | 'success'
  | 'inprogress'
  | 'failed'
  | 'pending'

/** The four underlying colour tones (soft bg + text + dot) from ds.css. */
type Tone = 'success' | 'info' | 'danger' | 'neutral' | 'warn'

const TONE_CLASSES: Record<Tone, string> = {
  success: 'bg-ok-soft text-ok',
  info: 'bg-accent-soft text-accent',
  danger: 'bg-danger-soft text-danger',
  // ds.css uses a raw #EEF0F4 here (no token); matched exactly for fidelity.
  neutral: 'bg-[#EEF0F4] text-muted',
  warn: 'bg-warn-soft text-warn',
}

const TONE_DOT: Record<Tone, string> = {
  success: 'bg-ok',
  info: 'bg-accent',
  danger: 'bg-danger',
  neutral: 'bg-muted-2',
  warn: 'bg-warn',
}

/** Map every variant alias onto its underlying tone (mirrors ds.css selectors). */
const VARIANT_TONE: Record<BadgeVariant, Tone> = {
  paid: 'success',
  active: 'success',
  completed: 'success',
  success: 'success',
  ok: 'success',

  sent: 'info',
  info: 'info',
  inprogress: 'info',

  overdue: 'danger',
  danger: 'danger',
  failed: 'danger',

  draft: 'neutral',
  neutral: 'neutral',

  pending: 'warn',
  warn: 'warn',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
  /**
   * Show the leading status dot (prototype `.b-dot`). Defaults to true to match
   * the status pills in Components.html; set false for a dot-less label pill.
   */
  dot?: boolean
  children?: ReactNode
}

const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { variant = 'neutral', dot = true, className, children, ...rest },
  ref,
) {
  const tone = VARIANT_TONE[variant]
  return (
    <span
      ref={ref}
      className={cx(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-[20px] px-2.5 py-[3px] text-[11.5px] font-medium',
        TONE_CLASSES[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span className={cx('h-1.5 w-1.5 rounded-full', TONE_DOT[tone])} aria-hidden="true" />}
      {children}
    </span>
  )
})

/**
 * Map an invoice / quote status string to a Badge variant.
 *
 * Convenience for consuming pages so they don't repeat the mapping. Unknown or
 * empty statuses fall back to `neutral`. Matching is case-insensitive and
 * tolerates spaces / hyphens (e.g. "In Progress", "in-progress" → inprogress).
 */
export function statusToBadgeVariant(status: string | null | undefined): BadgeVariant {
  if (!status) return 'neutral'
  const key = status.toLowerCase().replace(/[\s_-]+/g, '')
  const map: Record<string, BadgeVariant> = {
    paid: 'paid',
    sent: 'sent',
    issued: 'sent',
    overdue: 'overdue',
    draft: 'draft',
    cancelled: 'neutral',
    canceled: 'neutral',
    void: 'neutral',
    voided: 'neutral',
    accepted: 'paid',
    approved: 'paid',
    active: 'active',
    completed: 'completed',
    complete: 'completed',
    success: 'success',
    inprogress: 'inprogress',
    pending: 'pending',
    partial: 'pending',
    declined: 'danger',
    rejected: 'danger',
    failed: 'failed',
    expired: 'overdue',
  }
  return map[key] ?? 'neutral'
}

export default Badge
