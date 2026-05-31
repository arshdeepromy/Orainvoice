/**
 * Unit tests for PayRateHistoryPanel.
 *
 * Refs: Staff Management Phase 1 — R3.5
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn() },
}))

import apiClient from '@/api/client'
import PayRateHistoryPanel from '../PayRateHistoryPanel'

const mockData = {
  items: [
    {
      id: 'rate-1',
      effective_from: '2026-05-01',
      hourly_rate: '27.50',
      overtime_rate: '41.25',
      change_reason: 'rate_change',
      changed_by_email: 'admin@example.com',
    },
    {
      id: 'rate-2',
      effective_from: '2026-01-15',
      hourly_rate: '25.00',
      overtime_rate: null,
      change_reason: 'initial_rate',
      changed_by_email: null,
    },
  ],
  total: 2,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PayRateHistoryPanel', () => {
  it('is collapsed initially and does not fetch', () => {
    render(<PayRateHistoryPanel staffId="staff-123" />)

    expect(
      screen.getByRole('button', { name: /pay rate history/i }),
    ).toHaveAttribute('aria-expanded', 'false')
    expect(apiClient.get).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('fetches and renders rows when expanded', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: mockData })

    render(<PayRateHistoryPanel staffId="staff-123" />)

    fireEvent.click(screen.getByRole('button', { name: /pay rate history/i }))

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/api/v2/staff/staff-123/pay-rates',
        expect.objectContaining({ signal: expect.any(Object) }),
      )
    })

    await waitFor(() => {
      expect(screen.getByText('2026-05-01')).toBeInTheDocument()
    })

    expect(screen.getByText('27.50')).toBeInTheDocument()
    expect(screen.getByText('41.25')).toBeInTheDocument()
    expect(screen.getByText('rate_change')).toBeInTheDocument()
    expect(screen.getByText('admin@example.com')).toBeInTheDocument()

    // Second row — null overtime + null email render as fallbacks
    expect(screen.getByText('2026-01-15')).toBeInTheDocument()
    expect(screen.getByText('25.00')).toBeInTheDocument()
    expect(screen.getByText('initial_rate')).toBeInTheDocument()
    expect(screen.getByText('system')).toBeInTheDocument()
  })

  it('renders empty-state copy when the API returns no rows', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { items: [], total: 0 },
    })

    render(<PayRateHistoryPanel staffId="staff-123" />)
    fireEvent.click(screen.getByRole('button', { name: /pay rate history/i }))

    await waitFor(() => {
      expect(screen.getByText(/no pay rate changes yet/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows an error message when the fetch fails', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('Network error'))

    render(<PayRateHistoryPanel staffId="staff-123" />)
    fireEvent.click(screen.getByRole('button', { name: /pay rate history/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/failed to load pay rate history/i),
      ).toBeInTheDocument()
    })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
