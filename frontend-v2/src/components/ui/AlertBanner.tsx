import type { ReactNode } from 'react'

/**
 * AlertBanner — inline status banner (Task 13 port of
 * frontend/src/components/ui/AlertBanner).
 *
 * Public API preserved verbatim (`variant`, `title`, `children`, `onDismiss`,
 * `className`) so consuming auth pages keep their exact behaviour. Styling is
 * remapped to the prototype's `.alert` family from
 * OraInvoice_Handoff/app/auth.css:
 *   .alert       flex, gap 11px, padding 13px 15px, rounded-ctl, 13.5px / 1.5.
 *   .alert.err   danger-soft bg / danger text.
 *   .alert.warn  warn-soft bg / warn text.
 *   .alert.ok    ok-soft bg / ok text.
 *   .alert.info  accent-soft bg / accent text.
 * Each variant shows the prototype's leading stroke icon. The `success`
 * variant maps onto `.alert.ok`. The dismiss button is designed on-the-fly in
 * the same language (FR-2b): a quiet icon-button tinted to the alert's
 * currentColor.
 */
type AlertVariant = 'success' | 'warning' | 'error' | 'info'

interface AlertBannerProps {
  variant?: AlertVariant
  title?: string
  children: ReactNode
  onDismiss?: () => void
  className?: string
}

const variantClasses: Record<AlertVariant, string> = {
  success: 'bg-ok-soft text-ok',
  warning: 'bg-warn-soft text-warn',
  error: 'bg-danger-soft text-danger',
  info: 'bg-accent-soft text-accent',
}

/** Leading stroke-icon path per variant (from the prototype's `.alert svg`). */
const variantIconPath: Record<AlertVariant, string> = {
  // check-circle
  success: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
  // warning triangle (Login.html verify-alert)
  warning: 'M12 9v4m0 4h.01M10.3 3.9l-8 14A2 2 0 004 21h16a2 2 0 001.7-3l-8-14a2 2 0 00-3.4 0z',
  // x-circle
  error: 'M12 9v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  // info-circle (Signup.html info alert)
  info: 'M12 16v-4m0-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
}

const variantRoles: Record<AlertVariant, 'alert' | 'status'> = {
  success: 'status',
  warning: 'alert',
  error: 'alert',
  info: 'status',
}

export function AlertBanner({
  variant = 'info',
  title,
  children,
  onDismiss,
  className = '',
}: AlertBannerProps) {
  return (
    <div
      className={`flex items-start gap-[11px] rounded-ctl px-[15px] py-[13px] text-[13.5px] leading-[1.5] ${variantClasses[variant]} ${className}`}
      role={variantRoles[variant]}
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
        <path d={variantIconPath[variant]} />
      </svg>
      <div className="flex-1">
        {title && <p className="font-medium">{title}</p>}
        <div>{children}</div>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="ml-auto rounded p-1 hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
          aria-label="Dismiss alert"
          type="button"
        >
          <span aria-hidden="true">×</span>
        </button>
      )}
    </div>
  )
}
