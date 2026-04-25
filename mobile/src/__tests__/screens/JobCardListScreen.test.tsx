import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import JobCardListScreen from '@/screens/jobs/JobCardListScreen'

/**
 * Unit tests for JobCardListScreen trade family gating.
 * Requirements: 11.1, 5.4
 */

// Mock the contexts
const mockIsModuleEnabled = vi.fn()
const mockTradeFamily = vi.fn<() => string | null>()
const mockUser = vi.fn()

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
    user: mockUser(),
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

// Mock useApiList to return empty data
vi.mock('@/hooks/useApiList', () => ({
  useApiList: () => ({
    items: [],
    total: 0,
    isLoading: false,
    isRefreshing: false,
    error: null,
    hasMore: false,
    search: '',
    setSearch: vi.fn(),
    refresh: vi.fn(),
    loadMore: vi.fn(),
    filters: {},
    setFilters: vi.fn(),
  }),
}))

// Mock apiClient
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

function renderScreen() {
  return render(
    <MemoryRouter>
      <JobCardListScreen />
    </MemoryRouter>,
  )
}

describe('JobCardListScreen trade family gating', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser.mockReturnValue({ role: 'owner' })
  })

  it('should render job cards list when jobs module is enabled and trade family is automotive-transport', () => {
    mockIsModuleEnabled.mockImplementation((slug: string) => slug === 'jobs')
    mockTradeFamily.mockReturnValue('automotive-transport')

    renderScreen()

    expect(screen.getByText('Job Cards')).toBeInTheDocument()
  })

  it('should NOT render when jobs module is disabled', () => {
    mockIsModuleEnabled.mockReturnValue(false)
    mockTradeFamily.mockReturnValue('automotive-transport')

    renderScreen()

    expect(screen.queryByText('Job Cards')).not.toBeInTheDocument()
  })

  it('should NOT render when trade family is not automotive-transport', () => {
    mockIsModuleEnabled.mockImplementation((slug: string) => slug === 'jobs')
    mockTradeFamily.mockReturnValue('electrical')

    renderScreen()

    expect(screen.queryByText('Job Cards')).not.toBeInTheDocument()
  })

  it('should NOT render when trade family is null', () => {
    mockIsModuleEnabled.mockImplementation((slug: string) => slug === 'jobs')
    mockTradeFamily.mockReturnValue(null)

    renderScreen()

    expect(screen.queryByText('Job Cards')).not.toBeInTheDocument()
  })
})
