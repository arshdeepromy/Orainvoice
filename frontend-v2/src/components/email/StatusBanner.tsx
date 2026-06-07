import { cx } from '../ui/cx'

/**
 * StatusBanner — inline failure/warning banner for the Send Email composer.
 *
 * A controlled, presentational component (R14.1): the parent (SendEmailModal,
 * task 11.7) decides the tone, message, and which actions to pass, mapping each
 * `FailureKind` to the right combination. This component only renders and calls
 * the handlers it is given. It is also reused for the preview load-error banner
 * and the over-size banner (the parent picks tone/message/actions).
 *
 * Behaviour (design.md → "StatusBanner.tsx"):
 *   - Renders `role="alert"` so screen readers announce it immediately (R27.3,
 *     R14.1). A leading stroke icon always accompanies the colour so colour is
 *     never the sole signal (R27.5).
 *   - `tone='red'` maps to the design-system danger tokens; `tone='amber'` maps
 *     to the warn tokens (R14.2–R14.5).
 *   - A Dismiss (×) action hides the banner without closing the modal — it just
 *     calls `onDismiss` (R14.6). The banner never auto-dismisses; there are no
 *     timers, so the user retains control (R14.7).
 *   - A **Retry** button renders ONLY when `onRetry` is provided. The parent
 *     passes it solely for SOFT_PROVIDER / BUDGET_EXCEEDED, where re-submitting
 *     the same payload can change the outcome (R14.8).
 *   - A **Copy details** button renders ONLY when `onCopyDetails` is provided.
 *     The parent passes it for SOFT_AUTH and owns the actual clipboard copy of
 *     the sanitised debug string (provider_key, attempt count, timestamp); this
 *     component just renders the button and calls `onCopyDetails` (R14.4).
 *   - The × has `aria-label="Dismiss"` and every action is a real, keyboard-
 *     reachable `<button>`.
 */

export type BannerTone = 'red' | 'amber'

export interface StatusBannerProps {
  tone: BannerTone
  message: string
  onDismiss: () => void
  /** Provided only for SOFT_PROVIDER / BUDGET_EXCEEDED (R14.8). */
  onRetry?: () => void
  /** Provided only for SOFT_AUTH (R14.4). */
  onCopyDetails?: () => void
}

const toneClasses: Record<BannerTone, string> = {
  red: 'bg-danger-soft text-danger',
  amber: 'bg-warn-soft text-warn',
}

/** Leading stroke-icon path per tone (matches the prototype's `.alert svg`). */
const toneIconPath: Record<BannerTone, string> = {
  // x-circle
  red: 'M12 9v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  // warning triangle
  amber: 'M12 9v4m0 4h.01M10.3 3.9l-8 14A2 2 0 004 21h16a2 2 0 001.7-3l-8-14a2 2 0 00-3.4 0z',
}

export function StatusBanner({
  tone,
  message,
  onDismiss,
  onRetry,
  onCopyDetails,
}: StatusBannerProps) {
  return (
    <div
      role="alert"
      className={cx(
        'flex items-start gap-[11px] rounded-ctl px-[15px] py-[13px] text-[13.5px] leading-[1.5]',
        toneClasses[tone],
      )}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className="mt-px h-[18px] w-[18px] flex-shrink-0"
      >
        <path d={toneIconPath[tone]} />
      </svg>

      <div className="flex flex-1 flex-col gap-[8px]">
        <p>{message}</p>

        {(onRetry || onCopyDetails) && (
          <div className="flex flex-wrap items-center gap-[14px]">
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="min-h-[32px] rounded-ctl border border-current px-[12px] text-[12.5px] font-medium hover:bg-black/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
              >
                Retry
              </button>
            )}
            {onCopyDetails && (
              <button
                type="button"
                onClick={onCopyDetails}
                className="rounded text-[12.5px] font-medium underline underline-offset-2 hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
              >
                Copy details
              </button>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="ml-auto grid h-[24px] w-[24px] flex-shrink-0 place-items-center rounded leading-none hover:bg-black/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  )
}

export default StatusBanner
