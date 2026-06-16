/**
 * Rehearsals — safe consumption, loading, empty & error states (Task 17.8).
 *
 * Covers (Req 9.1 graceful states, Req 26.1 history):
 *   • Loading spinner shown before config + history resolve.
 *   • Empty state: no rehearsals → "No rehearsals yet".
 *   • Network/5xx error → retry banner; clicking Retry re-fetches and recovers.
 *
 * The `@/api/client` default export is mocked so the REAL api module
 * (`@/api/backup/rehearsals`) runs end-to-end against deterministic shapes,
 * exercising its `?? []` / `?? 0` safe reads.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))

import apiClient from '@/api/client'
import { Rehearsals } from '../Rehearsals'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>

const CONFIG = {
  id: 'cfg-1',
  rehearsal_cron: null,
  rto_seconds: 3600,
  rpo_seconds: 86400,
  restore_maintenance_active: false,
}

/** Route an api/client GET to the right deterministic payload. */
function resolveGet(url: string, rehearsals: unknown[]) {
  if (url === '/backup/config') return Promise.resolve({ data: CONFIG })
  if (url === '/backup/rehearsals') {
    return Promise.resolve({ data: { items: rehearsals, total: rehearsals.length } })
  }
  return Promise.resolve({ data: {} })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Rehearsals — loading', () => {
  it('shows a loading spinner before config + history resolve', () => {
    mockGet.mockImplementation(() => new Promise(() => {}))
    render(<Rehearsals />)
    expect(screen.getByRole('status', { name: 'Loading rehearsals' })).toBeInTheDocument()
  })
})

describe('Rehearsals — empty state (no rehearsals)', () => {
  it('renders the "no rehearsals yet" empty state', async () => {
    mockGet.mockImplementation((url: string) => resolveGet(url, []))
    render(<Rehearsals />)
    expect(await screen.findByText('No rehearsals yet')).toBeInTheDocument()
  })
})

describe('Rehearsals — network error + retry', () => {
  it('shows a retry banner on failure and recovers when Retry re-fetches', async () => {
    mockGet.mockRejectedValue(new Error('boom'))
    render(<Rehearsals />)

    expect(await screen.findByText('Could not load restore rehearsals.')).toBeInTheDocument()

    // Recover on the next fetch.
    mockGet.mockImplementation((url: string) => resolveGet(url, []))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('No rehearsals yet')).toBeInTheDocument()
    expect(screen.queryByText('Could not load restore rehearsals.')).not.toBeInTheDocument()
  })
})
