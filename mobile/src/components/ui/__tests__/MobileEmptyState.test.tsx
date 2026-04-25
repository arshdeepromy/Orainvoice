import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { MobileEmptyState } from '../MobileEmptyState'

describe('MobileEmptyState', () => {
  it('renders message', () => {
    render(<MobileEmptyState message="No invoices found" />)
    expect(screen.getByText('No invoices found')).toBeInTheDocument()
  })

  it('renders default icon when no custom icon provided', () => {
    const { container } = render(<MobileEmptyState message="Empty" />)
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('renders custom icon when provided', () => {
    render(
      <MobileEmptyState
        message="Empty"
        icon={<span data-testid="custom-icon">🔍</span>}
      />,
    )
    expect(screen.getByTestId('custom-icon')).toBeInTheDocument()
  })

  it('renders action button when provided', () => {
    render(
      <MobileEmptyState
        message="No items"
        action={<button>Create first item</button>}
      />,
    )
    expect(screen.getByRole('button', { name: 'Create first item' })).toBeInTheDocument()
  })
})
