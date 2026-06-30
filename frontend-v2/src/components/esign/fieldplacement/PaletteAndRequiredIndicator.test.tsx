/**
 * Palette + required/optional indicator — example tests (Task 6.5).
 *
 * Exercises the assembled Field_Placement_Editor end-to-end (palette →
 * recipient legend → page drop layer → FieldOverlay) to cover the two
 * acceptance criteria this task targets:
 *
 *   • R2.1 — the Field_Palette offers all six supported field types
 *     (`signature`, `initials`, `name`, `date`, `email`, `text`);
 *   • R5.5 — every placed field shows a *visible* required/optional indicator.
 *     A `signature` field (required by default, R2.3) renders the
 *     `field-required-{clientId}` "*" marker; a `text` field (optional by
 *     default, R2.3) renders the `field-optional-{clientId}` marker.
 *
 * The editor renders the PDF via `usePdfDocument`, which imports `pdfjs-dist`,
 * so we reuse the mock pattern established in `PdfRendering.test.tsx`: mock
 * `pdfjs-dist` + the `?url` worker asset, stub canvas `getContext`, and rely on
 * the documented eager-render fallback (jsdom has no IntersectionObserver).
 *
 * Placement is driven through the editor's real interaction path: arm a type in
 * the palette (tap-to-arm), then click the empty page drop layer — exactly what
 * `FieldPlacementEditor` wires up — so the test verifies the indicator appears
 * on a field the editor itself created.
 *
 * _Requirements: 2.1, 5.5_
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import FieldPlacementEditor, {
  type FieldPlacementEditorRecipient,
} from './FieldPlacementEditor'
import { FIELD_TYPES } from './hooks/useFieldSet'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset)                       */
/*  — same deterministic single-page happy-path doc as PdfRendering.   */
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
/*  Test fixtures                                                      */
/* ------------------------------------------------------------------ */

/** A minimal File whose only used method is `arrayBuffer()`. */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

const RECIPIENTS: FieldPlacementEditorRecipient[] = [
  { key: 0, name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' },
]

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  pdfMock.state.numPages = 1
  pdfMock.state.pageWidth = 600
  pdfMock.state.pageHeight = 800

  // jsdom doesn't implement the canvas 2d context; provide a truthy stub so
  // PdfPageCanvas can rasterise past its `getContext` guard.
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

describe('Field palette and required/optional indicator', () => {
  // R2.1 — the palette offers all ten supported field types.
  it('offers all field-type controls in the editor palette', async () => {
    render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} />)

    // Wait for the page to render so the editor is fully mounted.
    await screen.findByTestId('pdf-page-1')

    for (const type of FIELD_TYPES) {
      expect(screen.getByTestId(`palette-${type}`)).toBeInTheDocument()
    }
    // Exactly ten types, no more, no fewer.
    expect(FIELD_TYPES).toHaveLength(10)
    expect(screen.getByTestId('palette-signature')).toBeInTheDocument()
    expect(screen.getByTestId('palette-initials')).toBeInTheDocument()
    expect(screen.getByTestId('palette-name')).toBeInTheDocument()
    expect(screen.getByTestId('palette-date')).toBeInTheDocument()
    expect(screen.getByTestId('palette-email')).toBeInTheDocument()
    expect(screen.getByTestId('palette-text')).toBeInTheDocument()
    expect(screen.getByTestId('palette-number')).toBeInTheDocument()
    expect(screen.getByTestId('palette-radio')).toBeInTheDocument()
    expect(screen.getByTestId('palette-checkbox')).toBeInTheDocument()
    expect(screen.getByTestId('palette-dropdown')).toBeInTheDocument()
  })

  // R5.5 — a placed required field (signature) shows a visible required marker.
  it('shows a visible required indicator on a placed signature field', async () => {
    render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} />)

    await screen.findByTestId('pdf-page-1')

    // Arm the signature type, then click the empty page drop layer to place it.
    fireEvent.click(screen.getByTestId('palette-signature'))
    fireEvent.click(screen.getByTestId('drop-layer-1'))

    // The field renders with its required (*) indicator (signature defaults to
    // required, R2.3); the optional indicator is absent for the same field.
    const requiredMarker = await screen.findByTestId(/^field-required-/)
    expect(requiredMarker).toBeInTheDocument()
    expect(requiredMarker).toHaveTextContent('*')
    expect(requiredMarker).toHaveAttribute('title', 'Required')
    expect(screen.queryByTestId(/^field-optional-/)).not.toBeInTheDocument()
  })

  // R5.5 — a placed optional field (text) shows a visible optional indicator.
  it('shows a visible optional indicator on a placed text field', async () => {
    render(<FieldPlacementEditor file={makePdfFile()} recipients={RECIPIENTS} />)

    await screen.findByTestId('pdf-page-1')

    // Arm the text type (defaults to optional, R2.3), then place it.
    fireEvent.click(screen.getByTestId('palette-text'))
    fireEvent.click(screen.getByTestId('drop-layer-1'))

    const optionalMarker = await screen.findByTestId(/^field-optional-/)
    expect(optionalMarker).toBeInTheDocument()
    expect(optionalMarker).toHaveAttribute('title', 'Optional')
    expect(screen.queryByTestId(/^field-required-/)).not.toBeInTheDocument()
  })
})
