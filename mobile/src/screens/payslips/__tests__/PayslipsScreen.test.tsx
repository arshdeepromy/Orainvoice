/**
 * Unit tests for the mobile PayslipsScreen (Phase 4 task D11 / G9).
 *
 * Cases covered:
 *   1. Empty state — renders the "No payslips yet" hint when the API
 *      returns an empty list.
 *   2. Populated list — renders one row per finalised payslip with
 *      pay period range and gross/net summary, plus a PDF button.
 *   3. Defensive client-side filter — drafts/voided payslips are
 *      filtered out client-side even if the server slipped one in.
 *
 * **Validates: Staff Management Phase 4 task D11, R8a, G9**
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

/* ------------------------------------------------------------------ */
/* Mocks                                                              */
/* ------------------------------------------------------------------ */

// Konsta UI — minimal stubs so our screen renders predictably in jsdom.
vi.mock('konsta/react', () => ({
  Page: ({ children, ...props }: any) => (
    <div data-testid={props['data-testid']}>{children}</div>
  ),
  Block: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  List: ({ children, ...props }: any) => (
    <ul data-testid={props['data-testid']}>{children}</ul>
  ),
  ListItem: ({ title, subtitle, after, ...props }: any) => (
    <li data-testid={props['data-testid']}>
      <span>{title}</span>
      {subtitle && <span>{subtitle}</span>}
      {after && <span>{after}</span>}
    </li>
  ),
  Preloader: () => <div data-testid="preloader">Loading…</div>,
}))

// PullRefresh: pass-through.
vi.mock('@/components/gestures/PullRefresh', () => ({
  PullRefresh: ({ children }: any) => <div>{children}</div>,
}))

// ModuleGate: render children unconditionally for the test.
vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const mockGet = vi.fn()
vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

interface MyPayslipFixture {
  id: string
  pay_period_id: string
  pay_period: {
    id: string
    start_date: string
    end_date: string
    pay_date: string
    status: string
  } | null
  status: 'draft' | 'finalised' | 'voided'
  gross_pay: string
  net_pay: string
  finalised_at: string | null
  pdf_url: string | null
}

function buildPayslip(
  overrides: Partial<MyPayslipFixture> = {},
): MyPayslipFixture {
  return {
    id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    pay_period_id: 'pppppppp-pppp-pppp-pppp-pppppppppppp',
    pay_period: {
      id: 'pppppppp-pppp-pppp-pppp-pppppppppppp',
      start_date: '2026-06-01',
      end_date: '2026-06-14',
      pay_date: '2026-06-17',
      status: 'finalised',
    },
    status: 'finalised',
    gross_pay: '1200.00',
    net_pay: '950.00',
    finalised_at: '2026-06-15T00:00:00Z',
    pdf_url: '/api/v2/staff/me/payslips/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/pdf',
    ...overrides,
  }
}

/* ------------------------------------------------------------------ */
/* Tests                                                              */
/* ------------------------------------------------------------------ */

describe('PayslipsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the empty-state hint when there are no payslips', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } })

    const PayslipsScreen = (await import('../PayslipsScreen')).default
    render(<PayslipsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('payslips-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('payslips-empty')).toHaveTextContent(
      /No payslips yet/i,
    )
    expect(screen.queryByTestId('payslips-list')).not.toBeInTheDocument()
  })

  it('renders the populated list with period range, gross + net, and a PDF button', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        items: [
          buildPayslip(),
          buildPayslip({
            id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
            gross_pay: '900.00',
            net_pay: '720.00',
          }),
        ],
        total: 2,
      },
    })

    const PayslipsScreen = (await import('../PayslipsScreen')).default
    render(<PayslipsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('payslips-list')).toBeInTheDocument()
    })

    // NZD-formatted gross / net.
    expect(screen.getAllByText(/NZD1,200\.00/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/NZD950\.00/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/NZD900\.00/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/NZD720\.00/).length).toBeGreaterThan(0)

    // PDF button per row.
    expect(
      screen.getByTestId('payslip-pdf-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('payslip-pdf-bbbbbbbb-cccc-dddd-eeee-ffffffffffff'),
    ).toBeInTheDocument()
  })

  it('hits /api/v2/staff/me/payslips with offset+limit pagination params', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } })

    const PayslipsScreen = (await import('../PayslipsScreen')).default
    render(<PayslipsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalled()
    })

    const firstCall = mockGet.mock.calls[0]
    expect(firstCall?.[0]).toBe('/api/v2/staff/me/payslips')
    expect(firstCall?.[1]?.params).toEqual({
      offset: 0,
      limit: 50,
    })
  })

  it('filters out drafts and voided payslips defensively (client-side)', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        items: [
          buildPayslip(),
          buildPayslip({
            id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
            status: 'draft',
          }),
          buildPayslip({
            id: 'cccccccc-dddd-eeee-ffff-000000000000',
            status: 'voided',
          }),
        ],
        total: 3,
      },
    })

    const PayslipsScreen = (await import('../PayslipsScreen')).default
    render(<PayslipsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('payslips-list')).toBeInTheDocument()
    })

    // Only the finalised row renders.
    expect(
      screen.getByTestId('payslip-item-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'payslip-item-bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
      ),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'payslip-item-cccccccc-dddd-eeee-ffff-000000000000',
      ),
    ).not.toBeInTheDocument()
  })
})
