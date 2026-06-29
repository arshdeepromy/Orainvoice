/**
 * DependencyInspector — example tests (task 17.5).
 *
 * Covers the conditional / dependent-fields panel:
 *   • an empty state renders when no field is selected;
 *   • the advisory notice is always shown for a selected field (R14.7);
 *   • the Trigger_Field picker offers every OTHER field but never the dependent
 *     itself (R14.2);
 *   • a valid rule is routed through `addDependency` and fires `onAddDependency`
 *     with the chosen trigger / condition / effect (R14.1, R14.3);
 *   • a `value` is carried only for `equals` / `not_equals` conditions (R14.3);
 *   • an edge that closes a cycle is rejected inline and never recorded (R14.4);
 *   • existing rules for the field render and fire `onRemoveDependency`.
 *
 * Vitest + React Testing Library.
 *
 * _Requirements: 14.1, 14.2, 14.3, 14.4, 14.7_
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { DependencyInspector } from './DependencyInspector'
import type { FieldDependency } from '../lib/dependencyGraph'
import type { PlacedField } from './hooks/useFieldSet'

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

const CHECKBOX = makeField({ clientId: 'f_trigger', type: 'text', label: 'Agree' })
const DEPENDENT = makeField({ clientId: 'f_dep', type: 'text', label: 'Reason' })
const FIELDS: PlacedField[] = [CHECKBOX, DEPENDENT]

function setup(opts: {
  field: PlacedField | null
  dependencies?: FieldDependency[]
}) {
  const handlers = {
    onAddDependency: vi.fn(),
    onRemoveDependency: vi.fn(),
  }
  render(
    <DependencyInspector
      field={opts.field}
      fields={FIELDS}
      dependencies={opts.dependencies ?? []}
      {...handlers}
    />,
  )
  return handlers
}

describe('DependencyInspector', () => {
  it('shows an empty prompt when nothing is selected', () => {
    setup({ field: null })
    expect(screen.getByTestId('dependency-inspector-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('dependency-inspector')).not.toBeInTheDocument()
  })

  it('always shows the advisory notice for a selected field (R14.7)', () => {
    setup({ field: DEPENDENT })
    expect(screen.getByTestId('dependency-advisory-notice')).toBeInTheDocument()
    expect(screen.getByTestId('dependency-advisory-notice')).toHaveTextContent(/not enforced/i)
  })

  it('offers every other field as a trigger but never the dependent itself (R14.2)', () => {
    setup({ field: DEPENDENT })
    const select = screen.getByLabelText('When this field') as HTMLSelectElement
    const optionValues = Array.from(select.options).map((o) => o.value)
    expect(optionValues).toContain('f_trigger')
    expect(optionValues).not.toContain('f_dep')
  })

  it('records a valid rule through addDependency with the chosen trigger/condition/effect', () => {
    const { onAddDependency } = setup({ field: DEPENDENT })

    fireEvent.change(screen.getByLabelText('When this field'), {
      target: { value: 'f_trigger' },
    })
    fireEvent.change(screen.getByLabelText('Condition'), { target: { value: 'is_checked' } })
    fireEvent.change(screen.getByLabelText('Then'), { target: { value: 'require' } })
    fireEvent.click(screen.getByText('Add rule'))

    expect(onAddDependency).toHaveBeenCalledTimes(1)
    expect(onAddDependency).toHaveBeenCalledWith({
      dependentClientId: 'f_dep',
      triggerClientId: 'f_trigger',
      condition: 'is_checked',
      effect: 'require',
    })
  })

  it('carries a comparison value for equals/not_equals conditions (R14.3)', () => {
    const { onAddDependency } = setup({ field: DEPENDENT })

    fireEvent.change(screen.getByLabelText('When this field'), {
      target: { value: 'f_trigger' },
    })
    fireEvent.change(screen.getByLabelText('Condition'), { target: { value: 'equals' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'Yes' } })
    fireEvent.click(screen.getByText('Add rule'))

    expect(onAddDependency).toHaveBeenCalledWith({
      dependentClientId: 'f_dep',
      triggerClientId: 'f_trigger',
      condition: 'equals',
      effect: 'show',
      value: 'Yes',
    })
  })

  it('rejects a cycle-closing rule inline and does not record it (R14.4)', () => {
    // Existing edge: f_trigger depends on f_dep. Adding f_dep → f_trigger closes a cycle.
    const existing: FieldDependency[] = [
      {
        dependentClientId: 'f_trigger',
        triggerClientId: 'f_dep',
        condition: 'is_checked',
        effect: 'show',
      },
    ]
    const { onAddDependency } = setup({ field: DEPENDENT, dependencies: existing })

    fireEvent.change(screen.getByLabelText('When this field'), {
      target: { value: 'f_trigger' },
    })
    fireEvent.click(screen.getByText('Add rule'))

    expect(onAddDependency).not.toHaveBeenCalled()
    expect(screen.getByTestId('dependency-error')).toHaveTextContent(/circular/i)
  })

  it('renders existing rules for the field and removes them', () => {
    const existing: FieldDependency[] = [
      {
        dependentClientId: 'f_dep',
        triggerClientId: 'f_trigger',
        condition: 'is_checked',
        effect: 'require',
      },
    ]
    const { onRemoveDependency } = setup({ field: DEPENDENT, dependencies: existing })

    expect(screen.getByTestId('dependency-row')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Remove'))
    expect(onRemoveDependency).toHaveBeenCalledWith(0)
  })
})
