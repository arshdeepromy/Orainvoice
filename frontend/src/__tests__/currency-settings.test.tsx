import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — MultiCurrency Module, Tasks 40.12, 40.13
 */

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
  {
    id: 'r2', base_currency: 'NZD', target_currency: 'AUD',
    rate: '0.92000000', source: 'openexchangerates', effective_date: '2025-01-15',
    created_at: '2025-01-15T10:00:00Z',
  },
]

describe('CurrencySettings', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockImplementation((url: string) => {
        if (url.includes('/rates')) return Promise.resolve({ data: mockRates })
        return Promise.resolve({ data: mockCurrencies })
      })
  }

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<CurrencySettings />)
    expect(screen.getByRole('status', { name: 'Loading currency settings' })).toBeInTheDocument()
  })

  it('displays enabled currencies in a table', async () => {
    setupMocks()
    render(<CurrencySettings />)

    const table = await screen.findByRole('grid', { name: 'Enabled currencies list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4) // header + 3 currencies
    expect(screen.getByTestId('currency-row-NZD')).toHaveTextContent('NZD')
    expect(screen.getByTestId('currency-row-NZD')).toHaveTextContent('✓ Base')
    expect(screen.getByTestId('currency-row-USD')).toHaveTextContent('USD')
  })

  it('displays exchange rates in a table', async () => {
    setupMocks()
    render(<CurrencySettings />)

    const table = await screen.findByRole('grid', { name: 'Exchange rates list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 rates
    expect(screen.getByTestId('rate-row-NZD-USD')).toHaveTextContent('0.61000000')
  })

  it('shows enable currency form when button clicked', async () => {
    setupMocks()
    render(<CurrencySettings />)
    await screen.findByRole('grid', { name: 'Enabled currencies list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Enable currency' }))

    expect(screen.getByRole('form', { name: 'Enable currency form' })).toBeInTheDocument()
  })

  it('submits enable currency form', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new' } })
    render(<CurrencySettings />)
    await screen.findByRole('grid', { name: 'Enabled currencies list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Enable currency' }))
    await user.type(screen.getByLabelText('Currency Code'), 'GBP')
    await user.click(screen.getByRole('button', { name: 'Save currency' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/currencies/enable', expect.objectContaining({
      currency_code: 'GBP',
      is_base: false,
    }))
  })

  it('shows manual rate form when button clicked', async () => {
    setupMocks()
    render(<CurrencySettings />)
    await screen.findByRole('grid', { name: 'Exchange rates list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add manual rate' }))

    expect(screen.getByRole('form', { name: 'Set exchange rate form' })).toBeInTheDocument()
  })

  it('submits manual rate form', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new-rate' } })
    render(<CurrencySettings />)
    await screen.findByRole('grid', { name: 'Exchange rates list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add manual rate' }))
    await user.type(screen.getByLabelText('Base Currency'), 'NZD')
    await user.type(screen.getByLabelText('Target Currency'), 'EUR')
    await user.type(screen.getByLabelText('Rate'), '0.55')

    await user.click(screen.getByRole('button', { name: 'Save rate' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/currencies/rates', expect.objectContaining({
      base_currency: 'NZD',
      target_currency: 'EUR',
      rate: 0.55,
    }))
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<CurrencySettings />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load currency settings')
  })

  it('shows empty state when no currencies', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })
    render(<CurrencySettings />)
    expect(await screen.findByText('No currencies enabled')).toBeInTheDocument()
  })

  it('refresh button calls provider endpoint', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })
    render(<CurrencySettings />)
    await screen.findByRole('grid', { name: 'Enabled currencies list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Refresh rates from provider' }))

    expect(apiClient.post).toHaveBeenCalledWith(
      expect.stringContaining('/api/v2/currencies/rates/refresh'),
    )
  })
})
