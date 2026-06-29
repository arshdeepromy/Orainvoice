/**
 * FieldInspector — example tests (task 6.3).
 *
 * Covers the per-field property controls the inspector exposes:
 *   • recipient re-assignment fires `onAssign` with the chosen recipient (R4.3);
 *   • the required switch fires `onSetRequired` with the toggled value (R5.1);
 *   • label/placeholder inputs show for `text` fields and fire `onSetTextMeta`
 *     (R5.2), and are hidden for non-text fields;
 *   • the delete control fires `onDelete` (R3.4);
 *   • an empty state renders when no field is selected.
 *
 * Vitest + React Testing Library.
 *
 * _Requirements: 4.3, 5.1, 5.2, 3.4, 10.1_
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { FieldInspector, type InspectorRecipient } from './FieldInspector'
import type { PlacedField } from './hooks/useFieldSet'

const RECIPIENTS: InspectorRecipient[] = [
  { key: 10, name: 'Alex Tran' },
  { key: 20, name: 'Sam Lee' },
]

function makeField(overrides: Partial<PlacedField> = {}): PlacedField {
  return {
    clientId: 'f_1',
    type: 'signature',
    page: 1,
    rect: { positionX: 10, positionY: 10, width: 20, height: 8 },
    recipientKey: 10,
    required: true,
    ...overrides,
  }
}

function setup(field: PlacedField | null) {
  const handlers = {
    onAssign: vi.fn(),
    onSetRequired: vi.fn(),
    onSetTextMeta: vi.fn(),
    onDelete: vi.fn(),
  }
  render(<FieldInspector field={field} recipients={RECIPIENTS} {...handlers} />)
  return handlers
}

describe('FieldInspector', () => {
  it('shows an empty prompt when nothing is selected', () => {
    setup(null)
    expect(screen.getByTestId('field-inspector-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('field-inspector')).not.toBeInTheDocument()
  })

  it('re-assigns the field to the chosen recipient (R4.3)', () => {
    const { onAssign } = setup(makeField())
    const select = screen.getByLabelText('Assigned to') as HTMLSelectElement
    expect(select.value).toBe('10')
    fireEvent.change(select, { target: { value: '20' } })
    expect(onAssign).toHaveBeenCalledWith('f_1', 20)
  })

  it('toggles the required flag (R5.1)', () => {
    const { onSetRequired } = setup(makeField({ required: true }))
    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(toggle)
    expect(onSetRequired).toHaveBeenCalledWith('f_1', false)
  })

  it('shows label + placeholder inputs only for text fields and fires onSetTextMeta (R5.2)', () => {
    const { onSetTextMeta } = setup(makeField({ type: 'text', required: false }))
    const label = screen.getByLabelText('Label')
    fireEvent.change(label, { target: { value: 'Job reference' } })
    expect(onSetTextMeta).toHaveBeenCalledWith('f_1', 'Job reference', undefined)

    const placeholder = screen.getByLabelText('Placeholder')
    fireEvent.change(placeholder, { target: { value: 'Enter the job number' } })
    expect(onSetTextMeta).toHaveBeenCalledWith('f_1', undefined, 'Enter the job number')
  })

  it('hides text metadata inputs for non-text fields', () => {
    setup(makeField({ type: 'signature' }))
    expect(screen.queryByLabelText('Label')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Placeholder')).not.toBeInTheDocument()
  })

  it('deletes the field (R3.4)', () => {
    const { onDelete } = setup(makeField())
    fireEvent.click(screen.getByRole('button', { name: /delete this signature field/i }))
    expect(onDelete).toHaveBeenCalledWith('f_1')
  })
})
