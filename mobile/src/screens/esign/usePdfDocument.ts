/**
 * usePdfDocument (mobile) — load a sender-selected PDF entirely on-device and
 * expose the per-page geometry the Mobile_Field_Placement_Editor needs to lay
 * out its touch overlay (R16).
 *
 * This is the mobile twin of
 * `frontend-v2/src/components/esign/fieldplacement/hooks/usePdfDocument.ts`. It
 * owns the `pdfjs-dist` document lifecycle:
 *
 *   - reads the selected `File` into an `ArrayBuffer` and opens it as a
 *     `PDFDocumentProxy` (R1.1) — purely client-side, the bytes are NEVER
 *     transmitted until a confirmed send (R1.6);
 *   - computes each page's rendered CSS dimensions from a cheap
 *     `getViewport({ scale })` (no rasterisation) so the editor can reserve
 *     space and keep overlay geometry stable while pixels arrive (R1.2);
 *   - chooses a responsive `renderScale` per page that fits the available width
 *     across the 320–430 px mobile viewport range (R16.6) and is capped for
 *     many-page documents to bound memory on a phone;
 *   - exposes a `RenderedPage` per page plus a `setPageStatus` callback so each
 *     page canvas can report its render lifecycle. If the document fails to open
 *     or any page fails to render, `hasRenderError` flips so the editor can
 *     surface a humanized message and block the send (R1.4).
 *
 * The render scale never leaks into the normalized field coordinates — the
 * shared coordinate mapping divides out the rendered pixel dimensions — so two
 * senders at different zoom levels produce identical normalized fields (R7.2),
 * which is what keeps the mobile/web geometry invariants identical (R16.9).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
// Vite bundles the worker as a hashed asset and hands back its URL (`?url`),
// so the worker ships with the app rather than being fetched from a CDN. This
// mirrors the frontend-v2 wiring in usePdfDocument.ts.
import PdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

// Bundle + wire the worker exactly once, at module load. Guarded so repeated
// imports (and test re-imports) don't clobber an already-set worker source.
if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorkerUrl
}

/** A page's render lifecycle, reported by the page canvas as it rasterises. */
export type PageRenderStatus = 'pending' | 'rendering' | 'rendered' | 'error'

/** Per-page geometry + lifecycle the editor needs to lay out the overlay. */
export interface RenderedPage {
  /** 1-based page number. */
  pageNumber: number
  /** Rendered element width in CSS px at this page's `renderScale`. */
  cssWidth: number
  /** Rendered element height in CSS px at this page's `renderScale`. */
  cssHeight: number
  /** pdf.js scale used to size this page's canvas. */
  renderScale: number
  /** Where this page is in its render lifecycle. */
  status: PageRenderStatus
}

export interface UsePdfDocumentOptions {
  /**
   * CSS px width available to render a page into (typically the editor's
   * content column width). Drives the responsive `renderScale`. Defaults to
   * the 320 px minimum supported mobile viewport when not yet measured.
   */
  availableWidth?: number
}

export interface UsePdfDocumentResult {
  /** The opened document, or `null` until it loads / after a load failure. */
  pdf: PDFDocumentProxy | null
  /** Number of pages in the document (0 until loaded). */
  numPages: number
  /** Per-page geometry + status, in page order. */
  pages: RenderedPage[]
  /** True while the document is being read and opened. */
  loading: boolean
  /**
   * Humanized error code when the document could not be opened, else `null`.
   * The editor maps this to a user-facing "couldn't be displayed" message.
   */
  error: string | null
  /**
   * True if the document failed to open OR any page failed to render. The
   * editor keeps the send control disabled while this is true (R1.4).
   */
  hasRenderError: boolean
  /** Report a page's render lifecycle (called by the page canvas). */
  setPageStatus: (pageNumber: number, status: PageRenderStatus) => void
}

