/**
 * Tests for the Copy Week confirmation modal (B11).
 *
 * Validates: R8.2, R8.8.
 */

import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import CopyWeekConfirmModal from '../components/CopyWeekConfirmModal'

afterEach(() => cleanup())

describe('CopyWeekConfirmModal', () => {
  it('renders source + target counts and submits with overwrite=false', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(
      <CopyWeekConfirmModal
        open={true}
        sourceCount={5}
        targetCount={2}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    )
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /copy week/i }))
    expect(onConfirm).toHaveBeenCalledWith(false)
  })

  it('submits with overwrite=true when checkbox is ticked', () => {
    const onConfirm = vi.fn()
    render(
      <CopyWeekConfirmModal
        open={true}
        sourceCount={5}
        targetCount={2}
        onConfirm={onConfirm}
        onClose={() => {}}
      />,
    )
    const checkbox = screen.getByRole('checkbox')
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByRole('button', { name: /copy week/i }))
    expect(onConfirm).toHaveBeenCalledWith(true)
  })
})
