import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

/**
 * Validates: Requirements 17.1, 17.5, 17.6, 16.4
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    mfaPending: false,
    mfaSessionToken: null,
    login: vi.fn(),
    loginWithGoogle: vi.fn(),
    loginWithPasskey: vi.fn(),
    logout: vi.fn(),
    completeMfa: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isSalesperson: false,
  }),
}))

import apiClient from '@/api/client'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { ErrorBoundaryWithRetry } from '@/components/common/ErrorBoundaryWithRetry'
import { ModulePageWrapper } from '@/components/common/ModulePageWrapper'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function GuardConsumer({ moduleSlug }: { moduleSlug: string }) {
  const { isAllowed, isLoading } = useModuleGuard(moduleSlug)
  if (isLoading) return <div data-testid="guard-loading">Loading</div>
  return <div data-testid="guard-result">{isAllowed ? 'allowed' : 'denied'}</div>
}

function DashboardPage() {
  return <div data-testid="dashboard">Dashboard</div>
}

function renderWithProviders(
  ui: React.ReactElement,
  { initialEntries = ['/test'] }: { initialEntries?: string[] } = {},
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ModuleProvider>
        <FeatureFlagProvider>
          <Routes>
            <Route path="/test" element={ui} />
            <Route path="/dashboard" element={<DashboardPage />} />
          </Routes>
        </FeatureFlagProvider>
      </ModuleProvider>
    </MemoryRouter>,
  )
}

/* ------------------------------------------------------------------ */
/*  useModuleGuard tests                                               */
/* ------------------------------------------------------------------ */

describe('useModuleGuard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns isAllowed: true when module is enabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/modules') {
        return Promise.resolve({
          data: [
            { slug: 'kitchen_display', display_name: 'Kitchen', description: '', category: 'hospitality', is_core: false, is_enabled: true },
          ],
        })
      }
      // Flags endpoint
      return Promise.resolve({ data: {} })
    })

    renderWithProviders(<GuardConsumer moduleSlug="kitchen_display" />)

    const result = await screen.findByTestId('guard-result')
    expect(result).toHaveTextContent('allowed')
  })

  it('redirects to /dashboard when module is disabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/modules') {
        return Promise.resolve({
          data: [
            { slug: 'kitchen_display', display_name: 'Kitchen', description: '', category: 'hospitality', is_core: false, is_enabled: false },
          ],
        })
      }
      return Promise.resolve({ data: {} })
    })

    renderWithProviders(<GuardConsumer moduleSlug="kitchen_display" />)

    // Should redirect to dashboard
    expect(await screen.findByTestId('dashboard')).toBeInTheDocument()
  })

  it('redirects to /dashboard when module is not in the list', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/modules') {
        return Promise.resolve({
          data: [
            { slug: 'invoicing', display_name: 'Invoicing', description: '', category: 'core', is_core: true, is_enabled: true },
          ],
        })
      }
      return Promise.resolve({ data: {} })
    })

    renderWithProviders(<GuardConsumer moduleSlug="franchise" />)

    expect(await screen.findByTestId('dashboard')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ErrorBoundaryWithRetry tests                                       */
/* ------------------------------------------------------------------ */

function ThrowChunkError(): React.ReactElement {
  throw Object.assign(new Error('Loading chunk abc123 failed'), { name: 'ChunkLoadError' })
}

function ThrowGenericError(): React.ReactElement {
  throw new Error('Something unexpected happened')
}

describe('ErrorBoundaryWithRetry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Suppress React error boundary console.error noise
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundaryWithRetry>
        <div data-testid="child">Hello</div>
      </ErrorBoundaryWithRetry>,
    )

    expect(screen.getByTestId('child')).toBeInTheDocument()
  })

  it('renders chunk error UI with retry button for ChunkLoadError', () => {
    render(
      <ErrorBoundaryWithRetry>
        <ThrowChunkError />
      </ErrorBoundaryWithRetry>,
    )

    expect(screen.getByTestId('error-boundary-chunk')).toBeInTheDocument()
    expect(screen.getByTestId('error-boundary-retry')).toBeInTheDocument()
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
  })

  it('renders generic error UI for non-chunk errors', () => {
    render(
      <ErrorBoundaryWithRetry>
        <ThrowGenericError />
      </ErrorBoundaryWithRetry>,
    )

    expect(screen.getByTestId('error-boundary-generic')).toBeInTheDocument()
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('detects chunk errors from "loading chunk" message pattern', () => {
    function ThrowLoadingChunk(): React.ReactElement {
      throw new Error('Loading chunk 42 failed')
    }

    render(
      <ErrorBoundaryWithRetry>
        <ThrowLoadingChunk />
      </ErrorBoundaryWithRetry>,
    )

    expect(screen.getByTestId('error-boundary-chunk')).toBeInTheDocument()
  })

  it('detects chunk errors from "dynamically imported module" message pattern', () => {
    function ThrowDynamicImport(): React.ReactElement {
      throw new Error('Failed to fetch dynamically imported module: /src/pages/Kitchen.tsx')
    }

    render(
      <ErrorBoundaryWithRetry>
        <ThrowDynamicImport />
      </ErrorBoundaryWithRetry>,
    )

    expect(screen.getByTestId('error-boundary-chunk')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ModulePageWrapper tests                                            */
/* ------------------------------------------------------------------ */

describe('ModulePageWrapper', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children when module is enabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/modules') {
        return Promise.resolve({
          data: [
            { slug: 'kitchen_display', display_name: 'Kitchen', description: '', category: 'hospitality', is_core: false, is_enabled: true },
          ],
        })
      }
      return Promise.resolve({ data: {} })
    })

    renderWithProviders(
      <ModulePageWrapper moduleSlug="kitchen_display">
        <div data-testid="page-content">Kitchen Page</div>
      </ModulePageWrapper>,
    )

    expect(await screen.findByTestId('page-content')).toBeInTheDocument()
  })

  it('redirects when module is disabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/modules') {
        return Promise.resolve({
          data: [
            { slug: 'kitchen_display', display_name: 'Kitchen', description: '', category: 'hospitality', is_core: false, is_enabled: false },
          ],
        })
      }
      return Promise.resolve({ data: {} })
    })

    renderWithProviders(
      <ModulePageWrapper moduleSlug="kitchen_display">
        <div data-testid="page-content">Kitchen Page</div>
      </ModulePageWrapper>,
    )

    expect(await screen.findByTestId('dashboard')).toBeInTheDocument()
    expect(screen.queryByTestId('page-content')).not.toBeInTheDocument()
  })

  it('renders children when module is enabled and flag is enabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/modules') {
        return Promise.resolve({
          data: [
            { slug: 'kitchen_display', display_name: 'Kitchen', description: '', category: 'hospitality', is_core: false, is_enabled: true },
          ],
        })
      }
      // Flags API
      return Promise.resolve({ data: { kitchen_display: true } })
    })

    renderWithProviders(
      <ModulePageWrapper moduleSlug="kitchen_display" flagKey="kitchen_display">
        <div data-testid="page-content">Kitchen Page</div>
      </ModulePageWrapper>,
    )

    expect(await screen.findByTestId('page-content')).toBeInTheDocument()
  })
})
