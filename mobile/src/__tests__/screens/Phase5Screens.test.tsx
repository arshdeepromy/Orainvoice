import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/**
 * Phase 5 — Unit tests for Quote, Job Card, Vehicle, and Booking screens.
 *
 * - Smoke test each screen renders with mocked data
 * - Test module gating hides screens when module disabled
 * - Test job card sorting order
 * - Test timer start/stop flow
 *
 * Requirements: 24.1, 25.1, 29.1, 30.1, 55.1
 */

/* ------------------------------------------------------------------ */
/* Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockIsModuleEnabled = vi.fn()
const mockTradeFamily = vi.fn<() => string | null>()

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    isModuleEnabled: mockIsModuleEnabled,
    tradeFamily: mockTradeFamily(),
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', role: 'owner', first_name: 'Test' },
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: vi.fn(),
  }),
}))

vi.mock('@/hooks/useHaptics', () => ({
  useHaptics: () => ({
    light: vi.fn(),
    medium: vi.fn(),
    heavy: vi.fn(),
    selection: vi.fn(),
  }),
}))

vi.mock('@/hooks/useGeolocation', () => ({
  useGeolocation: () => ({
    getCurrentPosition: vi.fn().mockResolvedValue(null),
  }),
}))

vi.mock('@/hooks/useCamera', () => ({
  useCamera: () => ({
    takePhoto: vi.fn().mockResolvedValue(null),
  }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
const mockPatch = vi.fn()
const mockDelete = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    patch: (...args: unknown[]) => mockPatch(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}))

/* ------------------------------------------------------------------ */
/* Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import QuoteListScreen from '@/screens/quotes/QuoteListScreen'
import QuoteCreateScreen from '@/screens/quotes/QuoteCreateScreen'
import QuoteDetailScreen from '@/screens/quotes/QuoteDetailScreen'
import JobCardListScreen from '@/screens/jobs/JobCardListScreen'
import JobCardCreateScreen from '@/screens/jobs/JobCardCreateScreen'
import JobCardDetailScreen from '@/screens/jobs/JobCardDetailScreen'
import JobBoardScreen from '@/screens/jobs/JobBoardScreen'
import VehicleListScreen from '@/screens/vehicles/VehicleListScreen'
import VehicleProfileScreen from '@/screens/vehicles/VehicleProfileScreen'
import BookingCalendarScreen from '@/screens/bookings/BookingCalendarScreen'
import { sortJobCards } from '@/screens/jobs/JobCardListScreen'
import {
  formatTimer,
  startTimer,
  stopTimer,
} from '@/screens/jobs/JobBoardScreen'
import type { JobCard } from '@shared/types/job'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderInRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

/* ------------------------------------------------------------------ */
/* Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  mockTradeFamily.mockReturnValue('automotive-transport')
  // Default: all modules enabled
  mockIsModuleEnabled.mockReturnValue(true)
  // Default API responses
  mockGet.mockResolvedValue({ data: { items: [], total: 0 } })
  mockPost.mockResolvedValue({ data: { id: 'new-id' } })
})

/* ================================================================== */
/* 1. Smoke tests — each screen renders without crashing              */
/* ================================================================== */

