/**
 * Safe consumption + AbortController binding — example tests (Task 13.4).
 *
 * Proves Requirement 9.5 across the create-and-send seam:
 *
 *   "WHEN the Field_Placement_Editor consumes Esign_Module API responses, THE
 *    Field_Placement_Editor SHALL use typed access with optional chaining and
 *    array fallbacks AND SHALL bind each in-flight request to an AbortController
 *    that is aborted on unmount or cancel."
 *
 * Three angles, all backing R9.5:
 *
 *   1. **The create call forwards an AbortSignal.** `createEnvelope` in
 *      `api/esign.ts` passes the caller's signal straight through to the axios
 *      client as `{ signal }` (unit test against the mocked client).
 *
 *   2. **The client is typed + safe-by-construction.** A lightweight static
 *      assertion over `api/esign.ts` confirms the create call uses a typed
 *      generic (no `as any`) and the module reads responses with `?.` / `?? []`
 *      so a partial/blank payload can never crash a consumer.
 *
 *   3. **The in-flight request is bound to a controller aborted on
 *      unmount/cancel.** Driving the real `FieldPlacementEditor` (and, end to
 *      end, the real `SendForSignatureModal`), the signal handed to the create
 *      call is live during the send and becomes `aborted` the moment the editor
 *      unmounts or the modal is cancelled/closed mid-flight.
 *
 * `pdfjs-dist` is mocked with the same pattern as `PdfRendering.test.tsx` /
 * `EditorInteractions.test.tsx` so the page lifecycle is deterministic without a
 * real PDF engine; `@/api/client` is mocked so the unit test can inspect the
 * axios config without a network. jsdom has no canvas 2d context or Pointer
 * Capture, so both are stubbed.
 *
 * These are example tests (Vitest + React Testing Library), not property tests.
 *
 * _Requirements: 9.5_
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset) — PdfRendering pattern */
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
  const getDocument = vi.fn(() => ({ promise: Promise.resolve(makeDoc()), destroy: vi.fn() }))
  return { GlobalWorkerOptions, getDocument }
})

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'mock-worker-url' }))

/* ------------------------------------------------------------------ */
/*  Mock the shared axios client (so the unit test can inspect config) */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import apiClient from '@/api/client'
import { createEnvelope } from '@/api/esign'
import type { EnvelopeCreate } from '@/api/esign'
import FieldPlacementEditor, {
  type FieldPlacementEditorRecipient,
} from './FieldPlacementEditor'
import { SendForSignatureModal } from '../SendForSignatureModal'
import { FIELD_TYPE_DRAG_MIME } from './FieldPalette'

const mockedPost = apiClient.post as unknown as ReturnType<typeof vi.fn>

/* ------------------------------------------------------------------ */
/*  Fixtures + helpers                                                 */
/* ------------------------------------------------------------------ */

/** A minimal File whose only used method is `arrayBuffer()` (for the editor). */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

/** A real, non-empty PDF File the modal's step-1 picker accepts. */
function realPdfFile(name = 'agreement.pdf'): File {
  return new File(['%PDF-1.4\n%mock pdf bytes'], name, { type: 'application/pdf' })
}

/** One signer recipient (drives colour + assignment; index 0). */
const RECIPIENTS: FieldPlacementEditorRecipient[] = [
  { key: 0, name: 'Alex Tran', signing_role: 'signer' },
]

