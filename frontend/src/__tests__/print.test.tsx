import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import fs from 'fs'
import path from 'path'

/**
 * Validates: Requirements 75.1, 75.2, 75.3
 */

/* ------------------------------------------------------------------ */
/*  Mock dependencies                                                  */
/* ------------------------------------------------------------------ */

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'inv-1' }),
  NavLink: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Outlet: () => <div />,
}))

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return { default: { get: mockGet, post: mockPost } }
})

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ settings: { branding: { name: 'Test Workshop' } } }),
}))

import apiClient from '@/api/client'
import { PrintButton } from '../components/ui/PrintButton'

/* ------------------------------------------------------------------ */
/*  PrintButton component tests                                        */
/* ------------------------------------------------------------------ */

describe('PrintButton', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders with default label "Print"', () => {
    render(<PrintButton />)
    const btn = screen.getByRole('button', { name: 'Print' })
    expect(btn).toBeInTheDocument()
  })

  it('renders with custom label', () => {
    render(<PrintButton label="Print Statement" />)
    expect(screen.getByRole('button', { name: 'Print Statement' })).toBeInTheDocument()
  })

  it('calls window.print() on click (Req 75.3)', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    render(<PrintButton />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Print' }))
    expect(printSpy).toHaveBeenCalledTimes(1)
    printSpy.mockRestore()
  })

  it('has no-print class so it hides during print (Req 75.2)', () => {
    render(<PrintButton />)
    const btn = screen.getByRole('button', { name: 'Print' })
    expect(btn.className).toContain('no-print')
  })

  it('renders a printer icon SVG', () => {
    render(<PrintButton />)
    const btn = screen.getByRole('button', { name: 'Print' })
    const svg = btn.querySelector('svg')
    expect(svg).toBeInTheDocument()
    expect(svg?.getAttribute('aria-hidden')).toBe('true')
  })
})

/* ------------------------------------------------------------------ */
/*  Print CSS stylesheet tests                                         */
/* ------------------------------------------------------------------ */

describe('Print stylesheet (Req 75.1, 75.2)', () => {
  let cssContent: string

  beforeEach(() => {
    const cssPath = path.resolve(__dirname, '../styles/print.css')
    cssContent = fs.readFileSync(cssPath, 'utf-8')
  })

  it('contains @media print block', () => {
    expect(cssContent).toContain('@media print')
  })

  it('hides nav, aside, header, footer elements', () => {
    expect(cssContent).toMatch(/nav[\s,]/)
    expect(cssContent).toMatch(/aside[\s,]/)
    expect(cssContent).toMatch(/header[\s,]/)
    expect(cssContent).toMatch(/footer[\s,]/)
    expect(cssContent).toContain('display: none !important')
  })

  it('hides elements with data-print-hide attribute', () => {
    expect(cssContent).toContain('[data-print-hide]')
  })

  it('hides elements with no-print class', () => {
    expect(cssContent).toContain('.no-print')
  })

  it('sets white background on body', () => {
    expect(cssContent).toContain('background: white !important')
  })

  it('sets black text for readability', () => {
    expect(cssContent).toContain('color: #111 !important')
  })

  it('configures A4 page size with margins', () => {
    expect(cssContent).toContain('size: A4')
    expect(cssContent).toContain('margin: 15mm')
  })

  it('prevents table rows from breaking across pages', () => {
    expect(cssContent).toContain('page-break-inside: avoid')
  })

  it('repeats table headers across pages', () => {
    expect(cssContent).toContain('display: table-header-group')
  })

  it('hides dialogs and modals during print', () => {
    expect(cssContent).toContain('[role="dialog"]')
  })
})

/* ------------------------------------------------------------------ */
/*  Print CSS is imported in index.css                                 */
/* ------------------------------------------------------------------ */

describe('Print CSS integration', () => {
  it('index.css imports the print stylesheet', () => {
    const indexCssPath = path.resolve(__dirname, '../index.css')
    const indexCss = fs.readFileSync(indexCssPath, 'utf-8')
    expect(indexCss).toContain("@import './styles/print.css'")
  })
})

/* ------------------------------------------------------------------ */
/*  Report pages include PrintButton                                   */
/* ------------------------------------------------------------------ */

describe('Report pages have Print buttons (Req 75.3)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('CustomerStatement has a Print Statement button', async () => {
    const mockStatement = {
      customer_name: 'Jane Doe',
      lines: [{ date: '2024-01-15', description: 'INV-001', amount: 500, balance: 500 }],
      outstanding_balance: 500,
    }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStatement })

    const { default: CustomerStatement } = await import('../pages/reports/CustomerStatement')
    render(<CustomerStatement />)

    // Fill in customer ID and generate
    const user = userEvent.setup()
    const input = screen.getByPlaceholderText('Enter customer ID…')
    await user.type(input, 'cust-1')
    await user.click(screen.getByRole('button', { name: 'Generate' }))

    expect(await screen.findByRole('button', { name: 'Print Statement' })).toBeInTheDocument()
  })

  it('OutstandingInvoices has a Print Report button', async () => {
    const mockData = {
      invoices: [],
      total_outstanding: 0,
    }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockData })

    const { default: OutstandingInvoices } = await import('../pages/reports/OutstandingInvoices')
    render(<OutstandingInvoices />)

    expect(await screen.findByRole('button', { name: 'Print Report' })).toBeInTheDocument()
  })

  it('GstReturnSummary has a Print Report button', async () => {
    const mockGst = {
      total_sales: 10000,
      standard_rated_sales: 9000,
      zero_rated_sales: 1000,
      total_gst_collected: 1500,
      net_gst: 1500,
    }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockGst })

    const { default: GstReturnSummary } = await import('../pages/reports/GstReturnSummary')
    render(<GstReturnSummary />)

    expect(await screen.findByRole('button', { name: 'Print Report' })).toBeInTheDocument()
  })
})
