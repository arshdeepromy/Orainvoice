/**
 * Editor interaction wiring — example tests (Task 6.6).
 *
 * Exercises the live `FieldPlacementEditor` orchestrator (Task 6.4) wired to its
 * real `FieldOverlay` (Task 6.2), `FieldPalette` (Task 6.1), `useFieldSet`
 * reducer, and `usePdfDocument` PDF renderer, to prove the three interaction
 * surfaces are connected end-to-end:
 *
 *   • drag-to-add — dropping a palette field type onto a page's drop layer adds
 *     a field of that type at the drop point (R3.1);
 *   • keyboard — a selected field moves with the arrow keys (Shift = larger
 *     step, R10.2) and is removed with Delete / Backspace (R10.3);
 *   • pointer / touch — a field can be dragged via Pointer Events on a 320 px
 *     viewport (R10.5).
 *
 * `pdfjs-dist` is mocked (the module the hook imports as `* as pdfjsLib` plus
 * the `?url` worker asset) using the same pattern as `PdfRendering.test.tsx`, so
 * the document/page lifecycle is deterministic without a real PDF engine. With
 * the default (unmeasured) column width the editor renders pages at the 320 px
 * minimum-viewport floor, which is exactly the width R10.5 calls out — so the
 * pointer drag below runs at a 320 px page.
 *
 * jsdom implements neither canvas 2d nor Pointer Capture, so `getContext`,
 * `setPointerCapture`, and `releasePointerCapture` are stubbed.
 *
 * These are example tests (Vitest + React Testing Library), not property tests.
 *
 * _Requirements: 3.1, 10.2, 10.3, 10.5_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import FieldPlacementEditor, {
  type FieldPlacementEditorRecipient,
} from './FieldPlacementEditor'
import { FIELD_TYPE_DRAG_MIME } from './FieldPalette'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset) — PdfRendering pattern */
/* ------------------------------------------------------------------ */

