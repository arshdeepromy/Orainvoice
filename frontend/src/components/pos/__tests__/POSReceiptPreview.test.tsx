import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import type { ReceiptData } from '../../../utils/escpos'
import POSReceiptPreview from '../POSReceiptPreview'

/**
 * Validates: Requirements 5.2, 5.3
 * Unit tests for POSReceiptPreview component
 */

function makeReceiptData(overrides: Partial<ReceiptData> = {}): ReceiptData {
  return {
    orgName: 'Test Business Ltd',
    orgAddress: '123 Main Street, Auckland',
    orgPhone: '09-555-1234',
    gstNumber: '123-456-789',
    receiptNumber: 'INV-0042',
    date: '15/06/2025',
    customerName: 'Jane Smith',
    items: [
      { name: 'Brake Pads', quantity: 2, unitPrice: 45.0, total: 90.0 },
      { name: 'Oil Filter', quantity: 1, unitPrice: 25.5, total: 25.5 },
    ],
    subtotal: 115.5,
    taxLabel: 'GST (15%)',
    taxAmount: 17.33,
    total: 132.83,
    paymentMethod: 'card',
    amountPaid: 100.0,
    balanceDue: 32.83,
    footer: 'Thanks for visiting!',
    ...overrides,
  }
}

describe('POSReceiptPreview', () => {
  it('renders with correct maxWidth for 80mm paper (72mm)', () => {
    const { container } = render(
      <POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />,
    )
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper.style.maxWidth).toBe('72mm')
  })

  it('renders with correct maxWidth for 58mm paper (48mm)', () => {
    const { container } = render(
      <POSReceiptPreview receiptData={makeReceiptData()} paperWidth={58} />,
    )
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper.style.maxWidth).toBe('48mm')
  })

  it('uses monospace font family (Courier New)', () => {
    const { container } = render(
      <POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />,
    )
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper.style.fontFamily).toBe('"Courier New", monospace')
  })

  it('displays org header (name, address, phone)', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('Test Business Ltd')).toBeInTheDocument()
    expect(screen.getByText('123 Main Street, Auckland')).toBeInTheDocument()
    expect(screen.getByText('09-555-1234')).toBeInTheDocument()
  })

  it('displays GST number when present', () => {
    render(
      <POSReceiptPreview receiptData={makeReceiptData({ gstNumber: '999-888-777' })} paperWidth={80} />,
    )
    expect(screen.getByText('GST: 999-888-777')).toBeInTheDocument()
  })

  it('displays receipt number and date', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('INV-0042')).toBeInTheDocument()
    expect(screen.getByText('15/06/2025')).toBeInTheDocument()
  })

  it('displays customer name when present', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('Jane Smith')).toBeInTheDocument()
  })

  it('displays line items with quantity, price, and total', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('Brake Pads')).toBeInTheDocument()
    expect(screen.getByText('Oil Filter')).toBeInTheDocument()
    // quantity x price
    expect(screen.getByText('2 x $45.00')).toBeInTheDocument()
    expect(screen.getByText('1 x $25.50')).toBeInTheDocument()
    // totals
    expect(screen.getByText('$90.00')).toBeInTheDocument()
    expect(screen.getByText('$25.50')).toBeInTheDocument()
  })

  it('displays subtotal, tax, and total', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('Subtotal:')).toBeInTheDocument()
    expect(screen.getByText('$115.50')).toBeInTheDocument()
    expect(screen.getByText('GST (15%)')).toBeInTheDocument()
    expect(screen.getByText('$17.33')).toBeInTheDocument()
    expect(screen.getByText('TOTAL:')).toBeInTheDocument()
    expect(screen.getByText('$132.83')).toBeInTheDocument()
  })

  it('displays payment method', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('CARD')).toBeInTheDocument()
  })

  it('displays balance due in bold when > 0', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData({ balanceDue: 32.83 })} paperWidth={80} />)
    const label = screen.getByText('BALANCE DUE:')
    const row = label.closest('div')
    expect(row?.className).toContain('font-bold')
  })

  it('displays footer message', () => {
    render(<POSReceiptPreview receiptData={makeReceiptData()} paperWidth={80} />)
    expect(screen.getByText('Thanks for visiting!')).toBeInTheDocument()
  })

  it('does not display customer line when customerName is undefined', () => {
    render(
      <POSReceiptPreview receiptData={makeReceiptData({ customerName: undefined })} paperWidth={80} />,
    )
    expect(screen.queryByText('Customer:')).not.toBeInTheDocument()
  })

  it('does not display balance due when balanceDue is 0', () => {
    render(
      <POSReceiptPreview receiptData={makeReceiptData({ balanceDue: 0 })} paperWidth={80} />,
    )
    expect(screen.queryByText('BALANCE DUE:')).not.toBeInTheDocument()
  })
})
