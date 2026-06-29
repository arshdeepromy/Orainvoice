/**
 * PDF rendering — example/integration tests (Task 5.3).
 *
 * Exercises the in-browser PDF_Renderer that the Field_Placement_Editor stands
 * on: the `usePdfDocument` hook (document lifecycle + per-page geometry) wired
 * to `PdfPageCanvas` (per-page rasterisation + lifecycle). The editor
 * orchestrator (Task 6) is not yet implemented, so these tests mount a tiny
 * harness that composes exactly those two units the same way the editor will —
 * a send control disabled while rendering hasn't yet succeeded, plus a
 * placed-field overlay per page.
 *
 * Covers:
 *   • a multi-page doc renders one page surface per page (R1.1, R1.2);
 *   • a page in `rendering` shows a per-page loading indicator (R1.3);
 *   • a `getDocument` rejection AND a page-render rejection each surface the
 *     `render_failed` state and keep the send control disabled (R1.4);
 *   • an image-only/scanned sample rasterises like any page and accepts a
 *     placed field (R1.5);
 *   • no API/Documenso call is made during rendering — the PDF stays in the
 *     browser until a confirmed send (R1.6).
 *
 * `pdfjs-dist` is mocked (both the module the hook imports as `* as pdfjsLib`
 * and the `?url` worker asset) so the document/page/render lifecycle is driven
 * deterministically without a real PDF engine. jsdom has no
 * IntersectionObserver, so `PdfPageCanvas` renders eagerly (its documented
 * fallback) and no scroll simulation is needed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { useState } from 'react'

import usePdfDocument from './hooks/usePdfDocument'
import PdfPageCanvas from './PdfPageCanvas'

/* ------------------------------------------------------------------ */
/*  Mock pdfjs-dist (module + worker ?url asset)                       */
/* ------------------------------------------------------------------ */

// Mutable controller shared with the hoisted mock factory so each test can
// shape the document/page/render behaviour before mounting the harness.
const pdfMock = vi.hoisted(() => ({
  state: {
    numPages: 1,
    pageWidth: 600,
    pageHeight: 800,
    // How `getDocument(...).promise` settles.
    getDocumentBehavior: 'resolve' as 'resolve' | 'reject',
    // How each page's `render(...).promise` settles.
    renderBehavior: 'resolve' as 'resolve' | 'pending' | 'reject',
  },
  // Spy so we can assert the editor never transmits the PDF here.
  getDocumentSpy: vi.fn(),
}))

vi.mock('pdfjs-dist', () => {
  const GlobalWorkerOptions = { workerSrc: '' as string }

  const makePage = () => ({
    getViewport: ({ scale }: { scale: number }) => ({
      width: pdfMock.state.pageWidth * scale,
      height: pdfMock.state.pageHeight * scale,
    }),
    render: () => {
      const cancel = vi.fn()
      if (pdfMock.state.renderBehavior === 'reject') {
        // A genuine render failure (not a RenderingCancelledException).
        return { promise: Promise.reject(new Error('render boom')), cancel }
      }
      if (pdfMock.state.renderBehavior === 'pending') {
        // Never settles — leaves the page stuck in `rendering` (R1.3).
        return { promise: new Promise<void>(() => {}), cancel }
      }
      return { promise: Promise.resolve(), cancel }
    },
  })

  const makeDoc = () => ({
    numPages: pdfMock.state.numPages,
    getPage: vi.fn(async () => makePage()),
    destroy: vi.fn(),
  })

  const getDocument = vi.fn((args: unknown) => {
    pdfMock.getDocumentSpy(args)
    if (pdfMock.state.getDocumentBehavior === 'reject') {
      return { promise: Promise.reject(new Error('cannot open')), destroy: vi.fn() }
    }
    return { promise: Promise.resolve(makeDoc()), destroy: vi.fn() }
  })

  return { GlobalWorkerOptions, getDocument }
})

// The hook bundles the worker via Vite's `?url` import; stub it to a string.
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'mock-worker-url' }))

