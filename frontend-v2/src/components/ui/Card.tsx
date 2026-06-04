import { forwardRef } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

/**
 * Card + Card.Head + Card.Body — the design system's surface container.
 *
 * Matches the prototype's `.card` family from OraInvoice_Handoff/app/ds.css:
 *   .card       card bg, 1px border, rounded-card (14px), shadow-card.
 *   .card-head  flex row, space-between, gap 12, padding 17px 20px, bottom
 *               border; its `h2` is 15px / 600 and a `.link` is 12.5px / 500
 *               accent.
 *   .card-body  padding 20px.
 *
 * Composition mirrors the prototype markup
 *   <section class="card"><div class="card-head"><h2>…</h2></div>
 *     <div class="card-body">…</div></section>
 * via <Card><CardHead>…</CardHead><CardBody>…</CardBody></Card>, also reachable
 * as Card.Head / Card.Body.
 */

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children?: ReactNode
}

const CardRoot = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx(
        'rounded-card border border-border bg-card shadow-card',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
})

// Omit the native `title` attr (string) so we can accept a ReactNode heading.
export interface CardHeadProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /**
   * Convenience: when provided, renders as the prototype's `.card-head h2`
   * (15px / 600). Omit and pass `children` for full control of the header row.
   */
  title?: ReactNode
  /** Right-aligned content (actions, a `.link`, a badge, etc.). */
  action?: ReactNode
  children?: ReactNode
}

const CardHead = forwardRef<HTMLDivElement, CardHeadProps>(function CardHead(
  { title, action, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx(
        'flex items-center justify-between gap-3 border-b border-border px-5 py-[17px]',
        className,
      )}
      {...rest}
    >
      {children ?? (
        <>
          {title != null && <h2 className="text-[15px] font-semibold text-text">{title}</h2>}
          {action != null && <div className="flex items-center gap-2">{action}</div>}
        </>
      )}
    </div>
  )
})

export interface CardBodyProps extends HTMLAttributes<HTMLDivElement> {
  children?: ReactNode
}

const CardBody = forwardRef<HTMLDivElement, CardBodyProps>(function CardBody(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('p-5', className)} {...rest}>
      {children}
    </div>
  )
})

/** A `.card-head .link` styled accent link/button for header actions. */
export interface CardLinkProps extends HTMLAttributes<HTMLElement> {
  children?: ReactNode
}

type CardComponent = typeof CardRoot & {
  Head: typeof CardHead
  Body: typeof CardBody
}

const Card = CardRoot as CardComponent
Card.Head = CardHead
Card.Body = CardBody

export { CardHead, CardBody }
export default Card
