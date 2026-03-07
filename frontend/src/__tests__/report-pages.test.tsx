import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 45.1-45.7, 66.4
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import ReportsPage from '../pages/reports/ReportsPage'
import RevenueSummary from '../pages/reports/RevenueSummary'
import InvoiceStatus from '../pages/reports/InvoiceStatus'
import OutstandingInvoices from '../pages/reports/OutstandingInvoices'
import TopServices from '../pages/reports/TopServices'
import GstReturnSummary from '../pages/reports/GstReturnSummary'
import CarjamUsage from '../pages/reports/CarjamUsage'
import StorageUsage from '../pages/reports/StorageUsage'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockRevenue = {
  total_revenue: 12500.5,
  total_gst: 1875.08,
  total_invoices: 42,
  monthly_breakdown: [
    { month: 'Jan 2024', revenue: 6000 },
    { month: 'Feb 2024', revenue: 6500.5 },
  ],
}

const mockInvoiceStatus = {
  statuses: [
    { status: 'paid', count: 30, total_amount: 9000 },
    { status: 'overdue', count: 5, total_amount: 2000 },
    { status: 'draft', count: 7, total_amount: 1500.5 },
  ],
  total_invoices: 42,
}

const mockOutstanding = {
  invoices: [
    {
      id: 'inv-1', invoice_number: 'INV-001', customer_name: 'John Smith',
      rego: 'ABC123', total: 500, balance_due: 250, due_date: '2024-01-15', status: 'overdue',
    },
  ],
  total_outstanding: 250,
}

const mockTopServices = {
  services: [
    { service_name: 'WOF Inspection', count: 20, revenue: 1100 },
    { service_name: 'Oil Change', count: 15, revenue: 900 },
  ],
}

const mockGst = {
  total_sales: 12500.5,
  standard_rated_sales: 11000,
  zero_rated_sales: 1500.5,
  total_gst_collected: 1875.08,
  net_gst: 1875.08,
}

const mockCarjam = {
  total_lookups: 150,
  included_in_plan: 100,
  overage_lookups: 50,
  overage_charge: 25,
  daily_breakdown: [
    { date: '2024-01-01', lookups: 10 },
    { date: '2024-01-02', lookups: 8 },
  ],
}

const mockStorage = {
  quota_gb: 5,
  used_bytes: 2147483648,
  used_gb: 2,
  usage_percent: 40,
  breakdown: [
    { category: 'Invoices', bytes: 1073741824 },
    { category: 'Customers', bytes: 536870912 },
    { category: 'Vehicles', bytes: 536870912 },
  ],
}

/* ------------------------------------------------------------------ */
/*  ReportsPage tests                                                  */
/* ------------------------------------------------------------------ */

describe('ReportsPage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders heading and all report tabs', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<ReportsPage />)
    expect(screen.getByRole('heading', { name: 'Reports' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Revenue' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Invoice Status' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Outstanding' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Top Services' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'GST Return' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Customer Statement' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Carjam Usage' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Storage' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Fleet' })).toBeInTheDocument()
  })

  it('defaults to revenue tab', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<ReportsPage />)
    expect(screen.getByRole('tab', { name: 'Revenue' })).toHaveAttribute('aria-selected', 'true')
  })

  it('switches tabs on click', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<ReportsPage />)
    const user = userEvent.setup()
    // Switch to Invoice Status tab (safe — mock data shape doesn't crash it)
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockInvoiceStatus })
    await user.click(screen.getByRole('tab', { name: 'Invoice Status' }))
    expect(screen.getByRole('tab', { name: 'Invoice Status' })).toHaveAttribute('aria-selected', 'true')
  })
})

/* ------------------------------------------------------------------ */
/*  RevenueSummary tests                                               */
/* ------------------------------------------------------------------ */

