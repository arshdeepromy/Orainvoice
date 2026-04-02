/**
 * Unit tests for ClaimCreateForm component.
 *
 * Requirements: 1.1-1.8, 8.1-8.4
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

const mockNavigate = vi.fn()
let mockSearchParams = new URLSearchParams()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useSearchParams: () => [mockSearchParams, vi.fn()],
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

import apiClient from '../../../api/client'
import ClaimCreateForm from '../ClaimCreateForm'

const mockCustomers = {
  items: [
    { id: 'cust-1', first_name: 'John', last_name: 'Doe', email: 'john@example.com' },
    { id: 'cust-2', first_name: 'Jane', last_name: 'Smith', email: 'jane@example.com' },
  ],
}

const mockInvoices = {
  items: [
    { id: 'inv-1', invoice_number: 'INV-001', total: 500, status: 'paid' },
    { id: 'inv-2', invoice_number: 'INV-002', total: 200, status: 'issued' },
  ],
}

const mockJobCards = {
  job_cards: [
    { id: 'jc-1', description: 'Brake repair', status: 'completed', vehicle_rego: 'ABC123' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  mockSearchParams = new URLSearchParams()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()

  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (typeof url === 'string' && url.includes('/customers')) {
      return { data: mockCustomers }
    }
    if (typeof url === 'string' && url.includes('/invoices/')) {
      return { data: { invoice: { line_items: [{ id: 'li-1', description: 'Brake pads', item_type: 'part', quantity: 2, line_total: 80 }] } } }
    }
    if (typeof url === 'string' && url.includes('/invoices')) {
      return { data: mockInvoices }
    }
    if (typeof url === 'string' && url.includes('/job-cards')) {
      return { data: mockJobCards }
    }
    return { data: {} }
  })
})

describe('ClaimCreateForm', () => {
  it('renders the form with all required fields', () => {
    render(<ClaimCreateForm />)

    expect(screen.getByText('New Claim')).toBeInTheDocument()
    expect(screen.getByLabelText(/Customer/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Claim Type/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Description/)).toBeInTheDocument()
  })

  it('searches customers when typing in customer field', async () => {
    const user = userEvent.setup()
    render(<ClaimCreateForm />)

    const customerInput = screen.getByPlaceholderText('Search customers…')
    await user.type(customerInput, 'John')

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/customers',
        expect.objectContaining({
          params: expect.objectContaining({ search: 'John' }),
        }),
      )
    })
  })

  it('selects a customer from dropdown', async () => {
    const user = userEvent.setup()
    render(<ClaimCreateForm />)

    const customerInput = screen.getByPlaceholderText('Search customers…')
    await user.type(customerInput, 'John')

    await waitFor(() => {
      expect(screen.getByText(/John Doe/)).toBeInTheDocument()
    })

    await user.click(screen.getByText(/John Doe/))

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
      expect(screen.getByText('Change')).toBeInTheDocument()
    })
  })

  it('loads invoices after customer selection', async () => {
    const user = userEvent.setup()
    render(<ClaimCreateForm />)

    const customerInput = screen.getByPlaceholderText('Search customers…')
    await user.type(customerInput, 'John')

    await waitFor(() => {
      expect(screen.getByText(/John Doe/)).toBeInTheDocument()
    })

    await user.click(screen.getByText(/John Doe/))

    await waitFor(() => {
      const invoiceSelect = screen.getByLabelText(/Invoice/)
      expect(invoiceSelect).not.toBeDisabled()
    })
  })

  it('shows validation hint when no invoice or job card selected', async () => {
    const user = userEvent.setup()
    render(<ClaimCreateForm />)

    const customerInput = screen.getByPlaceholderText('Search customers…')
    await user.type(customerInput, 'John')

    await waitFor(() => {
      expect(screen.getByText(/John Doe/)).toBeInTheDocument()
    })

    await user.click(screen.getByText(/John Doe/))

    await waitFor(() => {
      expect(screen.getByText(/At least one of Invoice or Job Card is required/)).toBeInTheDocument()
    })
  })

  it('submits claim and navigates to detail on success', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { id: 'new-claim-id', status: 'open' },
    })

    render(<ClaimCreateForm />)

    // Select customer
    const customerInput = screen.getByPlaceholderText('Search customers…')
    await user.type(customerInput, 'John')
    await waitFor(() => expect(screen.getByText(/John Doe/)).toBeInTheDocument())
    await user.click(screen.getByText(/John Doe/))

    // Select claim type
    await waitFor(() => {
      const typeSelect = screen.getByLabelText(/Claim Type/)
      expect(typeSelect).toBeInTheDocument()
    })
    await user.selectOptions(screen.getByLabelText(/Claim Type/), 'warranty')

    // Enter description
    await user.type(screen.getByLabelText(/Description/), 'Product is defective')

    // Select invoice
    await waitFor(() => {
      const invoiceSelect = screen.getByLabelText(/Invoice/)
      expect(invoiceSelect).not.toBeDisabled()
    })
    await user.selectOptions(screen.getByLabelText(/Invoice/), 'inv-1')

    // Submit
    await user.click(screen.getByText('Create Claim'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/claims',
        expect.objectContaining({
          customer_id: 'cust-1',
          claim_type: 'warranty',
          description: 'Product is defective',
          invoice_id: 'inv-1',
        }),
      )
    })

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/claims/new-claim-id')
    })
  })

  it('shows error message on submission failure', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockRejectedValue({
      response: { data: { detail: 'Customer not found' } },
    })

    render(<ClaimCreateForm />)

    // Select customer
    const customerInput = screen.getByPlaceholderText('Search customers…')
    await user.type(customerInput, 'John')
    await waitFor(() => expect(screen.getByText(/John Doe/)).toBeInTheDocument())
    await user.click(screen.getByText(/John Doe/))

    // Fill form
    await user.selectOptions(screen.getByLabelText(/Claim Type/), 'defect')
    await user.type(screen.getByLabelText(/Description/), 'Broken item')

    await waitFor(() => {
      const invoiceSelect = screen.getByLabelText(/Invoice/)
      expect(invoiceSelect).not.toBeDisabled()
    })
    await user.selectOptions(screen.getByLabelText(/Invoice/), 'inv-1')

    await user.click(screen.getByText('Create Claim'))

    await waitFor(() => {
      expect(screen.getByText('Customer not found')).toBeInTheDocument()
    })
  })

  it('navigates back to claims list on Cancel', async () => {
    const user = userEvent.setup()
    render(<ClaimCreateForm />)

    const cancelButtons = screen.getAllByText('Cancel')
    await user.click(cancelButtons[0])
    expect(mockNavigate).toHaveBeenCalledWith('/claims')
  })

  it('pre-populates customer and invoice from query params', async () => {
    mockSearchParams = new URLSearchParams({
      customer_id: 'cust-1',
      invoice_id: 'inv-1',
    })

    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (typeof url === 'string' && url === '/customers/cust-1') {
        return { data: { first_name: 'John', last_name: 'Doe' } }
      }
      if (typeof url === 'string' && url.includes('/customers')) {
        return { data: mockCustomers }
      }
      if (typeof url === 'string' && url.includes('/invoices/')) {
        return { data: { invoice: { line_items: [] } } }
      }
      if (typeof url === 'string' && url.includes('/invoices')) {
        return { data: mockInvoices }
      }
      if (typeof url === 'string' && url.includes('/job-cards')) {
        return { data: mockJobCards }
      }
      return { data: {} }
    })

    render(<ClaimCreateForm />)

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })
  })
})
