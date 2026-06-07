import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import StaffKpiStrip from './StaffKpiStrip'
import type { StaffListKpis } from '@/api/staff'

/**
 * StaffKpiStrip component tests (Task 9.9).
 *
 * Covers R1.1 (four labelled cards), R1.2–R1.5 (values), and R1.7 (null avg
 * hourly rate renders "—"). `getStaffListKpis` is mocked so the org-wide KPIs
 * resolve deterministically; the "Total staff" card is driven by the prop.
 */

const h = vi.hoisted(() => ({
  kpis: null as StaffListKpis | null,
}))

vi.mock('@/api/staff', () => ({
  getStaffListKpis: vi.fn(async () => h.kpis),
}))

beforeEach(() => {
  h.kpis = {
    total_staff: 12,
    employee_count: 8,
    with_login_count: 5,
    avg_hourly_rate: 32.5,
  }
})

describe('StaffKpiStrip', () => {
  it('renders four cards with the expected labels', async () => {
    render(<StaffKpiStrip totalStaff={12} />)
    expect(screen.getByText('Total staff')).toBeInTheDocument()
    expect(screen.getByText('Employees')).toBeInTheDocument()
    expect(screen.getByText('With login access')).toBeInTheDocument()
    expect(screen.getByText('Avg hourly rate')).toBeInTheDocument()
  })

  it('shows the total from the prop and the KPI values from the endpoint', async () => {
    render(<StaffKpiStrip totalStaff={12} />)
    // Total staff comes from the prop and renders immediately.
    expect(screen.getByText('12')).toBeInTheDocument()
    // Employees / With login access come from the resolved KPIs.
    await waitFor(() => expect(screen.getByText('8')).toBeInTheDocument())
    expect(screen.getByText('5')).toBeInTheDocument()
    // Avg hourly rate is currency-formatted (NZD).
    expect(screen.getByText(/\$32\.50/)).toBeInTheDocument()
  })

  it('renders "—" for avg hourly rate when it is null (R1.7)', async () => {
    h.kpis = {
      total_staff: 3,
      employee_count: 3,
      with_login_count: 0,
      avg_hourly_rate: null,
    }
    render(<StaffKpiStrip totalStaff={3} />)
    // Wait for the KPI fetch to resolve (with_login_count 0 appears).
    await waitFor(() => expect(screen.getByText('With login access')).toBeInTheDocument())
    // The Avg hourly rate card shows the placeholder.
    await waitFor(() => expect(screen.getByText('—')).toBeInTheDocument())
  })
})
