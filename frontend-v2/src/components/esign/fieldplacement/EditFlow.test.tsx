/**
 * Edit-after-send flow — example tests (Task 16.8, R13).
 *
 * Exercises the `FieldPlacementEditor` in **edit mode** (an `envelopeId` is
 * supplied) against the live orchestrator (Task 6.4 + the edit wiring of
 * Task 16.7), driving the seed / replace / void paths through injected
 * `getEnvelopeFieldsFn` / `replaceEnvelopeFieldsFn` / `voidEnvelopeFn` stubs so
 * nothing touches the network.
 *
 * Covers:
 *   • R13.1 / R13.3 — opening on an editable envelope seeds the Field_Set +
 *     recipients from `GET …/fields` and submits the edited set via
 *     `PUT …/fields` (the send control is labelled "Save changes" in edit mode);
 *   • R13.4 / R13.5 — when the GET reports `editable: false`, the
 *     Non_Editable_State banner shows and **Void & recreate** is offered;
 *     clicking it calls `voidEnvelope` and fires `onVoidAndRecreate` with a copy
 *     of the read Field_Set + recipients for a fresh pre-populated send;
 *   • R13.4 (race) — a `PUT …/fields` that comes back with code `not_editable`
 *     (someone signed meanwhile) flips the editor into the Non_Editable_State.
 *
 * `pdfjs-dist` is mocked (the module the hook imports as `* as pdfjsLib` plus
 * the `?url` worker asset) using the same pattern as `PdfRendering.test.tsx` /
 * `AutosaveCancelRetry.test.tsx`, so the document/page lifecycle is
 * deterministic without a real PDF engine. jsdom implements neither canvas 2d
 * nor Pointer Capture, so `getContext`, `setPointerCapture`, and
 * `releasePointerCapture` are stubbed.
 *
 * These are example tests (Vitest + React Testing Library), not property tests.
 *
 * _Requirements: 13.1, 13.4, 13.5_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import FieldPlacementEditor from './FieldPlacementEditor'
import type {
  EnvelopeFieldsOut,
  EnvelopeOut,
  FieldOut,
  FieldSetReplace,
  RecipientOut,
} from '@/api/esign'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset) — shared pattern       */
/* ------------------------------------------------------------------ */

