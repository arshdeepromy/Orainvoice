/**
 * PpsrCard tests — covers the three states the design calls out:
 *
 *   1. Module disabled  → card returns null (ModuleGate fallback)
 *   2. Module enabled, no prior search → empty state with "Run PPSR
 *      check now" link pointing at `/ppsr/search?rego=<rego>`
 *   3. Module enabled, prior search present → match chip + relative
 *      "Last checked …" line + "Re-run check" link
 *
 * **Validates: PPSR module spec task D5**
 */

import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/* ── Mocks ─────────────────────────────────────────────────────────── */

const mockUseModules = vi.fn()

vi.mock('@/contexts/ModuleContext', () => ({
  ModuleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useModules: () => mockUseModules(),
}))

vi.mock('@/api/ppsr', () => ({
  ppsrApi: {
    listSearches: vi.fn(),
  },
}))

import { ppsrApi } from '@/api/ppsr'
import { PpsrCard } from '../PpsrCard'

/* ── Helpers ───────────────────────────────────────────────────────── */

function enableModule(slug: string) {
  mockUseModules.mockReturnValue({
    modules: [],
    enabledModules: [slug],
    isLoading: false,
    error: null,
    isEnabled: (s: string) => s === slug,
    refetch: vi.fn(),
  })
}

function disableAllModules() {
  mockUseModules.mockReturnValue({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: () => false,
    refetch: vi.fn(),
  })
}

function renderCard(rego = 'ABC123') {
  return render(
    <MemoryRouter>
      <PpsrCard rego={rego} />
    </MemoryRouter>,
  )
}

/* ── Lifecycle ─────────────────────────────────────────────────────── */

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
})

/* ── Tests ─────────────────────────────────────────────────────────── */

describe('PpsrCard', () => {
  it('returns null when the ppsr module is disabled', () => {
    disableAllModules()

    const { container } = renderCard()

    // ModuleGate renders the fallback (null) — there should be no card markup.
    expect(container.querySelector('[data-testid="ppsr-card"]')).toBeNull()
    // Inner component must not have called the API.
    expect(ppsrApi.listSearches).not.toHaveBeenCalled()
  })

  it('renders the empty state with a "Run PPSR check now" CTA when no prior search exists', async () => {
    enableModule('ppsr')
    vi.mocked(ppsrApi.listSearches).mockResolvedValue({ items: [], total: 0 })

    renderCard('ABC123')

    // Wait for fetch to settle — loading text disappears.
    await waitFor(() => {
      expect(screen.getByText(/no ppsr check on file/i)).toBeInTheDocument()
    })

    const cta = screen.getByTestId('ppsr-card-run-now')
    expect(cta).toHaveTextContent(/run ppsr check now/i)
    expect(cta).toHaveAttribute('href', '/ppsr/search?rego=ABC123')

    // listSearches called with the normalised rego + limit:1.
    expect(ppsrApi.listSearches).toHaveBeenCalledWith(
      expect.objectContaining({ rego: 'ABC123', limit: 1 }),
      expect.any(AbortSignal),
    )
  })

  it('renders the latest match summary plus a "Re-run check" link when a prior search exists', async () => {
    enableModule('ppsr')
    vi.mocked(ppsrApi.listSearches).mockResolvedValue({
      items: [
        {
          id: 'search-1',
          rego: 'ABC123',
          match: 'N',
          match_description: 'No match found',
          statement_count: 0,
          has_warnings: false,
          has_ownership_data: false,
          not_found: false,
          forgotten_at: null,
          org_vehicle_id: null,
          user_id: 'user-1',
          created_at: new Date().toISOString(),
        },
      ],
      total: 1,
    })

    renderCard('ABC123')

    // Match chip and re-run link both render once data resolves.
    await waitFor(() => {
      expect(screen.getByTestId('ppsr-card-match-chip')).toBeInTheDocument()
    })

    expect(screen.getByText(/no money owing/i)).toBeInTheDocument()
    expect(screen.getByText(/last checked/i)).toBeInTheDocument()

    const rerun = screen.getByTestId('ppsr-card-rerun')
    expect(rerun).toHaveTextContent(/re-run check/i)
    expect(rerun).toHaveAttribute('href', '/ppsr/search?rego=ABC123')
  })

  it('uppercases lower-case rego before deep-linking', async () => {
    enableModule('ppsr')
    vi.mocked(ppsrApi.listSearches).mockResolvedValue({ items: [], total: 0 })

    renderCard('abc123')

    await waitFor(() => {
      expect(screen.getByTestId('ppsr-card-run-now')).toHaveAttribute(
        'href',
        '/ppsr/search?rego=ABC123',
      )
    })

    expect(ppsrApi.listSearches).toHaveBeenCalledWith(
      expect.objectContaining({ rego: 'ABC123' }),
      expect.any(AbortSignal),
    )
  })
})
