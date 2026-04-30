import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatusBadge from '../StatusBadge'
import { STATUS_CONFIG } from '@/utils/statusConfig'

describe('StatusBadge', () => {
  it('renders the correct label for each known status', () => {
    for (const [status, config] of Object.entries(STATUS_CONFIG)) {
      const { unmount } = render(<StatusBadge status={status} />)
      expect(screen.getByText(config.label)).toBeInTheDocument()
      unmount()
    }
  })

  it('applies the correct colour classes for a known status', () => {
    const { container } = render(<StatusBadge status="paid" />)
    const chip = container.firstElementChild as HTMLElement
    expect(chip.className).toContain('text-emerald-600')
    expect(chip.className).toContain('bg-emerald-100')
  })

  it('falls back to uppercase status key for unknown statuses', () => {
    render(<StatusBadge status="some_custom_status" />)
    expect(screen.getByText('SOME_CUSTOM_STATUS')).toBeInTheDocument()
  })

  it('falls back to gray styling for unknown statuses', () => {
    const { container } = render(<StatusBadge status="unknown_xyz" />)
    const chip = container.firstElementChild as HTMLElement
    expect(chip.className).toContain('text-gray-500')
    expect(chip.className).toContain('bg-gray-100')
  })

  it('defaults to sm size', () => {
    const { container } = render(<StatusBadge status="draft" />)
    const chip = container.firstElementChild as HTMLElement
    expect(chip.className).toContain('text-xs')
  })

  it('applies md size classes when size="md"', () => {
    const { container } = render(<StatusBadge status="draft" size="md" />)
    const chip = container.firstElementChild as HTMLElement
    expect(chip.className).toContain('text-sm')
  })

  it('renders all 8 invoice statuses without error', () => {
    const statuses = [
      'draft', 'issued', 'partially_paid', 'paid',
      'overdue', 'voided', 'refunded', 'partially_refunded',
    ]
    for (const status of statuses) {
      const { unmount } = render(<StatusBadge status={status} />)
      const config = STATUS_CONFIG[status]
      expect(screen.getByText(config.label)).toBeInTheDocument()
      unmount()
    }
  })
})
