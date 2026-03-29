import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/* ── Mocks ── */

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useParams: () => ({ id: 'test-uuid' }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  }
})

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

import apiClient from '../../../api/client'
import VehicleProfilePage from '../VehicleProfile'

/* ── Helpers ── */

function createVehicleData(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'test-uuid',
    rego: 'ABC123',
    make: 'Toyota',
    model: 'Corolla',
    year: 2020,
    colour: 'White',
    body_type: 'Sedan',
    fuel_type: 'Petrol',
    engine_size: '1.8L',
    seats: 5,
    odometer: 85000,
    last_pulled_at: '2025-01-01',
    vin: 'JTD12345678901234',
    chassis: null,
    engine_no: null,
    transmission: 'Automatic',
    country_of_origin: 'Japan',
    number_of_owners: 2,
    vehicle_type: 'Passenger',
    submodel: 'GX',
    second_colour: null,
    lookup_type: 'carjam',
    wof_expiry: { date: '2025-12-01', days_remaining: 180, indicator: 'green' },
    rego_expiry: { date: '2025-11-01', days_remaining: 150, indicator: 'green' },
    linked_customers: [
      { id: 'cust-1', first_name: 'Jane', last_name: 'Smith', email: 'jane@example.com', phone: '021-555-1234' },
    ],
    service_history: [
      {
        invoice_id: 'inv-1',
        invoice_number: 'INV-001',
        status: 'paid',
        issue_date: '2025-01-15',
        total: '230.00',
        odometer: 84000,
        customer_name: 'Jane Smith',
        description: 'Full service',
      },
    ],
    ...overrides,
  }
}

/** Wait for the component to finish loading */
async function waitForLoaded() {
  await waitFor(() => {
    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })
}

/** Click the Service History tab to reveal report buttons */
async function openServiceTab(user: ReturnType<typeof userEvent.setup>) {
  const serviceTab = screen.getByRole('tab', { name: /service history/i })
  await user.click(serviceTab)
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
  vi.mocked(apiClient.get).mockResolvedValue({ data: createVehicleData() })
})

describe('VehicleProfile — Report Flows', () => {
  // Req 5.3: Print button shows loading state during PDF generation
  it('print button shows loading state during PDF generation', async () => {
    const user = userEvent.setup()

    // Make the POST hang so we can observe the loading state
    let resolvePost!: (value: unknown) => void
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => { resolvePost = resolve }),
    )

    render(<VehicleProfilePage />)
    await waitForLoaded()
    await openServiceTab(user)

    const printBtn = screen.getByRole('button', { name: /print report/i })
    expect(printBtn).not.toBeDisabled()

    await user.click(printBtn)

    // Button should be disabled and show loading (aria-busy)
    await waitFor(() => {
      expect(printBtn).toBeDisabled()
      expect(printBtn).toHaveAttribute('aria-busy', 'true')
    })

    // Resolve the POST to clear loading
    resolvePost({ data: new Blob(['pdf-bytes'], { type: 'application/pdf' }) })

    await waitFor(() => {
      expect(printBtn).not.toBeDisabled()
      expect(printBtn).toHaveAttribute('aria-busy', 'false')
    })
  })

  // Req 6.1: Email modal opens on button click
  it('email modal opens on button click', async () => {
    const user = userEvent.setup()
    render(<VehicleProfilePage />)
    await waitForLoaded()
    await openServiceTab(user)

    const emailBtn = screen.getByRole('button', { name: /email to customer/i })
    await user.click(emailBtn)

    await waitFor(() => {
      expect(screen.getByText('Email Service History')).toBeInTheDocument()
    })
  })

  // Req 6.6: Success notification after email sent
  it('shows success notification after email sent', async () => {
    const user = userEvent.setup()

    render(<VehicleProfilePage />)
    await waitForLoaded()
    await openServiceTab(user)

    // Open email modal
    await user.click(screen.getByRole('button', { name: /email to customer/i }))
    await waitFor(() => {
      expect(screen.getByText('Email Service History')).toBeInTheDocument()
    })

    // Mock the POST to succeed for the email send
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { vehicle_id: 'test-uuid', recipient_email: 'jane@example.com', pdf_size_bytes: 1234, status: 'sent' },
    })

    // Click send — use getByText since dialog content may not be in the accessible role tree
    await user.click(screen.getByText('Send Email'))

    // Success toast should appear
    await waitFor(() => {
      expect(screen.getByText(/service history report sent to jane@example.com/i)).toBeInTheDocument()
    })
  })

  // Req 6.7: Error message on email failure
  it('shows error message on email failure', async () => {
    const user = userEvent.setup()

    render(<VehicleProfilePage />)
    await waitForLoaded()
    await openServiceTab(user)

    // Open email modal
    await user.click(screen.getByRole('button', { name: /email to customer/i }))
    await waitFor(() => {
      expect(screen.getByText('Email Service History')).toBeInTheDocument()
    })

    // Now mock the POST to reject for the email send
    vi.mocked(apiClient.post).mockRejectedValue({
      response: { data: { detail: 'Failed to send email: SMTP connection refused' } },
    })

    // Click send
    const sendBtn = screen.getByText('Send Email')
    await user.click(sendBtn)

    // Error message should appear (in modal alert and toast)
    await waitFor(() => {
      const matches = screen.getAllByText(/SMTP connection refused/i)
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  // Req 6.5: Send button disabled during sending
  it('send button is disabled during sending', async () => {
    const user = userEvent.setup()

    render(<VehicleProfilePage />)
    await waitForLoaded()
    await openServiceTab(user)

    // Open email modal
    await user.click(screen.getByRole('button', { name: /email to customer/i }))
    await waitFor(() => {
      expect(screen.getByText('Email Service History')).toBeInTheDocument()
    })

    // Now mock the POST to hang
    let resolvePost!: (value: unknown) => void
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => { resolvePost = resolve }),
    )

    const sendBtn = screen.getByText('Send Email').closest('button')!
    await user.click(sendBtn)

    // Button should be disabled while sending
    await waitFor(() => {
      expect(sendBtn).toBeDisabled()
      expect(sendBtn).toHaveAttribute('aria-busy', 'true')
    })

    // Resolve to clear sending state
    resolvePost({
      data: { vehicle_id: 'test-uuid', recipient_email: 'jane@example.com', pdf_size_bytes: 1234, status: 'sent' },
    })

    // Modal closes on success, so we just verify the request completed
    await waitFor(() => {
      expect(screen.queryByText('Email Service History')).not.toBeInTheDocument()
    })
  })

  // Req 6.4: Manual email input shown when no customer email
  it('shows manual email input when no customer email exists', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createVehicleData({
        linked_customers: [
          { id: 'cust-2', first_name: 'Bob', last_name: 'Jones', email: null, phone: '021-555-9999' },
        ],
      }),
    })

    render(<VehicleProfilePage />)
    await waitForLoaded()
    await openServiceTab(user)

    // Open email modal
    await user.click(screen.getByRole('button', { name: /email to customer/i }))
    await waitFor(() => {
      expect(screen.getByText('Email Service History')).toBeInTheDocument()
    })

    // Should show the warning and manual email input
    expect(screen.getByText(/no customer email found/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/recipient email/i)).toBeInTheDocument()
  })
})
