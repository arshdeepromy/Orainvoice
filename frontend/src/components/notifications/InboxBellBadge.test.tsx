import { render, screen, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Validates: Requirements AC-2, AC-5
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return {
    default: { get: mockGet },
  }
})

import apiClient from '@/api/client'
import InboxBellBadge from './InboxBellBadge'

describe('InboxBellBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns null (no badge) when unread count is 0', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { count: 0 },
    })

    const { container } = render(<InboxBellBadge />)

    // Let the initial fetch resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(container.innerHTML).toBe('')
  })

  it('shows "5" when unread count is 5', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { count: 5 },
    })

    render(<InboxBellBadge />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByLabelText('5 unread notifications')).toBeInTheDocument()
  })

  it('shows "99+" when unread count exceeds 99', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { count: 150 },
    })

    render(<InboxBellBadge />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText('99+')).toBeInTheDocument()
    expect(screen.getByLabelText('150 unread notifications')).toBeInTheDocument()
  })

  it('polls the API every 30 seconds', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { count: 1 },
    })

    render(<InboxBellBadge />)

    // Initial fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(apiClient.get).toHaveBeenCalledTimes(1)
    expect(apiClient.get).toHaveBeenCalledWith(
      '/notifications/inbox/unread-count',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    // Advance 30s — second poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    expect(apiClient.get).toHaveBeenCalledTimes(2)

    // Advance another 30s — third poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    expect(apiClient.get).toHaveBeenCalledTimes(3)
  })
})
