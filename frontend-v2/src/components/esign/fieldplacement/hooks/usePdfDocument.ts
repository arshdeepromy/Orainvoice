/**
 * usePdfDocument — load a sender-selected PDF entirely in the browser and expose
 * the per-page geometry the Field_Placement_Editor needs to lay out its overlay.
 *
 * Why this exists
 * ---------------
 * The field-placement editor renders every page of the uploaded PDF so the
 * Org_Sender can drop field boxes onto exact positions. This hook owns the
 * `pdfjs-dist` document lifecycle:
 *
 *   - reads the selected `File` into an `ArrayBuffer` and opens it as a
 *     `PDFDocumentProxy` (R1.1) — purely client-side, the bytes are NEVER
 *     transmitted to Documenso here; the existing send pipeline uploads them
 *     only on a confirmed send (R1.6);
 *   - computes, for every page, the rendered CSS dimensions from a cheap
 *     `getViewport({ scale })` (no rasterisation), so the editor can reserve
 *     each page's space up-front and keep scroll/overlay geometry stable while
 *     pixels arrive progressively (R1.2);
 *   - chooses a responsive `renderScale` per page that fits the available
 *     width (≥320 px viewport range, R7.2/R10.5) and is capped for many-page
 *     documents to bound memory;
 *   - exposes a `RenderedPage` per page plus a `setPageStatus` callback so the
 *     per-page canvas (`PdfPageCanvas`) can report its render lifecycle. If the
 *     document fails to open or any page fails to render, `hasRenderError` flips
 *     so the editor can surface a humanized message and block the send (R1.4).
 *
 * The render scale never leaks into the normalized field coordinates — the
 * coordinate mapping divides out the rendered pixel dimensions — so two senders
 * at different zoom levels produce identical normalized fields (R7.2).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
// Vite bundles the worker as a hashed asset and hands back its URL (`?url`),
// so the worker ships with the app rather than being fetched from a CDN.
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
   * the 320 px minimum supported viewport when not yet measured.
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

/** Minimum supported viewport / render width (R7.2, R10.5). */
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
  // Intrinsic (scale-1) page geometry, captured once when the document opens.
  // Width changes recompute the render scale from this WITHOUT reopening the
  // document — reopening on every resize caused a scrollbar/ResizeObserver
  // feedback loop that made the editor flash and never finish loading.
  const [pageBases, setPageBases] = useState<{ width: number; height: number }[]>([])
  const [pages, setPages] = useState<RenderedPage[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // ── Effect 1: open the document. Depends ONLY on `file`. ────────────────
  // Reads the bytes, opens the PDF, and captures each page's intrinsic
  // (scale-1) viewport. Never re-runs on width changes.
  useEffect(() => {
    if (!file) {
      setPdf(null)
      setPageBases([])
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
    setPageBases([])
    setPages([])

    const load = async () => {
      try {
        // Read the bytes fresh in this effect run. pdf.js takes ownership of
        // the buffer, but re-reading on every (re)mount keeps StrictMode's
        // double-invoke safe.
        const data = await file.arrayBuffer()
        if (cancelled) return

        loadingTask = pdfjsLib.getDocument({ data })
        const doc = await loadingTask.promise
        if (cancelled) {
          // Lost the race against an unmount/file change — discard.
          void doc.destroy()
          return
        }
        loadedDoc = doc

        // Cheap per-page geometry: getViewport never rasterises, so we can
        // capture each page's intrinsic size up-front.
        const numPages = doc.numPages
        const bases: { width: number; height: number }[] = []
        for (let pageNumber = 1; pageNumber <= numPages; pageNumber += 1) {
          const page = await doc.getPage(pageNumber)
          if (cancelled) {
            void doc.destroy()
            return
          }
          const baseViewport = page.getViewport({ scale: 1 })
          bases.push({ width: baseViewport.width, height: baseViewport.height })
        }

        if (cancelled) {
          void doc.destroy()
          return
        }
        setPdf(doc)
        setPageBases(bases)
        setLoading(false)
      } catch {
        if (cancelled) return
        // Any failure to read/open/measure the document blocks the send (R1.4).
        setError(RENDER_FAILED)
        setPdf(null)
        setPageBases([])
        setPages([])
        setLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
      // Abort an in-flight load and free the document/worker resources.
      if (loadingTask) void loadingTask.destroy()
      if (loadedDoc) void loadedDoc.destroy()
    }
  }, [file])

  // ── Effect 2: (re)compute per-page render scale + CSS geometry. ─────────
  // Depends on the intrinsic bases (set once per document) and the available
  // width. A width change only resizes pages here; it never reopens the PDF.
  useEffect(() => {
    if (pageBases.length === 0) {
      setPages([])
      return
    }
    const numPages = pageBases.length
    setPages((prev) => {
      const next: RenderedPage[] = pageBases.map((base, i) => {
        const pageNumber = i + 1
        const renderScale = computeRenderScale(
          base.width,
          availableWidth ?? MIN_VIEWPORT_WIDTH,
          numPages,
        )
        const cssWidth = base.width * renderScale
        const cssHeight = base.height * renderScale
        const existing = prev.find((p) => p.pageNumber === pageNumber)
        // Preserve a page's render lifecycle when its scale is unchanged so a
        // no-op width fluctuation never forces a re-rasterise; only reset to
        // 'pending' when the scale actually changed.
        const status: PageRenderStatus =
          existing && existing.renderScale === renderScale ? existing.status : 'pending'
        return { pageNumber, cssWidth, cssHeight, renderScale, status }
      })
      // Bail out of the state update entirely if nothing changed (keeps the
      // reference stable and avoids re-render churn).
      const unchanged =
        prev.length === next.length &&
        next.every((p, i) => {
          const q = prev[i]
          return (
            q &&
            q.pageNumber === p.pageNumber &&
            q.cssWidth === p.cssWidth &&
            q.cssHeight === p.cssHeight &&
            q.renderScale === p.renderScale &&
            q.status === p.status
          )
        })
      return unchanged ? prev : next
    })
  }, [pageBases, availableWidth])

  const setPageStatus = useCallback(
    (pageNumber: number, status: PageRenderStatus) => {
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
    },
    [],
  )

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
