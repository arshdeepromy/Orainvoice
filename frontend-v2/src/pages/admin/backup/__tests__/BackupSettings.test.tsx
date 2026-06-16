/**
 * BackupSettings — safe consumption, loading, empty & 422 validation (Task 17.8).
 *
 * Covers (Req 1.4 safe consumption, Req 9.1 graceful states):
 *   • Loading spinner shown before destinations resolve.
 *   • Empty state: no destinations configured → "No destinations yet".
 *   • 422 validation error → the backend's `detail` message is surfaced in the
 *     Add-destination form rather than crashing the page.
 *
 * The `@/api/client` default export is mocked so the REAL api module
 * (`@/api/backup/settings`) runs end-to-end against deterministic shapes.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import apiClient from '@/api/client'
import { BackupSettings } from '../BackupSettings'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>
const mockPost = apiClient.post as ReturnType<typeof vi.fn>

function renderSettings() {
  return render(
    <MemoryRouter initialEntries={['/admin/backup/settings']}>
      <BackupSettings />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BackupSettings — loading', () => {
  it('shows a loading spinner before destinations resolve', () => {
    mockGet.mockImplementation(() => new Promise(() => {}))
    renderSettings()
    expect(screen.getByRole('status', { name: 'Loading destinations' })).toBeInTheDocument()
  })
})

describe('BackupSettings — empty state (no destinations)', () => {
  it('renders the "no destinations yet" empty state', async () => {
    mockGet.mockResolvedValue({ data: { items: [], total: 0 } })
    renderSettings()
    expect(await screen.findByText('No destinations yet')).toBeInTheDocument()
  })
})

describe('BackupSettings — 422 validation error surfaced', () => {
  it('shows the backend validation detail when creating a destination fails (422)', async () => {
    // Destinations list loads empty so the Add flow is reachable.
    mockGet.mockResolvedValue({ data: { items: [], total: 0 } })
    // The create POST is rejected with a 422 validation detail.
    mockPost.mockRejectedValue({
      response: { status: 422, data: { detail: 'share_path is required' } },
    })

    renderSettings()
    await screen.findByText('No destinations yet')

    // Open the Add-destination form for a NAS destination.
    fireEvent.change(screen.getByLabelText('Add a destination'), {
      target: { value: 'nas' },
    })

    // The modal renders the per-type form; supply the client-side-required name.
    fireEvent.change(await screen.findByLabelText('Display name'), {
      target: { value: 'My NAS' },
    })

    // Submit — the backend returns 422 and the detail must surface to the user.
    fireEvent.click(screen.getByRole('button', { name: 'Add destination' }))

    expect(await screen.findByText('share_path is required')).toBeInTheDocument()
    // The page did not crash — the form is still mounted.
    expect(screen.getByText('Could not save')).toBeInTheDocument()
  })
})
