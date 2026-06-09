/**
 * F0 + F2 — Configure Reminders modal renders all four category rows and
 * shows per-row consent indicators (covered ✓ vs needs-consent ⚠) from the
 * customer's existing reminder_consent.
 *
 * Feature: customer-reminder-consent
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'cust-123' }),
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: (slug: string) => slug === 'vehicles' || slug === 'sms' }),
}))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', email: 'a@t.com', name: 'A', role: 'org_admin', org_id: 'o1' } }),
}))

import apiClient from '@/api/client'
import CustomerProfilePage from '../CustomerProfile'

const mockCustomer = {
  id: 'cust-123',
  first_name: 'Jane',
  last_name: 'Smith',
  email: 'jane@example.com',
  phone: '021-555-0002',
  address: null,
  notes: null,
  is_anonymised: false,
  enable_portal: false,
  portal_token: null,
  portal_token_expires_at: null,
  last_portal_access_at: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  vehicles: [],
  invoices: [],
  total_spend: '0.00',
  outstanding_balance: '0.00',
  // Existing consent covers wof_expiry via sms only.
  custom_fields: {
    reminder_consent: {
      given_at: '2026-06-08T00:00:00Z',
      source: 'kiosk_self_checkin',
      consent_text_version: 'v1',
      entries: [{ vehicle_id: null, category: 'wof_expiry', channel: 'sms' }],
    },
  },
}

// Categories enabled; wof_expiry on sms (covered), the rest uncovered. The
// WOF row shows only with a WOF vehicle and COF only with a COF vehicle, so
// the fixture links one of each.
const remindersResponse = {
  data: {
    service_due: { enabled: true, days_before: 30, channel: 'email' },
    wof_expiry: { enabled: true, days_before: 30, channel: 'sms' },
    cof_expiry: { enabled: true, days_before: 30, channel: 'email' },
    vehicles: [
      {
        global_vehicle_id: 'veh-wof',
        rego: 'WOF111',
        make: 'Toyota',
        model: 'Hilux',
        year: 2021,
        inspection_type: 'wof',
        service_due_date: null,
        wof_expiry: '2026-07-01',
        cof_expiry: null,
      },
      {
        global_vehicle_id: 'veh-cof',
        rego: 'COF222',
        make: 'Hino',
        model: 'Truck',
        year: 2020,
        inspection_type: 'cof',
        service_due_date: null,
        wof_expiry: null,
        cof_expiry: '2026-08-01',
      },
    ],
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url === '/customers/cust-123') return { data: mockCustomer }
    if (url === '/customers/cust-123/reminders') return remindersResponse
    return { data: {} }
  })
})

describe('Configure Reminders modal — rows + consent indicators', () => {
  it('renders all four category rows with correct consent indicators', async () => {
    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: 'Jane Smith' })).toBeInTheDocument(),
    )

    await user.click(
      screen.getByRole('button', { name: /reminders configured|configure reminders/i }),
    )

    // Service Due + the per-vehicle inspection rows render; Registration is
    // no longer offered.
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /Service Due/ })).toBeInTheDocument(),
    )
    expect(screen.getByRole('heading', { name: /WOF Expiry/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /COF Expiry/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Registration Expiry/ })).not.toBeInTheDocument()

    // wof_expiry on sms is covered → ✓; the others are not → ⚠ (F2).
    expect(screen.getByTestId('consent-ok-wof_expiry')).toBeInTheDocument()
    expect(screen.getByTestId('consent-needed-service_due')).toBeInTheDocument()
    expect(screen.getByTestId('consent-needed-cof_expiry')).toBeInTheDocument()
  })
})
