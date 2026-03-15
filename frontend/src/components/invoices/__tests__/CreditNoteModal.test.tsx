import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockAddToast = vi.fn()
vi.mock('../../ui/Toast', () => ({
  useToast: () => ({ toasts: [], addToast: mockAddToast, dismissToast: vi.fn() }),
  ToastContainer: () => null,
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

import apiClient from '../../../api/client'
import { CreditNoteModal } from '../CreditNoteModal'

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onSuccess: vi.fn(),
  invoiceId: 'inv-123',
  creditableAmount: 500,
}

function getButton(name: RegExp) {
  return screen.getByRole('button', { name, hidden: true })
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
})

describe('CreditNoteModal', () => {
  it('renders form fields when opened', () => {
    render(<CreditNoteModal {...defaultProps} />)

    expect(screen.getByLabelText(/amount/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/reason/i)).toBeInTheDocument()
    expect(getButton(/add item/i)).toBeInTheDocument()
  })

  it('displays creditable amount helper text', () => {
    render(<CreditNoteModal {...defaultProps} />)
    expect(screen.getByText('Maximum: $500.00')).toBeInTheDocument()
  })

  it('shows validation errors on blur for empty reason', async () => {
    const user = userEvent.setup()
    render(<CreditNoteModal {...defaultProps} />)

    const reasonField = screen.getByLabelText(/reason/i)
    await user.click(reasonField)
    await user.tab()

    await waitFor(() => {
      expect(screen.getByText('Reason is required')).toBeInTheDocument()
    })
  })

  it('shows validation errors on blur for invalid amount', async () => {
    const user = userEvent.setup()
    render(<CreditNoteModal {...defaultProps} />)

    const amountField = screen.getByLabelText(/amount/i)
    await user.click(amountField)
    await user.tab()

    await waitFor(() => {
      expect(screen.getByText('Amount must be greater than zero')).toBeInTheDocument()
    })
  })

  it('submits correct payload to API endpoint', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { id: 'cn-1' } })

    render(<CreditNoteModal {...defaultProps} />)

    const amountField = screen.getByLabelText(/amount/i)
    await user.clear(amountField)
    await user.type(amountField, '100')

    const reasonField = screen.getByLabelText(/reason/i)
    await user.type(reasonField, 'Test reason')

    await user.click(getButton(/create credit note/i))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/invoices/inv-123/credit-note', {
        amount: 100,
        reason: 'Test reason',
        items: [],
        process_stripe_refund: false,
      })
    })
  })

  it('shows success toast and calls onSuccess on API success', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { id: 'cn-1' } })

    render(<CreditNoteModal {...defaultProps} />)

    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '100')
    await user.type(screen.getByLabelText(/reason/i), 'Test reason')
    await user.click(getButton(/create credit note/i))

    await waitFor(() => {
      expect(mockAddToast).toHaveBeenCalledWith('success', 'Credit note created successfully')
    })
    expect(defaultProps.onSuccess).toHaveBeenCalled()
    expect(defaultProps.onClose).toHaveBeenCalled()
  })

  it('shows inline error message on API failure, modal stays open', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockRejectedValueOnce({
      response: { data: { detail: 'Server error' } },
    })

    render(<CreditNoteModal {...defaultProps} />)

    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '100')
    await user.type(screen.getByLabelText(/reason/i), 'Test reason')
    await user.click(getButton(/create credit note/i))

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument()
    })
    expect(defaultProps.onClose).not.toHaveBeenCalled()
  })

  it('disables submit button during loading', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockReturnValueOnce(new Promise(() => {}))

    render(<CreditNoteModal {...defaultProps} />)

    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '100')
    await user.type(screen.getByLabelText(/reason/i), 'Test reason')
    await user.click(getButton(/create credit note/i))

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /creating/i, hidden: true })
      expect(btn).toBeDisabled()
    })
  })

  it('add item row and remove item row', async () => {
    const user = userEvent.setup()
    render(<CreditNoteModal {...defaultProps} />)

    await user.click(getButton(/add item/i))

    expect(screen.getByLabelText('Item 1 description')).toBeInTheDocument()
    expect(screen.getByLabelText('Item 1 amount')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /remove item 1/i, hidden: true }))

    expect(screen.queryByLabelText('Item 1 description')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Item 1 amount')).not.toBeInTheDocument()
  })

  it('shows item total and mismatch warning', async () => {
    const user = userEvent.setup()
    render(<CreditNoteModal {...defaultProps} />)

    // Set credit note amount to 100
    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '100')

    // Add an item with amount 50
    await user.click(getButton(/add item/i))
    const itemAmountField = screen.getByLabelText('Item 1 amount')
    await user.clear(itemAmountField)
    await user.type(itemAmountField, '50')

    await waitFor(() => {
      expect(screen.getByText(/items total/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/item amounts do not match/i)).toBeInTheDocument()
  })

  it('resets form state when closed and reopened', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<CreditNoteModal {...defaultProps} />)

    // Fill in some values
    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '200')
    await user.type(screen.getByLabelText(/reason/i), 'Some reason')

    // Close the modal
    rerender(<CreditNoteModal {...defaultProps} open={false} />)

    // Reopen the modal
    rerender(<CreditNoteModal {...defaultProps} open={true} />)

    // Fields should be reset
    const amountField = screen.getByLabelText(/amount/i) as HTMLInputElement
    expect(amountField.value).toBe('')
    const reasonField = screen.getByLabelText(/reason/i) as HTMLTextAreaElement
    expect(reasonField.value).toBe('')
  })
})
