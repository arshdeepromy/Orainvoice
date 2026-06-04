/**
 * PpsrDetailDrawer — slide-in detail panel for a saved PPSR search.
 *
 * Implements design §6.4 / §8 of `.kiro/specs/ppsr-module/design.md`:
 *
 *   - Opens when `open && searchId`; fetches via
 *     `ppsrApi.getSearch(id)` with an `AbortController`.
 *   - Renders the result via the shared `PpsrResultPanel`.
 *   - Handles HTTP 410 (forgotten) gracefully — shows a banner
 *     explaining that the payload was wiped.
 *   - Provides a Forget button when `isAdmin === true`.
 *   - Pure-Tailwind drawer (no external library) — overlay + slide-in
 *     panel + Esc-to-close + click-outside-to-close.
 *
 * Follows `.kiro/steering/safe-api-consumption.md` patterns.
 *
 * **Validates: PPSR module spec task D4**
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { ppsrApi, type PpsrSearchResult } from '@/api/ppsr'
import { PpsrResultPanel } from './PpsrResultPanel'

// ===========================================================================
// Props
// ===========================================================================

export interface PpsrDetailDrawerProps {
  /** Search id to fetch. Drawer is inert when `null`. */
  searchId: string | null
  /** Show / hide the drawer. */
  open: boolean
  /** Close handler — called on Esc, overlay click, and the close button. */
  onClose: () => void
  /**
   * When true, the drawer renders a Forget button. Pass
   * `currentUser.role === 'org_admin'` from the parent.
   */
  isAdmin?: boolean
  /** Optional callback invoked after a successful forget. */
  onForgotten?: (searchId: string) => void
}

// ===========================================================================
// Forgotten-state shape
// ===========================================================================

interface ForgottenState {
  forgottenAt: string | null
  /** Optional summary fields the server may include alongside the 410. */
  rego?: string | null
  match?: string | null
  matchDescription?: string | null
  statementCount?: number | null
}

// ===========================================================================
// Helper — extract a readable error message
// ===========================================================================

function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)
      ?.detail
    if (typeof detail === 'string' && detail.trim().length > 0) {
      return detail
    }
    if (err.message) return err.message
  }
  if (err instanceof Error) return err.message
  return 'Failed to load PPSR check'
}