describe('Smoke tests — screens render with mocked data', () => {
  it('QuoteListScreen renders', async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [
          {
            id: 'q1',
            quote_number: 'Q-001',
            customer_name: 'Alice',
            status: 'draft',
            total: 1500,
            valid_until: '2025-12-31',
            created_at: '2025-01-01',
          },
        ],
        total: 1,
      },
    })

    await act(async () => {
      renderInRouter(<QuoteListScreen />)
    })

    expect(screen.getByTestId('quote-list-page')).toBeInTheDocument()
  })

  it('QuoteCreateScreen renders', async () => {
    await act(async () => {
      renderInRouter(<QuoteCreateScreen />)
    })

    expect(screen.getByTestId('quote-create-page')).toBeInTheDocument()
  })

  it('QuoteDetailScreen renders loading then error for missing id', async () => {
    mockGet.mockRejectedValue(new Error('Not found'))

    await act(async () => {
      renderInRouter(<QuoteDetailScreen />)
    })

    expect(screen.getByTestId('quote-detail-page')).toBeInTheDocument()
  })

  it('JobCardListScreen renders', async () => {
    await act(async () => {
      renderInRouter(<JobCardListScreen />)
    })

    expect(screen.getByTestId('job-card-list-page')).toBeInTheDocument()
  })

  it('JobCardCreateScreen renders', async () => {
    mockGet.mockResolvedValue({ data: { items: [] } })

    await act(async () => {
      renderInRouter(<JobCardCreateScreen />)
    })

    expect(screen.getByTestId('job-card-create-page')).toBeInTheDocument()
  })

  it('JobCardDetailScreen renders loading state', async () => {
    // Will show loading then error since no id param
    mockGet.mockRejectedValue(new Error('Not found'))

    await act(async () => {
      renderInRouter(<JobCardDetailScreen />)
    })

    expect(screen.getByTestId('job-card-detail-page')).toBeInTheDocument()
  })

  it('JobBoardScreen renders', async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [
          {
            id: 'j1',
            title: 'Fix engine',
            status: 'in_progress',
            customer_name: 'Bob',
            timer_running: false,
            created_at: '2025-01-01',
            updated_at: '2025-01-01',
          },
        ],
        total: 1,
      },
    })

    await act(async () => {
      renderInRouter(<JobBoardScreen />)
    })

    expect(screen.getByTestId('job-board-page')).toBeInTheDocument()
  })

  it('VehicleListScreen renders', async () => {
    await act(async () => {
      renderInRouter(<VehicleListScreen />)
    })

    expect(screen.getByTestId('vehicle-list-page')).toBeInTheDocument()
  })

  it('VehicleProfileScreen renders loading then error', async () => {
    mockGet.mockRejectedValue(new Error('Not found'))

    await act(async () => {
      renderInRouter(<VehicleProfileScreen />)
    })

    expect(screen.getByTestId('vehicle-profile-page')).toBeInTheDocument()
  })

  it('BookingCalendarScreen renders', async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [
          {
            id: 'b1',
            customer_name: 'Charlie',
            date: new Date().toISOString().split('T')[0],
            start_time: '09:00',
            duration_minutes: 60,
            status: 'scheduled',
          },
        ],
        total: 1,
      },
    })

    await act(async () => {
      renderInRouter(<BookingCalendarScreen />)
    })

    expect(screen.getByTestId('booking-calendar-page')).toBeInTheDocument()
  })
})

/* ================================================================== */
/* 2. Module gating — screens hidden when module disabled             */
/* ================================================================== */

describe('Module gating — screens hidden when module disabled', () => {
  it('QuoteListScreen hidden when quotes module disabled', async () => {
    mockIsModuleEnabled.mockReturnValue(false)

    await act(async () => {
      renderInRouter(<QuoteListScreen />)
    })

    expect(screen.queryByTestId('quote-list-page')).not.toBeInTheDocument()
  })

  it('QuoteCreateScreen hidden when quotes module disabled', async () => {
    mockIsModuleEnabled.mockReturnValue(false)

    await act(async () => {
      renderInRouter(<QuoteCreateScreen />)
    })

    expect(screen.queryByTestId('quote-create-page')).not.toBeInTheDocument()
  })

  it('JobCardListScreen hidden when jobs module disabled', async () => {
    mockIsModuleEnabled.mockReturnValue(false)

    await act(async () => {
      renderInRouter(<JobCardListScreen />)
    })

    expect(screen.queryByTestId('job-card-list-page')).not.toBeInTheDocument()
  })

  it('JobBoardScreen hidden when jobs module disabled', async () => {
    mockIsModuleEnabled.mockReturnValue(false)

    await act(async () => {
      renderInRouter(<JobBoardScreen />)
    })

    expect(screen.queryByTestId('job-board-page')).not.toBeInTheDocument()
  })

  it('VehicleListScreen hidden when vehicles module disabled', async () => {
    mockIsModuleEnabled.mockReturnValue(false)

    await act(async () => {
      renderInRouter(<VehicleListScreen />)
    })

    expect(screen.queryByTestId('vehicle-list-page')).not.toBeInTheDocument()
  })

  it('VehicleListScreen hidden when trade family is not automotive-transport', async () => {
    mockIsModuleEnabled.mockReturnValue(true)
    mockTradeFamily.mockReturnValue('electrical')

    await act(async () => {
      renderInRouter(<VehicleListScreen />)
    })

    expect(screen.queryByTestId('vehicle-list-page')).not.toBeInTheDocument()
  })

  it('BookingCalendarScreen hidden when bookings module disabled', async () => {
    mockIsModuleEnabled.mockReturnValue(false)

    await act(async () => {
      renderInRouter(<BookingCalendarScreen />)
    })

    expect(screen.queryByTestId('booking-calendar-page')).not.toBeInTheDocument()
  })
})

/* ================================================================== */
/* 3. Job card sorting order                                          */
/* ================================================================== */

