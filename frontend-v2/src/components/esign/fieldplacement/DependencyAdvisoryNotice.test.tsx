/**
 * Advisory-notice example tests (Task 17.9, R14.7).
 *
 * The conditional / dependent-fields model is **advisory** only: Documenso has
 * no cross-field conditional primitive, so a Field_Dependency is recorded for
 * the Org_Sender's reference but is NOT enforced during signing — every field
 * is shown to the recipient unconditionally, and a `require`-effect dependency
 * degrades to optional (R14.6–R14.8). The product must surface this prominently
 * (R14.7).
 *
 * These focused example tests assert that the advisory notice is present and
 * visible at both surfaces that R14.7 covers:
 *
 *   • the {@link DependencyInspector} panel shows a prominent advisory notice
 *     (`data-testid="dependency-advisory-notice"`) for a selected field, whose
 *     copy makes clear the rules are "not enforced" during signing;
 *   • the {@link FieldPlacementEditor} renders an editor-level advisory banner
 *     (`data-testid="dependency-advisory-banner"`) once at least one dependency
 *     exists, regardless of the current selection.
 *
 * This complements `DependencyInspector.test.tsx` (Task 17.5) by isolating the
 * R14.7 advisory-notice behaviour as its own example, including the end-to-end
 * editor surfacing once a rule is added.
 *
 * Vitest + React Testing Library. `pdfjs-dist` is mocked (module + `?url`
 * worker asset) using the same pattern as `EditFlow.test.tsx` /
 * `PdfRendering.test.tsx`, so the editor mounts without a real PDF engine.
 *
 * _Requirements: 14.7_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { DependencyInspector } from './DependencyInspector'
import FieldPlacementEditor from './FieldPlacementEditor'
import type { PlacedField } from './hooks/useFieldSet'
import type { EnvelopeFieldsOut, FieldOut, RecipientOut } from '@/api/esign'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset) — shared pattern       */
/* ------------------------------------------------------------------ */

const pdfMock = vi.hoisted(() => ({
  state: { numPages: 1, pageWidth: 600, pageHeight: 800 },
}))

vi.mock('pdfjs-dist', () => {
  const GlobalWorkerOptions = { workerSrc: '' as string }

  const makePage = () => ({
    getViewport: ({ scale }: { scale: number }) => ({
      width: pdfMock.state.pageWidth * scale,
      height: pdfMock.state.pageHeight * scale,
    }),
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
  })

  const makeDoc = () => ({
    numPages: pdfMock.state.numPages,
    getPage: vi.fn(async () => makePage()),
    destroy: vi.fn(),
  })

  const getDocument = vi.fn(() => ({
    promise: Promise.resolve(makeDoc()),
    destroy: vi.fn(),
  }))

  return { GlobalWorkerOptions, getDocument }
})

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'mock-worker-url' }))

/* ------------------------------------------------------------------ */
/*  DependencyInspector — the panel-level advisory notice (R14.7)       */
/* ------------------------------------------------------------------ */

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

describe('DependencyInspector — advisory notice (R14.7)', () => {
  it('shows a prominent, visible advisory notice for a selected field', () => {
    const dependent = makeField({ clientId: 'f_dep', type: 'text', label: 'Reason' })
    const trigger = makeField({ clientId: 'f_trigger', type: 'text', label: 'Agree' })

    render(
      <DependencyInspector
        field={dependent}
        fields={[trigger, dependent]}
        dependencies={[]}
        onAddDependency={vi.fn()}
        onRemoveDependency={vi.fn()}
      />,
    )

    const notice = screen.getByTestId('dependency-advisory-notice')
    expect(notice).toBeInTheDocument()
    expect(notice).toBeVisible()
    // The copy must make the advisory nature unambiguous (R14.7).
    expect(notice).toHaveTextContent(/not enforced/i)
  })
})

/* ------------------------------------------------------------------ */
/*  FieldPlacementEditor — the editor-level advisory banner (R14.7)     */
/* ------------------------------------------------------------------ */

/** A minimal File whose only used method is `arrayBuffer()` (editor path). */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

function signerRecipient(): RecipientOut {
  return {
    id: 'rcpt-1',
    name: 'Alex Tran',
    email: 'alex@example.com',
    signing_role: 'SIGNER',
    recipient_status: 'pending',
  }
}

/** Two text fields assigned to the same recipient so a dependency is possible. */
function textField(overrides: Partial<FieldOut> = {}): FieldOut {
  return {
    type: 'text',
    page: 1,
    recipient_index: 0,
    position_x: 10,
    position_y: 20,
    width: 25,
    height: 8,
    required: true,
    ...overrides,
  }
}

/** An editable `GET …/fields` response seeding two fields (so a trigger exists). */
function twoFieldEnvelope(): EnvelopeFieldsOut {
  return {
    fields: [textField({ position_y: 20 }), textField({ position_y: 50 })],
    recipients: [signerRecipient()],
    editable: true,
  }
}

function overlays(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-testid^="field-overlay-"]'))
}

beforeEach(() => {
  vi.clearAllMocks()
  pdfMock.state.numPages = 1
  pdfMock.state.pageWidth = 600
  pdfMock.state.pageHeight = 800

  HTMLCanvasElement.prototype.getContext = vi.fn(
    () => ({}) as unknown as CanvasRenderingContext2D,
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext

  if (!HTMLElement.prototype.setPointerCapture) {
    HTMLElement.prototype.setPointerCapture = vi.fn()
  }
  if (!HTMLElement.prototype.releasePointerCapture) {
    HTMLElement.prototype.releasePointerCapture = vi.fn()
  }
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('FieldPlacementEditor — advisory banner once a dependency exists (R14.7)', () => {
  it('surfaces the editor-level advisory banner after a conditional rule is added', async () => {
    const getEnvelopeFieldsFn = vi.fn(async () => twoFieldEnvelope())

    render(
      <FieldPlacementEditor
        file={makePdfFile()}
        recipients={[]}
        envelopeId="env-1"
        getEnvelopeFieldsFn={getEnvelopeFieldsFn}
        replaceEnvelopeFieldsFn={vi.fn(async () => [textField()])}
      />,
    )

    // Two seeded fields → two overlays; no banner until a dependency exists.
    await waitFor(() => expect(overlays()).toHaveLength(2))
    expect(screen.queryByTestId('dependency-advisory-banner')).toBeNull()

    // Select a field so the DependencyInspector renders its add form. The
    // overlay selects on focus / pointer-down (not click).
    fireEvent.focus(overlays()[0])
    await screen.findByTestId('dependency-inspector')

    // Add a conditional rule: pick the only other field as the trigger.
    const triggerSelect = screen.getByLabelText('When this field') as HTMLSelectElement
    const triggerValue = Array.from(triggerSelect.options)
      .map((o) => o.value)
      .find((v) => v !== '')
    expect(triggerValue).toBeTruthy()
    fireEvent.change(triggerSelect, { target: { value: triggerValue } })
    fireEvent.click(screen.getByText('Add rule'))

    // The editor-level advisory banner now appears and reads "not enforced".
    const banner = await screen.findByTestId('dependency-advisory-banner')
    expect(banner).toBeVisible()
    expect(banner).toHaveTextContent(/not enforced/i)
  })
})
