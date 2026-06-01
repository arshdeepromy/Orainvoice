/**
 * Unit tests for PpsrHistoryTable.
 *
 * Validates the three scenarios called out in the spec task D4:
 *   1. Pagination — clicking "Next" / "Previous" requests the next /
 *      previous page of results via offset / limit.
 *   2. Row click opens the PpsrDetailDrawer.
 *   3. Bumping `refreshKey` re-fetches the first page (parent uses
 *      this after a fresh search).
 *
 * Mocks `@/api/ppsr` so no network calls are made.
 *
 * **Validates: PPSR module spec task D4**
 */

import { render, screen, within, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Stub LocaleContext (consumed transitively via PpsrResultPanel inside
// PpsrDetailDrawer) so the component can resolve a locale without
// pulling in the full provider tree.
vi.mock('@/contexts/LocaleContext', () => ({
  useLocale: () => ({
    locale: 'en-NZ',
    direction: 'ltr',
    isRtl: false,
    setLocale: vi.fn(),
    supportedLocales: ['en'],
    localeNames: { en: 'English' },
  }),
}))

// Mock the typed PPSR API client. Hoisted by Vitest so the imports
// below see the mocked module.
vi.mock('@/api/ppsr', () => {
  const listSearches = vi.fn()
  const getSearch = vi.fn()
  const exportPdf = vi.fn()
  const forgetSearch = vi.fn()
  const linkVehicle = vi.fn()
  const search = vi.fn()
  const getQuota = vi.fn()
  const ppsrApi = {
    listSearches,
    getSearch,
    exportPdf,
    forgetSearch,
    linkVehicle,
    search,
    getQuota,
  }
  return {
    ppsrApi,
    listSearches,
    getSearch,
    exportPdf,
    forgetSearch,
    linkVehicle,
    search,
    getQuota,
    default: ppsrApi,
  }
})

import { ppsrApi, type PpsrSearchSummary } from '@/api/ppsr'
import { PpsrHistoryTable } from '../PpsrHistoryTable'

// ===========================================================================
// Fixtures
// ===========================================================================

function makeRow(overrides: Partial<PpsrSearchSummary> = {}): PpsrSearchSummary {
  return {
    id: '00000000-0000-0000-0000-00000000aaaa',
    rego: 'ABC123',
    match: 'N',
    match_description: 'No security interests on file',
    statement_count: 0,
    has_warnings: false,
    has_ownership_data: false,
    not_found: false,
    forgotten_at: null,
    org_vehicle_id: null,
    user_id: '00000000-0000-0000-0000-00000000bbbb',
    created_at: '2026-06-01T03:32:00Z',
    ...overrides,
  }
}

function pageOf(items: PpsrSearchSummary[], total: number) {
  return { items, total }
}

// ===========================================================================
// Tests
// ===========================================================================

describe('PpsrHistoryTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches page 1 on mount with offset=0, limit=25', async () => {
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue(
      pageOf(
        [makeRow({ id: 'row-1', rego: 'ABC123' })],
        1,
      ),
    )

    render(<PpsrHistoryTable />)

    await waitFor(() => {
      expect(ppsrApi.listSearches).toHaveBeenCalledTimes(1)
    })
    const firstCallArgs = (ppsrApi.listSearches as ReturnType<typeof vi.fn>)
      .mock.calls[0]
    expect(firstCallArgs[0]).toEqual({ offset: 0, limit: 25 })

    expect(await screen.findByText('ABC123')).toBeInTheDocument()
  })

  it('paginates via the next / previous buttons', async () => {
    // Build 26 unique rows so the paginator shows two pages.
    const allRows = Array.from({ length: 26 }, (_, i) =>
      makeRow({
        id: `00000000-0000-0000-0000-00000000${i.toString(16).padStart(4, '0')}`,
        rego: `REGO${i.toString().padStart(3, '0')}`,
      }),
    )

    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockImplementation(
      async (params: { offset?: number; limit?: number }) => {
        const offset = params?.offset ?? 0
        const limit = params?.limit ?? 25
        return pageOf(allRows.slice(offset, offset + limit), allRows.length)
      },
    )

    render(<PpsrHistoryTable />)

    // Page 1 shows the first row.
    expect(await screen.findByText('REGO000')).toBeInTheDocument()

    const next = await screen.findByTestId('ppsr-history-next')
    const user = userEvent.setup()
    await user.click(next)

    // Page 2 should now request offset=25.
    await waitFor(() => {
      const calls = (ppsrApi.listSearches as ReturnType<typeof vi.fn>).mock
        .calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toEqual({ offset: 25, limit: 25 })
    })

    // Row 26 (REGO025) is on page 2.
    expect(await screen.findByText('REGO025')).toBeInTheDocument()

    // Click Previous → snap back to page 1.
    const prev = await screen.findByTestId('ppsr-history-prev')
    await user.click(prev)

    await waitFor(() => {
      const calls = (ppsrApi.listSearches as ReturnType<typeof vi.fn>).mock
        .calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toEqual({ offset: 0, limit: 25 })
    })

    expect(await screen.findByText('REGO000')).toBeInTheDocument()
  })

  it('opens the detail drawer when a row is clicked', async () => {
    const id = '11111111-1111-1111-1111-111111111111'
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue(
      pageOf([makeRow({ id, rego: 'ZZZ999' })], 1),
    )
    // Drawer fetch resolves with a minimal PpsrSearchResult.
    ;(ppsrApi.getSearch as ReturnType<typeof vi.fn>).mockResolvedValue({
      search_id: id,
      rego: 'ZZZ999',
      cached: false,
      cached_at: null,
      source_search_id: null,
      match: 'N',
      match_description: 'No security interests',
      statement_count: 0,
      ppsr_details: [],
      ownership_history: null,
      current_owner: null,
      warnings: [],
      basic: null,
      not_found: false,
      charges_cents: null,
      carjam_request_id: null,
    })

    render(<PpsrHistoryTable />)

    const row = await screen.findByTestId(`ppsr-history-row-${id}`)
    const user = userEvent.setup()
    await user.click(row)

    // Drawer mounts and fetches the detail.
    await waitFor(() => {
      expect(ppsrApi.getSearch).toHaveBeenCalledWith(id, expect.anything())
    })
    expect(await screen.findByTestId('ppsr-detail-drawer')).toBeInTheDocument()
  })

  it('refetches the first page when refreshKey is bumped', async () => {
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue(
      pageOf([makeRow({ id: 'r1', rego: 'AAA111' })], 1),
    )

    const { rerender } = render(<PpsrHistoryTable refreshKey={0} />)

    await waitFor(() => {
      expect(ppsrApi.listSearches).toHaveBeenCalledTimes(1)
    })

    // Bump refreshKey — table should re-fetch.
    await act(async () => {
      rerender(<PpsrHistoryTable refreshKey={1} />)
    })

    await waitFor(() => {
      expect(ppsrApi.listSearches).toHaveBeenCalledTimes(2)
    })

    const lastCall = (ppsrApi.listSearches as ReturnType<typeof vi.fn>).mock
      .calls[1]
    // refreshKey bump should request offset=0 (page 1).
    expect(lastCall[0]).toEqual({ offset: 0, limit: 25 })
  })

  it('renders the empty state when no searches exist', async () => {
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue(
      pageOf([], 0),
    )
    render(<PpsrHistoryTable />)
    expect(await screen.findByTestId('ppsr-history-empty')).toBeInTheDocument()
  })

  it('renders the match colour chip per design §6.0', async () => {
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue(
      pageOf(
        [
          makeRow({
            id: 'red-row',
            rego: 'OWING1',
            match: 'Y',
            match_description: 'Money owing',
            statement_count: 2,
          }),
        ],
        1,
      ),
    )

    render(<PpsrHistoryTable />)

    const row = await screen.findByTestId('ppsr-history-row-red-row')
    const chip = within(row).getByLabelText('Money owing')
    expect(chip.className).toMatch(/bg-red-50/)
    expect(chip.className).toMatch(/dark:bg-red-900/)
  })

  it('shows a "Forgotten" pill when forgotten_at is set', async () => {
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue(
      pageOf(
        [
          makeRow({
            id: 'forgotten-row',
            rego: 'WIPED1',
            forgotten_at: '2026-06-02T10:00:00Z',
          }),
        ],
        1,
      ),
    )

    render(<PpsrHistoryTable />)
    const row = await screen.findByTestId('ppsr-history-row-forgotten-row')
    expect(within(row).getByText(/Forgotten/i)).toBeInTheDocument()
  })
})
