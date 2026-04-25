import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { OfflineIndicator } from '../OfflineIndicator'

// Mock the OfflineContext
const mockUseOffline = vi.fn()
vi.mock('@/contexts/OfflineContext', () => ({
  useOffline: () => mockUseOffline(),
}))

describe('OfflineIndicator', () => {
  it('renders nothing when online', () => {
    mockUseOffline.mockReturnValue({ isOnline: true, pendingCount: 0 })
    const { container } = render(<OfflineIndicator />)
    expect(container.firstChild).toBeNull()
  })

  it('renders offline banner when offline', () => {
    mockUseOffline.mockReturnValue({ isOnline: false, pendingCount: 0 })
    render(<OfflineIndicator />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.getByText('Offline')).toBeInTheDocument()
  })

  it('shows pending count when offline with queued mutations', () => {
    mockUseOffline.mockReturnValue({ isOnline: false, pendingCount: 3 })
    render(<OfflineIndicator />)
    expect(screen.getByText(/3 pending/)).toBeInTheDocument()
  })

  it('does not show pending count when count is zero', () => {
    mockUseOffline.mockReturnValue({ isOnline: false, pendingCount: 0 })
    render(<OfflineIndicator />)
    expect(screen.queryByText(/pending/)).not.toBeInTheDocument()
  })
})
