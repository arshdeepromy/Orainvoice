/**
 * SalespersonDashboard tests (Task 17).
 *
 * Verifies the variant renders against the real backend response shapes it
 * consumes (the `toArr` normaliser accepts both bare arrays and wrapped
 * objects), including the summary counts, the overdue banner, the appointment
 * list and the job-card / invoice DataTables — plus the empty/degraded cases
 * (safe-api-consumption: a malformed response must not crash).
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({ default: { get: vi.fn() } }))

import apiClient from '@/api/client'
import { SalespersonDashboard } from './SalespersonDashboard'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>

function renderDashboard() {
  return render(
    <MemoryRouter>
      <SalespersonDashboard />
    </MemoryRouter>,
  )
}

/** Populated responses — note the mixed shapes the toArr normaliser handles. */
function populated(url: string, opts?: { params?: Record<string, unknown> }) {
  if (url === '/bookings') {
    // bare array shape
    return Promise.resolve({
      data: [{ id: 'a1', time: '09:00', customer_name: 'M. Taufa', vehicle_rego: 'ABC123', service_type: 'WOF' }],
    })
  }
  if (url === '/job-cards') {
    // wrapped { job_cards }
    return Promise.resolve({
      data: { job_cards: [{ id: 'j1', reference: 'JC-100', customer_name: 'Bay Plumbing', vehicle_rego: 'XYZ789', status: 'active', created_at: '2025-11-01' }] },
    })
  }
  if (url === '/invoices') {
    if (opts?.params?.status === 'overdue') {
      return Promise.resolve({
        data: { invoices: [{ id: 'o1', invoice_number: 'INV-9', customer_name: 'Late Co', vehicle_rego: 'OLD000', total: 999.5, status: 'overdue', issue_date: '2025-10-01' }] },
      })
    }
    return Promise.resolve({
      data: { invoices: [{ id: 'i1', invoice_number: 'INV-1', customer_name: 'Acme', vehicle_rego: 'NEW111', total: 250, status: 'paid', issue_date: '2025-11-10' }] },
    })
  }
  return Promise.resolve({ data: {} })
}

describe('SalespersonDashboard — populated', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockImplementation((url: string, opts?: { params?: Record<string, unknown> }) => populated(url, opts))
  })

  it('renders summary cards and the overdue banner', async () => {
    renderDashboard()
    expect(await screen.findByText("Today's Appointments", { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByText('Active Job Cards', { selector: 'h2' })).toBeInTheDocument()
    // Overdue banner present because one overdue invoice was returned.
    expect(screen.getByText(/requiring attention/i)).toBeInTheDocument()
  })

  it('renders the appointment and recent invoice data', async () => {
    renderDashboard()
    expect(await screen.findByText('M. Taufa')).toBeInTheDocument()
    expect(screen.getByText('JC-100')).toBeInTheDocument()
    expect(screen.getByText('INV-1')).toBeInTheDocument()
  })
})

describe('SalespersonDashboard — empty / safe consumption', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the tables empty without crashing on empty responses', async () => {
    mockGet.mockImplementation(() => Promise.resolve({ data: {} }))
    renderDashboard()
    // Summary labels still render; the DataTables show their empty-state row.
    expect(await screen.findByText('Active Job Cards', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getAllByText('No data available').length).toBeGreaterThan(0)
  })
})
