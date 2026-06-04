import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

/**
 * Button — the design system's primary action control.
 *
 * Matches the prototype's `.btn` family from OraInvoice_Handoff/app/ds.css and
 * the variants enumerated in OraInvoice_Handoff/app/Components.html:
 *
 *   .btn          base: inline-flex, h-40, px-16, gap-8, rounded-ctl (10px),
 *                 13.5px / 600, 1px transparent border, active translateY(1px),
 *                 svg 17×17.
 *   .btn-primary  accent bg, white text, layered drop + inset-highlight shadow,
 *                 hover → accent-press.
 *   .btn-ghost    card bg, text, border → hover canvas bg + border-strong.
 *   .btn-quiet    transparent, muted text → hover canvas bg + text.
 *   .btn-danger   danger bg, white text.
 *   .btn-sm       h-34, px-12, 13px.
 *   .btn-icon     square (w-40, px-0); .btn-icon.btn-sm → w-34.
 *
 * Additions designed on-the-fly to fit the same language (FR-2b): a focus-visible
 * accent ring for keyboard users, a disabled state, an optional `loading`
 * spinner, `leftIcon`/`rightIcon` slots (the Components.html primary button
 * shows a leading glyph), `fullWidth`, and optional anchor rendering via `href`
 * so a link can be styled as a button.
 */
export type ButtonVariant = 'primary' | 'ghost' | 'quiet' | 'danger'
export type ButtonSize = 'md' | 'sm'

/* ── Class fragments, mapped 1:1 to the ds.css rules ── */

/** `.btn` base — shared by every variant/size, anchors and buttons alike. */
const BASE =
  'inline-flex items-center justify-center gap-2 rounded-ctl border border-transparent font-semibold leading-none whitespace-nowrap align-middle ' +
  'transition-[background-color,border-color,transform] duration-150 active:translate-y-px ' +
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card ' +
  'disabled:pointer-events-none disabled:opacity-60 [&_svg]:h-[17px] [&_svg]:w-[17px] [&_svg]:flex-shrink-0'

const VARIANT: Record<ButtonVariant, string> = {
  // box-shadow = 0 1px 2px rgba(16,24,40,.18), inset 0 1px 0 rgba(255,255,255,.14)
  primary:
    'bg-accent text-white shadow-[0_1px_2px_rgba(16,24,40,0.18),inset_0_1px_0_rgba(255,255,255,0.14)] hover:bg-accent-press',
  ghost: 'bg-card text-text border-border hover:bg-canvas hover:border-border-strong',
  quiet: 'bg-transparent text-muted hover:bg-canvas hover:text-text',
  // ds.css .btn-danger has no hover; brightness-95 is a token-free hover affordance.
  danger: 'bg-danger text-white hover:brightness-95',
}

/** Text sizes — `.btn` (md) vs `.btn-sm`. */
const SIZE: Record<ButtonSize, string> = {
  md: 'h-10 px-4 text-[13.5px]',
  sm: 'h-[34px] px-3 text-[13px]',
}

/** Square `.btn-icon` widths (override the horizontal padding). */
const ICON_SIZE: Record<ButtonSize, string> = {
  md: 'w-10 px-0',
  sm: 'w-[34px] px-0',
}

/**
 * Compute the full className for a button-styled control. Exported so other
 * primitives / pages can render a button-styled element (e.g. a Headless UI
 * MenuButton) without duplicating the class strings.
 */
export function buttonClasses(opts: {
  variant?: ButtonVariant
  size?: ButtonSize
  fullWidth?: boolean
  iconOnly?: boolean
  className?: string
}): string {
  const { variant = 'primary', size = 'md', fullWidth, iconOnly, className } = opts
  return cx(
    BASE,
    VARIANT[variant],
    iconOnly ? ICON_SIZE[size] : SIZE[size],
    fullWidth && 'w-full',
    className,
  )
}

/** Minimal inline spinner used by the `loading` state (inherits currentColor). */
function Spinner() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="animate-spin"
      data-testid="button-spinner"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" className="opacity-25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Stretch to the full width of the container (`w-full`). */
  fullWidth?: boolean
  /** Render as a square icon-only button (`.btn-icon`). Pair with an aria-label. */
  iconOnly?: boolean
  /** Content rendered before the label (e.g. a 17×17 stroke glyph). */
  leftIcon?: ReactNode
  /** Content rendered after the label. */
  rightIcon?: ReactNode
  /** Show a spinner and disable interaction. */
  loading?: boolean
  /**
   * When provided, the control renders as a styled anchor (`<a>`) instead of a
   * `<button>` so links can look like buttons. `disabled`/`loading`/icon props
   * still apply; the ref then points at the anchor.
   */
  href?: string
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    fullWidth = false,
    iconOnly = false,
    leftIcon,
    rightIcon,
    loading = false,
    href,
    type,
    className,
    children,
    disabled,
    ...rest
  },
  ref,
) {
  const classes = buttonClasses({ variant, size, fullWidth, iconOnly, className })
  const isDisabled = disabled || loading

  const content = (
    <>
      {loading ? <Spinner /> : leftIcon}
      {children}
      {!loading && rightIcon}
    </>
  )

  // Anchor rendering — link styled as a button. A disabled link drops its href
  // and is marked aria-disabled (anchors can't be natively disabled).
  if (href !== undefined) {
    return (
      <a
        ref={ref as unknown as React.Ref<HTMLAnchorElement>}
        href={isDisabled ? undefined : href}
        aria-disabled={isDisabled || undefined}
        aria-busy={loading || undefined}
        className={cx(classes, isDisabled && 'pointer-events-none opacity-60')}
        {...(rest as unknown as React.AnchorHTMLAttributes<HTMLAnchorElement>)}
      >
        {content}
      </a>
    )
  }

  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={classes}
      {...rest}
    >
      {content}
    </button>
  )
})

export default Button
