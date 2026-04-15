import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import PrinterErrorModal from '../PrinterErrorModal'

/**
 * Validates: Requirements 3.1, 3.2, 3.3, 3.7
 * Unit tests for PrinterErrorModal component
 */

// Mock the Modal component since jsdom doesn't support <dialog>.showModal()
vi.mock('@/components/ui/Modal', () => ({
  Modal: ({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) =>
    open ? (
      <div data-testid="modal" role="dialog" aria-label={title}>
        <h2>{title}</h2>
        <button onClick={onClose} aria-label="Close dialog">×</button>
        {children}
      </div>
    ) : null,
}))

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  errorMessage: 'Connection refused: printer at 192.168.1.50',
  onBrowserPrint: vi.fn(),
}

describe('PrinterErrorModal', () => {
  it('renders the error message', () => {
    render(<PrinterErrorModal {...defaultProps} />)
    expect(screen.getByText('Connection refused: printer at 192.168.1.50')).toBeInTheDocument()
  })

  it('renders the "Use Browser Print" button', () => {
    render(<PrinterErrorModal {...defaultProps} />)
    expect(screen.getByRole('button', { name: 'Use Browser Print' })).toBeInTheDocument()
  })

  it('renders the "Enable Browser Print for Future Prints" checkbox', () => {
    render(<PrinterErrorModal {...defaultProps} />)
    expect(screen.getByLabelText(/Enable Browser Print for Future Prints/i)).toBeInTheDocument()
  })

  it('renders the "Go to Printer Settings" link with correct href', () => {
    render(<PrinterErrorModal {...defaultProps} />)
    const link = screen.getByRole('link', { name: /Go to Printer Settings/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/settings/printers')
  })

  it('calls onBrowserPrint with false when checkbox is unchecked', async () => {
    const onBrowserPrint = vi.fn()
    const user = userEvent.setup()
    render(<PrinterErrorModal {...defaultProps} onBrowserPrint={onBrowserPrint} />)

    await user.click(screen.getByRole('button', { name: 'Use Browser Print' }))
    expect(onBrowserPrint).toHaveBeenCalledWith(false)
  })

  it('calls onBrowserPrint with true when checkbox is checked', async () => {
    const onBrowserPrint = vi.fn()
    const user = userEvent.setup()
    render(<PrinterErrorModal {...defaultProps} onBrowserPrint={onBrowserPrint} />)

    await user.click(screen.getByLabelText(/Enable Browser Print for Future Prints/i))
    await user.click(screen.getByRole('button', { name: 'Use Browser Print' }))
    expect(onBrowserPrint).toHaveBeenCalledWith(true)
  })

  it('does not render content when open is false', () => {
    render(<PrinterErrorModal {...defaultProps} open={false} />)
    expect(screen.queryByText('Connection refused: printer at 192.168.1.50')).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
