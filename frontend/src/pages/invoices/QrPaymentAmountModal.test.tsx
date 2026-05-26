/**
 * Unit tests for QrPaymentAmountModal.
 *
 * Validates: Requirements 2.5
 */

import { render, screen, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { QrPaymentAmountModal } from './QrPaymentAmountModal'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const baseInvoice = {
  id: 'inv_1',
  balance_due: 200,
  invoice_number: 'INV-2026-001',
}

interface SetupOverrides {
  loading?: boolean
  invoice?: typeof baseInvoice
  open?: boolean
}

function renderModal(overrides: SetupOverrides = {}) {
  const onClose = vi.fn()
  const onContinue = vi.fn().mockResolvedValue(undefined)
  const utils = render(
    <QrPaymentAmountModal
      open={overrides.open ?? true}
      onClose={onClose}
      onContinue={onContinue}
      invoice={overrides.invoice ?? baseInvoice}
      loading={overrides.loading}
    />,
  )
  return { ...utils, onClose, onContinue }
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('QrPaymentAmountModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not render anything when open is false', () => {
    renderModal({ open: false })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders with Full radio pre-selected and the partial-amount input hidden', () => {
    renderModal()

    const fullRadio = screen.getByRole('radio', { name: /full payment/i }) as HTMLInputElement
    const partialRadio = screen.getByRole('radio', { name: /partial payment/i }) as HTMLInputElement

    expect(fullRadio).toBeChecked()
    expect(partialRadio).not.toBeChecked()

    // No partial-amount input is visible while in Full mode
    expect(screen.queryByLabelText(/amount \(nzd\)/i)).not.toBeInTheDocument()

    // Header reflects the invoice number
    expect(screen.getByRole('heading', { name: /qr payment for inv-2026-001/i })).toBeInTheDocument()
  })

  it('toggling to Partial reveals the amount input pre-populated with balance_due', async () => {
    const user = userEvent.setup()
    renderModal()

    await user.click(screen.getByRole('radio', { name: /partial payment/i }))

    const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
    expect(input).toBeInTheDocument()
    expect(input.value).toBe('200.00')

    // Selecting Partial leaves the radio in Partial mode
    expect(screen.getByRole('radio', { name: /partial payment/i })).toBeChecked()
  })

  it('Continue with Full mode calls onContinue(null)', async () => {
    const user = userEvent.setup()
    const { onContinue } = renderModal()

    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(onContinue).toHaveBeenCalledTimes(1)
    expect(onContinue).toHaveBeenCalledWith(null)
  })

  it('Continue with Partial mode calls onContinue with the typed amount', async () => {
    const user = userEvent.setup()
    const { onContinue } = renderModal()

    await user.click(screen.getByRole('radio', { name: /partial payment/i }))
    const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
    await user.clear(input)
    await user.type(input, '50.25')

    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(onContinue).toHaveBeenCalledTimes(1)
    expect(onContinue).toHaveBeenCalledWith(50.25)
  })

  describe('Continue is disabled at boundary conditions', () => {
    it('disabled and shows error when amount is empty', async () => {
      const user = userEvent.setup()
      renderModal()
      await user.click(screen.getByRole('radio', { name: /partial payment/i }))
      const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
      await user.clear(input)

      expect(input.value).toBe('')
      expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(/enter an amount/i)
    })

    it('disabled and shows error when amount is below the $0.50 Stripe minimum', async () => {
      const user = userEvent.setup()
      renderModal()
      await user.click(screen.getByRole('radio', { name: /partial payment/i }))
      const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
      await user.clear(input)
      await user.type(input, '0.49')

      expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(/at least \$0\.50/i)
    })

    it('disabled and shows error when amount exceeds the outstanding balance', async () => {
      const user = userEvent.setup()
      renderModal()
      await user.click(screen.getByRole('radio', { name: /partial payment/i }))
      const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
      await user.clear(input)
      await user.type(input, '200.01')

      expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(/cannot exceed/i)
    })

    it('disabled when the input cannot be parsed as a number (just a decimal point)', async () => {
      const user = userEvent.setup()
      renderModal()
      await user.click(screen.getByRole('radio', { name: /partial payment/i }))
      const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
      await user.clear(input)
      await user.type(input, '.')

      // sanitiser keeps '.', validation should reject as NaN-equivalent
      expect(input.value).toBe('.')
      expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
      expect(screen.getByRole('alert')).toHaveTextContent(/enter an amount/i)
    })
  })

  it('clicking the backdrop calls onClose', () => {
    const { onClose } = renderModal()

    const dialog = screen.getByRole('dialog')
    // Fire the click directly on the dialog element so e.target === e.currentTarget
    fireEvent.click(dialog)

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('clicks bubbling from inner content do not call onClose (only true backdrop clicks)', () => {
    const { onClose } = renderModal()

    // Clicking on the heading (an inner child) should not close
    fireEvent.click(screen.getByRole('heading', { name: /qr payment/i }))

    expect(onClose).not.toHaveBeenCalled()
  })

  it('pressing Escape calls onClose', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('clicking the X (close) button calls onClose', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.click(screen.getByRole('button', { name: /close/i }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('clicking the Cancel button calls onClose', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('silently truncates 3+ decimal places to 2 decimal places', async () => {
    const user = userEvent.setup()
    renderModal()

    await user.click(screen.getByRole('radio', { name: /partial payment/i }))
    const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
    await user.clear(input)
    await user.type(input, '12.3456')

    expect(input.value).toBe('12.34')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  describe('loading state', () => {
    it('disables the Continue, Cancel, and X close buttons', () => {
      renderModal({ loading: true })

      expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
      expect(screen.getByRole('button', { name: /close/i })).toBeDisabled()
    })

    it('does not call onClose on Escape while loading', async () => {
      const user = userEvent.setup()
      const { onClose } = renderModal({ loading: true })

      await user.keyboard('{Escape}')

      expect(onClose).not.toHaveBeenCalled()
    })

    it('does not call onClose on backdrop click while loading', () => {
      const { onClose } = renderModal({ loading: true })

      fireEvent.click(screen.getByRole('dialog'))

      expect(onClose).not.toHaveBeenCalled()
    })

    it('does not invoke onContinue when Continue is clicked while loading (button is disabled)', async () => {
      const user = userEvent.setup()
      const { onContinue } = renderModal({ loading: true })

      // userEvent respects the disabled state and will not fire the click handler
      await user.click(screen.getByRole('button', { name: 'Continue' }))

      expect(onContinue).not.toHaveBeenCalled()
    })

    it('renders the spinner inside the Continue button while loading', () => {
      renderModal({ loading: true })

      const spinner = document.querySelector('.animate-spin')
      expect(spinner).toBeInTheDocument()
    })
  })

  it('resets to Full mode and balance-due amount when re-opened', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onContinue = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(
      <QrPaymentAmountModal
        open
        onClose={onClose}
        onContinue={onContinue}
        invoice={baseInvoice}
      />,
    )

    // Switch to Partial and modify the amount
    await user.click(screen.getByRole('radio', { name: /partial payment/i }))
    const input = screen.getByLabelText(/amount \(nzd\)/i) as HTMLInputElement
    await user.clear(input)
    await user.type(input, '15.00')
    expect(input.value).toBe('15.00')

    // Close and re-open with a new balance
    await act(async () => {
      rerender(
        <QrPaymentAmountModal
          open={false}
          onClose={onClose}
          onContinue={onContinue}
          invoice={baseInvoice}
        />,
      )
    })
    await act(async () => {
      rerender(
        <QrPaymentAmountModal
          open
          onClose={onClose}
          onContinue={onContinue}
          invoice={{ ...baseInvoice, balance_due: 99.5 }}
        />,
      )
    })

    // Modal is back to Full mode and the balance reflects the new invoice
    expect(screen.getByRole('radio', { name: /full payment.*99\.50/i })).toBeChecked()
    expect(screen.queryByLabelText(/amount \(nzd\)/i)).not.toBeInTheDocument()
  })
})
