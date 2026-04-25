import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MobileListItem } from '../MobileListItem'

describe('MobileListItem', () => {
  it('renders title and subtitle', () => {
    render(<MobileListItem title="John Doe" subtitle="john@example.com" />)
    expect(screen.getByText('John Doe')).toBeInTheDocument()
    expect(screen.getByText('john@example.com')).toBeInTheDocument()
  })

  it('renders trailing content', () => {
    render(<MobileListItem title="Invoice" trailing={<span>$100</span>} />)
    expect(screen.getByText('$100')).toBeInTheDocument()
  })

  it('renders leading content', () => {
    render(<MobileListItem title="Item" leading={<span data-testid="icon">★</span>} />)
    expect(screen.getByTestId('icon')).toBeInTheDocument()
  })

  it('is interactive when onTap is provided', () => {
    const onTap = vi.fn()
    render(<MobileListItem title="Tap me" onTap={onTap} />)
    const item = screen.getByRole('button')
    expect(item).toBeInTheDocument()
    fireEvent.click(item)
    expect(onTap).toHaveBeenCalledOnce()
  })

  it('is not interactive without onTap', () => {
    render(<MobileListItem title="Static" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('has min-h-[44px] for touch target', () => {
    const { container } = render(<MobileListItem title="Item" />)
    const item = container.firstChild as HTMLElement
    expect(item.className).toContain('min-h-[44px]')
  })
})
