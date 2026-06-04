import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button, IconButton, Card, Badge, statusToBadgeVariant, cx } from './index'

/**
 * UI primitives tests (Task 11) — fast variant/prop rendering checks for the
 * shared Button, IconButton, Card and Badge built from the ds.css classes.
 */

describe('cx', () => {
  it('joins truthy strings, arrays and object maps; drops falsy values', () => {
    expect(cx('a', false, null, undefined, 'b')).toBe('a b')
    expect(cx(['a', 'b'], { c: true, d: false })).toBe('a b c')
  })
})

describe('Button — variants & sizes', () => {
  it('renders the primary variant with the accent bg + inset-highlight shadow', () => {
    render(<Button>Save</Button>)
    const btn = screen.getByRole('button', { name: 'Save' })
    expect(btn).toHaveClass('bg-accent')
    // Inset highlight shadow on the primary button (ds.css .btn-primary).
    expect(btn.className).toContain('inset_0_1px_0_rgba(255,255,255,0.14)')
    // Default md size + button type.
    expect(btn).toHaveClass('h-10')
    expect(btn).toHaveAttribute('type', 'button')
  })

  it('maps ghost / quiet / danger variants to the ds.css class fragments', () => {
    const { rerender } = render(<Button variant="ghost">Ghost</Button>)
    expect(screen.getByRole('button')).toHaveClass('bg-card', 'border-border')

    rerender(<Button variant="quiet">Quiet</Button>)
    expect(screen.getByRole('button')).toHaveClass('bg-transparent', 'text-muted')

    rerender(<Button variant="danger">Delete</Button>)
    expect(screen.getByRole('button')).toHaveClass('bg-danger', 'text-white')
  })

  it('applies the sm size and fullWidth/iconOnly modifiers', () => {
    const { rerender } = render(<Button size="sm">Small</Button>)
    expect(screen.getByRole('button')).toHaveClass('h-[34px]')

    rerender(<Button fullWidth>Wide</Button>)
    expect(screen.getByRole('button')).toHaveClass('w-full')

    rerender(
      <Button iconOnly aria-label="More">
        <svg />
      </Button>,
    )
    expect(screen.getByRole('button', { name: 'More' })).toHaveClass('w-10', 'px-0')
  })

  it('renders left/right icons and a loading spinner (disabled + aria-busy)', async () => {
    const onClick = vi.fn()
    const { rerender } = render(
      <Button leftIcon={<svg data-testid="left" />} rightIcon={<svg data-testid="right" />}>
        Go
      </Button>,
    )
    expect(screen.getByTestId('left')).toBeInTheDocument()
    expect(screen.getByTestId('right')).toBeInTheDocument()

    rerender(
      <Button loading onClick={onClick}>
        Go
      </Button>,
    )
    const btn = screen.getByRole('button')
    expect(screen.getByTestId('button-spinner')).toBeInTheDocument()
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('aria-busy', 'true')
    await userEvent.click(btn)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders as a styled anchor when href is given', () => {
    render(<Button href="/invoices/new">New invoice</Button>)
    const link = screen.getByRole('link', { name: 'New invoice' })
    expect(link).toHaveAttribute('href', '/invoices/new')
    expect(link).toHaveClass('bg-accent')
  })

  it('appends a caller className last so overrides win by source order', () => {
    render(<Button className="custom-x">X</Button>)
    expect(screen.getByRole('button').className.trim().endsWith('custom-x')).toBe(true)
  })
})

describe('IconButton', () => {
  it('requires an aria-label and renders a 40px square with optional badge', () => {
    render(
      <IconButton aria-label="Notifications" badge>
        <svg />
      </IconButton>,
    )
    const btn = screen.getByRole('button', { name: 'Notifications' })
    expect(btn).toHaveClass('h-10', 'w-10', 'rounded-ctl')
    // Badge dot present (decorative).
    expect(btn.querySelector('span[aria-hidden="true"]')).not.toBeNull()
  })
})

describe('Card', () => {
  it('composes head + body with the ds.css surface classes', () => {
    render(
      <Card data-testid="card">
        <Card.Head title="Recent invoices" action={<a className="text-accent">View all</a>} />
        <Card.Body>Body content</Card.Body>
      </Card>,
    )
    const card = screen.getByTestId('card')
    expect(card).toHaveClass('rounded-card', 'border-border', 'bg-card', 'shadow-card')
    // Head renders the title as an h2 and the action.
    expect(screen.getByRole('heading', { level: 2, name: 'Recent invoices' })).toBeInTheDocument()
    expect(screen.getByText('View all')).toBeInTheDocument()
    expect(screen.getByText('Body content')).toBeInTheDocument()
  })
})

describe('Badge — status variants', () => {
  // tone class expectations for the four Task 11 status names + generic tones
  const cases: Array<[Parameters<typeof Badge>[0]['variant'], string, string]> = [
    ['paid', 'bg-ok-soft', 'text-ok'],
    ['sent', 'bg-accent-soft', 'text-accent'],
    ['overdue', 'bg-danger-soft', 'text-danger'],
    ['draft', 'bg-[#EEF0F4]', 'text-muted'],
    ['warn', 'bg-warn-soft', 'text-warn'],
    ['ok', 'bg-ok-soft', 'text-ok'],
    ['danger', 'bg-danger-soft', 'text-danger'],
    ['neutral', 'bg-[#EEF0F4]', 'text-muted'],
    ['info', 'bg-accent-soft', 'text-accent'],
  ]

  it.each(cases)('variant %s → %s / %s with a status dot', (variant, bg, fg) => {
    render(<Badge variant={variant}>{String(variant)}</Badge>)
    const badge = screen.getByText(String(variant))
    expect(badge).toHaveClass(bg, fg, 'rounded-[20px]')
    // Dot shown by default.
    expect(badge.querySelector('span[aria-hidden="true"]')).not.toBeNull()
  })

  it('hides the dot when dot={false}', () => {
    render(<Badge variant="paid" dot={false}>Paid</Badge>)
    expect(screen.getByText('Paid').querySelector('span[aria-hidden="true"]')).toBeNull()
  })
})

describe('statusToBadgeVariant', () => {
  it('maps known statuses case/format-insensitively and falls back to neutral', () => {
    expect(statusToBadgeVariant('Paid')).toBe('paid')
    expect(statusToBadgeVariant('OVERDUE')).toBe('overdue')
    expect(statusToBadgeVariant('in progress')).toBe('inprogress')
    expect(statusToBadgeVariant('in-progress')).toBe('inprogress')
    expect(statusToBadgeVariant('issued')).toBe('sent')
    expect(statusToBadgeVariant(undefined)).toBe('neutral')
    expect(statusToBadgeVariant('something-unknown')).toBe('neutral')
  })
})
