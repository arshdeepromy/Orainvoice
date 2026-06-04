import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

/**
 * IconButton — the 40px square icon control used in the top bar.
 *
 * Matches the prototype's `.icon-btn` from OraInvoice_Handoff/app/ds.css:
 *   width/height 40, rounded-ctl (10px), 1px border, card bg, muted icon;
 *   hover → canvas bg, text color, border-strong; svg 19×19. Also supports the
 *   `.icon-btn .bdg` indicator (a 7×7 danger dot with a 2px card-colored ring,
 *   top:7px right:8px) used by the notifications bell.
 *
 * This is the same visual the ported TopBar (Task 8) inlines for its
 * notifications button; IconButton captures it so future code uses the
 * primitive instead of re-inlining the classes.
 *
 * Accessibility: `aria-label` is REQUIRED in the type — an icon-only control has
 * no text content, so a label is mandatory for screen readers.
 */
export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** Required — icon-only buttons must be labelled for assistive tech. */
  'aria-label': string
  /** The icon to render (typically a 19×19 stroke SVG glyph). */
  children: ReactNode
  /**
   * Show the small status indicator dot in the top-right corner
   * (prototype `.icon-btn .bdg`). Used by the notifications bell.
   */
  badge?: boolean
}

const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { children, badge = false, type, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={cx(
        'relative grid h-10 w-10 flex-shrink-0 place-items-center rounded-ctl border border-border bg-card text-muted',
        'transition-[background-color,color,border-color] duration-150',
        'hover:bg-canvas hover:text-text hover:border-border-strong',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card',
        'disabled:pointer-events-none disabled:opacity-60 [&_svg]:h-[19px] [&_svg]:w-[19px]',
        className,
      )}
      {...rest}
    >
      {children}
      {badge && (
        <span
          className="absolute right-2 top-[7px] h-[7px] w-[7px] rounded-full border-2 border-card bg-danger"
          aria-hidden="true"
        />
      )}
    </button>
  )
})

export default IconButton
