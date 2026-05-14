import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

// Mock apiClient before importing the component
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
  },
}))

// Mock useTenant context
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ refetch: vi.fn() }),
}))

import apiClient from '@/api/client'

// We only test the InventoryTab which is rendered inside OrgSettings
// under the "Inventory" tab. Import the full page and navigate to that tab.
import { OrgSettings } from './OrgSettings'

const mockedGet = vi.mocked(apiClient.get)
const mockedPut = vi.mocked(apiClient.put)

describe('OrgSettings — InventoryTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: GET /org/settings returns auto_expense_on_stock_purchase = true
    mockedGet.mockResolvedValue({ data: { auto_expense_on_stock_purchase: true } })
    mockedPut.mockResolvedValue({ data: {} })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  async function renderInventoryTab() {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <OrgSettings />
      </MemoryRouter>
    )

    // Click the Inventory tab to show the InventoryTab component
    const inventoryTab = await screen.findByRole('tab', { name: /inventory/i })
    await user.click(inventoryTab)

    // Wait for the toggle to appear (after GET resolves)
    await waitFor(() => {
      expect(screen.getByRole('switch')).toBeInTheDocument()
    })

    return { user }
  }

  it('renders the auto-expense toggle with correct label', async () => {
    await renderInventoryTab()

    expect(screen.getByText('Automatically create expense when adding stock')).toBeInTheDocument()
    expect(
      screen.getByText(
        'When enabled, adding stock items or positive adjustments with a purchase price will automatically create an expense entry.'
      )
    ).toBeInTheDocument()
  })

  it('reflects GET response: toggle is ON when setting is true', async () => {
    mockedGet.mockResolvedValue({ data: { auto_expense_on_stock_purchase: true } })

    await renderInventoryTab()

    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('Enabled')).toBeInTheDocument()
  })

  it('reflects GET response: toggle is OFF when setting is false', async () => {
    mockedGet.mockResolvedValue({ data: { auto_expense_on_stock_purchase: false } })

    await renderInventoryTab()

    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('Disabled')).toBeInTheDocument()
  })

  it('defaults to true when setting is absent from response', async () => {
    // Simulate response without the key (existing orgs that haven't toggled)
    mockedGet.mockResolvedValue({ data: {} })

    await renderInventoryTab()

    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('Enabled')).toBeInTheDocument()
  })

  it('clicking toggle changes state from enabled to disabled', async () => {
    mockedGet.mockResolvedValue({ data: { auto_expense_on_stock_purchase: true } })

    const { user } = await renderInventoryTab()

    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'true')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('Disabled')).toBeInTheDocument()
  })

  it('clicking Save calls PUT with correct payload (auto_expense_on_stock_purchase: false)', async () => {
    mockedGet.mockResolvedValue({ data: { auto_expense_on_stock_purchase: true } })

    const { user } = await renderInventoryTab()

    // Toggle off
    const toggle = screen.getByRole('switch')
    await user.click(toggle)

    // Click Save
    const saveButton = screen.getByRole('button', { name: /save inventory settings/i })
    await user.click(saveButton)

    await waitFor(() => {
      expect(mockedPut).toHaveBeenCalledWith('/org/settings', {
        auto_expense_on_stock_purchase: false,
      })
    })
  })

  it('clicking Save calls PUT with correct payload (auto_expense_on_stock_purchase: true)', async () => {
    mockedGet.mockResolvedValue({ data: { auto_expense_on_stock_purchase: false } })

    const { user } = await renderInventoryTab()

    // Toggle on
    const toggle = screen.getByRole('switch')
    await user.click(toggle)

    // Click Save
    const saveButton = screen.getByRole('button', { name: /save inventory settings/i })
    await user.click(saveButton)

    await waitFor(() => {
      expect(mockedPut).toHaveBeenCalledWith('/org/settings', {
        auto_expense_on_stock_purchase: true,
      })
    })
  })
})
