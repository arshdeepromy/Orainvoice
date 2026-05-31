/**
 * Tests for the mobile fallback banner (B18).
 *
 * Validates: R18.1, R18.2.
 */

import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return { default: { get: mockGet } }
})

vi.mock('@/api/schedule', () => ({
  listEntries: vi.fn().mockResolvedValue({ entries: [], total: 0 }),
  bulkCreate: vi.fn(),
  copyWeek: vi.fn(),
  listTemplates: vi.fn().mockResolvedValue({ templates: [], total: 0 }),
}))

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
import RosterGridPage from '../RosterGridPage'

const get = apiClient.get as ReturnType<typeof vi.fn>

afterEach(() => cleanup())

beforeEach(() => {
  vi.clearAllMocks()
  get.mockImplementation((url: string) => {
    if (url === '/staff') return Promise.resolve({ data: { staff: [], total: 0 } })
    if (url === '/leave/approvals')
      return Promise.resolve({ data: { items: [], total: 0 } })
    return Promise.resolve({ data: {} })
  })
})

describe('RosterGridPage mobile fallback (B18)', () => {
  it('renders the fallback banner below 1024px viewport', () => {
    // Mock matchMedia to report we are below 1024px.
    const matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: matchMedia,
    })

    render(
      <MemoryRouter>
        <RosterGridPage />
      </MemoryRouter>,
    )
    expect(
      screen.getByTestId('roster-grid-mobile-fallback'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /open calendar view/i }),
    ).toHaveAttribute('href', '/schedule')
  })

  it('renders the grid above 1024px viewport', async () => {
    const matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: matchMedia,
    })

    render(
      <MemoryRouter>
        <RosterGridPage />
      </MemoryRouter>,
    )
    // No fallback.
    expect(
      screen.queryByTestId('roster-grid-mobile-fallback'),
    ).not.toBeInTheDocument()
  })
})
