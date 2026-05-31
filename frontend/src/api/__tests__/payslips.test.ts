/**
 * Unit tests for the typed payslips API client.
 *
 * Covers:
 *   - `listPayPeriods` returns `{ items: [], total: 0 }` when response
 *     body is empty/missing.
 *   - `listPayPeriods` forwards `params` (offset/limit/status) and the
 *     `signal` to the underlying axios call.
 *   - Compile-time check: `PayslipDetail` (returned by `getPayslip`)
 *     exposes `allowances` and `deductions` arrays.
 *
 * **Validates: Staff Management Phase 4 task D9**
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ---------------------------------------------------------------------------
// Mock the apiClient module BEFORE importing the SUT.
// ---------------------------------------------------------------------------

const { mockGet, mockPost, mockPatch, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('../client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    patch: mockPatch,
    delete: mockDelete,
  },
}))

// Imports must come after the mock is registered.
import {
  listPayPeriods,
  getPayslip,
  type PayslipDetail,
  type PayslipAllowance,
  type PayslipDeduction,
} from '../payslips'

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  mockPatch.mockReset()
  mockDelete.mockReset()
})

describe('listPayPeriods', () => {
  it('returns empty list + zero total when response body is missing', async () => {
    mockGet.mockResolvedValueOnce({ data: undefined })

    const result = await listPayPeriods()

    expect(result).toEqual({ items: [], total: 0 })
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('returns empty list + zero total when items/total are absent', async () => {
    mockGet.mockResolvedValueOnce({ data: {} })

    const result = await listPayPeriods()

    expect(result.items).toEqual([])
    expect(result.total).toBe(0)
  })

  it('forwards the populated body untouched', async () => {
    const body = {
      items: [
        {
          id: '00000000-0000-0000-0000-000000000001',
          org_id: '00000000-0000-0000-0000-000000000099',
          start_date: '2026-06-01',
          end_date: '2026-06-14',
          pay_date: '2026-06-17',
          status: 'open',
          created_at: '2026-06-01T00:00:00Z',
          finalised_at: null,
          paid_at: null,
        },
      ],
      total: 1,
    }
    mockGet.mockResolvedValueOnce({ data: body })

    const result = await listPayPeriods()

    expect(result.total).toBe(1)
    expect(result.items).toHaveLength(1)
    expect(result.items[0].status).toBe('open')
  })

  it('forwards params and signal to axios via the request config', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } })

    const controller = new AbortController()
    await listPayPeriods(
      { offset: 40, limit: 20, status: 'finalised' },
      controller.signal,
    )

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v2/pay-periods',
      expect.objectContaining({
        params: { offset: 40, limit: 20, status: 'finalised' },
        signal: controller.signal,
      }),
    )
  })

  it('uses an absolute /api/v2 path', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } })

    await listPayPeriods()

    expect(mockGet.mock.calls[0][0]).toBe('/api/v2/pay-periods')
  })
})

describe('getPayslip — type surface', () => {
  it('PayslipDetail exposes allowances and deductions arrays at compile time', async () => {
    // The body below is shaped exactly as PayslipDetail. If the type
    // ever drops `allowances` or `deductions`, this test stops compiling.
    const detail: PayslipDetail = {
      id: '00000000-0000-0000-0000-000000000010',
      org_id: '00000000-0000-0000-0000-000000000099',
      staff_id: '00000000-0000-0000-0000-000000000020',
      staff_name: 'Jane',
      pay_period_id: '00000000-0000-0000-0000-000000000001',
      pay_period: null,
      status: 'finalised',
      ordinary_hours: '40.00',
      overtime_hours: '0.00',
      public_holiday_hours: '0.00',
      ordinary_rate: '25.00',
      overtime_rate: null,
      public_holiday_rate: null,
      gross_pay: '1000.00',
      gross_ytd: '1000.00',
      net_pay: '820.00',
      pdf_file_key: null,
      emailed_at: null,
      finalised_at: '2026-06-17T00:00:00Z',
      notes: null,
      created_at: '2026-06-15T00:00:00Z',
      updated_at: '2026-06-17T00:00:00Z',
      allowances: [],
      deductions: [],
      reimbursements: [],
      leave_lines: [],
    }
    mockGet.mockResolvedValueOnce({ data: detail })

    const result = await getPayslip(detail.id)

    // Runtime sanity — every required nested array is present.
    expect(Array.isArray(result.allowances)).toBe(true)
    expect(Array.isArray(result.deductions)).toBe(true)
    expect(Array.isArray(result.reimbursements)).toBe(true)
    expect(Array.isArray(result.leave_lines)).toBe(true)

    // Static-type smoke check: assigning items into the typed slots
    // would fail to compile if the field were missing or mistyped.
    const _allowance: PayslipAllowance[] = result.allowances
    const _deduction: PayslipDeduction[] = result.deductions
    void _allowance
    void _deduction
  })
})
