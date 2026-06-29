/**
 * PdfPageCanvas — render exactly ONE page of the uploaded PDF to a `<canvas>`
 * for the Field_Placement_Editor.
 *
 * Why this exists
 * ---------------
 * `usePdfDocument` owns the document lifecycle and the per-page geometry
 * (`RenderedPage`: 1-based `pageNumber`, the rendered CSS `cssWidth`/`cssHeight`,
 * the `renderScale`, and a `status`). This component owns the *rasterisation* of
 * a single page:
 *
 *   - it reserves the page's exact CSS box up-front from the descriptor dims so
 *     scroll position and overlay geometry stay stable before pixels arrive
 *     (R1.2), then rasterises the page into a `<canvas>` sized to that page's
 *     `getViewport({ scale: renderScale })` (R1.1);
 *   - rendering is **lazy** — it defers `page.render()` until the page scrolls
 *     near the viewport (IntersectionObserver) so a many-page document stays
 *     responsive and bounded in memory. Where IntersectionObserver is
 *     unavailable (e.g. jsdom) it renders eagerly;
 *   - it reports its render lifecycle back through `setPageStatus`
 *     (`rendering` → `rendered`, or `error`), and shows a per-page loading
 *     indicator while `status === 'rendering'`, clearing it on completion
 *     (R1.3);
 *   - scanned / image-only pages need no special handling: PDF.js rasterises
 *     them to the canvas like any other page, so fields place on them
 *     identically (R1.5);
 *   - if the page render throws, it flips the page to `status: 'error'` so the
 *     editor can surface the humanized `render_failed` message and block the
 *     send (R1.4).
 *
 * The render scale is purely a display concern — it never leaks into the
 * normalized field coordinates, which divide out `cssWidth`/`cssHeight`
 * (see coordinateMapping.ts), so the canvas can rasterise at device pixel ratio
 * for crispness while the CSS box stays at the page's `cssWidth`/`cssHeight`.
 */

import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import type { PageRenderStatus, RenderedPage } from './hooks/usePdfDocument'

export interface PdfPageCanvasProps {
  /** The opened document this page belongs to. */
  pdf: PDFDocumentProxy
  /** Per-page geometry + lifecycle for the page this canvas renders. */
  page: RenderedPage
  /** Report this page's render lifecycle back to the document hook. */
  setPageStatus: (pageNumber: number, status: PageRenderStatus) => void
  /**
   * Optional overlay (the field boxes for this page) rendered above the canvas
   * inside the same CSS-sized box, so overlay px line up with the rasterised
   * page 1:1.
   */
  children?: React.ReactNode
}

/** How far outside the viewport to start rendering a page (lazy buffer). */
const LAZY_RENDER_ROOT_MARGIN = '600px 0px'

/**
 * Render one PDF page. Reserves its CSS box immediately, rasterises lazily, and
 * reports `rendering`/`rendered`/`error` through `setPageStatus`.
 */
export default function PdfPageCanvas({
  pdf,
  page,
  setPageStatus,
  children,
}: PdfPageCanvasProps) {
  const { pageNumber, cssWidth, cssHeight, renderScale, status } = page

  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  // Becomes true once the page is at/near the viewport (or eagerly when there
  // is no IntersectionObserver). Drives the single render pass.
  const [visible, setVisible] = useState<boolean>(false)

  // Lazily flip `visible` when the page nears the viewport. Falls back to
  // eager rendering where IntersectionObserver is unavailable (e.g. jsdom).
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true)
            observer.disconnect()
            break
          }
        }
      },
      { root: null, rootMargin: LAZY_RENDER_ROOT_MARGIN },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Rasterise the page exactly once it becomes visible. Cancels any in-flight
  // render task on unmount / dependency change so no work outlives the canvas.
  useEffect(() => {
    if (!visible) return

    let cancelled = false
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | null =
      null

    const render = async () => {
      try {
        setPageStatus(pageNumber, 'rendering')

        const pdfPage = await pdf.getPage(pageNumber)
        if (cancelled) return

        const canvas = canvasRef.current
        const context = canvas?.getContext('2d')
        if (!canvas || !context) {
          // No canvas to draw into (already torn down) — nothing to render.
          return
        }

        const viewport = pdfPage.getViewport({ scale: renderScale })

        // Rasterise at device pixel ratio for crispness while keeping the CSS
        // box at the page's cssWidth/cssHeight so overlay px map 1:1.
        const outputScale =
          typeof window !== 'undefined' && window.devicePixelRatio
            ? window.devicePixelRatio
            : 1
        canvas.width = Math.floor(viewport.width * outputScale)
        canvas.height = Math.floor(viewport.height * outputScale)
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`

        const transform =
          outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined

        renderTask = pdfPage.render({
          canvas,
          canvasContext: context,
          viewport,
          ...(transform ? { transform } : {}),
        })
        await renderTask.promise
        if (cancelled) return

        setPageStatus(pageNumber, 'rendered')
      } catch (err) {
        if (cancelled) return
        // A genuine render failure (not a cancellation) blocks the send (R1.4).
        // pdf.js throws a RenderingCancelledException when a task is cancelled;
        // that is expected teardown, not an error to surface.
        const name = (err as { name?: string } | null)?.name
        if (name === 'RenderingCancelledException') return
        setPageStatus(pageNumber, 'error')
      }
    }

    void render()

    return () => {
      cancelled = true
      if (renderTask) {
        try {
          renderTask.cancel()
        } catch {
          // Cancelling an already-settled task is a no-op we can ignore.
        }
      }
    }
  }, [visible, pdf, pageNumber, renderScale, setPageStatus])

  return (
    <div
      ref={containerRef}
      data-testid={`pdf-page-${pageNumber}`}
      data-page-number={pageNumber}
      data-status={status}
      className="relative mx-auto bg-white shadow-sm ring-1 ring-black/5 dark:ring-white/10"
      // Reserve the page's exact CSS box up-front so scroll/overlay geometry is
      // stable before the pixels arrive (R1.2).
      style={{ width: cssWidth, height: cssHeight }}
    >
      <canvas ref={canvasRef} className="block h-full w-full" aria-hidden="true" />

      {/* Field overlay (boxes) sits above the rasterised page, same CSS box. */}
      {children}

      {/* Per-page loading indicator while this page rasterises (R1.3). */}
      {status === 'rendering' && (
        <div
          role="status"
          aria-live="polite"
          data-testid={`pdf-page-loading-${pageNumber}`}
          className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-white/70 text-gray-500 dark:bg-gray-900/60 dark:text-gray-400"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
            className="h-6 w-6 animate-spin"
          >
            <circle
              cx="12"
              cy="12"
              r="9"
              stroke="currentColor"
              strokeWidth="2.4"
              className="opacity-25"
            />
            <path
              d="M21 12a9 9 0 0 0-9-9"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
            />
          </svg>
          <span className="text-xs">Loading page {pageNumber}…</span>
        </div>
      )}

      {/* Inline notice when this page could not be rasterised (R1.4). The
          editor surfaces the blocking render_failed message; this just marks
          the failed page in place. */}
      {status === 'error' && (
        <div
          role="alert"
          data-testid={`pdf-page-error-${pageNumber}`}
          className="absolute inset-0 flex items-center justify-center bg-red-50 px-4 text-center text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300"
        >
          Page {pageNumber} couldn’t be displayed for field placement.
        </div>
      )}
    </div>
  )
}