/** Minimum supported viewport / render width (R16.6: 320 px). */
const MIN_VIEWPORT_WIDTH = 320
/** Floor on the render scale so a huge page never collapses to nothing. */
const MIN_RENDER_SCALE = 0.2
/** Cap the render scale for ordinary (few-page) documents. */
const MAX_RENDER_SCALE = 2
/** Above this page count, cap the scale harder to bound canvas memory. */
const MANY_PAGES_THRESHOLD = 15
/** Tighter scale cap applied to many-page documents. */
const MANY_PAGES_MAX_RENDER_SCALE = 1.25
/** Error code surfaced when the document cannot be opened/rendered (R1.4). */
const RENDER_FAILED = 'render_failed'

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

/**
 * Choose a render scale that fits `availableWidth`, never below the 320 px
 * floor's intent, and capped (harder for many-page docs) to bound memory.
 * `intrinsicWidth` is the page's width in CSS px at scale 1.
 */
function computeRenderScale(
  intrinsicWidth: number,
  availableWidth: number,
  numPages: number,
): number {
  if (!(intrinsicWidth > 0)) return 1
  const targetWidth = Math.max(availableWidth || MIN_VIEWPORT_WIDTH, MIN_VIEWPORT_WIDTH)
  const maxScale =
    numPages > MANY_PAGES_THRESHOLD ? MANY_PAGES_MAX_RENDER_SCALE : MAX_RENDER_SCALE
  return clamp(targetWidth / intrinsicWidth, MIN_RENDER_SCALE, maxScale)
}

/**
 * Load `file` as a PDF and expose its per-page geometry. Re-runs whenever the
 * file or the available width changes; tears the document down on unmount or
 * file change so no rendering work outlives the editor.
 */
export function usePdfDocument(
  file: File | null,
  options: UsePdfDocumentOptions = {},
): UsePdfDocumentResult {
  const { availableWidth } = options

  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [pages, setPages] = useState<RenderedPage[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!file) {
      setPdf(null)
      setPages([])
      setLoading(false)
      setError(null)
      return
    }

    let cancelled = false
    let loadingTask: ReturnType<typeof pdfjsLib.getDocument> | null = null
    let loadedDoc: PDFDocumentProxy | null = null

    setLoading(true)
    setError(null)
    setPdf(null)
    setPages([])

    const load = async () => {
      try {
        const data = await file.arrayBuffer()
        if (cancelled) return

        loadingTask = pdfjsLib.getDocument({ data })
        const doc = await loadingTask.promise
        if (cancelled) {
          void doc.destroy()
          return
        }
        loadedDoc = doc

        const numPages = doc.numPages
        const rendered: RenderedPage[] = []
        for (let pageNumber = 1; pageNumber <= numPages; pageNumber += 1) {
          const page = await doc.getPage(pageNumber)
          if (cancelled) {
            void doc.destroy()
            return
          }
          const baseViewport = page.getViewport({ scale: 1 })
          const renderScale = computeRenderScale(
            baseViewport.width,
            availableWidth ?? MIN_VIEWPORT_WIDTH,
            numPages,
          )
          const viewport = page.getViewport({ scale: renderScale })
          rendered.push({
            pageNumber,
            cssWidth: viewport.width,
            cssHeight: viewport.height,
            renderScale,
            status: 'pending',
          })
        }

        if (cancelled) {
          void doc.destroy()
          return
        }
        setPdf(doc)
        setPages(rendered)
        setLoading(false)
      } catch {
        if (cancelled) return
        setError(RENDER_FAILED)
        setPdf(null)
        setPages([])
        setLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
      if (loadingTask) void loadingTask.destroy()
      if (loadedDoc) void loadedDoc.destroy()
    }
  }, [file, availableWidth])

  const setPageStatus = useCallback((pageNumber: number, status: PageRenderStatus) => {
    setPages((prev) => {
      let changed = false
      const next = prev.map((p) => {
        if (p.pageNumber === pageNumber && p.status !== status) {
          changed = true
          return { ...p, status }
        }
        return p
      })
      return changed ? next : prev
    })
  }, [])

  const hasRenderError = useMemo(
    () => error !== null || pages.some((p) => p.status === 'error'),
    [error, pages],
  )

  return {
    pdf,
    numPages: pages.length,
    pages,
    loading,
    error,
    hasRenderError,
    setPageStatus,
  }
}

export default usePdfDocument
