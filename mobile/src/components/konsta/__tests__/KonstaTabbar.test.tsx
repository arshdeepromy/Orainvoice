import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { KonstaTabbar, resolveFourthTab, buildTabs } from '../KonstaTabbar'
import {
  JOBS_TAB,
  QUOTES_TAB,
  BOOKINGS_TAB,
  REPORTS_TAB,
} from '../KonstaTabbar'

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

function renderTabbar(
  route = '/dashboard',
  onMorePress?: () => void,
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <KonstaTabbar onMorePress={onMorePress} />
    </MemoryRouter>,
  )
}

// ─── resolveFourthTab (pure function) ───────────────────────────────────────

describe('resolveFourthTab', () => {
  it('returns Jobs tab when jobs module is enabled', () => {
    expect(resolveFourthTab(['jobs'])).toBe(JOBS_TAB)
  })

  it('returns Jobs tab when jobs and quotes are both enabled (jobs takes priority)', () => {
    expect(resolveFourthTab(['jobs', 'quotes'])).toBe(JOBS_TAB)
  })

  it('returns Quotes tab when quotes is enabled but jobs is not', () => {
    expect(resolveFourthTab(['quotes'])).toBe(QUOTES_TAB)
  })

  it('returns Bookings tab when bookings is enabled but jobs and quotes are not', () => {
    expect(resolveFourthTab(['bookings'])).toBe(BOOKINGS_TAB)
  })

  it('returns Reports tab when no dynamic modules are enabled', () => {
    expect(resolveFourthTab([])).toBe(REPORTS_TAB)
  })

  it('returns Reports tab when only unrelated modules are enabled', () => {
    expect(resolveFourthTab(['inventory', 'staff', 'expenses'])).toBe(REPORTS_TAB)
  })

  it('returns Quotes tab when quotes and bookings are enabled but not jobs', () => {
    expect(resolveFourthTab(['quotes', 'bookings'])).toBe(QUOTES_TAB)
  })
})

// ─── buildTabs ──────────────────────────────────────────────────────────────

describe('buildTabs', () => {
  it('always returns exactly 5 tabs', () => {
    expect(buildTabs([])).toHaveLength(5)
    expect(buildTabs(['jobs'])).toHaveLength(5)
    expect(buildTabs(['quotes', 'bookings'])).toHaveLength(5)
  })

  it('always has Home as first tab', () => {
    expect(buildTabs([])[0]?.id).toBe('home')
  })

  it('always has Invoices as second tab', () => {
    expect(buildTabs([])[1]?.id).toBe('invoices')
  })

  it('always has Customers as third tab', () => {
    expect(buildTabs([])[2]?.id).toBe('customers')
  })

  it('always has More as fifth tab', () => {
    expect(buildTabs([])[4]?.id).toBe('more')
  })

  it('places the dynamic 4th tab at index 3', () => {
    expect(buildTabs(['jobs'])[3]?.id).toBe('jobs')
    expect(buildTabs(['quotes'])[3]?.id).toBe('quotes')
    expect(buildTabs(['bookings'])[3]?.id).toBe('bookings')
    expect(buildTabs([])[3]?.id).toBe('reports')
  })
})

// ─── KonstaTabbar component ─────────────────────────────────────────────────

describe('KonstaTabbar', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
    mockUseModules.mockReturnValue({
      enabledModules: ['jobs'],
      isModuleEnabled: (slug: string) => slug === 'jobs',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
  })

  it('renders 5 tab links', () => {
    renderTabbar()
    expect(screen.getByTestId('tab-home')).toBeInTheDocument()
    expect(screen.getByTestId('tab-invoices')).toBeInTheDocument()
    expect(screen.getByTestId('tab-customers')).toBeInTheDocument()
    expect(screen.getByTestId('tab-jobs')).toBeInTheDocument()
    expect(screen.getByTestId('tab-more')).toBeInTheDocument()
  })

  it('renders tab labels', () => {
    renderTabbar()
    expect(screen.getByText('Home')).toBeInTheDocument()
    expect(screen.getByText('Invoices')).toBeInTheDocument()
    expect(screen.getByText('Customers')).toBeInTheDocument()
    expect(screen.getByText('Jobs')).toBeInTheDocument()
    expect(screen.getByText('More')).toBeInTheDocument()
  })

  it('renders Quotes tab when only quotes module is enabled', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['quotes'],
      isModuleEnabled: (slug: string) => slug === 'quotes',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    renderTabbar()
    expect(screen.getByTestId('tab-quotes')).toBeInTheDocument()
    expect(screen.getByText('Quotes')).toBeInTheDocument()
    expect(screen.queryByTestId('tab-jobs')).not.toBeInTheDocument()
  })

  it('renders Bookings tab when only bookings module is enabled', () => {
    mockUseModules.mockReturnValue({
      enabledModules: ['bookings'],
      isModuleEnabled: (slug: string) => slug === 'bookings',
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    renderTabbar()
    expect(screen.getByTestId('tab-bookings')).toBeInTheDocument()
    expect(screen.getByText('Bookings')).toBeInTheDocument()
  })

  it('renders Reports tab when no dynamic modules are enabled', () => {
    mockUseModules.mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      modules: [],
      isLoading: false,
      error: null,
      tradeFamily: null,
      refetch: async () => {},
    })
    renderTabbar()
    expect(screen.getByTestId('tab-reports')).toBeInTheDocument()
    expect(screen.getByText('Reports')).toBeInTheDocument()
  })

  it('navigates to the correct path when a tab is clicked', () => {
    renderTabbar()
    fireEvent.click(screen.getByTestId('tab-invoices'))
    expect(mockNavigate).toHaveBeenCalledWith('/invoices')
  })

  it('navigates to /dashboard when Home tab is clicked', () => {
    renderTabbar('/invoices')
    fireEvent.click(screen.getByTestId('tab-home'))
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard')
  })

  it('navigates to /customers when Customers tab is clicked', () => {
    renderTabbar()
    fireEvent.click(screen.getByTestId('tab-customers'))
    expect(mockNavigate).toHaveBeenCalledWith('/customers')
  })

  it('calls onMorePress instead of navigating when More tab is clicked', () => {
    const onMorePress = vi.fn()
    renderTabbar('/dashboard', onMorePress)
    fireEvent.click(screen.getByTestId('tab-more'))
    expect(onMorePress).toHaveBeenCalledOnce()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('does not crash when More tab is clicked without onMorePress', () => {
    renderTabbar('/dashboard')
    expect(() => fireEvent.click(screen.getByTestId('tab-more'))).not.toThrow()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('renders SVG icons for each tab', () => {
    renderTabbar()
    const svgs = document.querySelectorAll('svg')
    expect(svgs.length).toBe(5)
  })
})