const pdfMock = vi.hoisted(() => ({
  state: {
    numPages: 1,
    pageWidth: 600,
    pageHeight: 800,
  },
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
/*  Fixtures + helpers                                                 */
/* ------------------------------------------------------------------ */

/** A minimal File whose only used method is `arrayBuffer()` (editor path). */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

/** One signer recipient as read back from the envelope (UPPERCASE role). */
function signerRecipient(): RecipientOut {
  return {
    id: 'rcpt-1',
    name: 'Alex Tran',
    email: 'alex@example.com',
    signing_role: 'SIGNER',
    recipient_status: 'pending',
  }
}

/** One valid signature field assigned to recipient index 0. */
function signatureField(): FieldOut {
  return {
    type: 'signature',
    page: 1,
    recipient_index: 0,
    position_x: 10,
    position_y: 20,
    width: 25,
    height: 8,
    required: true,
  }
}

/** A `GET …/fields` response for an editable envelope (R13.1). */
function editableFields(): EnvelopeFieldsOut {
  return {
    fields: [signatureField()],
    recipients: [signerRecipient()],
    editable: true,
  }
}

/** A `GET …/fields` response for a Non_Editable_State envelope (R13.4). */
function nonEditableFields(): EnvelopeFieldsOut {
  return {
    fields: [signatureField()],
    recipients: [signerRecipient()],
    editable: false,
  }
}

/** A voided envelope, as `voidEnvelope` resolves it. */
function voidedEnvelope(): EnvelopeOut {
  return {
    id: 'env-1',
    agreement_type: 'nda',
    originating_entity_type: 'staff',
    originating_entity_id: 'staff-7',
    status: 'voided',
    recipients: [signerRecipient()],
    signed_document_url: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

/** All placed-field overlays currently in the DOM. */
function overlays(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>('[data-testid^="field-overlay-"]'),
  )
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/*  R13.1 / R13.3 — seed from GET, submit via PUT                       */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — edit mode seeds from GET and submits via PUT (R13.1, R13.3)', () => {
  it('seeds the Field_Set + recipients from getEnvelopeFields when opened on an editable envelope', async () => {
    const getEnvelopeFieldsFn = vi.fn(async () => editableFields())
    const replaceEnvelopeFieldsFn = vi.fn(async () => [signatureField()])

    render(
      <FieldPlacementEditor
        file={makePdfFile()}
        recipients={[]}
        envelopeId="env-1"
        getEnvelopeFieldsFn={getEnvelopeFieldsFn}
        replaceEnvelopeFieldsFn={replaceEnvelopeFieldsFn}
      />,
    )

    // The editor reads the live field set for the envelope (R13.1)…
    await waitFor(() => expect(getEnvelopeFieldsFn).toHaveBeenCalledTimes(1))
    expect(getEnvelopeFieldsFn).toHaveBeenCalledWith('env-1', expect.any(AbortSignal))

    // …and seeds it: the signature field appears as an overlay.
    await waitFor(() => expect(overlays()).toHaveLength(1))
    expect(overlays()[0]).toHaveAttribute('data-field-type', 'signature')

    // In edit mode the send control is labelled "Save changes" (not the create label).
    const saveBtn = screen.getByTestId('send-for-signature')
    expect(saveBtn).toHaveTextContent('Save changes')

    // No Non_Editable_State banner for an editable envelope.
    expect(screen.queryByTestId('non-editable-banner')).toBeNull()
  })

  it('submits the edited Field_Set via replaceEnvelopeFields (PUT) on save', async () => {
    const getEnvelopeFieldsFn = vi.fn(async () => editableFields())
    const replaceEnvelopeFieldsFn = vi.fn(async () => [signatureField()])
    const onEdited = vi.fn()

    render(
      <FieldPlacementEditor
        file={makePdfFile()}
        recipients={[]}
        envelopeId="env-1"
        getEnvelopeFieldsFn={getEnvelopeFieldsFn}
        replaceEnvelopeFieldsFn={replaceEnvelopeFieldsFn}
        onEdited={onEdited}
      />,
    )

    await waitFor(() => expect(overlays()).toHaveLength(1))

    const saveBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(saveBtn).toBeEnabled())
    fireEvent.click(saveBtn)

    // The edit submits through PUT …/fields — not the create endpoint (R13.3).
    await waitFor(() => expect(replaceEnvelopeFieldsFn).toHaveBeenCalledTimes(1))
    const [envelopeId, body, signal] = replaceEnvelopeFieldsFn.mock.calls[0] as unknown as [
      string,
      FieldSetReplace,
      AbortSignal,
    ]
    expect(envelopeId).toBe('env-1')
    expect(signal).toBeInstanceOf(AbortSignal)
    // The submitted set carries exactly the seeded signature field, mapped to
    // its recipient by index.
    expect(body.fields).toHaveLength(1)
    expect(body.fields[0]).toMatchObject({ type: 'signature', recipient_index: 0 })

    // The success callback fires with the field set read back from Documenso.
    await waitFor(() => expect(onEdited).toHaveBeenCalledTimes(1))
  })
})

/* ------------------------------------------------------------------ */
/*  R13.4 / R13.5 — Non_Editable_State banner + Void & recreate         */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — Non_Editable_State banner + Void & recreate (R13.4, R13.5)', () => {
  it('shows the Non_Editable_State banner and offers Void & recreate when the envelope is not editable', async () => {
    const getEnvelopeFieldsFn = vi.fn(async () => nonEditableFields())
    const replaceEnvelopeFieldsFn = vi.fn(async () => [signatureField()])

    render(
      <FieldPlacementEditor
        file={makePdfFile()}
        recipients={[]}
        envelopeId="env-1"
        getEnvelopeFieldsFn={getEnvelopeFieldsFn}
        replaceEnvelopeFieldsFn={replaceEnvelopeFieldsFn}
      />,
    )

    // editable: false → the banner appears and Void & recreate is offered (R13.4).
    await screen.findByTestId('non-editable-banner')
    expect(screen.getByTestId('void-and-recreate')).toBeInTheDocument()

    // The send control is disabled in a Non_Editable_State (no in-place edit).
    expect(screen.getByTestId('send-for-signature')).toBeDisabled()
  })

  it('voids the envelope and fires onVoidAndRecreate with the read Field_Set when Void & recreate is clicked', async () => {
    const getEnvelopeFieldsFn = vi.fn(async () => nonEditableFields())
    const voidEnvelopeFn = vi.fn(async () => voidedEnvelope())
    const onVoidAndRecreate = vi.fn()

    render(
      <FieldPlacementEditor
        file={makePdfFile()}
        recipients={[]}
        envelopeId="env-1"
        getEnvelopeFieldsFn={getEnvelopeFieldsFn}
        voidEnvelopeFn={voidEnvelopeFn}
        onVoidAndRecreate={onVoidAndRecreate}
      />,
    )

    const voidBtn = await screen.findByTestId('void-and-recreate')
    fireEvent.click(voidBtn)

    // The existing void path is invoked (R13.5)…
    await waitFor(() => expect(voidEnvelopeFn).toHaveBeenCalledTimes(1))
    expect(voidEnvelopeFn).toHaveBeenCalledWith('env-1', expect.any(AbortSignal))

    // …then a fresh send is pre-populated with a copy of the read Field_Set +
    // recipients (R13.5).
    await waitFor(() => expect(onVoidAndRecreate).toHaveBeenCalledTimes(1))
    const seed = onVoidAndRecreate.mock.calls[0][0] as {
      fields: { type: string }[]
      recipients: { signing_role: string }[]
    }
    expect(seed.fields).toHaveLength(1)
    expect(seed.fields[0]).toMatchObject({ type: 'signature' })
    expect(seed.recipients).toHaveLength(1)
    expect(seed.recipients[0]).toMatchObject({ signing_role: 'signer' })
  })
})

