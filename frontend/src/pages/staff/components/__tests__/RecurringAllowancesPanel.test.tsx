/**
 * Unit tests for RecurringAllowancesPanel (Phase 4 task D10).
 *
 * Cases covered:
 *   1. Empty state — renders the "No recurring allowance rules" hint
 *      when the API returns an empty list.
 *   2. Populated list — renders one row per rule with type name,
 *      effective amount, unit, active toggle, and remove button.
 *   3. Add modal — clicking "+ Add recurring allowance" opens the
 *      modal and triggers a load of allowance types.
 *
 * **Validates: Staff Management Phase 4 task D10, R3.5, G4**
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('@/api/payslips', () => ({
  listRecurringAllowances: vi.fn(),
  updateRecurringAllowance: vi.fn(),
  deactivateRecurringAllowance: vi.fn(),
  createRecurringAllowance: vi.fn(),
  listAllowanceTypes: vi.fn(),
}))

import {
  listRecurringAllowances,
  listAllowanceTypes,
} from '@/api/payslips'
import type { StaffRecurringAllowance, AllowanceType } from '@/api/payslips'

import RecurringAllowancesPanel from '../RecurringAllowancesPanel'

const STAFF_ID = '11111111-2222-3333-4444-555555555555'
const ORG = '00000000-0000-0000-0000-000000000001'

function buildAllowanceType(
  overrides: Partial<AllowanceType> = {},
): AllowanceType {
  return {
    id: 'tttttttt-tttt-tttt-tttt-tttttttttttt',
    org_id: ORG,
    code: 'meal',
    name: 'Meal allowance',
    taxable: true,
    default_amount: '15.00',
    unit: 'period',
    active: true,
    display_order: 0,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    ...overrides,
  }
}

function buildRule(
  overrides: Partial<StaffRecurringAllowance> = {},
): StaffRecurringAllowance {
  return {
    id: 'rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr',
    org_id: ORG,
    staff_id: STAFF_ID,
    allowance_type_id: 'tttttttt-tttt-tttt-tttt-tttttttttttt',
    allowance_type: buildAllowanceType(),
    amount: null,
    quantity: null,
    active: true,
    notes: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    ...overrides,
  }
}

const mockedList = listRecurringAllowances as ReturnType<typeof vi.fn>
const mockedListTypes = listAllowanceTypes as ReturnType<typeof vi.fn>

describe('RecurringAllowancesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedListTypes.mockResolvedValue({ items: [], total: 0 })
  })

  it('renders the empty-state hint when no rules exist', async () => {
    mockedList.mockResolvedValueOnce({ items: [], total: 0 })

    render(<RecurringAllowancesPanel staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(
        screen.getByTestId('recurring-allowances-empty'),
      ).toBeInTheDocument()
    })
    expect(
      screen.getByTestId('recurring-allowances-empty'),
    ).toHaveTextContent(/No recurring allowance rules/i)
    expect(
      screen.queryByTestId('recurring-allowances-table'),
    ).not.toBeInTheDocument()
  })

  it('renders one row per rule with type name, amount, unit, and remove button', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildRule({ amount: '20.00' }),
        buildRule({
          id: 'rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrr2',
          amount: null,
          allowance_type: buildAllowanceType({
            id: 'tttttttt-tttt-tttt-tttt-tttttttttt22',
            code: 'tool',
            name: 'Tool allowance',
            unit: 'shift',
            default_amount: '10.00',
          }),
          allowance_type_id: 'tttttttt-tttt-tttt-tttt-tttttttttt22',
          active: false,
        }),
      ],
      total: 2,
    })

    render(<RecurringAllowancesPanel staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(
        screen.getByTestId('recurring-allowances-table'),
      ).toBeInTheDocument()
    })

    // Row 1 — overridden amount $20.00.
    expect(screen.getByText('Meal allowance')).toBeInTheDocument()
    expect(screen.getByText('$20.00')).toBeInTheDocument()
    expect(screen.getByText('period')).toBeInTheDocument()

    // Row 2 — falls back to allowance_type.default_amount = $10.00.
    expect(screen.getByText('Tool allowance')).toBeInTheDocument()
    expect(screen.getByText('$10.00')).toBeInTheDocument()
    expect(screen.getByText('shift')).toBeInTheDocument()

    // Each row exposes a remove button.
    expect(
      screen.getByTestId(
        'recurring-allowance-remove-rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId(
        'recurring-allowance-remove-rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrr2',
      ),
    ).toBeInTheDocument()

    // Active toggle: rule 1 → checked, rule 2 → unchecked.
    const toggle1 = screen.getByTestId(
      'recurring-allowance-toggle-rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr',
    ) as HTMLInputElement
    const toggle2 = screen.getByTestId(
      'recurring-allowance-toggle-rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrr2',
    ) as HTMLInputElement
    expect(toggle1.checked).toBe(true)
    expect(toggle2.checked).toBe(false)
  })

  it('opens the AddRecurringAllowanceModal when "+ Add" is clicked', async () => {
    mockedList.mockResolvedValueOnce({ items: [], total: 0 })
    mockedListTypes.mockResolvedValueOnce({
      items: [buildAllowanceType()],
      total: 1,
    })

    render(<RecurringAllowancesPanel staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(
        screen.getByTestId('recurring-allowances-empty'),
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('recurring-allowances-add'))

    await waitFor(() => {
      expect(
        screen.getByTestId('add-recurring-allowance-modal'),
      ).toBeInTheDocument()
    })

    // Modal triggers a list of allowance types on open.
    await waitFor(() => {
      expect(mockedListTypes).toHaveBeenCalled()
    })
  })
})
