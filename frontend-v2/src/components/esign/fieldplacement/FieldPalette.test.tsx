/**
 * FieldPalette — unit tests (task 6.1).
 *
 * Verifies the palette in isolation:
 *   • offers all six supported field types as controls (R2.1);
 *   • tap-to-arm reports the chosen type and reflects the armed state (R2.1);
 *   • drag-to-add writes the field type onto the drag payload (R3.1 wiring);
 *   • every control meets the 44×44 px minimum target (R10.1).
 *
 * _Requirements: 2.1, 10.1_
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import FieldPalette, { FIELD_TYPE_DRAG_MIME } from './FieldPalette'
import { FIELD_TYPES } from './hooks/useFieldSet'

describe('FieldPalette', () => {
  it('offers all six supported field types (R2.1)', () => {
    render(<FieldPalette armedType={null} onArm={() => {}} />)
    for (const type of FIELD_TYPES) {
      expect(screen.getByTestId(`palette-${type}`)).toBeInTheDocument()
    }
    expect(FIELD_TYPES).toHaveLength(6)
  })

  it('arms a type on tap and reports it to the parent (R2.1)', () => {
    const onArm = vi.fn()
    render(<FieldPalette armedType={null} onArm={onArm} />)

    fireEvent.click(screen.getByTestId('palette-signature'))
    expect(onArm).toHaveBeenCalledWith('signature')
  })

  it('reflects the armed type via aria-pressed (R2.1)', () => {
    render(<FieldPalette armedType="date" onArm={() => {}} />)

    expect(screen.getByTestId('palette-date')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('palette-text')).toHaveAttribute('aria-pressed', 'false')
  })

  it('writes the field type onto the drag payload on drag start (R3.1 wiring)', () => {
    render(<FieldPalette armedType={null} onArm={() => {}} />)

    const setData = vi.fn()
    fireEvent.dragStart(screen.getByTestId('palette-text'), {
      dataTransfer: { setData, effectAllowed: 'none' },
    })
    expect(setData).toHaveBeenCalledWith(FIELD_TYPE_DRAG_MIME, 'text')
  })

  it('renders each control with a ≥44×44 px target (R10.1)', () => {
    render(<FieldPalette armedType={null} onArm={() => {}} />)
    for (const type of FIELD_TYPES) {
      const btn = screen.getByTestId(`palette-${type}`)
      expect(btn.className).toContain('min-h-[44px]')
      expect(btn.className).toContain('min-w-[44px]')
    }
  })

  it('disables every control when disabled', () => {
    render(<FieldPalette armedType={null} onArm={() => {}} disabled />)
    for (const type of FIELD_TYPES) {
      expect(screen.getByTestId(`palette-${type}`)).toBeDisabled()
    }
  })
})
