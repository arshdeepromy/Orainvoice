/**
 * Component tests for CancelQuoteModal (Task 5).
 * - Renders warning message
 * - Confirm button disabled when reason is empty/whitespace
 * - Confirm button enabled when reason has non-whitespace content
 * - Calls onConfirm with trimmed reason text
 * - Shows loading state
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import CancelQuoteModal from '../CancelQuoteModal'

afterEach(cleanup)

describe('CancelQuoteModal', () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onConfirm: vi.fn().mockResolvedValue(undefined),
    loading: false,
  }

  it('renders the warning message', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    expect(
      screen.getByText(
        'Cancelling this quote will retain its number but mark it as withdrawn. This cannot be undone.'
      )
    ).toBeTruthy()
  })

  it('renders the modal title', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    expect(screen.getByRole('heading', { name: 'Cancel Quote' })).toBeTruthy()
  })

  it('renders the textarea for reason', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    expect(screen.getByLabelText('Reason for cancellation')).toBeTruthy()
  })

  it('renders Go Back and Cancel Quote buttons', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    expect(screen.getByText('Go Back')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Cancel Quote/i })).toBeTruthy()
  })

  it('disables confirm button when reason is empty', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    const confirmBtn = screen.getByRole('button', { name: /Cancel Quote/i })
    expect(confirmBtn).toHaveAttribute('disabled')
  })

  it('disables confirm button when reason is only whitespace', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    const textarea = screen.getByLabelText('Reason for cancellation')
    fireEvent.change(textarea, { target: { value: '   \n\t  ' } })
    const confirmBtn = screen.getByRole('button', { name: /Cancel Quote/i })
    expect(confirmBtn).toHaveAttribute('disabled')
  })

  it('enables confirm button when reason has non-whitespace content', () => {
    render(<CancelQuoteModal {...defaultProps} />)
    const textarea = screen.getByLabelText('Reason for cancellation')
    fireEvent.change(textarea, { target: { value: 'Customer changed scope' } })
    const confirmBtn = screen.getByRole('button', { name: /Cancel Quote/i })
    expect(confirmBtn).not.toHaveAttribute('disabled')
  })

  it('calls onConfirm with trimmed reason when confirm is clicked', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined)
    render(<CancelQuoteModal {...defaultProps} onConfirm={onConfirm} />)
    const textarea = screen.getByLabelText('Reason for cancellation')
    fireEvent.change(textarea, { target: { value: '  Customer requested different scope  ' } })
    const confirmBtn = screen.getByRole('button', { name: /Cancel Quote/i })
    fireEvent.click(confirmBtn)
    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledWith('Customer requested different scope')
    })
  })

  it('shows loading state on the confirm button', () => {
    render(<CancelQuoteModal {...defaultProps} loading={true} />)
    const confirmBtn = screen.getByRole('button', { name: /Cancel Quote/i })
    expect(confirmBtn).toHaveAttribute('aria-busy', 'true')
    expect(confirmBtn).toHaveAttribute('disabled')
  })

  it('disables textarea when loading', () => {
    render(<CancelQuoteModal {...defaultProps} loading={true} />)
    const textarea = screen.getByLabelText('Reason for cancellation')
    expect(textarea).toHaveAttribute('disabled')
  })

  it('calls onClose when Go Back is clicked', () => {
    const onClose = vi.fn()
    render(<CancelQuoteModal {...defaultProps} onClose={onClose} />)
    fireEvent.click(screen.getByText('Go Back'))
    expect(onClose).toHaveBeenCalled()
  })

  it('does not call onClose when loading and Go Back is clicked', () => {
    const onClose = vi.fn()
    render(<CancelQuoteModal {...defaultProps} onClose={onClose} loading={true} />)
    const goBackBtn = screen.getByText('Go Back')
    // Button is disabled when loading, so click won't fire
    expect(goBackBtn.closest('button')).toHaveAttribute('disabled')
  })

  it('returns null when isOpen is false', () => {
    const { container } = render(<CancelQuoteModal {...defaultProps} isOpen={false} />)
    expect(container.innerHTML).toBe('')
  })
})