const pdfMock = vi.hoisted(() => ({
  state: {
    numPages: 1,
    // Intrinsic (scale-1) page size. At the 320 px viewport floor the editor
    // renders this 600-wide page at scale 320/600, i.e. an exactly 320 px page.
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
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

/** A minimal File whose only used method is `arrayBuffer()`. */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

/** One signer recipient (drives colour + assignment; index 0). */
const RECIPIENTS: FieldPlacementEditorRecipient[] = [
  { key: 0, name: 'Alex Tran', signing_role: 'signer' },
]

/** The page renders at the 320 px viewport floor (see file docs). */
const PAGE_CSS_WIDTH = 320

/** Default dropped-field size in overlay px (from FieldPlacementEditor). */
const DROP_W = 140
const DROP_H = 44

/** All placed-field overlays currently in the DOM. */
function overlays(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>('[data-testid^="field-overlay-"]'),
  )
}

/** Parse a numeric CSS px value (e.g. "90px" → 90). */
function px(value: string): number {
  return parseFloat(value)
}

/** Mount the editor and wait until the first page's drop layer is present. */
async function renderEditor() {
  const utils = render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} />)
  await screen.findByTestId('drop-layer-1')
  return utils
}

/**
 * Drop a palette field of `type` onto page `page` at the given client point,
 * mirroring the palette → drop-layer drag payload the editor reads (R3.1).
 *
 * jsdom's `DragEvent` does not extend `MouseEvent`, so `clientX`/`clientY` from
 * an init object are dropped; the synthetic event is built by hand with those
 * (and the `dataTransfer`) defined explicitly so the editor's drop handler reads
 * the real drop point.
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

  // jsdom has no canvas 2d context — provide a truthy stub so PdfPageCanvas can
  // proceed past its getContext guard.
  HTMLCanvasElement.prototype.getContext = vi.fn(
    () => ({}) as unknown as CanvasRenderingContext2D,
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext

  // jsdom doesn't implement Pointer Capture — stub it so FieldOverlay's pointer
  // drag/resize gestures don't throw (note in the task description).
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
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('FieldPlacementEditor — drag / keyboard / touch wiring', () => {
  // R3.1 — dragging a palette item onto a page adds a field of that type at the
  // drop point.
  it('adds a field at the drop point when a palette type is dropped on a page', async () => {
    await renderEditor()

    // No fields placed yet.
    expect(overlays()).toHaveLength(0)

    // Drop a signature field at (160, 200) on page 1 (layer origin is 0,0 in jsdom).
    dropField(1, 'signature', 160, 200)

    // Exactly one field is added, carrying the dragged type (R3.1, R2.2).
    await waitFor(() => expect(overlays()).toHaveLength(1))
    const overlay = overlays()[0]
    expect(overlay).toHaveAttribute('data-field-type', 'signature')

    // It lands centred on the drop point: top-left = drop − half the box size.
    // (Drop is in-bounds, so the reducer's clamp leaves the position intact.)
    expect(px(overlay.style.left)).toBeCloseTo(160 - DROP_W / 2, 1) // 90
    expect(px(overlay.style.top)).toBeCloseTo(200 - DROP_H / 2, 1) // 178
  })

  // R10.2 — a selected field moves with the arrow keys; Shift takes a larger step.
  it('moves a selected field with the arrow keys (Shift = larger step)', async () => {
    await renderEditor()

    // Placing a field selects it (the editor sets it as the selected field).
    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))
    const overlay = overlays()[0]
    expect(overlay).toHaveAttribute('data-selected', 'true')

    const startLeft = px(overlay.style.left)
    const startTop = px(overlay.style.top)

    // ArrowRight nudges +1 px on x; ArrowDown nudges +1 px on y (R10.2).
    fireEvent.keyDown(overlay, { key: 'ArrowRight' })
    expect(px(overlays()[0].style.left)).toBeCloseTo(startLeft + 1, 1)

    fireEvent.keyDown(overlays()[0], { key: 'ArrowDown' })
    expect(px(overlays()[0].style.top)).toBeCloseTo(startTop + 1, 1)

    // Shift takes a larger (10 px) step.
    fireEvent.keyDown(overlays()[0], { key: 'ArrowRight', shiftKey: true })
    expect(px(overlays()[0].style.left)).toBeCloseTo(startLeft + 1 + 10, 1)

    // ArrowLeft moves back toward the origin.
    fireEvent.keyDown(overlays()[0], { key: 'ArrowLeft' })
    expect(px(overlays()[0].style.left)).toBeCloseTo(startLeft + 1 + 10 - 1, 1)
  })

  // R10.3 — a selected field is removed with Delete, and (separately) Backspace.
  it('deletes a selected field with Delete and with Backspace', async () => {
    await renderEditor()

    // Delete removes the selected field.
    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))
    fireEvent.keyDown(overlays()[0], { key: 'Delete' })
    await waitFor(() => expect(overlays()).toHaveLength(0))

    // Backspace removes it too.
    dropField(1, 'name', 120, 160)
    await waitFor(() => expect(overlays()).toHaveLength(1))
    fireEvent.keyDown(overlays()[0], { key: 'Backspace' })
    await waitFor(() => expect(overlays()).toHaveLength(0))
  })

  // R10.5 — placement/adjustment works via Pointer Events at a 320 px viewport.
  it('drags a field via pointer events on a 320 px page', async () => {
    await renderEditor()

    // The page is laid out at the 320 px minimum-viewport floor (R10.5).
    await waitFor(() =>
      expect(px(screen.getByTestId('pdf-page-1').style.width)).toBeCloseTo(PAGE_CSS_WIDTH, 1),
    )

    dropField(1, 'signature', 160, 200)
    await waitFor(() => expect(overlays()).toHaveLength(1))
    const overlay = overlays()[0]
    const startLeft = px(overlay.style.left)
    const startTop = px(overlay.style.top)

    // Pointer down → move → up drags the box by the pointer delta (R10.5).
    fireEvent.pointerDown(overlay, { pointerId: 1, clientX: 100, clientY: 100 })
    fireEvent.pointerMove(overlay, { pointerId: 1, clientX: 130, clientY: 140 })
    fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 130, clientY: 140 })

    const moved = overlays()[0]
    expect(px(moved.style.left)).toBeCloseTo(startLeft + 30, 1)
    expect(px(moved.style.top)).toBeCloseTo(startTop + 40, 1)
  })
})