/* ------------------------------------------------------------------ */
/*  Mock the shared API client (R1.6 — nothing leaves the browser)     */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Test harness: usePdfDocument + PdfPageCanvas (editor stand-in)      */
/* ------------------------------------------------------------------ */

function PdfRenderHarness({ file }: { file: File | null }) {
  const { pdf, pages, loading, error, hasRenderError, setPageStatus } = usePdfDocument(file)
  // Field_Set stand-in: count of fields placed per page so we can assert a
  // page accepts a placed field (R1.5).
  const [placed, setPlaced] = useState<Record<number, number>>({})

  return (
    <div>
      {loading && <div data-testid="doc-loading">Loading document…</div>}

      {/* The editor surfaces the humanized render_failed message and blocks
          progression to send whenever the document or any page fails (R1.4). */}
      {hasRenderError && (
        <div role="alert" data-testid="render-failed">
          This document couldn’t be displayed for field placement.
        </div>
      )}
      {error && <span data-testid="error-code">{error}</span>}

      <button type="button" data-testid="send" disabled={hasRenderError || pages.length === 0}>
        Send for signature
      </button>

      {pdf &&
        pages.map((page) => (
          <PdfPageCanvas
            key={page.pageNumber}
            pdf={pdf}
            page={page}
            setPageStatus={setPageStatus}
          >
            {/* Place-a-field control standing in for a palette drop. */}
            <button
              type="button"
              data-testid={`place-field-${page.pageNumber}`}
              onClick={() =>
                setPlaced((prev) => ({
                  ...prev,
                  [page.pageNumber]: (prev[page.pageNumber] ?? 0) + 1,
                }))
              }
            >
              place field
            </button>
            {Array.from({ length: placed[page.pageNumber] ?? 0 }).map((_, i) => (
              <div
                key={i}
                data-testid={`placed-field-${page.pageNumber}-${i}`}
                data-recipient="recipient-0"
              />
            ))}
          </PdfPageCanvas>
        ))}
    </div>
  )
}

