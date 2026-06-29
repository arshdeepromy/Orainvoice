/**
 * Field assignment wiring — example tests (Task 6.7).
 *
 * Exercises the assignment behaviour of the assembled editor — the
 * `FieldPlacementEditor` orchestrator wired to `RecipientLegend` (the
 * active-recipient picker), `FieldPalette` (the field-type sources), and
 * `FieldOverlay` (the rendered field box). These are integration-style example
 * tests that mount the real editor and place fields through the same gestures
 * an Org_Sender uses.
 *
 * Covers:
 *   • placing a field assigns it to the currently-selected recipient, and a
 *     later placement follows a change of the selected recipient (R4.2);
 *   • a placed field renders in its assigned recipient's colour — the overlay's
 *     fill + border come from `recipientColor(index)` for that recipient's
 *     position in the Send_Flow recipient list (R4.4 render binding).
 *
 * `pdfjs-dist` is mocked (both the module the PDF hook imports and the `?url`
 * worker asset) so the document/page lifecycle is driven deterministically
 * without a real PDF engine — the same pattern used by `PdfRendering.test.tsx`.
 * jsdom has no IntersectionObserver, so `PdfPageCanvas` renders eagerly and no
 * scroll simulation is needed; a canvas 2d-context stub lets it rasterise.
 *
 * _Requirements: 4.2, 4.4_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import FieldPlacementEditor, {
  type FieldPlacementEditorRecipient,
} from './FieldPlacementEditor'
import { recipientColor } from './lib/fieldColors'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset)                       */
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

// Two signer recipients in a stable order — colours derive from index:
// index 0 → Alex Tran, index 1 → Sam Lee.
const RECIPIENTS: FieldPlacementEditorRecipient[] = [
  { key: 10, name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' },
  { key: 20, name: 'Sam Lee', email: 'sam@example.com', signing_role: 'signer' },
]

/** A minimal File whose only used method is `arrayBuffer()`. */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

/** Mount the editor and wait until the page (and its drop layer) is ready. */
async function renderEditor() {
  render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} />)
  // The drop/overlay layer for page 1 appears once the document has loaded.
  return screen.findByTestId('drop-layer-1')
}

/**
 * Place a field on a page via the tap-to-arm gesture: arm the chosen field type
 * in the palette, then tap the empty page drop layer. (Equivalent to a palette
 * drag-drop onto `drop-layer-{n}`.)
 */
function armAndPlace(type: string, dropLayer: HTMLElement) {
  fireEvent.click(screen.getByTestId(`palette-${type}`))
  fireEvent.click(dropLayer)
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  pdfMock.state.numPages = 1
  pdfMock.state.pageWidth = 600
  pdfMock.state.pageHeight = 800

  // jsdom lacks a canvas 2d context; a truthy stub lets PdfPageCanvas rasterise.
  HTMLCanvasElement.prototype.getContext = vi.fn(
    () => ({}) as unknown as CanvasRenderingContext2D,
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext
})

afterEach(() => {
  vi.restoreAllMocks()
})

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('Field placement — assignment wiring', () => {
  // R4.2 — a newly placed field is assigned to whichever recipient is selected.
  it('assigns a placed field to the currently-selected recipient (R4.2)', async () => {
    const dropLayer = await renderEditor()

    // Select the SECOND recipient (not the default first) as the active one.
    fireEvent.click(screen.getByTestId('recipient-20'))

    // Place a signature field — it must belong to Sam Lee (the selected one).
    armAndPlace('signature', dropLayer)
    expect(
      await screen.findByRole('button', { name: /Signature field for Sam Lee/i }),
    ).toBeInTheDocument()
    // Nothing was assigned to the unselected recipient.
    expect(
      screen.queryByRole('button', { name: /Signature field for Alex Tran/i }),
    ).not.toBeInTheDocument()

    // Switch the active recipient, place again — the new field follows the
    // current selection (the type stays armed after a placement).
    fireEvent.click(screen.getByTestId('recipient-10'))
    fireEvent.click(dropLayer)
    expect(
      await screen.findByRole('button', { name: /Signature field for Alex Tran/i }),
    ).toBeInTheDocument()
  })

  // R4.4 — a placed field is rendered in its assigned recipient's colour.
  it("renders a placed field in its recipient's colour (R4.4)", async () => {
    const dropLayer = await renderEditor()

    // Select the second recipient (index 1) and place a field for them.
    fireEvent.click(screen.getByTestId('recipient-20'))
    armAndPlace('signature', dropLayer)

    const overlay = await screen.findByRole('button', {
      name: /Signature field for Sam Lee/i,
    })

    // The field box is drawn with the index-1 recipient's colour (R4.4): a
    // translucent fill + a solid border, both from `recipientColor(1)`.
    const expected = recipientColor(1)
    await waitFor(() => {
      expect(overlay).toHaveStyle({ backgroundColor: expected.fill })
      expect(overlay).toHaveStyle({ borderColor: expected.solid })
    })

    // And distinctly NOT the first recipient's colour, so the binding is real.
    expect(recipientColor(1).solid).not.toBe(recipientColor(0).solid)
    expect(overlay).not.toHaveStyle({ backgroundColor: recipientColor(0).fill })
  })
})
