import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import JobCardListScreen from '@/screens/jobs/JobCardListScreen'

/**
 * Unit tests for JobCardListScreen module gating.
 * Requirements: 25.1, 25.2, 55.1
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

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: vi.fn(),
  }),
}))

// Mock apiClient
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
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

describe('JobCardListScreen module gating', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser.mockReturnValue({ id: 'u1', role: 'owner' })
    mockTradeFamily.mockReturnValue('automotive-transport')
  })

  it('should render when jobs module is enabled', () => {
    mockIsModuleEnabled.mockImplementation((slug: string) => slug === 'jobs')
    renderScreen()
    expect(screen.getByTestId('job-card-list-page')).toBeInTheDocument()
  })

  it('should NOT render when jobs module is disabled', () => {
    mockIsModuleEnabled.mockReturnValue(false)
    renderScreen()
    expect(screen.queryByTestId('job-card-list-page')).not.toBeInTheDocument()
  })
})
