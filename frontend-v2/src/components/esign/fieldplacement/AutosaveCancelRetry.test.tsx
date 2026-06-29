/**
 * Autosave / cancel / retry — example tests (Task 13.3).
 *
 * Exercises the Field_Set lifecycle described by Requirement 11, end-to-end,
 * against the live `FieldPlacementEditor` orchestrator (Task 6.4) and the
 * two-step `SendForSignatureModal` (Task 13.2):
 *
 *   • R11.1 — the in-progress Field_Set is retained in client state across
 *     in-editor page navigation (the `useFieldSet` reducer holds it): fields
 *     placed on different pages of a multi-page document all persist.
 *   • R11.2 — cancelling the editor discards the in-progress Field_Set and
 *     calls `onCancel`; and an in-flight send is aborted (its `AbortSignal`
 *     becomes aborted) when the editor is torn down — which is exactly what the
 *     modal's cancel/close does (it unmounts the editor).
 *   • R11.3 — reopening the Send_Flow starts from an empty Field_Set: closing
 *     and reopening the modal runs `resetForm`, rewinding to step 1 with no PDF
 *     and an empty editor on re-entry.
 *   • R11.4 — a rejected send leaves the placed Field_Set intact (so the sender
 *     can correct and retry) and surfaces the humanized error.
 *
 * `pdfjs-dist` is mocked (the module the hook imports as `* as pdfjsLib` plus
 * the `?url` worker asset) using the same pattern as `PdfRendering.test.tsx` /
 * `EditorInteractions.test.tsx`, so the document/page lifecycle is deterministic
 * without a real PDF engine. jsdom implements neither canvas 2d nor Pointer
 * Capture, so `getContext`, `setPointerCapture`, and `releasePointerCapture`
 * are stubbed.
 *
 * These are example tests (Vitest + React Testing Library), not property tests.
 *
 * _Requirements: 11.1, 11.2, 11.3, 11.4_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import FieldPlacementEditor, {
  type FieldPlacementEditorRecipient,
} from './FieldPlacementEditor'
import { FIELD_TYPE_DRAG_MIME } from './FieldPalette'
import { SendForSignatureModal } from '../SendForSignatureModal'
import type { EnvelopeOut } from '@/api/esign'

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

/** A real, non-empty PDF File the modal's client-side picker accepts. */
function realPdfFile(name = 'agreement.pdf'): File {
  return new File(['%PDF-1.4\n%mock pdf bytes'], name, { type: 'application/pdf' })
}

/** One signer recipient (drives colour + assignment; index 0). */
const RECIPIENTS: FieldPlacementEditorRecipient[] = [
  { key: 0, name: 'Alex Tran', signing_role: 'signer' },
]

/** All placed-field overlays currently in the DOM. */
function overlays(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>('[data-testid^="field-overlay-"]'),
  )
}

/**
 * Drop a palette field of `type` onto page `page` at the given client point,
 * mirroring the palette → drop-layer drag payload the editor reads (R3.1).
 * jsdom's `DragEvent` drops `clientX`/`clientY` from an init object, so the
 * synthetic event is built by hand with those (and the `dataTransfer`) defined
 * explicitly.
 */
function dropField(page: number, type: string, clientX: number, clientY: number) {
  const layer = screen.getByTestId(`drop-layer-${page}`)
  const dataTransfer = {
    getData: (t: string) => (t === FIELD_TYPE_DRAG_MIME ? type : ''),
    setData: vi.fn(),
    types: [FIELD_TYPE_DRAG_MIME],
    dropEffect: 'none',
  }

  const fire = (eventName: 'dragover' | 'drop') => {
    const event = new Event(eventName, { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'dataTransfer', { value: dataTransfer })
    Object.defineProperty(event, 'clientX', { value: clientX })
    Object.defineProperty(event, 'clientY', { value: clientY })
    fireEvent(layer, event)
  }

  fire('dragover')
  fire('drop')
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
/*  R11.1 — Field_Set survives in-editor page navigation               */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — Field_Set is retained across page navigation (R11.1)', () => {
  it('keeps fields placed on different pages of a multi-page document', async () => {
    pdfMock.state.numPages = 3
    render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} />)

    // Every page renders its own drop layer — "navigation" within the editor
    // is moving between these stacked pages.
    await screen.findByTestId('drop-layer-1')
    await screen.findByTestId('drop-layer-3')

    // Place a field on page 1, then on page 3 (navigating across pages).
    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))

    dropField(3, 'date', 120, 160)
    await waitFor(() => expect(overlays()).toHaveLength(2))

    // The reducer holds the full set: both fields persist simultaneously, each
    // on its own page (the page-1 field was not lost by navigating to page 3).
    const page1 = screen.getByTestId('drop-layer-1')
    const page3 = screen.getByTestId('drop-layer-3')
    expect(page1.querySelectorAll('[data-testid^="field-overlay-"]')).toHaveLength(1)
    expect(page3.querySelectorAll('[data-testid^="field-overlay-"]')).toHaveLength(1)
    expect(page1.querySelector('[data-field-type="signature"]')).not.toBeNull()
    expect(page3.querySelector('[data-field-type="date"]')).not.toBeNull()
  })
})

