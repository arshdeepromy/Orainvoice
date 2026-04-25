import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { MobileSpinner } from '../MobileSpinner'

describe('MobileSpinner', () => {
  it('renders with role=status', () => {
    render(<MobileSpinner />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('has sr-only loading text for accessibility', () => {
    render(<MobileSpinner />)
    expect(screen.getByText('Loading')).toBeInTheDocument()
  })

  it('applies size classes', () => {
    const { container: sm } = render(<MobileSpinner size="sm" />)
    expect(sm.querySelector('svg')?.getAttribute('class')).toContain('h-5')

    const { container: lg } = render(<MobileSpinner size="lg" />)
    expect(lg.querySelector('svg')?.getAttribute('class')).toContain('h-12')
  })

  it('has spin animation', () => {
    const { container } = render(<MobileSpinner />)
    expect(container.querySelector('svg')?.getAttribute('class')).toContain('animate-spin')
  })
})
