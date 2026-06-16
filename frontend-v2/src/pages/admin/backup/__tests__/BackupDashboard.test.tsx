/**
 * BackupDashboard — safe consumption, loading, empty & error states (Task 17.8).
 *
 * Covers (Req 1.4 page-level safe consumption, Req 9.1 graceful states):
 *   • Loading spinner shown before the dashboard data resolves.
 *   • Empty state: no destinations configured → the "configure a destination"
 *     CTA renders instead of the status grid.
 *   • Network/5xx error → a retry banner is shown, and clicking Retry re-fetches
 *     (the page recovers to the now-successful response).
 *
 * The `@/api/client` default export is mocked so the REAL api module
 * (`@/api/backup/dashboard`) runs end-to-end against deterministic shapes,
 * exercising its `?? []` / `?? 0` safe reads.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import apiClient from '@/api/client'
import { BackupDashboard } from '../BackupDashboard'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>

function renderDashboard() {
  return render(
    <MemoryRouter>
      <BackupDashboard />
    </MemoryRouter>,
  )
}

/** Deterministic config row (RPO/RTO + default scope). */
const CONFIG = {
  id: 'cfg-1',
  schedule_cron: '0 2 * * *',
  default_scope: 'both',
  rpo_seconds: 86400,
  rto_seconds: 14400,
}

/** Route an api/client GET to the right deterministic payload. */
function resolveGet(url: string, destinations: unknown[], backups: unknown[]) {
  if (url === '/backup/config') return Promise.resolve({ data: CONFIG })
  if (url === '/backup/destinations') {
    return Promise.resolve({ data: { items: destinations, total: destinations.length } })
  }
  if (url === '/backup/backups') {
    return Promise.resolve({ data: { items: backups, total: backups.length } })
  }
  return Promise.resolve({ data: {} })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BackupDashboard — loading', () => {
  it('shows a loading spinner before data resolves', () => {
    // Never-resolving GET keeps the page in its loading state.
    mockGet.mockImplementation(() => new Promise(() => {}))
    renderDashboard()
    expect(screen.getByRole('status', { name: 'Loading backup status' })).toBeInTheDocument()
  })
})

describe('BackupDashboard — empty state (no destinations)', () => {
  beforeEach(() => {
    mockGet.mockImplementation((url: string) => resolveGet(url, [], []))
  })

  it('renders the "configure a destination" empty state', async () => {
    renderDashboard()
    expect(await screen.findByText('No backup destination configured')).toBeInTheDocument()
    const cta = screen.getByRole('link', { name: 'Configure a destination' })
    expect(cta).toHaveAttribute('href', '/admin/backup/settings')
  })
})

describe('BackupDashboard — network error + retry', () => {
  it('shows a retry banner on failure and recovers when Retry re-fetches', async () => {
    // First load: every call rejects (simulating a 5xx / network failure).
    mockGet.mockImplementation(() => Promise.reject(new Error('network down')))
    renderDashboard()

    expect(await screen.findByText('Could not load backup status')).toBeInTheDocument()
    const retry = screen.getByRole('button', { name: 'Retry' })

    // Recover: subsequent loads succeed (with no destinations).
    mockGet.mockImplementation((url: string) => resolveGet(url, [], []))
    fireEvent.click(retry)

    // The page re-fetches and renders the recovered (empty) state.
    expect(await screen.findByText('No backup destination configured')).toBeInTheDocument()
    expect(screen.queryByText('Could not load backup status')).not.toBeInTheDocument()
  })
})
