/**
 * Accessibility — example tests (task 6.8).
 *
 * Covers the two accessibility guarantees the editor's interactive surfaces
 * must hold, across the field-placement components (FieldPalette,
 * RecipientLegend, FieldInspector, FieldOverlay):
 *
 *   • every interactive Field control and palette control meets the 44×44 CSS
 *     px minimum target size (R10.1) — asserted via the `min-h-[44px]` /
 *     `min-w-[44px]` Tailwind classes (palette / legend / inspector) and the
 *     inline `minWidth`/`minHeight` styles on the overlay box + resize handle;
 *   • a selected field's accessible name conveys its Field_Type and its
 *     assigned Recipient (R10.4), e.g. `"Signature field for Alex Tran"`.
 *
 * `jest-axe` / `vitest-axe` is not a dependency of `frontend-v2`, so this suite
 * asserts the concrete touch-target sizing and accessible-name wiring directly
 * (rather than a generic axe no-violations sweep).
 *
 * Vitest + React Testing Library.
 *
 * _Requirements: 10.1, 10.4_
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import FieldPalette from './FieldPalette'
import RecipientLegend, { type LegendRecipient } from './RecipientLegend'
import { FieldInspector, type InspectorRecipient } from './FieldInspector'
import FieldOverlay, { type FieldOverlayRecipient } from './FieldOverlay'
import { FIELD_TYPES, type FieldType, type PlacedField } from './hooks/useFieldSet'
import type { PageDims } from './lib/coordinateMapping'

/** A page big enough that the 44px-min overlay box is not the dominant size. */
const DIMS: PageDims = { cssWidth: 600, cssHeight: 800 }

const LEGEND_RECIPIENTS: LegendRecipient[] = [
  { key: 10, name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' },
  { key: 20, name: 'Sam Lee', email: 'sam@example.com', signing_role: 'viewer' },
]

const INSPECTOR_RECIPIENTS: InspectorRecipient[] = [
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

/** Asserts a 44×44 px minimum target via Tailwind min-size classes. */
function expectMinTargetClasses(el: HTMLElement) {
  expect(el.className).toContain('min-h-[44px]')
  expect(el.className).toContain('min-w-[44px]')
}

describe('Field-placement accessibility — 44×44 px touch targets (R10.1)', () => {
  it('renders every palette control with a ≥44×44 px target', () => {
    render(<FieldPalette armedType={null} onArm={() => {}} />)
    for (const type of FIELD_TYPES) {
      expectMinTargetClasses(screen.getByTestId(`palette-${type}`))
    }
  })

  it('renders every recipient picker control with a ≥44 px target', () => {
    render(
      <RecipientLegend
        recipients={LEGEND_RECIPIENTS}
        activeRecipientKey={10}
        onSelectRecipient={() => {}}
      />,
    )
    for (const r of LEGEND_RECIPIENTS) {
      // Legend rows are full-width and ≥44 px tall (height is the constrained
      // dimension for a horizontal row).
      expect(screen.getByTestId(`recipient-${r.key}`).className).toContain('min-h-[44px]')
    }
  })

  it('renders every inspector control with a ≥44×44 px target', () => {
    render(
      <FieldInspector
        field={makeField({ type: 'text', required: false })}
        recipients={INSPECTOR_RECIPIENTS}
        onAssign={() => {}}
        onSetRequired={() => {}}
        onSetTextMeta={() => {}}
        onDelete={() => {}}
      />,
    )
    // Recipient select, required switch, label + placeholder inputs, delete.
    expectMinTargetClasses(screen.getByLabelText('Assigned to'))
    expectMinTargetClasses(screen.getByRole('switch'))
    expectMinTargetClasses(screen.getByLabelText('Label'))
    expectMinTargetClasses(screen.getByLabelText('Placeholder'))
    expectMinTargetClasses(screen.getByRole('button', { name: /delete this text field/i }))
  })

  it('renders the field box and its resize handle at ≥44×44 px (inline min-size)', () => {
    const recipient: FieldOverlayRecipient = { index: 0, name: 'Alex Tran' }
    render(
      <FieldOverlay
        field={makeField()}
        dims={DIMS}
        selected
        recipient={recipient}
        onMove={() => {}}
        onResize={() => {}}
        onSelect={() => {}}
        onDelete={() => {}}
      />,
    )

    const box = screen.getByTestId('field-overlay-f_1')
    expect(box.style.minWidth).toBe('44px')
    expect(box.style.minHeight).toBe('44px')

    const handle = screen.getByTestId('field-resize-f_1')
    expect(handle.style.width).toBe('44px')
    expect(handle.style.height).toBe('44px')
  })
})

describe('Field-placement accessibility — selected field accessible name (R10.4)', () => {
  it("conveys the field's type and assigned recipient by name", () => {
    const recipient: FieldOverlayRecipient = { index: 0, name: 'Alex Tran' }
    render(
      <FieldOverlay
        field={makeField({ type: 'signature' })}
        dims={DIMS}
        selected
        recipient={recipient}
        onMove={() => {}}
        onResize={() => {}}
        onSelect={() => {}}
        onDelete={() => {}}
      />,
    )
    expect(
      screen.getByRole('button', { name: 'Signature field for Alex Tran' }),
    ).toBeInTheDocument()
  })

  it('reflects each field type in the accessible name', () => {
    const recipient: FieldOverlayRecipient = { index: 1, name: 'Sam Lee' }
    const expectedLabels: Record<FieldType, string> = {
      signature: 'Signature',
      initials: 'Initials',
      name: 'Name',
      date: 'Date',
      email: 'Email',
      text: 'Text',
      number: 'Number',
      radio: 'Radio',
      checkbox: 'Checkbox',
      dropdown: 'Dropdown',
    }
    for (const type of FIELD_TYPES) {
      const { unmount } = render(
        <FieldOverlay
          field={makeField({ clientId: `f_${type}`, type })}
          dims={DIMS}
          selected
          recipient={recipient}
          onMove={() => {}}
          onResize={() => {}}
          onSelect={() => {}}
          onDelete={() => {}}
        />,
      )
      expect(
        screen.getByRole('button', { name: `${expectedLabels[type]} field for Sam Lee` }),
      ).toBeInTheDocument()
      unmount()
    }
  })

  it('falls back to email, then a generic label, when no name is set', () => {
    const { unmount } = render(
      <FieldOverlay
        field={makeField({ clientId: 'f_email' })}
        dims={DIMS}
        selected
        recipient={{ index: 0, email: 'alex@example.com' }}
        onMove={() => {}}
        onResize={() => {}}
        onSelect={() => {}}
        onDelete={() => {}}
      />,
    )
    expect(
      screen.getByRole('button', { name: 'Signature field for alex@example.com' }),
    ).toBeInTheDocument()
    unmount()

    render(
      <FieldOverlay
        field={makeField({ clientId: 'f_generic' })}
        dims={DIMS}
        selected
        recipient={{ index: 2 }}
        onMove={() => {}}
        onResize={() => {}}
        onSelect={() => {}}
        onDelete={() => {}}
      />,
    )
    expect(
      screen.getByRole('button', { name: 'Signature field for recipient 3' }),
    ).toBeInTheDocument()
  })
})
