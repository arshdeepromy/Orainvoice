import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — Retention Module, Task 37.9
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import RetentionSummary from '../pages/construction/RetentionSummary'

const mockSummary = {
  project_id: 'proj-1',
  total_retention_withheld: '15000.00',
  total_retention_released: '5000.00',
  retention_balance: '10000.00',
  releases: [
    {
      id: 'rel-1',
      project_id: 'proj-1',
      amount: '5000.00',
      release_date: '2024-06-15',
      payment_id: null,
      notes: 'Partial release',
      created_at: '2024-06-15T10:00:00Z',
    },
  ],
}

const mockEmptySummary = {
  project_id: 'proj-2',
  total_retention_withheld: '0.00',
  total_retention_released: '0.00',
  retention_balance: '0.00',
  releases: [],
}

describe('RetentionSummary', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<RetentionSummary projectId="proj-1" />)
    expect(screen.getByRole('status', { name: 'Loading retention summary' })).toBeInTheDocument()
  })

  it('displays retention breakdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSummary })
    render(<RetentionSummary projectId="proj-1" />)

    const table = await screen.findByRole('table', { name: 'Retention breakdown' })
    expect(within(table).getByText('Total Retention Withheld')).toBeInTheDocument()
    expect(within(table).getByText('Total Released')).toBeInTheDocument()
    expect(within(table).getByText('Retention Balance')).toBeInTheDocument()
  })

  it('shows release history table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSummary })
    render(<RetentionSummary projectId="proj-1" />)

    const releasesTable = await screen.findByRole('grid', { name: 'Retention releases list' })
    const rows = within(releasesTable).getAllByRole('row')
    expect(rows).toHaveLength(2) // header + 1 release
  })

  it('shows release button when balance > 0', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSummary })
    render(<RetentionSummary projectId="proj-1" />)

    expect(await screen.findByRole('button', { name: 'Release retention' })).toBeInTheDocument()
  })

  it('hides release button when balance is 0', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockEmptySummary })
    render(<RetentionSummary projectId="proj-2" />)

    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Release retention' })).not.toBeInTheDocument()
  })

  it('opens release form when button clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSummary })
    render(<RetentionSummary projectId="proj-1" />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Release retention' }))

    expect(screen.getByRole('form', { name: 'Release retention form' })).toBeInTheDocument()
    expect(screen.getByLabelText('Amount')).toBeInTheDocument()
    expect(screen.getByLabelText('Release Date')).toBeInTheDocument()
    expect(screen.getByLabelText('Notes')).toBeInTheDocument()
  })

  it('submits release form with correct data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSummary })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'rel-2' } })

    render(<RetentionSummary projectId="proj-1" />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Release retention' }))

    await user.type(screen.getByLabelText('Amount'), '3000')
    await user.type(screen.getByLabelText('Release Date'), '2024-07-01')
    await user.type(screen.getByLabelText('Notes'), 'Second release')

    await user.click(screen.getByRole('button', { name: 'Confirm release' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/retentions/proj-1/release', {
      amount: 3000,
      release_date: '2024-07-01',
      notes: 'Second release',
    })
  })

  it('shows error when release fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSummary })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'Release amount exceeds remaining retention balance' } },
    })

    render(<RetentionSummary projectId="proj-1" />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Release retention' }))

    await user.type(screen.getByLabelText('Amount'), '5000')
    await user.type(screen.getByLabelText('Release Date'), '2024-07-01')

    await user.click(screen.getByRole('button', { name: 'Confirm release' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Release amount exceeds remaining retention balance')
  })
})
