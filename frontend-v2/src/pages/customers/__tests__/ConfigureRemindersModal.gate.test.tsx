/**
 * F3 / I3 — the Configure Reminders Save runs the consent gate: it opens the
 * Consent Confirmation modal iff `computeMissingConsent` is non-empty,
 * otherwise it PUTs directly.
 *
 * Feature: customer-reminder-consent
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'cust-123' }),
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: (s: string) => s === 'vehicles' || s === 'sms' }),
}))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', email: 'a@t.com', name: 'A', role: 'org_admin', org_id: 'o1' } }),
}))

import apiClient from '@/api/client'
import CustomerProfilePage from '../CustomerProfile'

const baseCustomer = {
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
}

// service_due enabled on email, NOT covered by existing consent → gate fires.
const reminders = {
  data: {
    service_due: { enabled: true, days_before: 30, channel: 'email' },
    wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
    cof_expiry: { enabled: false, days_before: 30, channel: 'email' },
    registration_expiry: { enabled: false, days_before: 30, channel: 'email' },
    vehicles: [],
  },
}

function mockGets(customer: unknown) {
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url === '/customers/cust-123') return { data: customer }
    if (url === '/customers/cust-123/reminders') return reminders
    if (url === '/customers/consent-text') return { data: { text: 'T', version: 'v1' } }
    return { data: {} }
  })
}

async function openModalAndSave() {
  const user = userEvent.setup()
  render(<CustomerProfilePage />)
  await waitFor(() =>
    expect(screen.getByRole('heading', { level: 1, name: 'Jane Smith' })).toBeInTheDocument(),
  )
  await user.click(
    screen.getByRole('button', { name: /reminders configured|configure reminders/i }),
  )
  await screen.findByRole('heading', { name: /Service Due/ })
  await user.click(screen.getByRole('button', { name: /^Save$/ }))
}

beforeEach(() => vi.clearAllMocks())

describe('Configure Reminders consent gate (F3)', () => {
  it('opens the Consent Confirmation modal when consent is missing', async () => {
    mockGets(baseCustomer) // no existing consent
    await openModalAndSave()
    await waitFor(() =>
      expect(screen.getByText(/Confirm reminder consent/i)).toBeInTheDocument(),
    )
    // The gate must NOT have PUT yet.
    expect(apiClient.put).not.toHaveBeenCalled()
  })

  it('PUTs directly when existing consent already covers the pair', async () => {
    mockGets({
      ...baseCustomer,
      custom_fields: {
        reminder_consent: {
          given_at: '2026-06-08T00:00:00Z',
          source: 'kiosk_self_checkin',
          consent_text_version: 'v1',
          entries: [{ vehicle_id: null, category: 'service_due', channel: 'email' }],
        },
      },
    })
    await openModalAndSave()
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith(
        '/customers/cust-123/reminders',
        expect.objectContaining({ service_due: expect.objectContaining({ enabled: true }) }),
      ),
    )
    expect(screen.queryByText(/Confirm reminder consent/i)).not.toBeInTheDocument()
  })
})