function isForgottenResponse(err: unknown): {
  forgotten: boolean
  payload: ForgottenState | null
} {
  if (!axios.isAxiosError(err)) return { forgotten: false, payload: null }
  if (err.response?.status !== 410) return { forgotten: false, payload: null }
  const body = (err.response?.data ?? {}) as Record<string, unknown>
  return {
    forgotten: true,
    payload: {
      forgottenAt:
        typeof body?.forgotten_at === 'string'
          ? (body.forgotten_at as string)
          : null,
      rego: typeof body?.rego === 'string' ? (body.rego as string) : null,
      match: typeof body?.match === 'string' ? (body.match as string) : null,
      matchDescription:
        typeof body?.match_description === 'string'
          ? (body.match_description as string)
          : null,
      statementCount:
        typeof body?.statement_count === 'number'
          ? (body.statement_count as number)
          : null,
    },
  }
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ===========================================================================
// Component
// ===========================================================================

export function PpsrDetailDrawer({
  searchId,
  open,
  onClose,
  isAdmin = false,
  onForgotten,
}: PpsrDetailDrawerProps) {
  const [result, setResult] = useState<PpsrSearchResult | null>(null)
  const [forgotten, setForgotten] = useState<ForgottenState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setLoading] = useState(false)
  const [isForgetting, setForgetting] = useState(false)
  const [isExporting, setExporting] = useState(false)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)

  // Esc-to-close.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Move focus to the close button when the drawer opens.
  useEffect(() => {
    if (open) {
      // Defer to the next tick so the element is mounted.
      const t = setTimeout(() => closeButtonRef.current?.focus(), 0)
      return () => clearTimeout(t)
    }
    return undefined
  }, [open])

  // Reset internal state whenever the drawer closes or the search id
  // changes — prevents flashing stale data on the next open.
  useEffect(() => {
    if (!open) {
      setResult(null)
      setForgotten(null)
      setError(null)
      setLoading(false)
    }
  }, [open])

  // Fetch the search detail.
  useEffect(() => {
    if (!open || !searchId) return undefined

    const controller = new AbortController()
    let cancelled = false

    async function fetchDetail() {
      setLoading(true)
      setError(null)
      setForgotten(null)
      setResult(null)
      try {
        const detail = await ppsrApi.getSearch(searchId!, controller.signal)
        if (cancelled) return
        setResult(detail ?? null)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if (cancelled) return
        const { forgotten: isForgotten, payload } = isForgottenResponse(err)
        if (isForgotten) {
          setForgotten(payload)
          return
        }
        setError(extractErrorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchDetail()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [open, searchId])

  // ---------------------------------------------------------------------
  // Action handlers (PDF export + admin forget)
  // ---------------------------------------------------------------------

  const handleExport = useCallback(async () => {
    if (!searchId || isExporting) return
    setExporting(true)
    try {
      const blob = await ppsrApi.exportPdf(searchId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `ppsr-${result?.rego ?? searchId}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      setError(extractErrorMessage(err))
    } finally {
      setExporting(false)
    }
  }, [searchId, result?.rego, isExporting])

  const handleForget = useCallback(async () => {
    if (!searchId || isForgetting || !isAdmin) return
    const ok = window.confirm(
      'Wipe the cached PPSR payload for this search? The audit-trail row stays.',
    )
    if (!ok) return
    setForgetting(true)
    try {
      await ppsrApi.forgetSearch(searchId)
      setForgotten({
        forgottenAt: new Date().toISOString(),
        rego: result?.rego ?? null,
        match: (result?.match ?? null) as string | null,
        matchDescription: result?.match_description ?? null,
        statementCount: result?.statement_count ?? null,
      })
      setResult(null)
      onForgotten?.(searchId)
    } catch (err: unknown) {
      setError(extractErrorMessage(err))
    } finally {
      setForgetting(false)
    }
  }, [searchId, result, isAdmin, isForgetting, onForgotten])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="ppsr-detail-drawer-title"
      data-testid="ppsr-detail-drawer"
      className="fixed inset-0 z-50 flex justify-end bg-ink/50"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-3xl flex-col overflow-y-auto bg-card shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-border bg-card px-4 py-3">
          <div className="min-w-0">
            <h2
              id="ppsr-detail-drawer-title"
              className="truncate text-lg font-semibold text-text"
            >
              PPSR check{' '}
              {result?.rego && (
                <span className="mono text-base text-muted">
                  · {result.rego}
                </span>
              )}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {isAdmin && (result || forgotten) && !forgotten && (
              <button
                type="button"
                onClick={handleForget}
                disabled={isForgetting}
                className="inline-flex h-9 min-h-[36px] items-center rounded-ctl border border-danger/40 bg-card px-3 text-xs font-medium text-danger shadow-card hover:bg-danger-soft focus:outline-none focus:ring-2 focus:ring-danger disabled:cursor-not-allowed disabled:opacity-50"
                data-testid="ppsr-detail-forget"
              >
                {isForgetting ? 'Forgetting…' : 'Forget'}
              </button>
            )}
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Close drawer"
              className="rounded-ctl p-2 text-muted-2 hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
              data-testid="ppsr-detail-close"
            >
              <span aria-hidden="true" className="text-xl leading-none">
                ×
              </span>
            </button>
          </div>
        </header>

        <div className="flex-1 px-4 py-4">
          {/* Loading -------------------------------------------------- */}
          {isLoading && (
            <p
              className="text-sm text-muted"
              data-testid="ppsr-detail-loading"
            >
              Loading PPSR check…
            </p>
          )}

          {/* Error ---------------------------------------------------- */}
          {!isLoading && error && (
            <div
              role="alert"
              className="rounded-ctl border border-danger/40 bg-danger-soft p-3 text-sm text-danger"
              data-testid="ppsr-detail-error"
            >
              {error}
            </div>
          )}

          {/* Forgotten ------------------------------------------------ */}
          {!isLoading && forgotten && (
            <div
              className="space-y-4"
              data-testid="ppsr-detail-forgotten"
            >
              <div className="rounded-ctl border border-warn/40 bg-warn-soft p-4 text-sm text-warn">
                <p className="font-medium">
                  Payload was wiped — only the audit summary remains
                </p>
                {forgotten.forgottenAt && (
                  <p className="mt-1 text-xs opacity-80">
                    Forgotten {formatDateTime(forgotten.forgottenAt)}
                  </p>
                )}
              </div>
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {forgotten.rego && (
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-2">
                      Rego
                    </dt>
                    <dd className="mono mt-0.5 text-sm text-text">
                      {forgotten.rego}
                    </dd>
                  </div>
                )}
                {forgotten.match && (
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-2">
                      Match
                    </dt>
                    <dd className="mt-0.5 text-sm text-text">
                      {forgotten.match}
                      {forgotten.matchDescription
                        ? ` — ${forgotten.matchDescription}`
                        : ''}
                    </dd>
                  </div>
                )}
                {forgotten.statementCount != null && (
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-2">
                      Statements
                    </dt>
                    <dd className="mono mt-0.5 text-sm text-text">
                      {forgotten.statementCount}
                    </dd>
                  </div>
                )}
              </dl>
            </div>
          )}

          {/* Result --------------------------------------------------- */}
          {!isLoading && !error && !forgotten && result && (
            <PpsrResultPanel
              result={result}
              onExport={handleExport}
            />
          )}
        </div>
      </div>
    </div>
  )
}

export default PpsrDetailDrawer
