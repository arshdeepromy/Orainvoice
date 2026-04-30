import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { KonstaNavbar } from '../KonstaNavbar'
import type { KonstaNavbarProps } from '../KonstaNavbar'

// ─── Mocks ──────────────────────────────────────────────────────────────────

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  )
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

let mockIsModuleEnabled = vi.fn((_slug: string) => false)
let mockEnabledModules: string[] = []

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: mockEnabledModules,
    isLoading: false,
    error: null,
    isModuleEnabled: mockIsModuleEnabled,
    tradeFamily: null,
    refetch: async () => {},
  }),
}))

let mockSelectedBranchId: string | null = null
let mockBranches: Array<{
  id: string
  name: string
  address: string | null
  phone: string | null
  is_active: boolean
}> = []

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: mockSelectedBranchId,
    branches: mockBranches,
    selectBranch: vi.fn(),
    isLoading: false,
    isBranchLocked: false,
  }),
}))

// ─── Helpers ────────────────────────────────────────────────────────────────

function renderNavbar(props: KonstaNavbarProps) {
  return render(
    <MemoryRouter>
      <KonstaNavbar {...props} />
    </MemoryRouter>,
  )
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe('KonstaNavbar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsModuleEnabled = vi.fn((_slug: string) => false)
    mockEnabledModules = []
    mockSelectedBranchId = null
    mockBranches = []
  })

  it('renders with a title', () => {
    renderNavbar({ title: 'Dashboard' })
    expect(screen.getByTestId('konsta-navbar')).toBeInTheDocument()
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
  })

  it('does not render back button on root screens (showBack=false)', () => {
    renderNavbar({ title: 'Invoices' })
    expect(screen.queryByTestId('navbar-back-button')).not.toBeInTheDocument()
  })

  it('renders back button on detail screens (showBack=true)', () => {
    renderNavbar({ title: 'Invoice Detail', showBack: true })
    expect(screen.getByTestId('navbar-back-button')).toBeInTheDocument()
  })

  it('calls navigate(-1) when back button is clicked without custom onBack', () => {
    renderNavbar({ title: 'Invoice Detail', showBack: true })
    fireEvent.click(screen.getByTestId('navbar-back-button'))
    expect(mockNavigate).toHaveBeenCalledWith(-1)
  })

  it('calls custom onBack handler when provided', () => {
    const onBack = vi.fn()
    renderNavbar({ title: 'Invoice Detail', showBack: true, onBack })
    fireEvent.click(screen.getByTestId('navbar-back-button'))
    expect(onBack).toHaveBeenCalledTimes(1)
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('renders right actions when provided', () => {
    renderNavbar({
      title: 'Invoices',
      rightActions: <button data-testid="search-btn">Search</button>,
    })
    expect(screen.getByTestId('search-btn')).toBeInTheDocument()
  })

  it('renders explicit subtitle text instead of branch selector', () => {
    mockIsModuleEnabled = vi.fn((slug: string) => slug === 'branch_management')
    mockBranches = [
      { id: 'b1', name: 'Main Branch', address: null, phone: null, is_active: true },
    ]
    mockSelectedBranchId = 'b1'

    renderNavbar({ title: 'Dashboard', subtitle: 'Custom Subtitle' })
    expect(screen.getByText('Custom Subtitle')).toBeInTheDocument()
    expect(screen.queryByTestId('branch-selector-pill')).not.toBeInTheDocument()
  })

  describe('branch selector pill', () => {
    it('does not show branch selector when branch_management is disabled', () => {
      mockIsModuleEnabled = vi.fn(() => false)
      renderNavbar({ title: 'Dashboard' })
      expect(screen.queryByTestId('branch-selector-pill')).not.toBeInTheDocument()
    })

    it('shows "All Branches" when branch_management is enabled and no branch selected', () => {
      mockIsModuleEnabled = vi.fn((slug: string) => slug === 'branch_management')
      mockBranches = [
        { id: 'b1', name: 'Main Branch', address: null, phone: null, is_active: true },
      ]
      mockSelectedBranchId = null

      renderNavbar({ title: 'Dashboard' })
      const pill = screen.getByTestId('branch-selector-pill')
      expect(pill).toBeInTheDocument()
      expect(pill).toHaveTextContent('All Branches')
    })

    it('shows selected branch name when a branch is selected', () => {
      mockIsModuleEnabled = vi.fn((slug: string) => slug === 'branch_management')
      mockBranches = [
        { id: 'b1', name: 'Auckland', address: null, phone: null, is_active: true },
        { id: 'b2', name: 'Wellington', address: null, phone: null, is_active: true },
      ]
      mockSelectedBranchId = 'b2'

      renderNavbar({ title: 'Dashboard' })
      const pill = screen.getByTestId('branch-selector-pill')
      expect(pill).toHaveTextContent('Wellington')
    })

    it('calls onBranchPress when the branch selector pill is tapped', () => {
      mockIsModuleEnabled = vi.fn((slug: string) => slug === 'branch_management')
      mockBranches = [
        { id: 'b1', name: 'Main Branch', address: null, phone: null, is_active: true },
      ]
      mockSelectedBranchId = 'b1'

      const onBranchPress = vi.fn()
      renderNavbar({ title: 'Dashboard', onBranchPress })

      fireEvent.click(screen.getByTestId('branch-selector-pill'))
      expect(onBranchPress).toHaveBeenCalledTimes(1)
    })

    it('shows "All Branches" when selected branch ID does not match any branch', () => {
      mockIsModuleEnabled = vi.fn((slug: string) => slug === 'branch_management')
      mockBranches = [
        { id: 'b1', name: 'Main Branch', address: null, phone: null, is_active: true },
      ]
      mockSelectedBranchId = 'nonexistent'

      renderNavbar({ title: 'Dashboard' })
      const pill = screen.getByTestId('branch-selector-pill')
      expect(pill).toHaveTextContent('All Branches')
    })
  })
})