/* ------------------------------------------------------------------ */
/*  R11.2 — cancel discards the set + aborts an in-flight send          */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — cancel discards the set and aborts in-flight send (R11.2)', () => {
  it('discards the in-progress Field_Set and calls onCancel', async () => {
    const onCancel = vi.fn()
    render(
      <FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} onCancel={onCancel} />,
    )
    await screen.findByTestId('drop-layer-1')

    // Place a couple of fields, then cancel (no send in flight).
    dropField(1, 'signature', 160, 200)
    dropField(1, 'name', 120, 320)
    await waitFor(() => expect(overlays()).toHaveLength(2))

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    // The Field_Set is discarded and the parent is notified (R11.2).
    await waitFor(() => expect(overlays()).toHaveLength(0))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('aborts the in-flight send when the editor is torn down on cancel', async () => {
    // The modal's cancel/close unmounts the editor; the editor's cleanup aborts
    // any in-flight send. We make onSend hang so a send is genuinely in flight,
    // capture its AbortSignal, then unmount and assert the signal was aborted.
    let capturedSignal: AbortSignal | null = null
    const onSend = vi.fn((_fields: unknown, signal: AbortSignal) => {
      capturedSignal = signal
      return new Promise<void>(() => {}) // never settles → stays in flight
    })

    const { unmount } = render(
      <FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} onSend={onSend} />,
    )
    await screen.findByTestId('drop-layer-1')

    // A valid set (the lone signer carries a signature field) enables send.
    dropField(1, 'signature', 160, 200)
    const sendBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(sendBtn).toBeEnabled())

    fireEvent.click(sendBtn)
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1))
    expect(capturedSignal).not.toBeNull()
    expect(capturedSignal!.aborted).toBe(false)

    // Tearing down the editor (what cancel/close does) aborts the in-flight send.
    unmount()
    expect(capturedSignal!.aborted).toBe(true)
  })
})

/* ------------------------------------------------------------------ */
/*  R11.4 — a failed send retains the Field_Set for retry               */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — a failed send retains the Field_Set (R11.4)', () => {
  it('keeps the placed fields and surfaces the humanized error when the send is rejected', async () => {
    const onSend = vi.fn(async () => {
      throw {
        response: {
          data: {
            message: 'Couldn’t create the fields on the document. Please try again.',
            code: 'documenso_error',
          },
        },
      }
    })

    render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} onSend={onSend} />)
    await screen.findByTestId('drop-layer-1')

    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))

    const sendBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(sendBtn).toBeEnabled())
    fireEvent.click(sendBtn)

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1))

    // The humanized error is surfaced (R11.4 / R12)…
    const error = await screen.findByTestId('send-error')
    expect(error).toHaveTextContent('Couldn’t create the fields on the document. Please try again.')

    // …and the Field_Set is retained so the sender can correct + retry.
    expect(overlays()).toHaveLength(1)
    expect(overlays()[0]).toHaveAttribute('data-field-type', 'signature')
    // Send is re-enabled for the retry (the set is still valid).
    await waitFor(() => expect(screen.getByTestId('send-for-signature')).toBeEnabled())
  })
})

/* ------------------------------------------------------------------ */
/*  R11.3 — reopening the Send_Flow starts from an empty Field_Set      */
/* ------------------------------------------------------------------ */

describe('SendForSignatureModal — reopening starts from an empty Field_Set (R11.3)', () => {
  function sentEnvelope(): EnvelopeOut {
    return {
      id: 'env-1',
      agreement_type: 'nda',
      originating_entity_type: 'staff',
      originating_entity_id: 'staff-7',
      status: 'sent',
      recipients: [],
      signed_document_url: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
  }

  async function fillStep1(user: ReturnType<typeof userEvent.setup>, file: File) {
    await user.upload(
      screen.getByLabelText('Select a PDF document to send for signature'),
      file,
    )
    await user.selectOptions(screen.getByLabelText('Agreement type'), 'nda')
    await user.type(screen.getByLabelText('Name'), 'Alex Tran')
    await user.type(screen.getByLabelText('Email'), 'alex@example.com')
  }

  it('rewinds to step 1 with no PDF and an empty editor after close + reopen', async () => {
    const user = userEvent.setup()
    const createEnvelopeFn = vi.fn(async () => sentEnvelope())
    const file = realPdfFile()

    const { rerender } = render(
      <SendForSignatureModal
        open
        onClose={vi.fn()}
        originatingEntityType="staff"
        originatingEntityId="staff-7"
        createEnvelopeFn={createEnvelopeFn}
      />,
    )

    // Compose step 1 and advance to the editor (step 2).
    await fillStep1(user, file)
    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))

    await screen.findByTestId('drop-layer-1')
    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))

    // Close the modal (cancel the flow), then reopen it.
    rerender(
      <SendForSignatureModal
        open={false}
        onClose={vi.fn()}
        originatingEntityType="staff"
        originatingEntityId="staff-7"
        createEnvelopeFn={createEnvelopeFn}
      />,
    )
    rerender(
      <SendForSignatureModal
        open
        onClose={vi.fn()}
        originatingEntityType="staff"
        originatingEntityId="staff-7"
        createEnvelopeFn={createEnvelopeFn}
      />,
    )

    // resetForm rewound to step 1: the field-placement editor is gone, the PDF
    // is cleared, and the recipient row is blank (R11.3).
    expect(
      screen.getByRole('button', { name: 'Continue to field placement' }),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('drop-layer-1')).toBeNull()
    expect(screen.getByText('No file selected')).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('')

    // Re-advancing to the editor shows an empty Field_Set — nothing carried over.
    await fillStep1(user, realPdfFile('second.pdf'))
    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))
    await screen.findByTestId('drop-layer-1')
    expect(overlays()).toHaveLength(0)
  })
})
