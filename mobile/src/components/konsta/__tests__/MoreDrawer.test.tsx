import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { MoreDrawer } from '../MoreDrawer'

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

const mockUseModules = vi.fn()
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => mockUseModules(),
}))

const mockUseAuth = vi.fn()
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

function renderDrawer(isOpen = true, onClose = vi.fn()) {
  return render(
    <MemoryRouter>
      <MoreDrawer isOpen={isOpen} onClose={onClose} />
    </MemoryRouter>,
  )
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe('MoreDrawer', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
    mockUseModules.mockReturnValue({
      enabledModules: ['quotes', 'inventory', 'expenses', 'staff', 'sms'],
      isModuleEnabled: (slug: string) =>
        ['quotes', 'inventory', 'expenses', 'staff', 'sms'].includes(slug),
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'salesperson' },
    })
  })

  it('renders the sheet with data-testid', () => {
    renderDrawer()
    expect(screen.getByTestId('more-drawer')).toBeInTheDocument()
  })

  it('renders the "More" title', () => {
    renderDrawer()
    expect(screen.getByText('More')).toBeInTheDocument()
  })

  it('renders visible items based on enabled modules', () => {
    renderDrawer()
    // Quotes is enabled
    expect(screen.getByTestId('more-item-quotes')).toBeInTheDocument()
    // Inventory is enabled
    expect(screen.getByTestId('more-item-inventory')).toBeInTheDocument()
    // Expenses is enabled
    expect(screen.getByTestId('more-item-expenses')).toBeInTheDocument()
    // Staff is enabled
    expect(screen.getByTestId('more-item-staff')).toBeInTheDocument()
    // SMS is enabled
    expect(screen.getByTestId('more-item-sms')).toBeInTheDocument()
  })

  it('hides items when their module is disabled', () => {
    mockUseModules.mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    renderDrawer()
    // Module-gated items should be hidden
    expect(screen.queryByTestId('more-item-quotes')).not.toBeInTheDocument()
    expect(screen.queryByTestId('more-item-inventory')).not.toBeInTheDocument()
    expect(screen.queryByTestId('more-item-pos')).not.toBeInTheDocument()
  })

  it('always shows items with null moduleSlug (reports, notifications)', () => {
    mockUseModules.mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-reports')).toBeInTheDocument()
    expect(screen.getByTestId('more-item-notifications')).toBeInTheDocument()
  })

  it('hides vehicles when trade family does not match', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['vehicles'],
      isModuleEnabled: (slug: string) => slug === 'vehicles',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: 'food-hospitality',
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.queryByTestId('more-item-vehicles')).not.toBeInTheDocument()
  })

  it('shows vehicles when trade family matches automotive-transport', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['vehicles'],
      isModuleEnabled: (slug: string) => slug === 'vehicles',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: 'automotive-transport',
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-vehicles')).toBeInTheDocument()
  })

  it('hides settings for non-admin users', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'salesperson' },
    })
    renderDrawer()
    expect(screen.queryByTestId('more-item-settings')).not.toBeInTheDocument()
  })

  it('shows settings for owner role', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'owner' },
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-settings')).toBeInTheDocument()
  })

  it('shows settings for admin role', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'admin' },
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-settings')).toBeInTheDocument()
  })

  it('groups items by category with section headers', () => {
    renderDrawer()
    // Sales category should be present (quotes is enabled)
    expect(screen.getByTestId('more-category-Sales')).toBeInTheDocument()
    // Operations category should be present (inventory, expenses are enabled)
    expect(screen.getByTestId('more-category-Operations')).toBeInTheDocument()
    // People category should be present (staff is enabled)
    expect(screen.getByTestId('more-category-People')).toBeInTheDocument()
    // Communications category should be present (sms is enabled)
    expect(screen.getByTestId('more-category-Communications')).toBeInTheDocument()
  })

  it('navigates to the correct route and closes drawer on item tap', () => {
    const onClose = vi.fn()
    renderDrawer(true, onClose)
    fireEvent.click(screen.getByTestId('more-item-quotes'))
    expect(mockNavigate).toHaveBeenCalledWith('/quotes')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('navigates to inventory route on tap', () => {
    const onClose = vi.fn()
    renderDrawer(true, onClose)
    fireEvent.click(screen.getByTestId('more-item-inventory'))
    expect(mockNavigate).toHaveBeenCalledWith('/inventory')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('renders item labels correctly', () => {
    renderDrawer()
    expect(screen.getByText('Quotes')).toBeInTheDocument()
    expect(screen.getByText('Inventory')).toBeInTheDocument()
    expect(screen.getByText('Expenses')).toBeInTheDocument()
    expect(screen.getByText('Staff')).toBeInTheDocument()
    expect(screen.getByText('SMS')).toBeInTheDocument()
  })

  it('renders category section headers', () => {
    renderDrawer()
    expect(screen.getByText('Sales')).toBeInTheDocument()
    expect(screen.getByText('Operations')).toBeInTheDocument()
    expect(screen.getByText('People')).toBeInTheDocument()
  })

  it('does not render empty categories', () => {
    mockUseModules.mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    renderDrawer()
    // Industry category should not appear (all items are module-gated)
    expect(screen.queryByTestId('more-category-Industry')).not.toBeInTheDocument()
    // Sales category should not appear (all items are module-gated)
    expect(screen.queryByTestId('more-category-Sales')).not.toBeInTheDocument()
  })

  it('shows construction items for building-construction trade family', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['progress_claims'],
      isModuleEnabled: (slug: string) => slug === 'progress_claims',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: 'building-construction',
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-construction')).toBeInTheDocument()
  })

  it('hides construction items for non-construction trade family', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['progress_claims'],
      isModuleEnabled: (slug: string) => slug === 'progress_claims',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: 'automotive-transport',
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.queryByTestId('more-item-construction')).not.toBeInTheDocument()
  })

  it('shows settings for org_admin role', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'org_admin' },
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-settings')).toBeInTheDocument()
  })

  it('shows hospitality items for food-hospitality trade family', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['tables', 'kitchen_display'],
      isModuleEnabled: (slug: string) =>
        ['tables', 'kitchen_display'].includes(slug),
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: 'food-hospitality',
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.getByTestId('more-item-floor-plan')).toBeInTheDocument()
    expect(screen.getByTestId('more-item-kitchen')).toBeInTheDocument()
  })

  it('hides hospitality items for non-hospitality trade family', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['tables', 'kitchen_display'],
      isModuleEnabled: (slug: string) =>
        ['tables', 'kitchen_display'].includes(slug),
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: 'automotive-transport',
      refetch: async () => {},
    })
    renderDrawer()
    expect(screen.queryByTestId('more-item-floor-plan')).not.toBeInTheDocument()
    expect(screen.queryByTestId('more-item-kitchen')).not.toBeInTheDocument()
  })
})
