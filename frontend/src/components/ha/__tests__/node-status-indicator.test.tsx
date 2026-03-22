import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
  },
}))

import apiClient from '@/api/client'
import { NodeStatusIndicator } from '../NodeStatusIndicator'

/* ── Mock data ── */

const mockStatusPrimary = {
  node_name: 'Pi-Main',
  role: 'primary',
  peer_status: 'healthy',
  sync_status: 'healthy',
}

const mockStatusStandby = {
  node_name: 'Pi-Standby',
  role: 'standby',
  peer_status: 'healthy',
  sync_status: 'healthy',
}

const mockStatusPeerUnreachable = {
  node_name: 'Pi-Main',
  role: 'primary',
  peer_status: 'unreachable',
  sync_status: 'disconnected',
}

const mockStatusStandalone = {
  node_name: 'unconfigured',
  role: 'standalone',
  peer_status: 'unknown',
  sync_status: 'not_configured',
}

/* ── Helper ── */

function setupMock(status: typeof mockStatusPrimary | null) {
  const mockGet = vi.mocked(apiClient.get)
  if (status === null) {
    mockGet.mockRejectedValue({ response: { status: 404 } })
  } else {
    mockGet.mockResolvedValue({ data: status })
  }
}

/* ── Tests ── */

describe('NodeStatusIndicator — Unit Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Validates: Requirements 8.1
  it('displays node name and role for primary', async () => {
    setupMock(mockStatusPrimary)

    render(<NodeStatusIndicator />)

    await waitFor(() => {
      expect(screen.getByText('Pi-Main')).toBeInTheDocument()
    })
    expect(screen.getByText('Primary')).toBeInTheDocument()
  })

  // Validates: Requirements 8.1
  it('displays node name and role for standby', async () => {
    setupMock(mockStatusStandby)

    render(<NodeStatusIndicator />)

    await waitFor(() => {
      expect(screen.getByText('Pi-Standby')).toBeInTheDocument()
    })
    expect(screen.getByText('Standby')).toBeInTheDocument()
  })

  // Validates: Requirements 8.3
  it('shows backup node notice when standby', async () => {
    setupMock(mockStatusStandby)

    render(<NodeStatusIndicator />)

    await waitFor(() => {
      expect(screen.getByText(/Running on backup node/)).toBeInTheDocument()
    })
  })

  // Validates: Requirements 8.3
  it('does not show backup notice when primary', async () => {
    setupMock(mockStatusPrimary)

    render(<NodeStatusIndicator />)

    await waitFor(() => {
      expect(screen.getByText('Pi-Main')).toBeInTheDocument()
    })
    expect(screen.queryByText(/Running on backup node/)).not.toBeInTheDocument()
  })

  // Validates: Requirements 8.2
  it('shows peer unreachable warning', async () => {
    setupMock(mockStatusPeerUnreachable)

    render(<NodeStatusIndicator />)

    await waitFor(() => {
      expect(screen.getByText(/Peer unreachable/)).toBeInTheDocument()
    })
  })

  // Validates: Requirements 8.1
  it('renders nothing when HA not configured (standalone)', async () => {
    setupMock(mockStatusStandalone)

    const { container } = render(<NodeStatusIndicator />)

    // Wait for the API call to resolve
    await waitFor(() => {
      expect(vi.mocked(apiClient.get)).toHaveBeenCalledWith('/ha/status')
    })

    // Component returns null for standalone role
    expect(container.innerHTML).toBe('')
  })

  // Validates: Requirements 8.1
  it('renders nothing when API returns 404', async () => {
    setupMock(null)

    const { container } = render(<NodeStatusIndicator />)

    // Wait for the API call to resolve (rejected)
    await waitFor(() => {
      expect(vi.mocked(apiClient.get)).toHaveBeenCalledWith('/ha/status')
    })

    // Component renders nothing on error
    expect(container.innerHTML).toBe('')
  })
})
