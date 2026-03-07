import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 9.1, 9.2, 9.7, 9.8, 9.9, 9.10, 10.1
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import ProductList from '../pages/inventory/ProductList'
import ProductDetail from '../pages/inventory/ProductDetail'
import CSVImport from '../pages/inventory/CSVImport'
import StockTake from '../pages/inventory/StockTake'
import PricingRules from '../pages/inventory/PricingRules'
import { isBarcodeDetectorSupported, scanBarcode } from '../utils/barcodeScanner'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockProducts = [
  {
    id: 'prod-1', name: 'Brake Pads', sku: 'BRK-001', barcode: '1234567890123',
    category_id: 'cat-1', sale_price: '45.00', stock_quantity: '100',
    is_active: true, unit_of_measure: 'each',
  },
  {
    id: 'prod-2', name: 'Oil Filter', sku: 'OIL-002', barcode: null,
    category_id: null, sale_price: '12.50', stock_quantity: '0',
    is_active: false, unit_of_measure: 'each',
  },
]

const mockCategories = [
  { id: 'cat-1', name: 'Brakes', parent_id: null, display_order: 0 },
]

const mockMovements = [
  {
    id: 'mov-1', product_id: 'prod-1', movement_type: 'sale',
    quantity_change: '-2', resulting_quantity: '98',
    reference_type: 'invoice', reference_id: 'inv-1',
    notes: 'Invoice #001', performed_by: 'user-1',
    created_at: '2024-06-01T10:00:00Z',
  },
]

const mockPricingRules = [
  {
    id: 'rule-1', product_id: 'prod-1', rule_type: 'customer_specific',
    priority: 1, customer_id: null, customer_tag: 'VIP',
    min_quantity: null, max_quantity: null,
    start_date: null, end_date: null,
    price_override: '40.00', discount_percent: null, is_active: true,
  },
]

/* ------------------------------------------------------------------ */
/*  ProductList tests                                                  */
/* ------------------------------------------------------------------ */

describe('ProductList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ProductList />)
    expect(screen.getByRole('status', { name: 'Loading products' })).toBeInTheDocument()
  })

  it('displays products with name, SKU, price, stock qty, status (Req 9.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('product-categories')) {
        return Promise.resolve({ data: { categories: mockCategories, total: 1 } })
      }
      return Promise.resolve({ data: { products: mockProducts, total: 2, page: 1, page_size: 20 } })
    })
    render(<ProductList />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
    expect(screen.getByText('Brake Pads')).toBeInTheDocument()
    expect(screen.getByText('BRK-001')).toBeInTheDocument()
    expect(screen.getByText('$45.00')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('Oil Filter')).toBeInTheDocument()
  })

  it('shows active/inactive status badges', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('product-categories')) {
        return Promise.resolve({ data: { categories: [], total: 0 } })
      }
      return Promise.resolve({ data: { products: mockProducts, total: 2, page: 1, page_size: 20 } })
    })
    render(<ProductList />)
    await screen.findByRole('grid')
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('shows empty state when no products', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('product-categories')) {
        return Promise.resolve({ data: { categories: [], total: 0 } })
      }
      return Promise.resolve({ data: { products: [], total: 0, page: 1, page_size: 20 } })
    })
    render(<ProductList />)
    expect(await screen.findByText('No products yet. Add your first product to get started.')).toBeInTheDocument()
  })

  it('renders search input and category filter', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('product-categories')) {
        return Promise.resolve({ data: { categories: mockCategories, total: 1 } })
      }
      return Promise.resolve({ data: { products: [], total: 0, page: 1, page_size: 20 } })
    })
    render(<ProductList />)
    await screen.findByRole('grid')
    expect(screen.getByLabelText('Search products')).toBeInTheDocument()
    expect(screen.getByLabelText('Category')).toBeInTheDocument()
  })

  it('renders barcode scan button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('product-categories')) {
        return Promise.resolve({ data: { categories: [], total: 0 } })
      }
      return Promise.resolve({ data: { products: [], total: 0, page: 1, page_size: 20 } })
    })
    render(<ProductList />)
    await screen.findByRole('grid')
    expect(screen.getByRole('button', { name: 'Scan barcode' })).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ProductDetail tests                                                */
