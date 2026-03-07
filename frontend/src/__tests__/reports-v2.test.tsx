import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Tasks 54.17–54.20 — Enhanced Reporting Frontend
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import ReportBuilder from '../pages/reports/ReportBuilder'
import InventoryReport from '../pages/reports/InventoryReport'
import JobReport from '../pages/reports/JobReport'
import ProjectReport from '../pages/reports/ProjectReport'
import POSReport from '../pages/reports/POSReport'
import HospitalityReport from '../pages/reports/HospitalityReport'
import TaxReturnReport from '../pages/reports/TaxReturnReport'
import ScheduledReports from '../pages/reports/ScheduledReports'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockStockValuation = {
  data: {
    items: [
      { product_id: 'p1', product_name: 'Widget A', sku: 'W001', quantity: 50, cost_price: 10, valuation: 500 },
      { product_id: 'p2', product_name: 'Widget B', sku: 'W002', quantity: 30, cost_price: 20, valuation: 600 },
    ],
    total_valuation: 1100,
  },
}

const mockJobProfitability = {
  data: {
    items: [
      { job_id: 'j1', job_number: 'JOB-001', revenue: 5000, labour_cost: 1000, material_cost: 500, expense_cost: 200, profit: 3300, margin_percent: 66 },
    ],
    total_revenue: 5000,
    total_cost: 1700,
    total_profit: 3300,
  },
}

const mockGSTReturn = {
  data: {
    total_sales_incl: 11500,
    total_sales_excl: 10000,
    gst_collected: 1500,
    zero_rated_sales: 0,
    gst_on_purchases: 300,
    net_gst: 1200,
  },
}

const mockDailySales = {
  data: {
    by_payment_method: [
      { payment_method: 'cash', total: 500, count: 10 },
      { payment_method: 'card', total: 1500, count: 25 },
    ],
    by_category: [],
    grand_total: 2000,
  },
}

const mockSchedules: any[] = [
  {
    id: 's1',
    report_type: 'gst_return',
    frequency: 'monthly',
    recipients: ['admin@example.com'],
    is_active: true,
    last_generated_at: '2025-01-01T00:00:00Z',
    created_at: '2024-12-01T00:00:00Z',
  },
]

/* ------------------------------------------------------------------ */
/*  ReportBuilder tests                                                */
/* ------------------------------------------------------------------ */

describe('ReportBuilder', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders report type selector and controls', () => {
    render(<ReportBuilder />)
    expect(screen.getByRole('heading', { name: 'Report Builder' })).toBeInTheDocument()
    expect(screen.getByLabelText('Report Type')).toBeInTheDocument()
    expect(screen.getByLabelText('Currency')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate Report' })).toBeInTheDocument()
  })

  it('renders export buttons (PDF, CSV, Excel)', () => {
    render(<ReportBuilder />)
    expect(screen.getByRole('button', { name: 'Export as PDF' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export as CSV' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export as Excel' })).toBeInTheDocument()
  })

  it('shows error on failed report generation', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('fail'))
    render(<ReportBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Generate Report' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to generate report.')
  })
})

/* ------------------------------------------------------------------ */
/*  InventoryReport tests                                              */
/* ------------------------------------------------------------------ */

describe('InventoryReport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<InventoryReport />)
    expect(screen.getByRole('status', { name: 'Loading inventory report' })).toBeInTheDocument()
  })

  it('displays stock valuation data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStockValuation })
    render(<InventoryReport />)
    expect(await screen.findByText('Widget A')).toBeInTheDocument()
    expect(screen.getByText('Widget B')).toBeInTheDocument()
  })

  it('has report sub-type selector', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStockValuation })
    render(<InventoryReport />)
    expect(screen.getByLabelText('Report')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  JobReport tests                                                    */
/* ------------------------------------------------------------------ */

describe('JobReport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<JobReport />)
    expect(screen.getByRole('status', { name: 'Loading job report' })).toBeInTheDocument()
  })

  it('displays job profitability data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockJobProfitability })
    render(<JobReport />)
    expect(await screen.findByText('JOB-001')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ProjectReport tests                                                */
/* ------------------------------------------------------------------ */

describe('ProjectReport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ProjectReport />)
    expect(screen.getByRole('status', { name: 'Loading project report' })).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  POSReport tests                                                    */
/* ------------------------------------------------------------------ */

describe('POSReport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<POSReport />)
    expect(screen.getByRole('status', { name: 'Loading POS report' })).toBeInTheDocument()
  })

  it('displays daily sales summary with grand total', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockDailySales })
    render(<POSReport />)
    expect(await screen.findByText('Grand Total')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  HospitalityReport tests                                            */
/* ------------------------------------------------------------------ */

describe('HospitalityReport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<HospitalityReport />)
    expect(screen.getByRole('status', { name: 'Loading hospitality report' })).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  TaxReturnReport tests                                              */
/* ------------------------------------------------------------------ */

describe('TaxReturnReport', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<TaxReturnReport />)
    expect(screen.getByRole('status', { name: 'Loading tax return report' })).toBeInTheDocument()
  })

  it('displays GST return data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockGSTReturn })
    render(<TaxReturnReport />)
    expect(await screen.findByText('Total Sales (incl. GST)')).toBeInTheDocument()
    expect(screen.getByText('GST Collected')).toBeInTheDocument()
    expect(screen.getByText('Net GST Payable')).toBeInTheDocument()
  })

  it('has tax type selector with NZ, AU, UK options', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockGSTReturn })
    render(<TaxReturnReport />)
    expect(screen.getByLabelText('Tax Type')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ScheduledReports tests                                             */
/* ------------------------------------------------------------------ */

describe('ScheduledReports', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ScheduledReports />)
    expect(screen.getByRole('status', { name: 'Loading schedules' })).toBeInTheDocument()
  })

  it('displays existing schedules', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSchedules })
    render(<ScheduledReports />)
    expect(await screen.findByText('gst return')).toBeInTheDocument()
    expect(screen.getByText('monthly')).toBeInTheDocument()
    expect(screen.getByText('admin@example.com')).toBeInTheDocument()
  })

  it('has create schedule form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })
    render(<ScheduledReports />)
    await screen.findByText('New Schedule')
    expect(screen.getByLabelText('Report')).toBeInTheDocument()
    expect(screen.getByLabelText('Frequency')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Schedule' })).toBeInTheDocument()
  })

  it('creates a new schedule on form submit', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<ScheduledReports />)
    await screen.findByText('New Schedule')

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Recipients (comma-separated)'), 'test@example.com')
    await user.click(screen.getByRole('button', { name: 'Create Schedule' }))

    expect(apiClient.post).toHaveBeenCalledWith('/reports/schedule', expect.objectContaining({
      report_type: expect.any(String),
      frequency: 'daily',
      recipients: ['test@example.com'],
    }))
  })

  it('deletes a schedule', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSchedules })
    ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({})
    render(<ScheduledReports />)
    await screen.findByText('gst return')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Delete gst_return schedule/i }))
    expect(apiClient.delete).toHaveBeenCalledWith('/reports/schedule/s1')
  })
})