/** A minimal, valid EnvelopeCreate payload for the unit test. */
const PAYLOAD: EnvelopeCreate = {
  agreement_type: 'nda',
  originating_entity_type: 'staff',
  originating_entity_id: 'staff-7',
  recipients: [{ name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' }],
  fields: [
    {
      type: 'signature',
      page: 1,
      recipient_index: 0,
      position_x: 10,
      position_y: 20,
      width: 30,
      height: 10,
      required: true,
    },
  ],
}

/**
 * Drop a palette field of `type` onto page `page` at the given client point,
 * mirroring the palette → drop-layer drag payload the editor reads (R3.1).
 * (Same hand-built synthetic DragEvent as EditorInteractions.test.tsx, since
 * jsdom's DragEvent drops clientX/clientY from an init object.)
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
/*  1. createEnvelope forwards the AbortSignal as { signal }           */
/* ------------------------------------------------------------------ */

describe('createEnvelope — forwards the AbortSignal (R9.5)', () => {
  it('passes the caller signal straight through to the axios client config', async () => {
    const controller = new AbortController()
    mockedPost.mockResolvedValueOnce({ data: { id: 'env-1', status: 'sent' } })

    await createEnvelope(realPdfFile(), PAYLOAD, controller.signal)

    expect(mockedPost).toHaveBeenCalledTimes(1)
    const [url, body, config] = mockedPost.mock.calls[0]
    expect(url).toBe('/api/v2/esign/envelopes')
    // The PDF + payload travel as multipart; the signal is bound to the request.
    expect(body).toBeInstanceOf(FormData)
    expect(config).toMatchObject({ signal: controller.signal })
    // The signal is forwarded by identity (the very controller the caller owns).
    expect((config as { signal?: AbortSignal }).signal).toBe(controller.signal)
  })

  it('still issues the request (without a signal) when none is supplied', async () => {
    mockedPost.mockResolvedValueOnce({ data: { id: 'env-2', status: 'sent' } })

    await createEnvelope(realPdfFile(), PAYLOAD)

    expect(mockedPost).toHaveBeenCalledTimes(1)
    const [, , config] = mockedPost.mock.calls[0]
    expect((config as { signal?: AbortSignal }).signal).toBeUndefined()
  })
})

/* ------------------------------------------------------------------ */
/*  2. The esign client is typed + safe-by-construction (static check) */
/* ------------------------------------------------------------------ */

describe('api/esign.ts — typed, safe-consumption source (R9.5)', () => {
  const source = readFileSync(
    resolve(process.cwd(), 'src/api/esign.ts'),
    'utf8',
  )

  /** The `createEnvelope` function body (the create-and-send seam R9.5 covers). */
  const createEnvelopeFnSource = (() => {
    const start = source.indexOf('export async function createEnvelope')
    expect(start).toBeGreaterThanOrEqual(0)
    // Up to the next top-level export (the function is self-contained before it).
    const rest = source.slice(start + 1)
    const next = rest.indexOf('\nexport ')
    return next >= 0 ? rest.slice(0, next) : rest
  })()

  it('types the create call with a generic and never casts to any', () => {
    // Typed generic on the create POST, and no `as any` cast in its body.
    expect(createEnvelopeFnSource).toContain('apiClient.post<EnvelopeOutWire>')
    expect(createEnvelopeFnSource).not.toMatch(/as\s+any/)
  })

  it('reads responses with optional chaining and array/scalar fallbacks', () => {
    // `?.` guards + `?? []` / `?? 0` so a partial/blank payload never crashes.
    expect(source).toContain('?? []')
    expect(source).toContain('?.')
    // The create endpoint threads the optional signal through to the request.
    expect(source).toMatch(/signal\?:\s*AbortSignal/)
    expect(createEnvelopeFnSource).toContain('signal,')
  })
})

/* ------------------------------------------------------------------ */
/*  3. The in-flight request is bound to a controller aborted on       */
/*     unmount / cancel                                                */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — binds the send to an AbortController (R9.5)', () => {
  it('hands onSend a live (un-aborted) signal during the send', async () => {
    let captured: AbortSignal | null = null
    // A send that never settles so the request stays "in flight".
    const onSend = vi.fn((_fields, signal: AbortSignal) => {
      captured = signal
      return new Promise<void>(() => {})
    })

    render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} onSend={onSend} />)
    await screen.findByTestId('drop-layer-1')

    // Place a signature field for the signer → validation passes → send enables.
    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))

    const sendBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(sendBtn).toBeEnabled())
    fireEvent.click(sendBtn)

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1))
    expect(captured).not.toBeNull()
    // The in-flight request is bound to a fresh, un-aborted controller.
    expect((captured as unknown as AbortSignal).aborted).toBe(false)
  })

  it('aborts the in-flight signal when the editor unmounts', async () => {
    let captured: AbortSignal | null = null
    const onSend = vi.fn((_fields, signal: AbortSignal) => {
      captured = signal
      return new Promise<void>(() => {})
    })

    const { unmount } = render(
      <FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} onSend={onSend} />,
    )
    await screen.findByTestId('drop-layer-1')

    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))

    const sendBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(sendBtn).toBeEnabled())
    fireEvent.click(sendBtn)

    await waitFor(() => expect(captured).not.toBeNull())
    expect((captured as unknown as AbortSignal).aborted).toBe(false)

    // Unmounting (e.g. the modal closing) aborts the in-flight request (R9.5).
    unmount()
    expect((captured as unknown as AbortSignal).aborted).toBe(true)
  })
})

describe('SendForSignatureModal — cancel/close aborts the in-flight create (R9.5)', () => {
  it('forwards a live signal to createEnvelope and aborts it when the modal closes', async () => {
    const user = userEvent.setup()

    let captured: AbortSignal | null = null
    // The injected create call captures the signal and never settles, so the
    // request is genuinely "in flight" when we close the modal.
    const createEnvelopeFn = vi.fn((_file: Blob | File, _payload: EnvelopeCreate, signal?: AbortSignal) => {
      captured = signal ?? null
      return new Promise<never>(() => {})
    })

    const file = realPdfFile()
    const { rerender } = render(
      <SendForSignatureModal
        open
        onClose={vi.fn()}
        originatingEntityType="staff"
        originatingEntityId="staff-7"
        createEnvelopeFn={createEnvelopeFn as never}
      />,
    )

    // Step 1 — compose: pick a PDF + agreement type + one signer recipient.
    await user.upload(
      screen.getByLabelText('Select a PDF document to send for signature'),
      file,
    )
    await user.selectOptions(screen.getByLabelText('Agreement type'), 'nda')
    await user.type(screen.getByLabelText('Name'), 'Jane Doe')
    await user.type(screen.getByLabelText('Email'), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))

    // Step 2 — place a signature field for the signer, then send.
    await screen.findByTestId('drop-layer-1')
    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))

    const sendBtn = screen.getByTestId('send-for-signature')
    await waitFor(() => expect(sendBtn).toBeEnabled())
    fireEvent.click(sendBtn)

    // The create call received a live AbortSignal (typed generics; safe).
    await waitFor(() => expect(createEnvelopeFn).toHaveBeenCalledTimes(1))
    expect(captured).not.toBeNull()
    expect((captured as unknown as AbortSignal).aborted).toBe(false)

    // Closing the modal mid-flight (cancel) unmounts the editor and aborts the
    // request the create call is bound to (R9.5).
    rerender(
      <SendForSignatureModal
        open={false}
        onClose={vi.fn()}
        originatingEntityType="staff"
        originatingEntityId="staff-7"
        createEnvelopeFn={createEnvelopeFn as never}
      />,
    )

    await waitFor(() => expect((captured as unknown as AbortSignal).aborted).toBe(true))
  })
})