/* ------------------------------------------------------------------ */

describe('ProductDetail', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner when loading product', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ProductDetail productId="prod-1" />)
    expect(screen.getByRole('status', { name: 'Loading product' })).toBeInTheDocument()
  })

  it('renders create form when no productId', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { categories: [], suppliers: [], total: 0 },
    })
    render(<ProductDetail />)
    expect(screen.getByRole('heading', { name: 'New Product' })).toBeInTheDocument()
    expect(screen.getByLabelText('Product name *')).toBeInTheDocument()
    expect(screen.getByLabelText('Sale price *')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Product' })).toBeInTheDocument()
  })

  it('renders tabs for existing product (Req 9.1, 9.7)', async () => {
    const mockProduct = {
      id: 'prod-1', name: 'Brake Pads', sku: 'BRK-001', barcode: '123',
      category_id: null, description: 'Test', unit_of_measure: 'each',
      sale_price: '45.00', cost_price: '20.00', tax_applicable: true,
      tax_rate_override: null, stock_quantity: '100',
      low_stock_threshold: '10', reorder_quantity: '50',
      allow_backorder: false, supplier_id: null, supplier_sku: null,
      images: [], is_active: true,
    }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/v2/products/prod-1')) return Promise.resolve({ data: mockProduct })
      if (url.includes('product-categories')) return Promise.resolve({ data: { categories: [] } })
      if (url.includes('suppliers')) return Promise.resolve({ data: { suppliers: [] } })
      if (url.includes('stock-movements')) return Promise.resolve({ data: { movements: mockMovements } })
      if (url.includes('pricing-rules')) return Promise.resolve({ data: { rules: [] } })
      return Promise.resolve({ data: {} })
    })
    render(<ProductDetail productId="prod-1" />)
    await screen.findByRole('heading', { name: 'Brake Pads' })
    expect(screen.getByRole('tab', { name: 'Details' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Stock History' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Pricing Rules' })).toBeInTheDocument()
  })

  it('validates required fields on save', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { categories: [], suppliers: [], total: 0 },
    })
    render(<ProductDetail />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Create Product' }))
    expect(await screen.findByText('Product name is required.')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  CSVImport tests                                                    */
/* ------------------------------------------------------------------ */

describe('CSVImport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders upload step initially (Req 9.9)', () => {
    render(<CSVImport />)
    expect(screen.getByText('1. Upload')).toBeInTheDocument()
    expect(screen.getByText('2. Preview & Map')).toBeInTheDocument()
    expect(screen.getByText('3. Results')).toBeInTheDocument()
    expect(screen.getByLabelText('Upload CSV file')).toBeInTheDocument()
  })

  it('parses CSV and shows preview step with field mapping', async () => {
    render(<CSVImport />)
    const user = userEvent.setup()

    const csvContent = 'Name,SKU,Price\nBrake Pads,BRK-001,45.00\nOil Filter,OIL-002,12.50'
    const file = new File([csvContent], 'products.csv', { type: 'text/csv' })

    const input = screen.getByLabelText('Upload CSV file')
    await user.upload(input, file)

    // Should move to preview step
    await waitFor(() => {
      expect(screen.getByText('products.csv')).toBeInTheDocument()
    })
    expect(screen.getByText('2 rows, 3 columns')).toBeInTheDocument()
    // Field mapping should be visible (headers appear in mapping + table, so use getAllByText)
    expect(screen.getAllByText('Name').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Field Mapping')).toBeInTheDocument()
  })

  it('shows import results after successful import', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { imported_count: 2, skipped_count: 0, error_count: 0, errors: [] },
    })

    render(<CSVImport />)
    const user = userEvent.setup()

    const csvContent = 'Name,SKU,Price\nBrake Pads,BRK-001,45.00\nOil Filter,OIL-002,12.50'
    const file = new File([csvContent], 'products.csv', { type: 'text/csv' })

    const input = screen.getByLabelText('Upload CSV file')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText('products.csv')).toBeInTheDocument()
    })

    // Click import button
    const importBtn = screen.getByRole('button', { name: /Import.*Products/i })
    await user.click(importBtn)

    await waitFor(() => {
      expect(screen.getByText('Import Complete')).toBeInTheDocument()
    })
    expect(screen.getByText('2')).toBeInTheDocument() // imported count
  })
})

