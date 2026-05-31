/**
 * Tests for the loading + error UX polish (B20).
 *
 * The submitBulk wrapper handles 422, 5xx, network, and aborted
 * cases. We exercise it via the apply-template button.
 *
 * Validates: R12.4, R12.5, R21.5, R21.7, R21.8.
 */

import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: {
      get: mockGet,
      post: mockPost,
      put: mockPut,
      delete: mockDelete,
    },
  }
})

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: () => {},
    isLoading: false,
    isBranchLocked: false,
  }),
}))

import apiClient from '@/api/client'

const get = apiClient.get as ReturnType<typeof vi.fn>
const post = apiClient.post as ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })

  get.mockImplementation((url: string) => {
    if (url === '/staff')
      return Promise.resolve({
        data: {
          staff: [
            {
              id: 's1',
              first_name: 'Alice',
              last_name: 'Adams',
              name: 'Alice Adams',
              position: 'Mechanic',
              is_active: true,
            },
          ],
          total: 1,
        },
      })
    if (url === '/schedule')
      return Promise.resolve({ data: { entries: [], total: 0 } })
    if (url === '/leave/approvals')
      return Promise.resolve({ data: { items: [], total: 0 } })
    if (url === '/schedule/templates')
      return Promise.resolve({
        data: {
          templates: [
            {
              id: 't1',
              org_id: 'o',
              name: 'Morning shift',
              start_time: '09:00:00',
              end_time: '17:00:00',
              entry_type: 'job',
              created_at: '',
            },
          ],
          total: 1,
        },
      })
    return Promise.resolve({ data: {} })
  })
})

afterEach(() => cleanup())

describe('RosterGridPage loading + error UX (B20)', () => {
  it('shows error toast on 5xx', async () => {
    post.mockRejectedValue({
      response: { status: 500, data: { detail: 'Server error' } },
    })

    const RosterGridPage = (await import('../RosterGridPage')).default
    render(
      <MemoryRouter>
        <RosterGridPage />
      </MemoryRouter>,
    )
    // Wait for the grid to appear.
    await waitFor(() =>
      expect(screen.getByTestId('roster-grid')).toBeInTheDocument(),
    )

    // Select a template.
    const morning = await screen.findByText('Morning shift')
    fireEvent.click(morning)

    // Pick the staff row.
    const staffHeader = screen.getByText('Alice Adams')
    fireEvent.click(staffHeader)

    // Pick a day column.
    const dayHeaders = screen.getAllByRole('columnheader')
    // The first columnheader is "Staff"; the next 14 are days.
    fireEvent.click(dayHeaders[1])

    // Apply.
    const apply = await screen.findByTestId('apply-template-button')
    fireEvent.click(apply)

    await waitFor(() => {
      expect(
        screen.getByText(/failed to save shifts/i),
      ).toBeInTheDocument()
    })
  })

  it('shows validation message on 422', async () => {
    post.mockRejectedValue({
      response: { status: 422, data: { detail: 'Bad time range' } },
    })

    const RosterGridPage = (await import('../RosterGridPage')).default
    render(
      <MemoryRouter>
        <RosterGridPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('roster-grid')).toBeInTheDocument(),
    )

    const morning = await screen.findByText('Morning shift')
    fireEvent.click(morning)
    fireEvent.click(screen.getByText('Alice Adams'))
    const dayHeaders = screen.getAllByRole('columnheader')
    fireEvent.click(dayHeaders[1])
    const apply = await screen.findByTestId('apply-template-button')
    fireEvent.click(apply)

    await waitFor(() => {
      expect(screen.getByText(/bad time range/i)).toBeInTheDocument()
    })
  })
})