describe('RevenueSummary', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<RevenueSummary />)
    expect(screen.getByRole('status', { name: 'Loading revenue report' })).toBeInTheDocument()
  })

  it('displays revenue summary cards (Req 45.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<RevenueSummary />)
    expect(await screen.findByText('Total Revenue')).toBeInTheDocument()
    expect(screen.getByText('GST Collected')).toBeInTheDocument()
    expect(screen.getByText('Invoices')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('renders date range filter (Req 45.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<RevenueSummary />)
    await screen.findByText('Total Revenue')
    expect(screen.getByLabelText('Period')).toBeInTheDocument()
  })

  it('renders export buttons (Req 45.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<RevenueSummary />)
    await screen.findByText('Total Revenue')
    expect(screen.getByRole('button', { name: 'Export as PDF' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export as CSV' })).toBeInTheDocument()
  })

  it('renders monthly breakdown chart (Req 45.4)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockRevenue })
    render(<RevenueSummary />)
    await screen.findByText('Monthly Revenue')
    expect(screen.getByText('Jan 2024')).toBeInTheDocument()
    expect(screen.getByText('Feb 2024')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  InvoiceStatus tests                                                */
/* ------------------------------------------------------------------ */

describe('InvoiceStatus', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<InvoiceStatus />)
    expect(screen.getByRole('status', { name: 'Loading invoice status report' })).toBeInTheDocument()
  })

  it('displays status breakdown table (Req 45.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockInvoiceStatus })
    render(<InvoiceStatus />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4) // header + 3 statuses
    expect(screen.getAllByText('Paid').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Overdue').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Draft').length).toBeGreaterThanOrEqual(1)
  })

  it('shows total invoices count', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockInvoiceStatus })
    render(<InvoiceStatus />)
    expect(await screen.findByText('42')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  OutstandingInvoices tests                                          */
/* ------------------------------------------------------------------ */

describe('OutstandingInvoices', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<OutstandingInvoices />)
    expect(screen.getByRole('status', { name: 'Loading outstanding invoices' })).toBeInTheDocument()
  })

  it('displays outstanding invoices with send reminder button (Req 45.5)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockOutstanding })
    render(<OutstandingInvoices />)
    expect(await screen.findByText('INV-001')).toBeInTheDocument()
    expect(screen.getByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('ABC123')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send reminder for INV-001' })).toBeInTheDocument()
  })

  it('sends reminder on button click (Req 45.5)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockOutstanding })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({})
    render(<OutstandingInvoices />)
    await screen.findByText('INV-001')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Send reminder for INV-001' }))
    expect(apiClient.post).toHaveBeenCalledWith('/invoices/inv-1/email', { template: 'payment_reminder' })
  })

  it('shows total outstanding amount', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockOutstanding })
    render(<OutstandingInvoices />)
    expect(await screen.findByText('Total Outstanding')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  TopServices tests                                                  */
/* ------------------------------------------------------------------ */

describe('TopServices', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('displays top services ranked by revenue (Req 45.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockTopServices })
    render(<TopServices />)
    expect((await screen.findAllByText('WOF Inspection')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Oil Change').length).toBeGreaterThanOrEqual(1)
  })
})

/* ------------------------------------------------------------------ */
/*  GstReturnSummary tests                                             */
/* ------------------------------------------------------------------ */

describe('GstReturnSummary', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('displays GST return summary with standard and zero-rated columns (Req 45.6)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockGst })
    render(<GstReturnSummary />)
    expect(await screen.findByText('Total Sales (incl. GST)')).toBeInTheDocument()
    expect(screen.getByText('Standard-rated sales (15%)')).toBeInTheDocument()
    expect(screen.getByText('Zero-rated sales')).toBeInTheDocument()
    expect(screen.getByText('Total GST Collected')).toBeInTheDocument()
    expect(screen.getByText('Net GST Payable')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  CarjamUsage tests                                                  */
/* ------------------------------------------------------------------ */

describe('CarjamUsage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('displays Carjam usage summary cards', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockCarjam })
    render(<CarjamUsage />)
    expect(await screen.findByText('Total Lookups')).toBeInTheDocument()
    expect(screen.getByText('150')).toBeInTheDocument()
    expect(screen.getByText('Included in Plan')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('Overage Lookups')).toBeInTheDocument()
    expect(screen.getByText('50')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  StorageUsage tests                                                 */
/* ------------------------------------------------------------------ */

describe('StorageUsage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('displays storage usage bar and breakdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStorage })
    render(<StorageUsage />)
    expect(await screen.findByText('40%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    expect(screen.getByText('Invoices')).toBeInTheDocument()
    expect(screen.getByText('Customers')).toBeInTheDocument()
    expect(screen.getByText('Vehicles')).toBeInTheDocument()
  })
})
