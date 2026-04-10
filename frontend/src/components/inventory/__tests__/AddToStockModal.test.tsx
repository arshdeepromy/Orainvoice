import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockAddToast = vi.fn()
vi.mock('../../ui/Toast', () => ({
  useToast: () => ({ toasts: [], addToast: mockAddToast, dismissToast: vi.fn() }),
  ToastContainer: () => null,
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

import apiClient from '../../../api/client'
import { AddToStockModal } from '../AddToStockModal'

const defaultProps = {
  isOpen: true,
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

function getButton(name: RegExp) {
  return screen.getByRole('button', { name, hidden: true })
}

const sampleParts = [
  { id: 'p1', name: 'Brake Pad Set', part_number: 'BP-100', brand: 'Bosch', part_type: 'part', is_active: true, supplier_id: 'sup-1', supplier_name: 'AutoParts Co' },
  { id: 'p2', name: 'Oil Filter', part_number: 'OF-200', brand: 'Mann', part_type: 'part', is_active: true, supplier_id: null, supplier_name: null },
]

/** Set up GET mocks for catalogue + stock items */
function mockCatalogueAndStock(opts?: { existingIds?: string[] }) {
  const existingIds = opts?.existingIds ?? []
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === '/inventory/stock-items') {
      return Promise.resolve({
        data: { stock_items: existingIds.map((id) => ({ catalogue_item_id: id })) },
      })
    }
    if (url === '/catalogue/parts') {
      return Promise.resolve({ data: { parts: sampleParts } })
    }
    if (url === '/catalogue/fluids') {
      return Promise.resolve({
        data: { products: [{ id: 'f1', product_name: 'Engine Oil 5W-30', brand_name: 'Castrol', fluid_type: 'oil', is_active: true, supplier_id: 'sup-2' }] },
      })
    }
    return Promise.resolve({ data: {} })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
})

/* ------------------------------------------------------------------ */
/*  Category Selector (Step 1) — Req 3.1, 3.2                         */
/* ------------------------------------------------------------------ */

describe('AddToStockModal — CategorySelector', () => {
  it('renders 3 category options: Parts, Tyres, Fluids / Oils', () => {
    mockCatalogueAndStock()
    render(<AddToStockModal {...defaultProps} />)

    expect(getButton(/select parts/i)).toBeInTheDocument()
    expect(getButton(/select tyres/i)).toBeInTheDocument()
    expect(getButton(/select fluids/i)).toBeInTheDocument()
  })

  it('advances to catalogue picker when a category is clicked', async () => {
    const user = userEvent.setup()
    mockCatalogueAndStock()
    render(<AddToStockModal {...defaultProps} />)

    await user.click(getButton(/select parts/i))

    await waitFor(() => {
      expect(screen.getByText(/select a parts item/i)).toBeInTheDocument()
    })
  })
})

/* ------------------------------------------------------------------ */
/*  Catalogue Picker (Step 2) — Req 3.4, 4.4, 4.5                     */
/* ------------------------------------------------------------------ */

describe('AddToStockModal — CataloguePicker', () => {
  async function goToCataloguePicker(user: ReturnType<typeof userEvent.setup>) {
    await user.click(getButton(/select parts/i))
    await waitFor(() => {
      expect(screen.getByText('Brake Pad Set')).toBeInTheDocument()
    })
  }

  it('filters catalogue items by search text', async () => {
    const user = userEvent.setup()
    mockCatalogueAndStock()
    render(<AddToStockModal {...defaultProps} />)

    await goToCataloguePicker(user)

    // Both items visible initially
    expect(screen.getByText('Brake Pad Set')).toBeInTheDocument()
    expect(screen.getByText('Oil Filter')).toBeInTheDocument()

    // Type search query
    const searchInput = screen.getByPlaceholderText(/search parts by name/i)
    await user.type(searchInput, 'Brake')

    // Only matching item visible
    expect(screen.getByText('Brake Pad Set')).toBeInTheDocument()
    expect(screen.queryByText('Oil Filter')).not.toBeInTheDocument()
  })

  it('shows "Already in stock" badge for items that are already stocked', async () => {
    const user = userEvent.setup()
    mockCatalogueAndStock({ existingIds: ['p1'] })
    render(<AddToStockModal {...defaultProps} />)

    await goToCataloguePicker(user)

    // p1 should have the badge and be disabled
    const p1Button = screen.getByRole('button', { name: /brake pad set.*already in stock/i, hidden: true })
    expect(p1Button).toBeDisabled()
    expect(screen.getByText('Already in stock')).toBeInTheDocument()

    // p2 should not be disabled
    const p2Button = screen.getByRole('button', { name: /oil filter$/i, hidden: true })
    expect(p2Button).not.toBeDisabled()
  })

  it('shows empty state message when no catalogue items exist', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/inventory/stock-items') {
        return Promise.resolve({ data: { stock_items: [] } })
      }
      if (url === '/catalogue/parts') {
        return Promise.resolve({ data: { parts: [] } })
      }
      return Promise.resolve({ data: {} })
    })
    render(<AddToStockModal {...defaultProps} />)

    await user.click(getButton(/select parts/i))

    await waitFor(() => {
      expect(screen.getByText(/no active parts items found/i)).toBeInTheDocument()
    })
  })

  it('navigates back to category selection on back button click', async () => {
    const user = userEvent.setup()
    mockCatalogueAndStock()
    render(<AddToStockModal {...defaultProps} />)

    await goToCataloguePicker(user)

    await user.click(getButton(/back to category selection/i))

    await waitFor(() => {
      expect(getButton(/select parts/i)).toBeInTheDocument()
    })
  })
})

/* ------------------------------------------------------------------ */
/*  Stock Details Form (Step 3) — Req 5.2, 5.3, 6.1                   */
/* ------------------------------------------------------------------ */

describe('AddToStockModal — StockDetailsForm', () => {
  async function goToDetailsStep(user: ReturnType<typeof userEvent.setup>) {
    mockCatalogueAndStock()
    render(<AddToStockModal {...defaultProps} />)

    // Step 1 → Step 2
    await user.click(getButton(/select parts/i))
    await waitFor(() => {
      expect(screen.getByText('Brake Pad Set')).toBeInTheDocument()
    })

    // Step 2 → Step 3 (select Brake Pad Set — has supplier)
    await user.click(screen.getByRole('button', { name: /brake pad set$/i, hidden: true }))
    await waitFor(() => {
      expect(screen.getByText(/adding: brake pad set/i)).toBeInTheDocument()
    })
  }

  it('shows validation errors when quantity is empty and reason is not selected', async () => {
    const user = userEvent.setup()
    await goToDetailsStep(user)

    // Click submit without filling anything
    await user.click(getButton(/add to stock/i))

    await waitFor(() => {
      expect(screen.getByText('Quantity must be greater than 0')).toBeInTheDocument()
      expect(screen.getByText('Please select a reason')).toBeInTheDocument()
    })
  })

  it('auto-populates supplier from catalogue item', async () => {
    const user = userEvent.setup()
    await goToDetailsStep(user)

    // Brake Pad Set has supplier_name 'AutoParts Co'
    expect(screen.getByText(/auto-populated from catalogue: autoparts co/i)).toBeInTheDocument()
  })

  it('navigates back to catalogue picker from details step', async () => {
    const user = userEvent.setup()
    await goToDetailsStep(user)

    await user.click(getButton(/back to catalogue picker/i))

    await waitFor(() => {
      expect(screen.getByText('Brake Pad Set')).toBeInTheDocument()
      expect(screen.getByText('Oil Filter')).toBeInTheDocument()
    })
  })
})
