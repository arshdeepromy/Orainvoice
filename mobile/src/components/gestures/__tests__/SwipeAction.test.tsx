import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SwipeAction } from '../SwipeAction'
import type { SwipeActionConfig } from '../SwipeAction'

const PhoneIcon = ({ className }: { className?: string }) => (
  <svg className={className} data-testid="phone-icon" />
)
const TrashIcon = ({ className }: { className?: string }) => (
  <svg className={className} data-testid="trash-icon" />
)

function makeLeftActions(): SwipeActionConfig[] {
  return [
    {
      label: 'Call',
      icon: PhoneIcon,
      color: 'bg-green-500',
      onAction: vi.fn(),
    },
  ]
}

function makeRightActions(): SwipeActionConfig[] {
  return [
    {
      label: 'Delete',
      icon: TrashIcon,
      color: 'bg-red-500',
      onAction: vi.fn(),
    },
  ]
}

describe('SwipeAction', () => {
  it('renders children', () => {
    render(
      <SwipeAction>
        <div>Item content</div>
      </SwipeAction>,
    )
    expect(screen.getByText('Item content')).toBeInTheDocument()
  })

  it('renders left action buttons', () => {
    const leftActions = makeLeftActions()
    render(
      <SwipeAction leftActions={leftActions}>
        <div>Item</div>
      </SwipeAction>,
    )
    expect(screen.getByLabelText('Call')).toBeInTheDocument()
  })

  it('renders right action buttons', () => {
    const rightActions = makeRightActions()
    render(
      <SwipeAction rightActions={rightActions}>
        <div>Item</div>
      </SwipeAction>,
    )
    expect(screen.getByLabelText('Delete')).toBeInTheDocument()
  })

  it('calls onAction when action button is clicked', () => {
    const rightActions = makeRightActions()
    render(
      <SwipeAction rightActions={rightActions}>
        <div>Item</div>
      </SwipeAction>,
    )
    fireEvent.click(screen.getByLabelText('Delete'))
    expect(rightActions[0].onAction).toHaveBeenCalledOnce()
  })

  it('has accessible role=group on container', () => {
    render(
      <SwipeAction>
        <div>Item</div>
      </SwipeAction>,
    )
    expect(screen.getByRole('group')).toBeInTheDocument()
  })

  it('action buttons have 44px minimum touch targets', () => {
    const leftActions = makeLeftActions()
    render(
      <SwipeAction leftActions={leftActions}>
        <div>Item</div>
      </SwipeAction>,
    )
    const btn = screen.getByLabelText('Call')
    expect(btn.style.minHeight).toBe('44px')
    expect(btn.style.minWidth).toBe('44px')
  })

  it('renders both left and right actions simultaneously', () => {
    const leftActions = makeLeftActions()
    const rightActions = makeRightActions()
    render(
      <SwipeAction leftActions={leftActions} rightActions={rightActions}>
        <div>Item</div>
      </SwipeAction>,
    )
    expect(screen.getByLabelText('Call')).toBeInTheDocument()
    expect(screen.getByLabelText('Delete')).toBeInTheDocument()
  })

  it('applies dark mode background class to content', () => {
    const { container } = render(
      <SwipeAction>
        <div>Item</div>
      </SwipeAction>,
    )
    const contentDiv = container.querySelector('.dark\\:bg-gray-900')
    expect(contentDiv).toBeInTheDocument()
  })
})
