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
import { RefundModal } from '../RefundModal'

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onSuccess: vi.fn(),
  invoiceId: 'inv-123',
  refundableAmount: 300,
}

function getButton(name: RegExp) {
  return screen.getByRole('button', { name, hidden: true })
}

/** Navigate to the confirmation step by filling amount and clicking Process Refund */
async function goToConfirmStep(user: ReturnType<typeof userEvent.setup>, amount = '100') {
  await user.clear(screen.getByLabelText(/amount/i))
  await user.type(screen.getByLabelText(/amount/i), amount)
  await user.click(getButton(/process refund/i))
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: /confirm refund/i, hidden: true })).toBeInTheDocument()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
})

describe('RefundModal', () => {
  it('renders form fields with Cash pre-selected and Stripe disabled', () => {
    render(<RefundModal {...defaultProps} />)

    expect(screen.getByLabelText(/amount/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/refund method/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/notes/i)).toBeInTheDocument()

    const select = screen.getByLabelText(/refund method/i) as HTMLSelectElement
    expect(select.value).toBe('cash')

    const stripeOption = screen.getByRole('option', { name: /stripe/i, hidden: true }) as HTMLOptionElement
    expect(stripeOption.disabled).toBe(true)
  })

  it('displays refundable amount helper text', () => {
    render(<RefundModal {...defaultProps} />)
    expect(screen.getByText('Maximum: $300.00')).toBeInTheDocument()
  })

  it('shows validation errors on blur for invalid amount', async () => {
    const user = userEvent.setup()
    render(<RefundModal {...defaultProps} />)

    const amountField = screen.getByLabelText(/amount/i)
    await user.click(amountField)
    await user.tab()

    await waitFor(() => {
      expect(screen.getByText('Amount must be greater than zero')).toBeInTheDocument()
    })
  })

  it('shows confirmation step with amount, method, notes before API call', async () => {
    const user = userEvent.setup()
    render(<RefundModal {...defaultProps} />)

    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '100')
    await user.type(screen.getByLabelText(/notes/i), 'Test notes')

    await user.click(getButton(/process refund/i))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /confirm refund/i, hidden: true })).toBeInTheDocument()
    })
    expect(screen.getByText('$100.00')).toBeInTheDocument()
    expect(screen.getByText('Cash')).toBeInTheDocument()
    expect(screen.getByText('Test notes')).toBeInTheDocument()
  })

  it('cancel confirmation returns to form editing state', async () => {
    const user = userEvent.setup()
    render(<RefundModal {...defaultProps} />)

    await goToConfirmStep(user)
    await user.click(getButton(/back/i))

    await waitFor(() => {
      expect(screen.getByLabelText(/amount/i)).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/refund method/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/notes/i)).toBeInTheDocument()
  })

  it('submits correct payload to API endpoint', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { id: 'ref-1' } })

    render(<RefundModal {...defaultProps} />)

    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '150')
    await user.type(screen.getByLabelText(/notes/i), 'Refund notes')

    await user.click(getButton(/process refund/i))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /confirm refund/i, hidden: true })).toBeInTheDocument()
    })

    await user.click(getButton(/confirm refund/i))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/payments/refund', {
        invoice_id: 'inv-123',
        amount: 150,
        method: 'cash',
        notes: 'Refund notes',
      })
    })
  })

  it('shows success toast and calls onSuccess on API success', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { id: 'ref-1' } })

    render(<RefundModal {...defaultProps} />)

    await goToConfirmStep(user)
    await user.click(getButton(/confirm refund/i))

    await waitFor(() => {
      expect(mockAddToast).toHaveBeenCalledWith('success', 'Refund processed successfully')
    })
    expect(defaultProps.onSuccess).toHaveBeenCalled()
    expect(defaultProps.onClose).toHaveBeenCalled()
  })

  it('shows inline error message on API failure, modal stays open', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockRejectedValueOnce({
      response: { data: { detail: 'Insufficient funds' } },
    })

    render(<RefundModal {...defaultProps} />)

    await goToConfirmStep(user)
    await user.click(getButton(/confirm refund/i))

    await waitFor(() => {
      expect(screen.getByText('Insufficient funds')).toBeInTheDocument()
    })
    // On error, modal returns to form state
    expect(screen.getByLabelText(/amount/i)).toBeInTheDocument()
    expect(defaultProps.onClose).not.toHaveBeenCalled()
  })

  it('disables submit button during loading', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockReturnValueOnce(new Promise(() => {}))

    render(<RefundModal {...defaultProps} />)

    await goToConfirmStep(user)
    await user.click(getButton(/confirm refund/i))

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /processing/i, hidden: true })
      expect(btn).toBeDisabled()
    })
  })

  it('resets form state when closed and reopened', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<RefundModal {...defaultProps} />)

    // Fill in some values
    await user.clear(screen.getByLabelText(/amount/i))
    await user.type(screen.getByLabelText(/amount/i), '200')
    await user.type(screen.getByLabelText(/notes/i), 'Some notes')

    // Close the modal
    rerender(<RefundModal {...defaultProps} open={false} />)

    // Reopen the modal
    rerender(<RefundModal {...defaultProps} open={true} />)

    // Fields should be reset
    const amountField = screen.getByLabelText(/amount/i) as HTMLInputElement
    expect(amountField.value).toBe('')
    const notesField = screen.getByLabelText(/notes/i) as HTMLTextAreaElement
    expect(notesField.value).toBe('')
  })
})
