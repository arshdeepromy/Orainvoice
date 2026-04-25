/**
 * Unit tests for WidgetCard component.
 *
 * Requirements: 14.1, 14.2, 15.5
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { WidgetCard } from '../WidgetCard'

function TestIcon({ className }: { className?: string }) {
  return <svg data-testid="widget-icon" className={className} />
}

function renderCard(props: Partial<Parameters<typeof WidgetCard>[0]> = {}) {
  const defaults = {
    title: 'Test Widget',
    icon: TestIcon,
    children: <p>Widget body content</p>,
  }
  return render(
    <MemoryRouter>
      <WidgetCard {...defaults} {...props} />
    </MemoryRouter>,
  )
}

describe('WidgetCard', () => {
  it('renders header with icon, title, and action link', () => {
    renderCard({
      title: 'Recent Customers',
      actionLink: { label: 'View all', to: '/customers' },
    })

    expect(screen.getByTestId('widget-icon')).toBeInTheDocument()
    expect(screen.getByText('Recent Customers')).toBeInTheDocument()

    const link = screen.getByText('View all')
    expect(link).toBeInTheDocument()
    expect(link.closest('a')).toHaveAttribute('href', '/customers')
  })

  it('renders children content when no error', () => {
    renderCard({ children: <p>Hello from widget</p> })

    expect(screen.getByText('Hello from widget')).toBeInTheDocument()
  })

  it('shows loading spinner when isLoading=true', () => {
    renderCard({ isLoading: true, title: 'Loading Widget' })

    // The Spinner renders a div with role="status"
    const spinner = screen.getByRole('status')
    expect(spinner).toBeInTheDocument()
    expect(spinner).toHaveAttribute('aria-label', 'Loading Loading Widget')
  })

  it('shows error message when error is set', () => {
    renderCard({ error: 'Something went wrong' })

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    // Children should NOT be rendered when error is set
    expect(screen.queryByText('Widget body content')).not.toBeInTheDocument()
  })

  it('does not render action link when actionLink is not provided', () => {
    renderCard({ title: 'No Link Widget' })

    expect(screen.getByText('No Link Widget')).toBeInTheDocument()
    // No anchor tags in the header
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
