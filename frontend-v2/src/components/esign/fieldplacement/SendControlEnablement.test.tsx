/**
 * Send-control enablement — example tests (Task 3.2).
 *
 * Exercises the pure client-side `validateFieldSet` (Task 3.1) the way the
 * Field_Placement_Editor will: a "Send for signature" control whose `disabled`
 * state is driven entirely by the validation result. The editor orchestrator
 * (Task 6) isn't built yet, so these tests mount a tiny harness that wires
 * `validateFieldSet` to a disabled/enabled send button plus controls that
 * mutate the Field_Set the same way the editor's actions will.
 *
 * Covers:
 *   • an invalid Field_Set keeps the send control disabled (R6.4);
 *   • correcting *every* validation failure enables the send control (R6.5),
 *     and correcting only *some* failures leaves it disabled until the last.
 *
 * These are example tests (Vitest + React Testing Library), not property tests.
 *
 * _Requirements: 6.4, 6.5_
 */
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'

import {
  validateFieldSet,
  type FieldValidationRecipient,
} from './lib/fieldValidation'
import type { FieldType, PlacedField } from './hooks/useFieldSet'

/* ------------------------------------------------------------------ */
/*  Test data helpers                                                  */
/* ------------------------------------------------------------------ */

let nextId = 0
/** Build a placed field with sensible, in-bounds defaults. */
function makeField(overrides: Partial<PlacedField> = {}): PlacedField {
  return {
    clientId: `f_${nextId++}`,
    type: 'signature' as FieldType,
    page: 1,
    rect: { positionX: 10, positionY: 10, width: 20, height: 8 },
    recipientKey: 0,
    required: true,
    ...overrides,
  }
}

const SIGNER: FieldValidationRecipient = { key: 0, signing_role: 'signer', name: 'Alex Tran' }
const VIEWER: FieldValidationRecipient = { key: 1, signing_role: 'viewer', name: 'Sam Lee' }

/* ------------------------------------------------------------------ */
/*  Harness: validateFieldSet drives a disabled/enabled send button    */
/* ------------------------------------------------------------------ */

interface HarnessProps {
  initialFields: PlacedField[]
  recipients: FieldValidationRecipient[]
  /** Editor-like mutations the test fires to correct each validation failure. */
  corrections: Record<string, (fields: PlacedField[]) => PlacedField[]>
}

/**
 * Stands in for the editor: holds the Field_Set in client state, re-runs
 * `validateFieldSet` on every render, and disables the send button whenever the
 * result is not `ok` (R6.4). Each "correction" button applies one editor-style
 * mutation so a test can drive the set from invalid → valid (R6.5).
 */
