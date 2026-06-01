/**
 * Unit tests for PpsrResultPanel.
 *
 * Validates the four scenarios called out in the spec task D3:
 *   1. match='Y'    → "Money Owing" headline rendered
 *   2. match='N'    → green banner colour class applied
 *   3. cached=true  → cached badge appears
 *   4. ppsr_details non-empty → financing-statements table renders
 *
 * **Validates: PPSR module spec task D3**
 */

import { render, screen, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

// Stub LocaleContext so the component can resolve a locale without
// needing the full app provider tree.
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

import { PpsrResultPanel } from '../PpsrResultPanel'
import type { PpsrSearchResult } from '@/api/ppsr'

function makeResult(overrides: Partial<PpsrSearchResult> = {}): PpsrSearchResult {
  return {
    search_id: '00000000-0000-0000-0000-000000000abc',
    rego: 'ABC123',
    cached: false,
    cached_at: null,
    source_search_id: null,
    match: 'N',
    match_description: 'No security interests registered',
    statement_count: 0,
    ppsr_details: [],
    ownership_history: null,
    current_owner: null,
    warnings: [],
    basic: null,
    not_found: false,
    charges_cents: null,
    carjam_request_id: null,
    ...overrides,
  }
}

describe('PpsrResultPanel', () => {
  it('renders "Money Owing" headline when match=Y', () => {
    render(
      <PpsrResultPanel
        result={makeResult({
          match: 'Y',
          match_description: 'Active security interest registered',
          statement_count: 1,
        })}
      />,
    )
    expect(screen.getByText(/Money Owing/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Active security interest registered/i),
    ).toBeInTheDocument()
  })

  it('applies the green banner classes when match=N', () => {
    render(
      <PpsrResultPanel
        result={makeResult({
          match: 'N',
          match_description: 'No security interests on file',
        })}
      />,
    )
    const panel = screen.getByTestId('ppsr-result-panel')
    const banner = within(panel).getByRole('status')
    // Light + dark green palette per design.md §6.0
    expect(banner.className).toMatch(/bg-emerald-50/)
    expect(banner.className).toMatch(/dark:bg-emerald-900/)
    // Default green-banner headline for match=N
    expect(within(banner).getByText(/No money owing/i)).toBeInTheDocument()
    // Colour-blindness glyph is rendered for the green state
    expect(within(banner).getByLabelText(/Green/i)).toHaveTextContent('🟢')
  })

  it('shows the cached badge when result.cached is true', () => {
    render(
      <PpsrResultPanel
        result={makeResult({
          cached: true,
          cached_at: '2026-06-01T03:32:00Z',
        })}
        onForceRefresh={() => {}}
      />,
    )
    expect(screen.getByTestId('ppsr-cached-badge')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Force refresh/i }),
    ).toBeInTheDocument()
  })

  it('does not show the cached badge when result.cached is false', () => {
    render(<PpsrResultPanel result={makeResult({ cached: false })} />)
    expect(screen.queryByTestId('ppsr-cached-badge')).not.toBeInTheDocument()
  })

  it('renders the financing-statements table when ppsr_details is non-empty', () => {
    render(
      <PpsrResultPanel
        result={makeResult({
          match: 'Y',
          statement_count: 2,
          ppsr_details: [
            {
              secured_party_name: 'Heartland Bank',
              collateral_description: 'Motor vehicle finance',
              registration_date: '2024-03-12',
              status: 'Active',
            },
            {
              secured_party_name: 'GE Money',
              collateral_description: 'Consumer loan',
              registration_date: '2023-08-04',
              status: 'Active',
            },
          ],
        })}
      />,
    )
    const table = screen.getByTestId('ppsr-financing-statements')
    expect(within(table).getByText(/Financing statements/i)).toBeInTheDocument()
    expect(within(table).getByText(/Heartland Bank/)).toBeInTheDocument()
    expect(within(table).getByText(/GE Money/)).toBeInTheDocument()
    expect(within(table).getByText(/Motor vehicle finance/)).toBeInTheDocument()
  })

  it('renders the basic vehicle card when basic is non-null', () => {
    render(
      <PpsrResultPanel
        result={makeResult({
          basic: {
            year: '2018',
            make: 'Toyota',
            model: 'Hilux',
            colour: 'Silver',
          },
        })}
      />,
    )
    const card = screen.getByTestId('ppsr-basic-card')
    expect(within(card).getByText(/2018 Toyota Hilux/)).toBeInTheDocument()
    expect(within(card).getByText(/Silver/)).toBeInTheDocument()
  })

  it('renders the charges footer with NZD currency formatting', () => {
    render(
      <PpsrResultPanel result={makeResult({ charges_cents: 50 })} />,
    )
    const footer = screen.getByTestId('ppsr-charges-footer')
    // Match either the standard "$0.50" or "NZ$0.50" format depending on
    // the runtime ICU locale data.
    expect(footer.textContent ?? '').toMatch(/0\.50/)
  })

  it('omits the charges footer when charges_cents is null', () => {
    render(<PpsrResultPanel result={makeResult({ charges_cents: null })} />)
    expect(screen.queryByTestId('ppsr-charges-footer')).not.toBeInTheDocument()
  })

  it('wires up the action callbacks', () => {
    const onExport = vi.fn()
    const onLink = vi.fn()
    const onNew = vi.fn()
    render(
      <PpsrResultPanel
        result={makeResult()}
        onExport={onExport}
        onLink={onLink}
        onNew={onNew}
      />,
    )
    screen.getByRole('button', { name: /Export PDF/i }).click()
    screen.getByRole('button', { name: /Save to vehicle file/i }).click()
    screen.getByRole('button', { name: /New search/i }).click()
    expect(onExport).toHaveBeenCalledTimes(1)
    expect(onLink).toHaveBeenCalledTimes(1)
    expect(onNew).toHaveBeenCalledTimes(1)
  })
})
