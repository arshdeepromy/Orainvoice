import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ */
/* Mocks                                                              */
/* ------------------------------------------------------------------ */

// Mock Konsta UI components
vi.mock('konsta/react', () => ({
  Page: ({ children, ...props }: any) => <div data-testid={props['data-testid']}>{children}</div>,
  Block: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  BlockTitle: ({ children }: any) => <h3>{children}</h3>,
  Card: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  List: ({ children }: any) => <ul>{children}</ul>,
  ListItem: ({ title, subtitle, after, ...props }: any) => (
    <li data-testid={props['data-testid']}>
      <span>{title}</span>
      {subtitle && <span>{subtitle}</span>}
      {after && <span>{after}</span>}
    </li>
  ),
  Button: ({ children, ...props }: any) => (
    <button data-testid={props['data-testid']} onClick={props.onClick}>
      {children}
    </button>
  ),
  Preloader: () => <div data-testid="preloader">Loading...</div>,
  Chip: ({ children, ...props }: any) => (
    <span data-testid={props['data-testid']} onClick={props.onClick}>
      {children}
    </span>
  ),
  Searchbar: ({ ...props }: any) => (
    <input data-testid={props['data-testid']} placeholder={props.placeholder} />
  ),
}))

// Mock KonstaNavbar
vi.mock('@/components/konsta/KonstaNavbar', () => ({
  KonstaNavbar: ({ title }: any) => <div data-testid="navbar">{title}</div>,
}))

// Mock StatusBadge
vi.mock('@/components/konsta/StatusBadge', () => ({
  default: ({ status }: any) => <span data-testid="status-badge">{status}</span>,
}))

// Mock HapticButton
vi.mock('@/components/konsta/HapticButton', () => ({
  default: ({ children, ...props }: any) => (
    <button data-testid={props['data-testid']} onClick={props.onClick}>
      {children}
    </button>
  ),
}))

// Mock PullRefresh
vi.mock('@/components/gestures/PullRefresh', () => ({
  PullRefresh: ({ children }: any) => <div>{children}</div>,
}))

// Mock useHaptics
vi.mock('@/hooks/useHaptics', () => ({
  useHaptics: () => ({
    light: vi.fn(),
    medium: vi.fn(),
    heavy: vi.fn(),
    selection: vi.fn(),
  }),
}))

// Mock AuthContext
const mockUser = { id: '1', role: 'owner', first_name: 'Test' }
const mockKioskUser = { id: '2', role: 'kiosk', first_name: 'Kiosk' }
let currentUser: any = mockUser

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: currentUser,
    logout: vi.fn(),
  }),
}))

// Mock API client — return empty items immediately
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [] } }),
    post: vi.fn().mockResolvedValue({ data: { id: '1' } }),
  },
}))

/* ------------------------------------------------------------------ */
/* Tests                                                              */
/* ------------------------------------------------------------------ */

describe('PortalScreen', () => {
  beforeEach(() => {
    currentUser = mockUser
    vi.clearAllMocks()
  })

  it('renders portal page', async () => {
    const PortalScreen = (await import('@/screens/portal/PortalScreen')).default
    render(
      <MemoryRouter initialEntries={['/portal']}>
        <PortalScreen />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('portal-page')).toBeInTheDocument()
    expect(screen.getByText('Customer Portal')).toBeInTheDocument()
  })

  it('renders tab selectors after loading', async () => {
    const PortalScreen = (await import('@/screens/portal/PortalScreen')).default
    render(
      <MemoryRouter initialEntries={['/portal']}>
        <PortalScreen />
      </MemoryRouter>,
    )

    // Wait for loading to finish and tabs to appear
    await waitFor(() => {
      expect(screen.getByTestId('portal-tab-invoices')).toBeInTheDocument()
    })
    expect(screen.getByTestId('portal-tab-quotes')).toBeInTheDocument()
    expect(screen.getByTestId('portal-tab-bookings')).toBeInTheDocument()
  })
})

describe('KioskScreen', () => {
  beforeEach(() => {
    currentUser = mockKioskUser
    vi.clearAllMocks()
  })

  it('renders kiosk page after loading', async () => {
    const KioskScreen = (await import('@/screens/kiosk/KioskScreen')).default
    render(
      <MemoryRouter initialEntries={['/kiosk']}>
        <KioskScreen />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('kiosk-page')).toBeInTheDocument()

    // Wait for loading to finish
    await waitFor(() => {
      expect(screen.getByText('Kiosk Mode')).toBeInTheDocument()
    })
  })

  it('renders exit button after loading', async () => {
    const KioskScreen = (await import('@/screens/kiosk/KioskScreen')).default
    render(
      <MemoryRouter initialEntries={['/kiosk']}>
        <KioskScreen />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('kiosk-exit')).toBeInTheDocument()
    })
  })
})

describe('KonstaShell kiosk role handling', () => {
  it('no longer exports resolveNavbarMeta — screens own their navbars', async () => {
    const mod = await import('@/components/konsta/KonstaShell') as Record<string, unknown>
    expect(mod.resolveNavbarMeta).toBeUndefined()
  })
})
