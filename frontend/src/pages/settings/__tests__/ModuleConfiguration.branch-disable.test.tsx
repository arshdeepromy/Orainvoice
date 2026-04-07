import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Unit tests for the branch_management disable confirmation dialog
 * in ModuleConfiguration.
 * Validates: Requirements 14.1, 14.2, 14.3, 14.4
 */

// --- Hoisted mocks ---

const { mockGet, mockPut } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPut: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: {
    get: mockGet,
    put: mockPut,
    interceptors: { response: { use: vi.fn(), eject: vi.fn() } },
  },
  setAccessToken: vi.fn(),
}))

vi.mock('@/components/ui/Modal', () => ({
  Modal: ({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) =>
    open ? (
      <div data-testid="modal" role="dialog" aria-label={title}>
        <h2>{title}</h2>
        <button onClick={onClose} aria-label="Close dialog">×</button>
        {children}
      </div>
    ) : null,
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    isEnabled: () => true,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFlag: vi.fn(),
}))

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: (_key: string, fallback: string) => fallback,
}))

vi.mock('@/components/ui/Badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))

vi.mock('@/components/ui/Button', () => ({
  Button: ({ children, onClick, ...props }: { children: React.ReactNode; onClick?: () => void; [key: string]: unknown }) => (
    <button onClick={onClick} data-testid={props['data-testid'] as string}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/Spinner', () => ({
  Spinner: () => <div data-testid="spinner">Loading...</div>,
}))

vi.mock('@/components/ui/AlertBanner', () => ({
  AlertBanner: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({
    addToast: vi.fn(),
    toasts: [],
    dismissToast: vi.fn(),
  }),
  ToastContainer: () => null,
}))

vi.mock('@/utils/moduleCalcs', () => ({
  cascadeDisable: () => [],
  autoEnableDependencies: () => [],
  isComingSoon: () => false,
}))

// --- Helpers ---

function makeBranchManagementModule(enabled: boolean) {
  return {
    slug: 'branch_management',
    name: 'Branch Management',
    display_name: 'Branch Management',
    description: 'Multi-branch support',
    category: 'operations',
    is_enabled: enabled,
    in_plan: true,
    dependencies: [],
    dependents: [],
    status: 'available',
  }
}

function makeBranches(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `branch-${i + 1}`,
    name: `Branch ${i + 1}`,
    is_active: true,
  }))
}

describe('ModuleConfiguration — branch_management disable dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows confirmation dialog when disabling branch_management with >1 active branch', async () => {
    const user = userEvent.setup()

    // Module list endpoint
    mockGet.mockImplementation((url: string) => {
      if (url === '/api/v2/modules') {
        return Promise.resolve({
          data: { modules: [makeBranchManagementModule(true)] },
        })
      }
      if (url === '/org/branches') {
        return Promise.resolve({
          data: { branches: makeBranches(3) },
        })
      }
      return Promise.resolve({ data: {} })
    })

    const { ModuleConfiguration } = await import('../ModuleConfiguration')
    render(<ModuleConfiguration />)

    // Wait for modules to load
    await waitFor(() => {
      expect(screen.getByTestId('module-configuration')).toBeInTheDocument()
    })

    // Find and click the toggle for Branch Management
    const toggle = screen.getByTestId('module-toggle-toggle-branch-management')
    await user.click(toggle)

    // The branch disable dialog should appear
    await waitFor(() => {
      expect(screen.getByTestId('branch-disable-dialog')).toBeInTheDocument()
    })

    // Verify the warning text
    expect(
      screen.getByText(/Disabling Branch Management will hide all branch features/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/branch_admin role will lose branch-specific access/),
    ).toBeInTheDocument()
  })

  it('does NOT show confirmation dialog when disabling branch_management with ≤1 active branch', async () => {
    const user = userEvent.setup()

    mockGet.mockImplementation((url: string) => {
      if (url === '/api/v2/modules') {
        return Promise.resolve({
          data: { modules: [makeBranchManagementModule(true)] },
        })
      }
      if (url === '/org/branches') {
        return Promise.resolve({
          data: { branches: makeBranches(1) },
        })
      }
      return Promise.resolve({ data: {} })
    })
    mockPut.mockResolvedValue({ data: {} })

    const { ModuleConfiguration } = await import('../ModuleConfiguration')
    render(<ModuleConfiguration />)

    await waitFor(() => {
      expect(screen.getByTestId('module-configuration')).toBeInTheDocument()
    })

    const toggle = screen.getByTestId('module-toggle-toggle-branch-management')
    await user.click(toggle)

    // Should NOT show the branch disable dialog — proceeds directly
    await waitFor(() => {
      expect(screen.queryByTestId('branch-disable-dialog')).not.toBeInTheDocument()
    })

    // Should have called the disable API directly
    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        expect.stringContaining('/api/v2/modules/branch_management/disable'),
      )
    })
  })

  it('proceeds with disable on confirm', async () => {
    const user = userEvent.setup()

    mockGet.mockImplementation((url: string) => {
      if (url === '/api/v2/modules') {
        return Promise.resolve({
          data: { modules: [makeBranchManagementModule(true)] },
        })
      }
      if (url === '/org/branches') {
        return Promise.resolve({
          data: { branches: makeBranches(2) },
        })
      }
      return Promise.resolve({ data: {} })
    })
    mockPut.mockResolvedValue({ data: {} })

    const { ModuleConfiguration } = await import('../ModuleConfiguration')
    render(<ModuleConfiguration />)

    await waitFor(() => {
      expect(screen.getByTestId('module-configuration')).toBeInTheDocument()
    })

    const toggle = screen.getByTestId('module-toggle-toggle-branch-management')
    await user.click(toggle)

    await waitFor(() => {
      expect(screen.getByTestId('branch-disable-dialog')).toBeInTheDocument()
    })

    // Click confirm
    const confirmBtn = screen.getByTestId('branch-disable-confirm-btn')
    await user.click(confirmBtn)

    // Should call the disable API with force=true
    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        '/api/v2/modules/branch_management/disable?force=true',
      )
    })
  })

  it('closes dialog on cancel without disabling', async () => {
    const user = userEvent.setup()

    mockGet.mockImplementation((url: string) => {
      if (url === '/api/v2/modules') {
        return Promise.resolve({
          data: { modules: [makeBranchManagementModule(true)] },
        })
      }
      if (url === '/org/branches') {
        return Promise.resolve({
          data: { branches: makeBranches(2) },
        })
      }
      return Promise.resolve({ data: {} })
    })

    const { ModuleConfiguration } = await import('../ModuleConfiguration')
    render(<ModuleConfiguration />)

    await waitFor(() => {
      expect(screen.getByTestId('module-configuration')).toBeInTheDocument()
    })

    const toggle = screen.getByTestId('module-toggle-toggle-branch-management')
    await user.click(toggle)

    await waitFor(() => {
      expect(screen.getByTestId('branch-disable-dialog')).toBeInTheDocument()
    })

    // Click cancel
    const cancelBtn = screen.getByTestId('branch-disable-cancel-btn')
    await user.click(cancelBtn)

    // Dialog should close
    await waitFor(() => {
      expect(screen.queryByTestId('branch-disable-dialog')).not.toBeInTheDocument()
    })

    // Should NOT have called the disable API
    expect(mockPut).not.toHaveBeenCalled()
  })
})