/* ------------------------------------------------------------------ */
/*  StockTake tests                                                    */
/* ------------------------------------------------------------------ */

describe('StockTake', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<StockTake />)
    expect(screen.getByRole('status', { name: 'Loading products for stocktake' })).toBeInTheDocument()
  })

  it('renders product list with counted quantity inputs (Req 9.8)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { products: mockProducts, total: 2, page: 1, page_size: 1000 },
    })
    render(<StockTake />)
    await screen.findByRole('grid')
    expect(screen.getByText('Brake Pads')).toBeInTheDocument()
    expect(screen.getByLabelText('Counted quantity for Brake Pads')).toBeInTheDocument()
    expect(screen.getByLabelText('Counted quantity for Oil Filter')).toBeInTheDocument()
  })

  it('shows variance when counted quantity is entered', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { products: mockProducts, total: 2, page: 1, page_size: 1000 },
    })
    render(<StockTake />)
    await screen.findByRole('grid')

    const user = userEvent.setup()
    const input = screen.getByLabelText('Counted quantity for Brake Pads')
    await user.type(input, '95')

    // Variance should be -5 (95 - 100)
    expect(screen.getByText('-5')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  PricingRules tests                                                 */
/* ------------------------------------------------------------------ */

describe('PricingRules', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<PricingRules />)
    expect(screen.getByRole('status', { name: 'Loading pricing rules' })).toBeInTheDocument()
  })

  it('displays rules sorted by priority (Req 10.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('pricing-rules')) {
        return Promise.resolve({ data: { rules: mockPricingRules } })
      }
      return Promise.resolve({ data: { products: mockProducts, total: 2, page: 1, page_size: 500 } })
    })
    render(<PricingRules />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(2) // header + 1 rule
    expect(screen.getByText('customer specific')).toBeInTheDocument()
    expect(screen.getByText('$40.00')).toBeInTheDocument()
  })

  it('opens create modal with form fields', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('pricing-rules')) {
        return Promise.resolve({ data: { rules: [] } })
      }
      return Promise.resolve({ data: { products: [], total: 0, page: 1, page_size: 500 } })
    })
    render(<PricingRules />)
    await screen.findByRole('grid')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Rule' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('New Pricing Rule')).toBeInTheDocument()
    expect(screen.getByLabelText('Rule type *')).toBeInTheDocument()
    expect(screen.getByLabelText('Priority')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  Barcode Scanner tests                                              */
/* ------------------------------------------------------------------ */

describe('barcodeScanner', () => {
  it('isBarcodeDetectorSupported returns false when not available', () => {
    expect(isBarcodeDetectorSupported()).toBe(false)
  })

  it('isBarcodeDetectorSupported returns true when BarcodeDetector exists', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(window as any).BarcodeDetector = class {}
    expect(isBarcodeDetectorSupported()).toBe(true)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).BarcodeDetector
  })

  it('scanBarcode returns empty array when no barcodes detected', async () => {
    const canvas = document.createElement('canvas')
    canvas.width = 100
    canvas.height = 100
    const results = await scanBarcode(canvas)
    expect(results).toEqual([])
  })
})
