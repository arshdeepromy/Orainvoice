/**
 * BackupHistory — safe consumption, empty/loading/error & 409 cancel (Task 17.8).
 *
 * Covers (Req 9.1 graceful states, Req 13.3 live job):
 *   • Loading spinner shown before the catalog resolves.
 *   • Empty state: no backups → "No backups available yet."
 *   • Network/5xx error → retry banner; clicking Retry re-fetches and recovers.
 *   • 409 conflict on cancel (job already terminal) → the user is told the job
 *     can no longer be cancelled instead of the page erroring out.
 *
 * The `@/api/client` default export is mocked so the REAL api module
 * (`@/api/backup/history`) runs end-to-end against deterministic shapes.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import apiClient from '@/api/client'
import { BackupHistory } from '../BackupHistory'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>
const mockPost = apiClient.post as ReturnType<typeof vi.fn>

function renderHistory(initialEntry = '/admin/backup/history') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <BackupHistory />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BackupHistory — loading', () => {
  it('shows a loading spinner before the catalog resolves', () => {
    mockGet.mockImplementation(() => new Promise(() => {}))
    renderHistory()
    expect(screen.getByRole('status', { name: 'Loading backup history' })).toBeInTheDocument()
  })
})

describe('BackupHistory — empty state (no backups)', () => {
  it('renders the empty catalog message', async () => {
    mockGet.mockResolvedValue({ data: { items: [], total: 0 } })
    renderHistory()
    expect(await screen.findByText('No backups available yet.')).toBeInTheDocument()
  })
})

describe('BackupHistory — network error + retry', () => {
  it('shows a retry banner on failure and recovers when Retry re-fetches', async () => {
    mockGet.mockRejectedValueOnce(new Error('boom'))
    renderHistory()

    expect(await screen.findByText('Could not load the backup history.')).toBeInTheDocument()

    // Recover on the next fetch.
    mockGet.mockResolvedValue({ data: { items: [], total: 0 } })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('No backups available yet.')).toBeInTheDocument()
    expect(screen.queryByText('Could not load the backup history.')).not.toBeInTheDocument()
  })
})

describe('BackupHistory — 409 conflict cancelling a job', () => {
  it('tells the user a terminal job can no longer be cancelled (409)', async () => {
    const runningJob = {
      id: 'job-1',
      status: 'running',
      progress_pct: 25,
      elapsed_seconds: 5,
      seconds_since_last_update: 1,
    }
    mockGet.mockImplementation((url: string) => {
      if (url === '/backup/backups') return Promise.resolve({ data: { items: [], total: 0 } })
      if (url.startsWith('/backup/backups/jobs/')) return Promise.resolve({ data: runningJob })
      return Promise.resolve({ data: {} })
    })
    // Cancel POST is refused because the job already reached a terminal state.
    mockPost.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: 'Job already finished' } },
    })

    renderHistory('/admin/backup/history?job_id=job-1')

    // Live banner appears once the first poll resolves; an active job exposes Cancel.
    await screen.findByText('Backup in progress')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    // Confirm in the dialog.
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel job' }))

    // 409 is surfaced as a clear, non-crashing message.
    expect(
      await screen.findByText('This job has already finished and can no longer be cancelled.'),
    ).toBeInTheDocument()
  })
})
