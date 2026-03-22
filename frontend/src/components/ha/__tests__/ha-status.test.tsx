import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock apiClient BEFORE importing the component
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import apiClient from '@/api/client'
import { HAStatusPanel } from '../HAStatusPanel'

/* ── Mock data ── */

const mockIdentityPrimary = {
  node_id: 'node-1',
  node_name: 'Pi-Main',
  role: 'primary',
  peer_endpoint: 'http://192.168.1.100:8999',
  auto_promote_enabled: false,
  heartbeat_interval_seconds: 10,
  failover_timeout_seconds: 90,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const mockIdentityStandby = { ...mockIdentityPrimary, role: 'standby', node_name: 'Pi-Standby' }

const mockHistory = [
  { timestamp: '2025-01-01T00:00:00Z', peer_status: 'healthy', replication_lag_seconds: 1.2, response_time_ms: 50, error: null },
]

const mockReplicationHealthy = {
  publication_name: 'orainvoice_ha_pub',
  subscription_name: 'orainvoice_ha_sub',
  subscription_status: 'active',
  replication_lag_seconds: 1.2,
  last_replicated_at: '2025-01-01T00:00:00Z',
  tables_published: 20,
  is_healthy: true,
}

const mockReplicationLagging = { ...mockReplicationHealthy, replication_lag_seconds: 45, is_healthy: false }

/* ── Types for mock data ── */

interface MockHistoryEntry {
  timestamp: string
  peer_status: string
  replication_lag_seconds: number | null
  response_time_ms: number | null
  error: string | null
}

interface MockIdentity {
  node_id: string
  node_name: string
  role: string
  peer_endpoint: string
  auto_promote_enabled: boolean
  heartbeat_interval_seconds: number
  failover_timeout_seconds: number
  created_at: string
  updated_at: string
}

interface MockReplication {
  publication_name: string
  subscription_name: string
  subscription_status: string
  replication_lag_seconds: number
  last_replicated_at: string
  tables_published: number
  is_healthy: boolean
}

/* ── Helper to set up API mocks ── */

function setupMocks(
  identity: MockIdentity | null = mockIdentityPrimary,
  history: MockHistoryEntry[] = mockHistory,
  replication: MockReplication | null = mockReplicationHealthy,
) {
  const mockGet = vi.mocked(apiClient.get)
  mockGet.mockImplementation((url: string) => {
    if (url === '/ha/identity') {
      if (identity === null) return Promise.reject({ response: { status: 404 } })
      return Promise.resolve({ data: identity })
    }
    if (url === '/ha/history') return Promise.resolve({ data: history })
    if (url === '/ha/replication/status') {
      if (replication === null) return Promise.reject({ response: { status: 404 } })
      return Promise.resolve({ data: replication })
    }
    return Promise.reject(new Error('Not found'))
  })
}

/* ── Tests ── */

describe('HAStatusPanel — Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Test 1: renders both nodes when HA is configured
  it('renders both nodes when HA is configured', async () => {
    setupMocks()

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Pi-Main')).toBeInTheDocument()
    })

    expect(screen.getByText('Peer Node')).toBeInTheDocument()
    expect(screen.getByText('HA Cluster Status')).toBeInTheDocument()
  })

  // Test 2: shows demote button when role is primary
  it('shows demote button when role is primary', async () => {
    setupMocks(mockIdentityPrimary)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Demote to Standby')).toBeInTheDocument()
    })
  })

  // Test 3: shows promote button when role is standby
  it('shows promote button when role is standby', async () => {
    setupMocks(mockIdentityStandby)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Promote to Primary')).toBeInTheDocument()
    })
  })

  // Test 4: does not show promote button when primary
  it('does not show promote button when primary', async () => {
    setupMocks(mockIdentityPrimary)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Demote to Standby')).toBeInTheDocument()
    })

    expect(screen.queryByText('Promote to Primary')).not.toBeInTheDocument()
  })

  // Test 5: does not show demote button when standby
  it('does not show demote button when standby', async () => {
    setupMocks(mockIdentityStandby)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Promote to Primary')).toBeInTheDocument()
    })

    expect(screen.queryByText('Demote to Standby')).not.toBeInTheDocument()
  })

  // Test 6: shows replication lag warning when lag > 30s
  it('shows replication lag warning when lag > 30s', async () => {
    setupMocks(mockIdentityPrimary, mockHistory, mockReplicationLagging)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Replication Lagging')).toBeInTheDocument()
    })
  })

  // Test 7: returns null when HA not configured
  it('returns null when HA not configured', async () => {
    setupMocks(null)

    const { container } = render(<HAStatusPanel />)

    // Wait for loading to finish (the spinner disappears)
    await waitFor(() => {
      expect(screen.queryByText('Loading HA status')).not.toBeInTheDocument()
    })

    // Component returns null when identity is null
    expect(container.innerHTML).toBe('')
  })

  // Test 8: confirmation dialog requires CONFIRM text
  it('confirmation dialog requires CONFIRM text for demote', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    setupMocks(mockIdentityPrimary)

    render(<HAStatusPanel />)

    // Wait for the component to load
    await waitFor(() => {
      expect(screen.getByText('Demote to Standby')).toBeInTheDocument()
    })

    // Click the demote button to open the modal
    await user.click(screen.getByText('Demote to Standby'))

    // Modal should appear with the title
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    // The confirm button (labeled "Demote") should be disabled initially
    const demoteConfirmBtn = screen.getAllByText('Demote').find(
      (el) => el.tagName === 'BUTTON' && el.closest('dialog'),
    )!
    expect(demoteConfirmBtn).toBeDisabled()

    // Type wrong text in the confirmation input
    const confirmInput = screen.getByLabelText('Type "CONFIRM" to proceed')
    await user.type(confirmInput, 'WRONG')
    expect(demoteConfirmBtn).toBeDisabled()

    // Also need a reason
    const reasonInput = screen.getByLabelText('Reason')
    await user.type(reasonInput, 'Rolling update')

    // Clear and type correct text
    await user.clear(confirmInput)
    await user.type(confirmInput, 'CONFIRM')
    expect(demoteConfirmBtn).not.toBeDisabled()
  })

  // Test 9: health indicator colors (green/amber/red)
  it('displays correct health indicator colors for healthy nodes', async () => {
    setupMocks()

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByText('Pi-Main')).toBeInTheDocument()
    })

    // Both nodes are healthy → both should have green indicators
    const healthyIndicators = screen.getAllByLabelText('Health: healthy')
    expect(healthyIndicators).toHaveLength(2)
    healthyIndicators.forEach((indicator) => {
      expect(indicator.className).toContain('bg-green-500')
    })
  })

  it('displays amber health indicator for degraded peer', async () => {
    const degradedHistory = [
      { timestamp: '2025-01-01T00:00:00Z', peer_status: 'degraded', replication_lag_seconds: 1.2, response_time_ms: 150, error: null },
    ]
    setupMocks(mockIdentityPrimary, degradedHistory)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByLabelText('Health: degraded')).toBeInTheDocument()
    })

    const degradedIndicator = screen.getByLabelText('Health: degraded')
    expect(degradedIndicator.className).toContain('bg-amber-500')
  })

  it('displays red health indicator for unreachable peer', async () => {
    const unreachableHistory = [
      { timestamp: '2025-01-01T00:00:00Z', peer_status: 'error', replication_lag_seconds: null, response_time_ms: null, error: 'Connection refused' },
    ]
    setupMocks(mockIdentityPrimary, unreachableHistory)

    render(<HAStatusPanel />)

    await waitFor(() => {
      expect(screen.getByLabelText('Health: unreachable')).toBeInTheDocument()
    })

    const unreachableIndicator = screen.getByLabelText('Health: unreachable')
    expect(unreachableIndicator.className).toContain('bg-red-500')
  })

  // Test 10: auto-refresh polling
  it('auto-refreshes data every 10 seconds', async () => {
    setupMocks()
    const mockGet = vi.mocked(apiClient.get)

    render(<HAStatusPanel />)

    // Wait for initial fetch
    await waitFor(() => {
      expect(screen.getByText('Pi-Main')).toBeInTheDocument()
    })

    const initialCallCount = mockGet.mock.calls.length

    // Advance timer by 10 seconds to trigger the polling interval
    await vi.advanceTimersByTimeAsync(10_000)

    await waitFor(() => {
      expect(mockGet.mock.calls.length).toBeGreaterThan(initialCallCount)
    })
  })
})