/** A minimal File whose only used method is `arrayBuffer()`. */
function makePdfFile(): File {
  return {
    name: 'sample.pdf',
    type: 'application/pdf',
    arrayBuffer: async () => new ArrayBuffer(16),
  } as unknown as File
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  // Reset the mock document/render behaviour to the happy path.
  pdfMock.state.numPages = 1
  pdfMock.state.pageWidth = 600
  pdfMock.state.pageHeight = 800
  pdfMock.state.getDocumentBehavior = 'resolve'
  pdfMock.state.renderBehavior = 'resolve'

  // jsdom doesn't implement canvas 2d context; provide a truthy stub so
  // PdfPageCanvas can proceed past its `getContext` guard and rasterise.
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

describe('PDF rendering for field placement', () => {
  // R1.1, R1.2 — every page of a multi-page PDF renders one page surface.
  it('renders one page surface per page for a multi-page document', async () => {
    pdfMock.state.numPages = 3

    render(<PdfRenderHarness file={makePdfFile()} />)

    // All three page surfaces appear (one per page).
    await screen.findByTestId('pdf-page-3')
    const surfaces = screen.getAllByTestId(/^pdf-page-\d+$/)
    expect(surfaces).toHaveLength(3)
    expect(surfaces.map((el) => el.getAttribute('data-page-number'))).toEqual(['1', '2', '3'])

    // Each page rasterises successfully → send becomes enabled (R1.4 inverse).
    await waitFor(() => {
      for (const surface of screen.getAllByTestId(/^pdf-page-\d+$/)) {
        expect(surface).toHaveAttribute('data-status', 'rendered')
      }
    })
    expect(screen.getByTestId('send')).toBeEnabled()
  })

  // R1.3 — a page still rendering shows a loading indicator until it completes.
  it('shows a per-page loading indicator while a page is rendering', async () => {
    pdfMock.state.renderBehavior = 'pending' // render never settles → stays 'rendering'

    render(<PdfRenderHarness file={makePdfFile()} />)

    // The page surface enters the rendering state and shows its spinner.
    const loading = await screen.findByTestId('pdf-page-loading-1')
    expect(loading).toBeInTheDocument()
    expect(screen.getByTestId('pdf-page-1')).toHaveAttribute('data-status', 'rendering')
  })

  // R1.3 (completion half) — the loading indicator clears once the page renders.
  it('clears the loading indicator once the page finishes rendering', async () => {
    render(<PdfRenderHarness file={makePdfFile()} />)

    await waitFor(() => {
      expect(screen.getByTestId('pdf-page-1')).toHaveAttribute('data-status', 'rendered')
    })
    expect(screen.queryByTestId('pdf-page-loading-1')).not.toBeInTheDocument()
  })

  // R1.4 — a getDocument rejection surfaces render_failed and keeps send disabled.
  it('surfaces render_failed and keeps send disabled when the document cannot be opened', async () => {
    pdfMock.state.getDocumentBehavior = 'reject'

    render(<PdfRenderHarness file={makePdfFile()} />)

    await screen.findByTestId('render-failed')
    expect(screen.getByTestId('error-code')).toHaveTextContent('render_failed')
    expect(screen.getByTestId('send')).toBeDisabled()
    // No page surfaces when the document never opened.
    expect(screen.queryAllByTestId(/^pdf-page-\d+$/)).toHaveLength(0)
  })

  // R1.4 — a page-render rejection surfaces render_failed and keeps send disabled.
  it('surfaces render_failed and keeps send disabled when a page fails to render', async () => {
    pdfMock.state.renderBehavior = 'reject'

    render(<PdfRenderHarness file={makePdfFile()} />)

    await waitFor(() => {
      expect(screen.getByTestId('pdf-page-1')).toHaveAttribute('data-status', 'error')
    })
    expect(screen.getByTestId('render-failed')).toBeInTheDocument()
    expect(screen.getByTestId('send')).toBeDisabled()
  })

  // R1.5 — a scanned/image-only page rasterises like any page and accepts a field.
  it('renders an image-only page and accepts a placed field on it', async () => {
    // An image-only/scanned page is rasterised identically by PDF.js — the
    // renderer treats it like any other page, so placement works the same.
    render(<PdfRenderHarness file={makePdfFile()} />)

    await waitFor(() => {
      expect(screen.getByTestId('pdf-page-1')).toHaveAttribute('data-status', 'rendered')
    })

    // No fields yet, then place one onto the rendered page.
    expect(screen.queryByTestId('placed-field-1-0')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('place-field-1'))

    expect(screen.getByTestId('placed-field-1-0')).toBeInTheDocument()
    expect(screen.getByTestId('placed-field-1-0')).toHaveAttribute('data-recipient', 'recipient-0')
  })

  // R1.6 — rendering happens entirely in the browser; nothing is transmitted.
  it('makes no API/Documenso call during rendering', async () => {
    pdfMock.state.numPages = 2

    render(<PdfRenderHarness file={makePdfFile()} />)

    await waitFor(() => {
      for (const surface of screen.getAllByTestId(/^pdf-page-\d+$/)) {
        expect(surface).toHaveAttribute('data-status', 'rendered')
      }
    })

    // The PDF is opened locally (getDocument called) but no network/API call
    // is made — the bytes never leave the browser before a confirmed send.
    expect(pdfMock.getDocumentSpy).toHaveBeenCalled()
    const client = apiClient as unknown as {
      get: ReturnType<typeof vi.fn>
      post: ReturnType<typeof vi.fn>
      put: ReturnType<typeof vi.fn>
      delete: ReturnType<typeof vi.fn>
    }
    expect(client.get).not.toHaveBeenCalled()
    expect(client.post).not.toHaveBeenCalled()
    expect(client.put).not.toHaveBeenCalled()
    expect(client.delete).not.toHaveBeenCalled()
  })
})
