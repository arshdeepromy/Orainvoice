import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AttachmentList, formatAttachmentSize } from './AttachmentList'
import type { AttachmentSpec } from './types'

/**
 * AttachmentList unit tests (task 12.5, R21.4).
 *
 * Covers the exported `formatAttachmentSize` boundary ({kb} KB < 1 MB else
 * {mb} MB), the required-row lock (checked + disabled + "Required", cannot be
 * unchecked), and the over-size boundary (onOverSizeChange fires true once the
 * selected total + body estimate exceeds emailSizeLimitBytes, false under it).
 */

const ONE_MB = 1024 * 1024

function spec(overrides: Partial<AttachmentSpec> = {}): AttachmentSpec {
  return {
    key: 'invoice_pdf',
    label: 'Invoice PDF',
    size_bytes: 50 * 1024,
    default_attached: true,
    required: false,
    ...overrides,
  }
}

describe('formatAttachmentSize', () => {
  it('renders KB (rounded) for sizes below 1 MB', () => {
    expect(formatAttachmentSize(50 * 1024)).toBe('50 KB')
    expect(formatAttachmentSize(1500)).toBe('1 KB')
  })

  it('renders MB (one decimal) at and above 1 MB', () => {
    expect(formatAttachmentSize(ONE_MB)).toBe('1.0 MB')
    expect(formatAttachmentSize(2.5 * ONE_MB)).toBe('2.5 MB')
  })

  it('falls back to 0 KB for non-finite or non-positive sizes', () => {
    expect(formatAttachmentSize(0)).toBe('0 KB')
    expect(formatAttachmentSize(-10)).toBe('0 KB')
    expect(formatAttachmentSize(Number.NaN)).toBe('0 KB')
  })
})

describe('AttachmentList — rendering', () => {
  it('renders one row per attachment with its label and human-readable size', () => {
    render(
      <AttachmentList
        attachments={[spec({ key: 'invoice_pdf', label: 'Invoice PDF', size_bytes: 80 * 1024 })]}
        selected={{ invoice_pdf: true }}
        onToggle={vi.fn()}
        emailSizeLimitBytes={25 * ONE_MB}
      />,
    )
    expect(screen.getByText('Invoice PDF')).toBeInTheDocument()
    expect(screen.getByText('80 KB')).toBeInTheDocument()
  })

  it('renders nothing when there are no attachments', () => {
    const { container } = render(
      <AttachmentList
        attachments={[]}
        selected={{}}
        onToggle={vi.fn()}
        emailSizeLimitBytes={25 * ONE_MB}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})

describe('AttachmentList — required lock', () => {
  it('renders a required row checked + disabled with the "Required" label', () => {
    render(
      <AttachmentList
        attachments={[spec({ required: true, default_attached: true })]}
        selected={{}}
        onToggle={vi.fn()}
        emailSizeLimitBytes={25 * ONE_MB}
      />,
    )
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement
    expect(checkbox).toBeChecked()
    expect(checkbox).toBeDisabled()
    expect(screen.getByText('Required')).toBeInTheDocument()
  })

  it('does not call onToggle when a required checkbox is clicked', async () => {
    const onToggle = vi.fn()
    render(
      <AttachmentList
        attachments={[spec({ required: true })]}
        selected={{}}
        onToggle={onToggle}
        emailSizeLimitBytes={25 * ONE_MB}
      />,
    )
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onToggle).not.toHaveBeenCalled()
  })

  it('calls onToggle with the key and checked state for an optional row', async () => {
    const onToggle = vi.fn()
    render(
      <AttachmentList
        attachments={[spec({ key: 'statement_pdf', required: false, default_attached: false })]}
        selected={{ statement_pdf: false }}
        onToggle={onToggle}
        emailSizeLimitBytes={25 * ONE_MB}
      />,
    )
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onToggle).toHaveBeenCalledWith('statement_pdf', true)
  })
})

describe('AttachmentList — over-size boundary', () => {
  it('reports false when the selected total + body estimate is under the limit', () => {
    const onOverSizeChange = vi.fn()
    render(
      <AttachmentList
        attachments={[spec({ size_bytes: 1 * ONE_MB, default_attached: true })]}
        selected={{ invoice_pdf: true }}
        onToggle={vi.fn()}
        emailSizeLimitBytes={25 * ONE_MB}
        estimatedBodyBytes={10 * 1024}
        onOverSizeChange={onOverSizeChange}
      />,
    )
    expect(onOverSizeChange).toHaveBeenCalledWith(false)
  })

  it('reports true once the selected total + body estimate exceeds the limit', () => {
    const onOverSizeChange = vi.fn()
    render(
      <AttachmentList
        attachments={[spec({ size_bytes: 26 * ONE_MB, default_attached: true })]}
        selected={{ invoice_pdf: true }}
        onToggle={vi.fn()}
        emailSizeLimitBytes={25 * ONE_MB}
        estimatedBodyBytes={10 * 1024}
        onOverSizeChange={onOverSizeChange}
      />,
    )
    expect(onOverSizeChange).toHaveBeenCalledWith(true)
    expect(screen.getByRole('alert')).toHaveTextContent(/exceeds the/i)
  })

  it('counts a required attachment toward the total even when unselected', () => {
    const onOverSizeChange = vi.fn()
    render(
      <AttachmentList
        attachments={[spec({ size_bytes: 30 * ONE_MB, required: true })]}
        selected={{}}
        onToggle={vi.fn()}
        emailSizeLimitBytes={25 * ONE_MB}
        onOverSizeChange={onOverSizeChange}
      />,
    )
    expect(onOverSizeChange).toHaveBeenCalledWith(true)
  })
})
