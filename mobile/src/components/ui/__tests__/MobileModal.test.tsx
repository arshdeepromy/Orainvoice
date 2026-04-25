import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MobileModal } from '../MobileModal'

describe('MobileModal', () => {
  it('renders nothing when isOpen is false', () => {
    render(
      <MobileModal isOpen={false} onClose={vi.fn()}>
        Content
      </MobileModal>,
    )
    expect(screen.queryByText('Content')).not.toBeInTheDocument()
  })

  it('renders content when isOpen is true', () => {
    render(
      <MobileModal isOpen={true} onClose={vi.fn()} title="My Modal">
        Modal content
      </MobileModal>,
    )
    expect(screen.getByText('Modal content')).toBeInTheDocument()
    expect(screen.getByText('My Modal')).toBeInTheDocument()
  })

  it('has role=dialog and aria-modal', () => {
    render(
      <MobileModal isOpen={true} onClose={vi.fn()} title="Test">
        Content
      </MobileModal>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog.getAttribute('aria-modal')).toBe('true')
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    render(
      <MobileModal isOpen={true} onClose={onClose} title="Test">
        Content
      </MobileModal>,
    )
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose on Escape key', () => {
    const onClose = vi.fn()
    render(
      <MobileModal isOpen={true} onClose={onClose}>
        Content
      </MobileModal>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('close button has 44px min touch target', () => {
    render(
      <MobileModal isOpen={true} onClose={vi.fn()} title="Test">
        Content
      </MobileModal>,
    )
    const closeBtn = screen.getByLabelText('Close')
    expect(closeBtn.className).toContain('min-h-[44px]')
    expect(closeBtn.className).toContain('min-w-[44px]')
  })
})
