/**
 * Smoke tests for PPSRSearchPage.
 *
 * Covers the three baseline expectations called out in spec task D2:
 *   1. The form renders (rego input + submit button).
 *   2. The QuotaStrip renders the counter pulled from `ppsrApi.getQuota`.
 *   3. The submit button is disabled when quota.used >= quota.included.
 *
 * Mocks `@/api/ppsr` so no network calls are made.
 *
 * **Validates: PPSR module spec task D2 / Requirement R8.**
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Stub LocaleContext (consumed transitively via PpsrResultPanel inside
// the history-table drawer).
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
  const search = vi.fn()
  const listSearches = vi.fn()
  const getSearch = vi.fn()
  const exportPdf = vi.fn()
  const forgetSearch = vi.fn()
  const linkVehicle = vi.fn()
  const getQuota = vi.fn()
  const ppsrApi = {
    search,
    listSearches,
    getSearch,
    exportPdf,
    forgetSearch,
    linkVehicle,
    getQuota,
  }
  return {
    ppsrApi,
    search,
    listSearches,
    getSearch,
    exportPdf,
    forgetSearch,
    linkVehicle,
    getQuota,
    default: ppsrApi,
  }
})

import { ppsrApi } from '@/api/ppsr'
import { PPSRSearchPage } from '../PPSRSearchPage'

// ===========================================================================
// Helpers
// ===========================================================================

function renderPage(initialEntry = '/ppsr/search') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <PPSRSearchPage />
    </MemoryRouter>,
  )
}

// ===========================================================================
// Tests
// ===========================================================================

describe('PPSRSearchPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(ppsrApi.listSearches as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
    })
  })

  it('renders the page header, quota strip, and search form', async () => {
    ;(ppsrApi.getQuota as ReturnType<typeof vi.fn>).mockResolvedValue({
      used: 7,
      included: 50,
      hidden_plate_used: 0,
      hidden_plate_included: 0,
      resets_at: '2026-07-01T00:00:00Z',
    })

    renderPage()

    // Page header
    expect(
      screen.getByRole('heading', { level: 1, name: /PPSR Vehicle Check/i }),
    ).toBeInTheDocument()

    // Quota strip — wait for the async fetch to populate.
    await waitFor(() => {
      expect(ppsrApi.getQuota).toHaveBeenCalled()
    })
    const counter = await screen.findByTestId('ppsr-quota-counter')
    expect(counter).toHaveTextContent('7')
    expect(counter).toHaveTextContent('50')

    // Search form is mounted.
    expect(screen.getByTestId('ppsr-search-form')).toBeInTheDocument()
    expect(screen.getByTestId('ppsr-rego-input')).toBeInTheDocument()
    expect(screen.getByTestId('ppsr-submit-button')).toBeInTheDocument()
  })

  it('disables the submit button when quota is exhausted', async () => {
    ;(ppsrApi.getQuota as ReturnType<typeof vi.fn>).mockResolvedValue({
      used: 50,
      included: 50,
      hidden_plate_used: 0,
      hidden_plate_included: 0,
      resets_at: '2026-07-01T00:00:00Z',
    })

    renderPage()

    // Wait for the quota fetch to land — submit becomes disabled when
    // the page learns the quota is exhausted.
    await waitFor(() => {
      const button = screen.getByTestId('ppsr-submit-button') as HTMLButtonElement
      expect(button.disabled).toBe(true)
    })

    // The page also surfaces an explanatory note alongside the button.
    expect(
      screen.getByText(/PPSR quota exhausted for this month/i),
    ).toBeInTheDocument()
  })

  it('pre-populates the rego input from the ?rego= query string', async () => {
    ;(ppsrApi.getQuota as ReturnType<typeof vi.fn>).mockResolvedValue({
      used: 0,
      included: 50,
      hidden_plate_used: 0,
      hidden_plate_included: 0,
      resets_at: null,
    })

    renderPage('/ppsr/search?rego=abc123')

    const input = screen.getByTestId('ppsr-rego-input') as HTMLInputElement
    // Rego is normalised to uppercase when seeded from the query string.
    await waitFor(() => {
      expect(input.value).toBe('ABC123')
    })
  })

  it('renders the owner-lookup checkboxes as disabled (CarJam config gating)', async () => {
    ;(ppsrApi.getQuota as ReturnType<typeof vi.fn>).mockResolvedValue({
      used: 0,
      included: 50,
      hidden_plate_used: 0,
      hidden_plate_included: 0,
      resets_at: null,
    })

    renderPage()

    // Phase 1 fallback: ppsr_owner_lookups_enabled defaults to false until
    // an org-scoped CarJam config endpoint exists.
    const currentOwner = (await screen.findByTestId(
      'ppsr-include-current-owner',
    )) as HTMLInputElement
    expect(currentOwner.disabled).toBe(true)

    const ownershipHistory = screen.getByTestId(
      'ppsr-include-ownership-history',
    ) as HTMLInputElement
    expect(ownershipHistory.disabled).toBe(true)
  })
})