/* ------------------------------------------------------------------ */
/*  R13.4 (race) — a PUT returning `not_editable` flips into the state  */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — a racing not_editable PUT flips into the Non_Editable_State (R13.4)', () => {
  it('shows the Non_Editable_State banner when the save returns code not_editable', async () => {
    const getEnvelopeFieldsFn = vi.fn(async () => editableFields())
    // The envelope was editable on load, but someone signed before the save
    // landed — the PUT comes back with the humanized `not_editable` code.
    const replaceEnvelopeFieldsFn = vi.fn(async () => {
      throw {
        response: {
          data: {
            message:
              'This document can no longer be edited because signing has begun.',
            code: 'not_editable',
          },
        },
      }
    })

    render(
      <FieldPlacementEditor
        file={makePdfFile()}
        recipients={[]}
        envelopeId="env-1"
        getEnvelopeFieldsFn={getEnvelopeFieldsFn}
        replaceEnvelopeFieldsFn={replaceEnvelopeFieldsFn}
      />,
    )

    // Seeded as editable — no banner yet, save is enabled.
    await waitFor(() => expect(overlays()).toHaveLength(1))
    expect(screen.queryByTestId('non-editable-banner')).toBeNull()

    const saveBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(saveBtn).toBeEnabled())
    fireEvent.click(saveBtn)

    // The racing `not_editable` response flips the editor into the
    // Non_Editable_State: the banner appears and Void & recreate is offered.
    await screen.findByTestId('non-editable-banner')
    expect(screen.getByTestId('void-and-recreate')).toBeInTheDocument()
    await waitFor(() => expect(replaceEnvelopeFieldsFn).toHaveBeenCalledTimes(1))
  })
})
