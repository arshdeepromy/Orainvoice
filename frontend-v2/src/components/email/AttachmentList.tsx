import { useEffect, useId, useMemo, useRef } from 'react'
import { cx } from '../ui/cx'
import type { AttachmentSpec } from './types'

/**
 * AttachmentList — the **Attachments** section of the Send Email composer.
 *
 * A controlled, presentational list (R7.1): one row per `AttachmentSpec`. It owns
 * no selection state — the committed checkbox state lives in `selected` (seeded by
 * the parent from each spec's `default_attached`, R7.2) and every toggle flows out
 * through `onToggle`. The parent (SendEmailModal, task 11.7) owns aggregating the
 * checked keys into the override payload's `attachments: string[]` (R7.5) and owns
 * disabling Send + rendering the over-size StatusBanner.
 *
 * Behaviour (design.md → "AttachmentList.tsx"):
 *   - Each row shows a checkbox (default from `default_attached`), the `label`, and
 *     a human-readable size — `{kb} KB` for sizes < 1 MB else `{mb} MB` (R7.2),
 *     rendered with `font-mono` + tabular-nums (`tnum`) so sizes align (R24.2).
 *   - Required attachments (`required=true`) render a checked **and** disabled
 *     ("locked") checkbox with a "Required" label/tooltip and cannot be unchecked
 *     (R7.2). A locked icon accompanies the text so colour is never the sole signal.
 *   - It computes the selected total (sum of `size_bytes` for checked rows) plus an
 *     `estimatedBodyBytes` body estimate (default 10 KB) and reports whether that
 *     exceeds `emailSizeLimitBytes` via `onOverSizeChange` so the parent can disable
 *     Send and show the over-size banner (R7.3). An inline indication is also shown.
 *   - When nothing is selected and there are no required attachments, that is a
 *     valid body-only email — the component forces nothing (R7.4).
 */

/** Default body-size estimate added to the attachment total (R7.3). */
export const DEFAULT_ESTIMATED_BODY_BYTES = 10 * 1024

const ONE_KB = 1024
const ONE_MB = 1024 * 1024

/**
 * Human-readable attachment size (R7.2): `{kb} KB` for sizes < 1 MB, otherwise
 * `{mb} MB`. KB is rounded to a whole number; MB keeps one decimal place.
 */
export function formatAttachmentSize(sizeBytes: number): string {
  const safe = Number.isFinite(sizeBytes) && sizeBytes > 0 ? sizeBytes : 0
  if (safe < ONE_MB) {
    return `${Math.round(safe / ONE_KB)} KB`
  }
  return `${(safe / ONE_MB).toFixed(1)} MB`
}

function LockIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-[13px] w-[13px] flex-shrink-0"
    >
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <path d="M7 11V7a5 5 0 0110 0v4" />
    </svg>
  )
}

export interface AttachmentListProps {
  attachments: AttachmentSpec[]
  /** Checked state keyed by `AttachmentSpec.key`; seeded from `default_attached`. */
  selected: Record<string, boolean>
  onToggle: (key: string, checked: boolean) => void
  /** Server-side EMAIL_SIZE_LIMIT exposed via the preview response (R7.3). */
  emailSizeLimitBytes: number
  /** Body-size estimate added to the attachment total; defaults to 10 KB (R7.3). */
  estimatedBodyBytes?: number
  /**
   * Reports the computed over-size condition (R7.3). The parent owns disabling
   * Send and rendering the over-size StatusBanner; this component only reports
   * the boolean whenever it changes.
   */
  onOverSizeChange?: (over: boolean) => void
}

export function AttachmentList({
  attachments,
  selected,
  onToggle,
  emailSizeLimitBytes,
  estimatedBodyBytes = DEFAULT_ESTIMATED_BODY_BYTES,
  onOverSizeChange,
}: AttachmentListProps) {
  const reactId = useId()

  // A required attachment is always counted as attached regardless of `selected`
  // (it cannot be unchecked — R7.2).
  const isChecked = (spec: AttachmentSpec) =>
    spec.required || selected[spec.key] === true

  const selectedBytes = useMemo(
    () =>
      attachments.reduce(
        (sum, spec) => (isChecked(spec) ? sum + (spec.size_bytes ?? 0) : sum),
        0,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attachments, selected],
  )

  const totalBytes = selectedBytes + estimatedBodyBytes
  const isOverSize = totalBytes > emailSizeLimitBytes

  // Report the over-size condition to the parent only when it actually changes,
  // so the parent can drive the Send-disabled state + banner (R7.3).
  const lastReported = useRef<boolean | null>(null)
  useEffect(() => {
    if (lastReported.current !== isOverSize) {
      lastReported.current = isOverSize
      onOverSizeChange?.(isOverSize)
    }
  }, [isOverSize, onOverSizeChange])

  if (attachments.length === 0) return null

  const groupLabelId = `attachments-label-${reactId}`

  return (
    <section aria-labelledby={groupLabelId} className="flex flex-col gap-[7px]">
      <h3 id={groupLabelId} className="text-[12.5px] font-medium text-text">
        Attachments
      </h3>

      <ul className="flex flex-col gap-[2px]">
        {attachments.map((spec) => {
          const checked = isChecked(spec)
          const checkboxId = `attachment-${reactId}-${spec.key}`
          return (
            <li key={spec.key}>
              <label
                htmlFor={checkboxId}
                className={cx(
                  'flex min-h-[40px] w-full items-center gap-[10px] rounded-ctl px-[8px] py-[6px]',
                  spec.required ? 'cursor-default' : 'cursor-pointer hover:bg-canvas',
                )}
              >
                <input
                  id={checkboxId}
                  type="checkbox"
                  checked={checked}
                  disabled={spec.required}
                  aria-disabled={spec.required ? 'true' : undefined}
                  onChange={(e) => {
                    if (spec.required) return
                    onToggle(spec.key, e.target.checked)
                  }}
                  className="h-[16px] w-[16px] flex-shrink-0 accent-accent disabled:opacity-60"
                />

                <span className="flex-1 truncate text-[13.5px] text-text">
                  {spec.label}
                </span>

                {spec.required && (
                  <span
                    title="Required"
                    className="inline-flex flex-shrink-0 items-center gap-[4px] rounded-chip border border-border bg-canvas px-[6px] py-[2px] text-[11px] font-medium text-muted"
                  >
                    <LockIcon />
                    Required
                  </span>
                )}

                <span className="mono flex-shrink-0 text-[12px] tabular-nums text-muted">
                  {formatAttachmentSize(spec.size_bytes)}
                </span>
              </label>
            </li>
          )
        })}
      </ul>

      {isOverSize && (
        <p className="text-[12px] text-danger" role="alert">
          Total attachment size {formatAttachmentSize(selectedBytes)} exceeds the{' '}
          {formatAttachmentSize(emailSizeLimitBytes)} limit. Uncheck attachments to
          continue.
        </p>
      )}
    </section>
  )
}

export default AttachmentList
