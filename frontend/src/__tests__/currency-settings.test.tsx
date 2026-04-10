import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/**
 * Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7
 */

// Mock contexts
vi.mock('@/hooks/useModuleGuard', () => ({
  useModuleGuard: () => ({
    isAllowed: true,
    isLoading: false,
    toasts: [],
    dismissToast: vi.fn(),
  }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFlag: () => true,
  useFeatureFlags: () => ({ flags: {}, isLoading: false, error: null, refetch: vi.fn() }),
}))

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: (_key: string, fallback: string) => fallback,
}))

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import CurrencySettings from '../pages/settings/CurrencySettings'

const mockCurrencies = [
  { id: 'c1', org_id: 'org-1', currency_code: 'NZD', is_base: true, enabled: true },
  { id: 'c2', org_id: 'org-1', currency_code: 'USD', is_base: false, enabled: true },
  { id: 'c3', org_id: 'org-1', currency_code: 'AUD', is_base: false, enabled: true },
]

const mockRates = [
  {
    id: 'r1', base_currency: 'NZD', target_currency: 'USD',
    rate: '0.61000000', source: 'manual', effective_date: '2025-01-15',
    created_at: '2025-01-15T10:00:00Z',
  },
]

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('CurrencySettings', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockImplementation((url: string) => {
        if (url.includes('/rates/history')) return Promise.resolve({ data: [] })
        if (url.includes('/rates')) return Promise.resolve({ data: mockRates })
        if (url.includes('/provider')) return Promise.resolve({ data: { provider: 'Open Exchange Rates', update_frequency: 'Daily', last_sync: '2025-01-15T10:00:00Z', status: 'active' } })
        return Promise.resolve({ data: mockCurrencies })
      })
  }

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    renderWithRouter(<CurrencySettings />)
    expect(screen.getByRole('status', { name: 'Loading currency settings' })).toBeInTheDocument()
  })

  it('displays base currency prominently (Req 13.1)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    expect(await screen.findByTestId('base-currency-code')).toHaveTextContent('NZD')
    expect(screen.getByTestId('base-currency-display')).toBeInTheDocument()
  })

  it('displays enabled currencies with format info (Req 13.1)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')
    expect(screen.getByTestId('currency-row-NZD')).toBeInTheDocument()
    expect(screen.getByTestId('currency-row-USD')).toBeInTheDocument()
    expect(screen.getByTestId('currency-row-AUD')).toBeInTheDocument()
  })

  it('shows sample formatted amounts per currency (Req 13.7)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('sample-format-NZD')
    expect(screen.getByTestId('sample-format-NZD')).toHaveTextContent('$1,234.57')
    expect(screen.getByTestId('sample-format-USD')).toHaveTextContent('$1,234.57')
  })

  it('shows missing rate warning for currencies without rates (Req 13.6)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    // AUD has no rate in mockRates — wait for the warning badge to appear
    const audBadge = await screen.findByTestId('missing-rate-AUD')
    expect(audBadge).toBeInTheDocument()
    // The alert banner should mention AUD
    const alerts = screen.getAllByRole('alert')
    const missingAlert = alerts.find((a) => a.textContent?.includes('AUD'))
    expect(missingAlert).toBeTruthy()
  })

  it('opens currency search panel with ISO 4217 list (Req 13.2)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')

    const user = userEvent.setup()
    await user.click(screen.getByTestId('open-currency-search'))
    expect(screen.getByTestId('currency-search-panel')).toBeInTheDocument()
    expect(screen.getByTestId('currency-search-input')).toBeInTheDocument()
  })

  it('filters currencies in search panel', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')

    const user = userEvent.setup()
    await user.click(screen.getByTestId('open-currency-search'))
    await user.type(screen.getByTestId('currency-search-input'), 'Euro')

    expect(screen.getByTestId('currency-option-EUR')).toBeInTheDocument()
  })

  it('enables a currency from search panel', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new' } })
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')

    const user = userEvent.setup()
    await user.click(screen.getByTestId('open-currency-search'))
    await user.type(screen.getByTestId('currency-search-input'), 'GBP')
    await user.click(screen.getByTestId('enable-currency-GBP'))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/currencies/enable', {
      currency_code: 'GBP',
      is_base: false,
    })
  })

  it('shows exchange rates tab with rate data (Req 13.3)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')

    const user = userEvent.setup()
    // Click the Exchange Rates tab
    await user.click(screen.getByRole('tab', { name: 'Exchange Rates' }))
    expect(screen.getByTestId('rate-row-NZD-USD')).toBeInTheDocument()
  })

  it('opens manual rate form (Req 13.3)', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Exchange Rates' }))
    await user.click(screen.getByTestId('open-rate-form'))
    expect(screen.getByTestId('manual-rate-form')).toBeInTheDocument()
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    renderWithRouter(<CurrencySettings />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Failed to load currency settings')
  })

  it('has 44px minimum touch targets on interactive elements', async () => {
    setupMocks()
    renderWithRouter(<CurrencySettings />)
    await screen.findByTestId('currency-row-NZD')

    const refreshBtn = screen.getByTestId('currency-refresh-btn')
    expect(refreshBtn.style.minHeight).toBe('44px')
    expect(refreshBtn.style.minWidth).toBe('44px')
  })
})