function SendControlHarness({ initialFields, recipients, corrections }: HarnessProps) {
  const [fields, setFields] = useState<PlacedField[]>(initialFields)
  const result = validateFieldSet(fields, recipients)

  return (
    <div>
      <ul data-testid="issues">
        {result.issues.map((issue, i) => (
          <li key={i} data-code={issue.code}>
            {issue.message}
          </li>
        ))}
      </ul>

      {Object.entries(corrections).map(([label, fn]) => (
        <button
          key={label}
          type="button"
          data-testid={`fix-${label}`}
          onClick={() => setFields((prev) => fn(prev))}
        >
          {label}
        </button>
      ))}

      <button type="button" data-testid="send" disabled={!result.ok}>
        Send for signature
      </button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('send-control enablement from validateFieldSet', () => {
  // R6.4 — a single-failure invalid Field_Set keeps send disabled; R6.5 — the
  // one correction enables it.
  it('keeps send disabled for a signer with no signature, and enables it once a signature is added', () => {
    // A signer whose only field is a (non-signature) name field → invalid.
    const initialFields = [makeField({ type: 'name', recipientKey: SIGNER.key })]

    render(
      <SendControlHarness
        initialFields={initialFields}
        recipients={[SIGNER]}
        corrections={{
          // Add the missing signature field for the signer.
          'add-signature': (fields) => [
            ...fields,
            makeField({ type: 'signature', recipientKey: SIGNER.key }),
          ],
        }}
      />,
    )

    // Invalid → disabled, and the offending signer is named (R6.1/R6.4).
    expect(screen.getByTestId('send')).toBeDisabled()
    const issue = screen.getByText(/Add a signature field for Alex Tran/i)
    expect(issue).toHaveAttribute('data-code', 'signature_field_missing')

    // Correct the only failure → enabled (R6.5).
    fireEvent.click(screen.getByTestId('fix-add-signature'))
    expect(screen.getByTestId('send')).toBeEnabled()
    expect(screen.queryByTestId('issues')?.children).toHaveLength(0)
  })

  // R6.4/R6.5 — with several independent failures, send stays disabled until
  // EVERY failure is corrected, not just some.
  it('stays disabled until the last of several failures is corrected', () => {
    const unassigned = makeField({ type: 'date', recipientKey: 99 }) // R6.2 — no such recipient
    const outOfBounds = makeField({
      type: 'date',
      recipientKey: SIGNER.key,
      rect: { positionX: 90, positionY: 10, width: 20, height: 8 }, // 90 + 20 > 100 (R6.3)
    })
    // No signature field for the signer → R6.1 failure as well.

    render(
      <SendControlHarness
        initialFields={[unassigned, outOfBounds]}
        recipients={[SIGNER, VIEWER]}
        corrections={{
          // R6.2 fix — assign the orphan field to the signer.
          assign: (fields) =>
            fields.map((f) =>
              f.clientId === unassigned.clientId ? { ...f, recipientKey: SIGNER.key } : f,
            ),
          // R6.3 fix — pull the out-of-bounds field back onto the page.
          'move-in-bounds': (fields) =>
            fields.map((f) =>
              f.clientId === outOfBounds.clientId
                ? { ...f, rect: { ...f.rect, positionX: 10 } }
                : f,
            ),
          // R6.1 fix — add the signer's signature field.
          'add-signature': (fields) => [
            ...fields,
            makeField({ type: 'signature', recipientKey: SIGNER.key }),
          ],
        }}
      />,
    )

    // Three independent failures up front → disabled.
    expect(screen.getByTestId('send')).toBeDisabled()
    const codes = () =>
      Array.from(screen.getByTestId('issues').children).map((li) => li.getAttribute('data-code'))
    expect(codes()).toEqual(
      expect.arrayContaining([
        'field_unassigned',
        'field_out_of_bounds',
        'signature_field_missing',
      ]),
    )

    // Correct them one at a time — still disabled while any failure remains.
    fireEvent.click(screen.getByTestId('fix-assign'))
    expect(screen.getByTestId('send')).toBeDisabled()

    fireEvent.click(screen.getByTestId('fix-move-in-bounds'))
    expect(screen.getByTestId('send')).toBeDisabled()

    // Last failure corrected → every rule holds → enabled (R6.5).
    fireEvent.click(screen.getByTestId('fix-add-signature'))
    expect(screen.getByTestId('send')).toBeEnabled()
    expect(screen.getByTestId('issues').children).toHaveLength(0)
  })

  // R4.6 — a viewer with no fields never blocks send: a valid set is enabled
  // from the start (the inverse case, so "disabled" isn't vacuously true).
  it('enables send for a valid Field_Set with a viewer that has no fields', () => {
    const fields = [makeField({ type: 'signature', recipientKey: SIGNER.key })]

    render(
      <SendControlHarness
        initialFields={fields}
        recipients={[SIGNER, VIEWER]}
        corrections={{}}
      />,
    )

    expect(screen.getByTestId('send')).toBeEnabled()
    expect(screen.getByTestId('issues').children).toHaveLength(0)
  })

  // A radio field with no options blocks send (mirrors the backend
  // field_options_missing rule); adding one option clears the failure.
  it('blocks send when a radio field has no options, and enables it once an option is added', () => {
    const fields = [
      makeField({ type: 'signature', recipientKey: SIGNER.key }),
      makeField({ type: 'radio', recipientKey: SIGNER.key, options: [] }),
    ]
    const radioId = fields[1].clientId

    render(
      <SendControlHarness
        initialFields={fields}
        recipients={[SIGNER]}
        corrections={{
          'add-option': (fs) =>
            fs.map((f) => (f.clientId === radioId ? { ...f, options: ['Yes'] } : f)),
        }}
      />,
    )

    // The radio with no options is invalid → disabled, with the options code.
    expect(screen.getByTestId('send')).toBeDisabled()
    const issue = screen.getByText(/Add at least one option to the radio field/i)
    expect(issue).toHaveAttribute('data-code', 'field_options_missing')

    // Authoring one option clears the only failure → enabled.
    fireEvent.click(screen.getByTestId('fix-add-option'))
    expect(screen.getByTestId('send')).toBeEnabled()
    expect(screen.getByTestId('issues').children).toHaveLength(0)
  })
})
