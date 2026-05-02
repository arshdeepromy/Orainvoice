import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 14.1, 14.2, 14.3
 * - 14.1: Display full portal URL when enable_portal=true and portal_token exists
 * - 14.2: Include "Copy Link" button that copies portal URL to clipboard
 * - 14.3: Display "Portal Access: Disabled" when enable_portal=false or portal_token is null
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import { CustomerViewModal } from '../components/customers/CustomerViewModal'

const mockGet = vi.mocked(apiClient.get)
const mockPost = vi.mocked(apiClient.post)

function makeCustomerData(overrides: Record<string, unknown> = {}) {
  return {
    id: 'cust-001',
    first_name: 'Jane',
    last_name: 'Smith',
    email: 'jane@example.com',
    customer_type: 'individual',
    enable_portal: false,
    portal_token: null,
    enable_bank_payment: true,
    currency: 'NZD',
    language: 'en',
    payment_terms: 'net_30',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

/** Helper: find the Portal Access section by its label text */
function getPortalSection() {
  const labels = screen.getAllByText('Portal Access')
  // The label is the <span class="text-xs ..."> — its parent is the section container
  return labels[0].closest('div')!
}

describe('CustomerViewModal — Portal Access Section', () => {
  it('shows "Disabled" when enable_portal is false', async () => {
    mockGet.mockResolvedValueOnce({ data: makeCustomerData({ enable_portal: false, portal_token: null }) })

    render(<CustomerViewModal open customerId="cust-001" onClose={() => {}} />)

    // Wait for data to load
    await screen.findByText('Jane Smith')

    const section = getPortalSection()
    expect(within(section).getByText('Disabled')).toBeInTheDocument()
    expect(screen.queryByText('Copy Link')).not.toBeInTheDocument()
    expect(screen.queryByText('Send Link')).not.toBeInTheDocument()
  })

  it('shows "Disabled" when enable_portal is true but portal_token is null', async () => {
    mockGet.mockResolvedValueOnce({ data: makeCustomerData({ enable_portal: true, portal_token: null }) })

    render(<CustomerViewModal open customerId="cust-001" onClose={() => {}} />)

    await screen.findByText('Jane Smith')

    const section = getPortalSection()
    expect(within(section).getByText('Disabled')).toBeInTheDocument()
    expect(screen.queryByText('Copy Link')).not.toBeInTheDocument()
  })

  it('shows portal URL with Copy Link and Send Link buttons when portal is enabled', async () => {
    mockGet.mockResolvedValueOnce({
      data: makeCustomerData({ enable_portal: true, portal_token: 'abc-123-token' }),
    })

    render(<CustomerViewModal open customerId="cust-001" onClose={() => {}} />)

    // Should show the portal URL
    expect(await screen.findByText(/\/portal\/abc-123-token/)).toBeInTheDocument()
    // Should show both action buttons
    expect(screen.getByText('Copy Link')).toBeInTheDocument()
    expect(screen.getByText('Send Link')).toBeInTheDocument()
  })

  it('copies portal URL to clipboard on Copy Link click', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      writable: true,
      configurable: true,
    })

    mockGet.mockResolvedValueOnce({
      data: makeCustomerData({ enable_portal: true, portal_token: 'abc-123-token' }),
    })

    render(<CustomerViewModal open customerId="cust-001" onClose={() => {}} />)

    await screen.findByText('Copy Link')
    await user.click(screen.getByText('Copy Link'))

    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('/portal/abc-123-token'),
    )

    // Should show "Copied" feedback
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })

  it('calls send-portal-link endpoint on Send Link click', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({
      data: makeCustomerData({ enable_portal: true, portal_token: 'abc-123-token' }),
    })
    mockPost.mockResolvedValueOnce({ data: { message: 'Portal link sent' } })

    render(<CustomerViewModal open customerId="cust-001" onClose={() => {}} />)

    await screen.findByText('Send Link')
    await user.click(screen.getByText('Send Link'))

    expect(mockPost).toHaveBeenCalledWith('/api/v2/customers/cust-001/send-portal-link')

    // Should show "Sent" feedback
    expect(await screen.findByText('Sent')).toBeInTheDocument()
  })

  it('shows error message when send-portal-link fails', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValueOnce({
      data: makeCustomerData({ enable_portal: true, portal_token: 'abc-123-token' }),
    })
    mockPost.mockRejectedValueOnce({
      response: { data: { detail: 'Customer has no email address' } },
    })

    render(<CustomerViewModal open customerId="cust-001" onClose={() => {}} />)

    await screen.findByText('Send Link')
    await user.click(screen.getByText('Send Link'))

    expect(await screen.findByText('Customer has no email address')).toBeInTheDocument()
  })
})
