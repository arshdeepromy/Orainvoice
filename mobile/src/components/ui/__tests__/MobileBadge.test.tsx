import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { MobileBadge } from '../MobileBadge'

describe('MobileBadge', () => {
  it('renders label text', () => {
    render(<MobileBadge label="Paid" variant="paid" />)
    expect(screen.getByText('Paid')).toBeInTheDocument()
  })

  it('applies paid variant styles (green)', () => {
    render(<MobileBadge label="Paid" variant="paid" />)
    const badge = screen.getByText('Paid')
    expect(badge.className).toContain('bg-green-100')
    expect(badge.className).toContain('dark:bg-green-900')
  })

  it('applies overdue variant styles (red)', () => {
    render(<MobileBadge label="Overdue" variant="overdue" />)
    const badge = screen.getByText('Overdue')
    expect(badge.className).toContain('bg-red-100')
  })

  it('applies draft variant styles (gray)', () => {
    render(<MobileBadge label="Draft" variant="draft" />)
    const badge = screen.getByText('Draft')
    expect(badge.className).toContain('bg-gray-100')
  })

  it('applies expiring variant styles (orange)', () => {
    render(<MobileBadge label="Expiring" variant="expiring" />)
    const badge = screen.getByText('Expiring')
    expect(badge.className).toContain('bg-orange-100')
  })

  it('defaults to info variant', () => {
    render(<MobileBadge label="Note" />)
    const badge = screen.getByText('Note')
    expect(badge.className).toContain('bg-blue-100')
  })
})
