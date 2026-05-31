/**
 * Unit tests for MyPayslipsPage (Phase 4 task D11 / G9).
 *
 * Cases covered:
 *   1. Empty state — renders the "No payslips yet" hint when the
 *      server returns an empty list.
 *   2. Populated list — renders one row per finalised payslip with
 *      pay period range, gross, net, and a PDF link pointing to the
 *      `/api/v2/staff/me/payslips/{id}/pdf` endpoint.
 *   3. Defensive client-side filter — drafts and voided payslips are
 *      filtered out client-side even if the server slipped one in.
 *
 * **Validates: Staff Management Phase 4 task D11, R8a, G9**
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('@/api/payslips', () => ({
  listMyPayslips: vi.fn(),
}))

vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}))

import { listMyPayslips } from '@/api/payslips'
import type { MyPayslip } from '@/api/payslips'

import MyPayslipsPage from '../MyPayslipsPage'

const ORG = '00000000-0000-0000-0000-000000000001'

function buildPayslip(overrides: Partial<MyPayslip> = {}): MyPayslip {
  return {
    id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    pay_period_id: 'pppppppp-pppp-pppp-pppp-pppppppppppp',
    pay_period: {
      id: 'pppppppp-pppp-pppp-pppp-pppppppppppp',
      org_id: ORG,
      start_date: '2026-06-01',
      end_date: '2026-06-14',
      pay_date: '2026-06-17',
      status: 'finalised',
      created_at: '2026-06-01T00:00:00Z',
      finalised_at: '2026-06-15T00:00:00Z',
      paid_at: null,
    },
    status: 'finalised',
    ordinary_hours: '40.00',
    overtime_hours: '0.00',
    public_holiday_hours: '0.00',
    ordinary_rate: '30.00',
    overtime_rate: '45.00',
    public_holiday_rate: '45.00',
    gross_pay: '1200.00',
    gross_ytd: '1200.00',
    net_pay: '950.00',
    finalised_at: '2026-06-15T00:00:00Z',
    emailed_at: null,
    pdf_url: '/api/v2/staff/me/payslips/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/pdf',
    ...overrides,
  }
}

const mockedList = listMyPayslips as ReturnType<typeof vi.fn>

describe('MyPayslipsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the empty-state hint when there are no payslips', async () => {
    mockedList.mockResolvedValueOnce({ items: [], total: 0 })

    render(<MyPayslipsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('my-payslips-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('my-payslips-empty')).toHaveTextContent(
      /No payslips yet/i,
    )
    expect(
      screen.queryByTestId('my-payslips-table'),
    ).not.toBeInTheDocument()
  })

  it('renders the populated table with period range, gross, net, and PDF link', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildPayslip(),
        buildPayslip({
          id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          gross_pay: '900.00',
          net_pay: '720.00',
        }),
      ],
      total: 2,
    })

    render(<MyPayslipsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('my-payslips-table')).toBeInTheDocument()
    })

    // Money columns formatted as NZD.
    expect(screen.getByText(/\$1,200\.00/)).toBeInTheDocument()
    expect(screen.getByText(/\$950\.00/)).toBeInTheDocument()
    expect(screen.getByText(/\$900\.00/)).toBeInTheDocument()
    expect(screen.getByText(/\$720\.00/)).toBeInTheDocument()

    // Period range.
    expect(screen.getAllByText(/1 Jun 2026/).length).toBeGreaterThan(0)

    // PDF link.
    const pdfLink = screen.getByTestId(
      'my-payslip-pdf-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    ) as HTMLAnchorElement
    expect(pdfLink.getAttribute('href')).toBe(
      '/api/v2/staff/me/payslips/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/pdf',
    )
    expect(pdfLink.getAttribute('target')).toBe('_blank')
    expect(pdfLink.getAttribute('rel')).toContain('noopener')
  })

  it('filters out drafts and voided payslips defensively (client-side)', async () => {
    mockedList.mockResolvedValueOnce({
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
    })

    render(<MyPayslipsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('my-payslips-table')).toBeInTheDocument()
    })

    // Only the finalised row renders.
    expect(
      screen.getByTestId(
        'my-payslip-row-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'my-payslip-row-bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
      ),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'my-payslip-row-cccccccc-dddd-eeee-ffff-000000000000',
      ),
    ).not.toBeInTheDocument()
  })
})
