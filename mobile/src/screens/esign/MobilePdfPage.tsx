/**
 * MobilePdfPage — render exactly ONE page of the uploaded PDF to a `<canvas>`
 * for the Mobile_Field_Placement_Editor (R16).
 *
 * This is the mobile twin of the frontend-v2 `PdfPageCanvas.tsx`:
 *
 *   - it reserves the page's exact CSS box up-front from the descriptor dims so
 *     scroll position and overlay geometry stay stable before pixels arrive
 *     (R1.2), then rasterises the page into a `<canvas>` sized to that page's
 *     `getViewport({ scale: renderScale })` (R1.1);
 *   - rendering is lazy on devices with IntersectionObserver (deferred until the
 *     page scrolls near the viewport, bounding memory on a phone) and eager
 *     where IntersectionObserver is unavailable (e.g. jsdom);
 *   - it reports its render lifecycle back through `setPageStatus`
 *     (`rendering` → `rendered`, or `error`), and shows a per-page loading
 *     indicator while `status === 'rendering'` (R1.3);
 *   - scanned / image-only pages need no special handling: pdf.js rasterises
 *     them like any other page so fields place on them identically (R1.5);
 *   - a render throw flips the page to `status: 'error'` so the editor can
 *     surface the humanized `render_failed` message and block the send (R1.4).
 *
 * Touch_Place (R16.4): a tap on the page surface (not on an existing field box)
 * reports the tap position in overlay CSS px via `onPlaceAt`, so the editor can
 * place the currently-armed Field_Type there through the shared `clampToPage` +
 * coordinate mapping.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { MobileSpinner } from '@/components/ui'
import type { PageRenderStatus, RenderedPage } from './usePdfDocument'

export interface MobilePdfPageProps {
  /** The opened document this page belongs to. */
  pdf: PDFDocumentProxy
  /** Per-page geometry + lifecycle for the page this canvas renders. */
  page: RenderedPage
  /** Report this page's render lifecycle back to the document hook. */
  setPageStatus: (pageNumber: number, status: PageRenderStatus) => void
  /**
   * Called when the sender taps the page surface (not an existing field) to
   * place a field. `xPx`/`yPx` are overlay CSS px relative to the page box.
   */
  onPlaceAt?: (pageNumber: number, xPx: number, yPx: number) => void
  /**
   * Optional overlay (the field boxes for this page) rendered above the canvas
   * inside the same CSS-sized box so overlay px line up with the page 1:1.
   */
  children?: ReactNode
}

/** How far outside the viewport to start rendering a page (lazy buffer). */
const LAZY_RENDER_ROOT_MARGIN = '400px 0px'

/**
 * Render one PDF page. Reserves its CSS box immediately, rasterises lazily, and
 * reports `rendering`/`rendered`/`error` through `setPageStatus`.
 */
export default function MobilePdfPage({
  pdf,
  page,
  setPageStatus,
  onPlaceAt,
  children,
}: MobilePdfPageProps) {
  const { pageNumber, cssWidth, cssHeight, renderScale, status } = page

  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [visible, setVisible] = useState<boolean>(false)

  // Lazily flip `visible` when the page nears the viewport. Falls back to eager
  // rendering where IntersectionObserver is unavailable (e.g. jsdom).
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
    let renderTask: ReturnType<
      Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']
    > | null = null

    const render = async () => {
      try {
        setPageStatus(pageNumber, 'rendering')

        const pdfPage = await pdf.getPage(pageNumber)
        if (cancelled) return

        const canvas = canvasRef.current
        const context = canvas?.getContext('2d')
        if (!canvas || !context) return

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
        // pdf.js throws RenderingCancelledException on teardown — not an error.
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

  // Touch_Place: a tap on the page surface (the button layer) places a field at
  // the tap point. Taps that land on an existing field box are handled by that
  // box (which stops propagation), so they select/adjust rather than place.
  const handlePlace = (clientX: number, clientY: number) => {
    if (!onPlaceAt) return
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const xPx = clientX - rect.left
    const yPx = clientY - rect.top
    onPlaceAt(pageNumber, xPx, yPx)
  }

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

      {/* Tap-to-place surface. Sits below the field boxes (children) so an
          existing field intercepts the tap first. */}
      {onPlaceAt && (
        <button
          type="button"
          data-testid={`pdf-page-place-${pageNumber}`}
          aria-label={`Place a field on page ${pageNumber}`}
          className="absolute inset-0 h-full w-full cursor-crosshair bg-transparent"
          onPointerUp={(e) => handlePlace(e.clientX, e.clientY)}
        />
      )}

      {/* Field overlay (boxes) sits above the tap surface, same CSS box. */}
      {children}

      {/* Per-page loading indicator while this page rasterises (R1.3). */}
      {status === 'rendering' && (
        <div
          role="status"
          aria-live="polite"
          data-testid={`pdf-page-loading-${pageNumber}`}
          className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-white/70 text-gray-500 dark:bg-gray-900/60 dark:text-gray-400"
        >
          <MobileSpinner size="sm" />
          <span className="text-xs">Loading page {pageNumber}…</span>
        </div>
      )}

      {/* Inline notice when this page could not be rasterised (R1.4). */}
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