describe('Job card sorting order', () => {
  it('sorts in_progress before pending before completed', () => {
    const cards: JobCard[] = [
      {
        id: '1',
        job_card_number: 'JC-001',
        customer_id: 'c1',
        customer_name: 'A',
        vehicle_id: null,
        vehicle_registration: null,
        status: 'completed',
        description: null,
        created_at: '2025-01-03',
      },
      {
        id: '2',
        job_card_number: 'JC-002',
        customer_id: 'c2',
        customer_name: 'B',
        vehicle_id: null,
        vehicle_registration: null,
        status: 'pending',
        description: null,
        created_at: '2025-01-02',
      },
      {
        id: '3',
        job_card_number: 'JC-003',
        customer_id: 'c3',
        customer_name: 'C',
        vehicle_id: null,
        vehicle_registration: null,
        status: 'in_progress',
        description: null,
        created_at: '2025-01-01',
      },
    ]

    const sorted = sortJobCards(cards)

    expect(sorted[0].status).toBe('in_progress')
    expect(sorted[1].status).toBe('pending')
    expect(sorted[2].status).toBe('completed')
  })

  it('sorts by created_at descending within same status group', () => {
    const cards: JobCard[] = [
      {
        id: '1',
        job_card_number: 'JC-001',
        customer_id: 'c1',
        customer_name: 'A',
        vehicle_id: null,
        vehicle_registration: null,
        status: 'in_progress',
        description: null,
        created_at: '2025-01-01',
      },
      {
        id: '2',
        job_card_number: 'JC-002',
        customer_id: 'c2',
        customer_name: 'B',
        vehicle_id: null,
        vehicle_registration: null,
        status: 'in_progress',
        description: null,
        created_at: '2025-01-03',
      },
      {
        id: '3',
        job_card_number: 'JC-003',
        customer_id: 'c3',
        customer_name: 'C',
        vehicle_id: null,
        vehicle_registration: null,
        status: 'in_progress',
        description: null,
        created_at: '2025-01-02',
      },
    ]

    const sorted = sortJobCards(cards)

    // Most recent first within in_progress group
    expect(sorted[0].id).toBe('2') // Jan 3
    expect(sorted[1].id).toBe('3') // Jan 2
    expect(sorted[2].id).toBe('1') // Jan 1
  })

  it('handles empty array', () => {
    expect(sortJobCards([])).toEqual([])
  })
})

/* ================================================================== */
/* 4. Timer start/stop flow                                           */
/* ================================================================== */

describe('Timer start/stop flow', () => {
  describe('formatTimer', () => {
    it('returns 00:00:00 for null input', () => {
      expect(formatTimer(null)).toBe('00:00:00')
    })

    it('returns 00:00:00 for undefined input', () => {
      expect(formatTimer(undefined)).toBe('00:00:00')
    })

    it('formats elapsed time correctly', () => {
      // Set started_at to 1 hour, 2 minutes, 3 seconds ago
      const now = Date.now()
      const startedAt = new Date(now - (3600 + 120 + 3) * 1000).toISOString()
      const result = formatTimer(startedAt)

      // Should be approximately 01:02:03 (may vary by 1 second due to timing)
      expect(result).toMatch(/^01:02:0[2-4]$/)
    })
  })

  describe('startTimer', () => {
    it('calls POST /job-cards/:id/start-timer and returns true on success', async () => {
      mockPost.mockResolvedValueOnce({ data: {} })

      const result = await startTimer('j1', { lat: -36.8, lng: 174.7 })

      expect(mockPost).toHaveBeenCalledWith('/api/v1/job-cards/j1/start-timer', {
        latitude: -36.8,
        longitude: 174.7,
      })
      expect(result).toBe(true)
    })

    it('calls POST with null geo when no location available', async () => {
      mockPost.mockResolvedValueOnce({ data: {} })

      const result = await startTimer('j1', null)

      expect(mockPost).toHaveBeenCalledWith('/api/v1/job-cards/j1/start-timer', {
        latitude: undefined,
        longitude: undefined,
      })
      expect(result).toBe(true)
    })

    it('returns false on API failure', async () => {
      mockPost.mockRejectedValueOnce(new Error('Network error'))

      const result = await startTimer('j1', null)

      expect(result).toBe(false)
    })
  })

  describe('stopTimer', () => {
    it('calls POST /job-cards/:id/stop-timer and returns true on success', async () => {
      mockPost.mockResolvedValueOnce({ data: {} })

      const result = await stopTimer('j1')

      expect(mockPost).toHaveBeenCalledWith('/api/v1/job-cards/j1/stop-timer')
      expect(result).toBe(true)
    })

    it('returns false on API failure', async () => {
      mockPost.mockRejectedValueOnce(new Error('Network error'))

      const result = await stopTimer('j1')

      expect(result).toBe(false)
    })
  })
})
