import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { MobileCard } from '../MobileCard'

describe('MobileCard', () => {
  it('renders children', () => {
    render(<MobileCard>Card content</MobileCard>)
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })

  it('applies dark mode and shadow classes', () => {
    const { container } = render(<MobileCard>Content</MobileCard>)
    const card = container.firstChild as HTMLElement
    expect(card.className).toContain('dark:bg-gray-800')
    expect(card.className).toContain('shadow-sm')
    expect(card.className).toContain('rounded-xl')
  })

  it('is not interactive when no onTap provided', () => {
    const { container } = render(<MobileCard>Content</MobileCard>)
    const card = container.firstChild as HTMLElement
    expect(card.getAttribute('role')).toBeNull()
    expect(card.getAttribute('tabindex')).toBeNull()
  })

  it('becomes interactive with onTap — role=button, tabIndex=0', () => {
    const onTap = vi.fn()
    const { container } = render(<MobileCard onTap={onTap}>Tap me</MobileCard>)
    const card = container.firstChild as HTMLElement
    expect(card.getAttribute('role')).toBe('button')
    expect(card.getAttribute('tabindex')).toBe('0')
  })

  it('calls onTap when clicked', () => {
    const onTap = vi.fn()
    render(<MobileCard onTap={onTap}>Tap me</MobileCard>)
    fireEvent.click(screen.getByText('Tap me'))
    expect(onTap).toHaveBeenCalledOnce()
  })

  it('calls onTap on Enter key', async () => {
    const onTap = vi.fn()
    render(<MobileCard onTap={onTap}>Tap me</MobileCard>)
    const card = screen.getByRole('button')
    await userEvent.type(card, '{Enter}')
    expect(onTap).toHaveBeenCalled()
  })

  it('applies custom className and padding', () => {
    const { container } = render(
      <MobileCard className="my-class" padding="p-8">
        Content
      </MobileCard>,
    )
    const card = container.firstChild as HTMLElement
    expect(card.className).toContain('my-class')
    expect(card.className).toContain('p-8')
    expect(card.className).not.toContain('p-4')
  })
})
