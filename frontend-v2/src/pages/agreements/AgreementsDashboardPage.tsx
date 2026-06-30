/**
 * AgreementsDashboardPage — the org-wide Agreements dashboard
 * (feature: esignature-integration, Task 17.2, R11).
 *
 * Lists the calling organisation's e-signature envelopes via the typed esign
 * API client (`listEnvelopes`), newest-updated first (the backend orders the
 * list; this page renders in the returned order, R11.4). For each envelope it
 * shows the agreement type, recipients, current status, and the originating-
 * entity reference (R11.2). A status-filter control narrows the list (R11.3);
 * on the fail-closed filter path (HTTP 200 with empty items + a humanized
 * `filter_unavailable` error) it shows the error and no rows (R11.6).
 *
 * Opening an envelope shows a detail drawer with per-recipient signing status
 * and, when a signed document is stored, a download link wired to
 * `downloadSignedDocument` (R11.5).
 *
 * States (frontend-feature-completeness checklist):
 *   - Loading skeleton (`animate-pulse` rows) on the initial fetch — never a
 *     blank screen.
 *   - Error state with a human-readable message + Retry button (re-issues the
 *     request).
 *   - Empty state (icon + message + guidance) when the org has no envelopes or
 *     the active filter matches none.
 *
 * Safe consumption (per `.kiro/steering/safe-api-consumption.md`): the typed
 * `@/api/esign` client already normalises wire payloads with `?.` / `?? []` /
 * `?? 0`, every call is typed (no `as any`), and every `useEffect` that fetches
 * uses an `AbortController` with cleanup.
 *
 * The route is registered at `/agreements` in `App.tsx` behind
 * `ModuleRoute moduleSlug="esignatures"`, matching the sidebar entry (Task 16.2).
 *
 * The Void action's confirmation modal is Task 17.4 and the SendForSignatureModal
 * is Task 17.1 — this page leaves light hooks for both but does not own them.
 *
 * _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 16.x_
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import VoidAgreementModal from '@/components/esign/VoidAgreementModal'
import {
  listEnvelopes,
  getEnvelope,
  downloadSignedDocument,
  ENVELOPE_STATUSES,
} from '@/api/esign'
import type {
  EnvelopeOut,
  EnvelopeStatus,
  EsignError,
  RecipientOut,
} from '@/api/esign'

/* ------------------------------------------------------------------ */
/*  Presentation helpers                                               */
/* ------------------------------------------------------------------ */

/** Humanize a snake_case enum value into Title Case for display. */
function humanizeToken(value: string | null | undefined): string {
  if (!value) return '—'
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

/** Map an envelope status onto the closest Badge tone. */
function statusVariant(status: string | null | undefined): BadgeVariant {
  switch ((status ?? '').toLowerCase()) {
    case 'completed':
      return 'success'
    case 'sent':
    case 'viewed':
      return 'info'
    case 'partially_signed':
      return 'pending'
    case 'declined':
    case 'error':
      return 'danger'
    case 'voided':
    case 'draft':
      return 'neutral'
    default:
      return 'neutral'
  }
}

/** Per-recipient status tone (pending / signed / viewed / declined). */
function recipientVariant(status: string | null | undefined): BadgeVariant {
  switch ((status ?? '').toLowerCase()) {
    case 'signed':
    case 'completed':
      return 'success'
    case 'viewed':
    case 'opened':
      return 'info'
    case 'declined':
    case 'rejected':
      return 'danger'
    case 'pending':
    default:
      return 'pending'
  }
}

/** Short originating-entity reference, e.g. "Invoice · 1a2b…". */
function originatingRef(envelope: EnvelopeOut): string {
  const type = humanizeToken(envelope.originating_entity_type)
  const id = envelope.originating_entity_id ?? ''
  if (!id) return type
  const shortId = id.length > 8 ? `${id.slice(0, 8)}…` : id
  return `${type} · ${shortId}`
}

/** Best-effort timestamp formatting; tolerates blank / invalid strings. */
function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function recipientSummary(recipients: RecipientOut[]): string {
  if ((recipients?.length ?? 0) === 0) return 'No recipients'
  const names = recipients
    .map((r) => r.name || r.email)
    .filter(Boolean)
  if (names.length === 0) return `${recipients.length} recipient(s)`
  if (names.length <= 2) return names.join(', ')
  return `${names.slice(0, 2).join(', ')} +${names.length - 2}`
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AgreementsDashboardPage() {
  const [items, setItems] = useState<EnvelopeOut[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  /** Set on the fail-closed filter path (R11.6): empty items + humanized error. */
  const [filterError, setFilterError] = useState<EsignError | null>(null)
  const [statusFilter, setStatusFilter] = useState<EnvelopeStatus | null>(null)
  /** Client-side agreement-type filter over the loaded rows (null = all types). */
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  /** When set, the signed-document preview modal is open for this envelope. */
  const [previewEnvelope, setPreviewEnvelope] = useState<EnvelopeOut | null>(null)
  /** Bumping this re-issues the list request (Retry + post-action refresh). */
  const [reloadKey, setReloadKey] = useState(0)

  /* Detail drawer */
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<EnvelopeOut | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailReloadKey, setDetailReloadKey] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')

  /**
   * The envelope the user asked to void. Setting this opens the
   * VoidAgreementModal (Task 17.4), which performs the irreversible void via
   * `voidEnvelope` and, on success, refreshes the list + closes the detail
   * drawer.
   */
  const [voidCandidate, setVoidCandidate] = useState<EnvelopeOut | null>(null)

  const TERMINAL_STATUSES = useMemo(
    () => new Set(['completed', 'declined', 'voided']),
    [],
  )

  /* ---- List fetch ---- */
  useEffect(() => {
    const controller = new AbortController()

    const load = async () => {
      setLoading(true)
      setError('')
      setFilterError(null)
      try {
        const result = await listEnvelopes(statusFilter, controller.signal)
        if (controller.signal.aborted) return
        setItems(result?.items ?? [])
        setTotal(result?.total ?? 0)
        // Fail-closed filter (R11.6): show the humanized error and no rows.
        setFilterError(result?.error ?? null)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError('We could not load your agreements. Please try again.')
          setItems([])
          setTotal(0)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    load()
    return () => controller.abort()
  }, [statusFilter, reloadKey])

  /* ---- Detail fetch (re-reads per-recipient status + signed-doc link) ---- */
  useEffect(() => {
    if (!selectedId) return
    const controller = new AbortController()

    const loadDetail = async () => {
      setDetailLoading(true)
      setDetailError('')
      setDownloadError('')
      try {
        const envelope = await getEnvelope(selectedId, controller.signal)
        if (!controller.signal.aborted) setDetail(envelope)
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setDetailError('We could not load this agreement. Please try again.')
        }
      } finally {
        if (!controller.signal.aborted) setDetailLoading(false)
      }
    }

    loadDetail()
    return () => controller.abort()
  }, [selectedId, detailReloadKey])

  const handleRetry = useCallback(() => setReloadKey((k) => k + 1), [])

  const handleSelectStatus = useCallback((next: EnvelopeStatus | null) => {
    setStatusFilter(next)
  }, [])

  const openDetail = useCallback((envelope: EnvelopeOut) => {
    setSelectedId(envelope.id || null)
    setDetail(envelope) // optimistic: render the list row while detail refreshes
  }, [])

  const closeDetail = useCallback(() => {
    setSelectedId(null)
    setDetail(null)
    setDetailError('')
    setDownloadError('')
  }, [])

  const handleDownload = useCallback(async (envelope: EnvelopeOut) => {
    if (!envelope.id) return
    setDownloading(true)
    setDownloadError('')
    try {
      const blob = await downloadSignedDocument(envelope.id)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `agreement-${envelope.id}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch {
      setDownloadError('We could not download the signed document. Please try again.')
    } finally {
      setDownloading(false)
    }
  }, [])

  const isTerminal = useCallback(
    (status: string | null | undefined) => TERMINAL_STATUSES.has((status ?? '').toLowerCase()),
    [TERMINAL_STATUSES],
  )

  /* ---- Void (Task 17.4) ---- */
  const closeVoidModal = useCallback(() => setVoidCandidate(null), [])

  const handleVoided = useCallback(() => {
    // The envelope is now terminal (`voided`): clear the candidate, close the
    // detail drawer, and refresh the list so the new status is reflected.
    setVoidCandidate(null)
    closeDetail()
    handleRetry()
  }, [closeDetail, handleRetry])

  const hasRows = (items?.length ?? 0) > 0

  /** Distinct agreement types present in the loaded rows, for the Type filter. */
  const availableTypes = useMemo(() => {
    const seen = new Set<string>()
    for (const e of items) if (e.agreement_type) seen.add(e.agreement_type)
    return Array.from(seen).sort()
  }, [items])

  /** Rows after applying the client-side Type filter (status is server-side). */
  const displayedItems = useMemo(
    () => (typeFilter ? items.filter((e) => e.agreement_type === typeFilter) : items),
    [items, typeFilter],
  )
  const hasDisplayedRows = (displayedItems?.length ?? 0) > 0

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Page header */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Agreements</h1>
          <p className="mt-1 text-sm text-muted">
            {total} agreement{total !== 1 ? 's' : ''} on file
          </p>
        </div>
        {/* Send-for-signature entry point is wired in Task 17.1 (SendForSignatureModal). */}
      </div>

      {/* Status filter chips (R11.3) */}
      <div className="mb-5 flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        <FilterChip
          label="All"
          active={statusFilter === null}
          onClick={() => handleSelectStatus(null)}
        />
        {ENVELOPE_STATUSES.map((status) => (
          <FilterChip
            key={status}
            label={humanizeToken(status)}
            active={statusFilter === status}
            onClick={() => handleSelectStatus(status)}
          />
        ))}
      </div>

      {/* Type filter chips — client-side, over the loaded rows */}
      {availableTypes.length > 0 && (
        <div
          className="mb-5 flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Filter by type"
        >
          <span className="mr-1 text-xs font-medium uppercase tracking-wider text-muted">
            Type
          </span>
          <FilterChip label="All" active={typeFilter === null} onClick={() => setTypeFilter(null)} />
          {availableTypes.map((type) => (
            <FilterChip
              key={type}
              label={humanizeToken(type)}
              active={typeFilter === type}
              onClick={() => setTypeFilter(type)}
            />
          ))}
        </div>
      )}

      {/* Fetch error state (R: human-readable + Retry) */}
      {error && (
        <div className="mb-6 rounded-card border border-danger/30 bg-danger-soft p-4" role="alert">
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-danger">{error}</p>
            <Button variant="ghost" size="sm" onClick={handleRetry}>
              Retry
            </Button>
          </div>
        </div>
      )}

      {/* Fail-closed filter notice (R11.6): humanized error, no rows shown */}
      {!error && filterError && (
        <div
          className="mb-6 rounded-card border border-warn/30 bg-warn-soft p-4"
          role="alert"
          data-testid="filter-error"
        >
          <p className="text-sm text-warn">{filterError.message}</p>
        </div>
      )}

      {/* Loading skeleton — never a blank screen */}
      {loading && <ListSkeleton />}

      {/* Empty state */}
      {!loading && !error && !filterError && !hasDisplayedRows && (
        <EmptyState filtered={statusFilter !== null || typeFilter !== null} />
      )}

      {/* Envelope list */}
      {!loading && hasDisplayedRows && (
        <div className="overflow-hidden rounded-card border border-border bg-card">
          <table className="min-w-full divide-y divide-border text-sm">
            <thead className="bg-canvas">
              <tr className="text-left text-xs font-medium uppercase tracking-wider text-muted">
                <th className="px-4 py-3">Agreement</th>
                <th className="px-4 py-3">Recipients</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Originating</th>
                <th className="px-4 py-3">Updated</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {displayedItems.map((envelope) => (
                <tr key={envelope.id} className="hover:bg-canvas/60">
                  <td className="px-4 py-3 font-medium text-text">
                    {humanizeToken(envelope.agreement_type)}
                  </td>
                  <td className="px-4 py-3 text-muted">
                    {recipientSummary(envelope.recipients)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant(envelope.status)}>
                      {humanizeToken(envelope.status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-muted">{originatingRef(envelope)}</td>
                  <td className="px-4 py-3 text-muted">
                    {formatTimestamp(envelope.updated_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {(envelope.status ?? '').toLowerCase() === 'completed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPreviewEnvelope(envelope)}
                          aria-label={`Preview signed ${humanizeToken(envelope.agreement_type)} document`}
                        >
                          Preview
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openDetail(envelope)}
                        aria-label={`Open ${humanizeToken(envelope.agreement_type)} agreement`}
                      >
                        View
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail drawer (R11.5) */}
      {selectedId && (
        <DetailDrawer
          envelope={detail}
          loading={detailLoading}
          error={detailError}
          downloading={downloading}
          downloadError={downloadError}
          canVoid={!!detail && !isTerminal(detail.status)}
          voiding={voidCandidate?.id === detail?.id}
          onClose={closeDetail}
          onRetry={() => setDetailReloadKey((k) => k + 1)}
          onDownload={() => detail && handleDownload(detail)}
          onPreview={() => detail && setPreviewEnvelope(detail)}
          onVoidRequest={() => detail && setVoidCandidate(detail)}
        />
      )}

      {/* Signed-document preview modal — fetches the PDF blob and renders it
          inline (R11.5 extends the download-only flow with an in-app preview). */}
      {previewEnvelope && (
        <SignedDocumentPreviewModal
          envelope={previewEnvelope}
          onClose={() => setPreviewEnvelope(null)}
        />
      )}

      {/*
        Void confirmation modal (Task 17.4, R7). Consumes the `voidCandidate`
        selected from the detail drawer, calls `voidEnvelope` on confirm, and on
        success clears the candidate, closes the drawer, and refreshes the list.
      */}
      <VoidAgreementModal
        envelope={voidCandidate}
        onClose={closeVoidModal}
        onVoided={handleVoided}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
        active
          ? 'border-accent bg-accent text-white'
          : 'border-border bg-card text-muted hover:bg-canvas',
      ].join(' ')}
    >
      {label}
    </button>
  )
}

function ListSkeleton() {
  return (
    <div className="overflow-hidden rounded-card border border-border bg-card" aria-hidden="true">
      <div className="divide-y divide-border">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-4">
            <div className="h-4 w-40 animate-pulse rounded bg-canvas" />
            <div className="h-4 w-32 animate-pulse rounded bg-canvas" />
            <div className="h-5 w-20 animate-pulse rounded-full bg-canvas" />
            <div className="ml-auto h-4 w-24 animate-pulse rounded bg-canvas" />
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div
      className="flex flex-col items-center justify-center rounded-card border border-dashed border-border bg-card px-6 py-16 text-center"
      data-testid="empty-state"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className="mb-4 h-10 w-10 text-muted-2"
      >
        <path d="M15.5 3.5a2.12 2.12 0 013 3L8.5 16.5l-4 1 1-4L15.5 3.5zM4 21h16" />
      </svg>
      <h2 className="text-sm font-medium text-text">
        {filtered ? 'No agreements match this filter' : 'No agreements yet'}
      </h2>
      <p className="mt-1 max-w-sm text-sm text-muted">
        {filtered
          ? 'Try a different status filter to see more of your agreements.'
          : 'Send a document for signature from an invoice, quote, or staff record and it will appear here.'}
      </p>
    </div>
  )
}

function DetailDrawer({
  envelope,
  loading,
  error,
  downloading,
  downloadError,
  canVoid,
  voiding,
  onClose,
  onRetry,
  onDownload,
  onPreview,
  onVoidRequest,
}: {
  envelope: EnvelopeOut | null
  loading: boolean
  error: string
  downloading: boolean
  downloadError: string
  canVoid: boolean
  voiding: boolean
  onClose: () => void
  onRetry: () => void
  onDownload: () => void
  onPreview: () => void
  onVoidRequest: () => void
}) {
  const recipients = envelope?.recipients ?? []

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" role="dialog" aria-modal="true" aria-label="Agreement detail">
      {/* Backdrop */}
      <button
        type="button"
        className="absolute inset-0 h-full w-full cursor-default"
        aria-label="Close detail"
        onClick={onClose}
      />
      {/* Panel */}
      <aside className="relative flex h-full w-full max-w-md flex-col overflow-y-auto bg-card shadow-pop">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-6 py-4">
          <h2 className="text-[15px] font-semibold text-text">
            {humanizeToken(envelope?.agreement_type) || 'Agreement'}
          </h2>
          <button
            onClick={onClose}
            className="rounded-ctl p-1 text-muted-2 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Close detail"
          >
            <span aria-hidden="true" className="text-xl leading-none">×</span>
          </button>
        </div>

        <div className="flex-1 space-y-6 px-6 py-5">
          {loading && (
            <div className="space-y-3" aria-hidden="true">
              <div className="h-4 w-32 animate-pulse rounded bg-canvas" />
              <div className="h-4 w-48 animate-pulse rounded bg-canvas" />
              <div className="h-16 w-full animate-pulse rounded bg-canvas" />
            </div>
          )}

          {!loading && error && (
            <div className="rounded-card border border-danger/30 bg-danger-soft p-4" role="alert">
              <div className="flex items-center justify-between gap-4">
                <p className="text-sm text-danger">{error}</p>
                <Button variant="ghost" size="sm" onClick={onRetry}>
                  Retry
                </Button>
              </div>
            </div>
          )}

          {!loading && !error && envelope && (
            <>
              <dl className="space-y-3 text-sm">
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-muted">Status</dt>
                  <dd>
                    <Badge variant={statusVariant(envelope.status)}>
                      {humanizeToken(envelope.status)}
                    </Badge>
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-muted">Originating</dt>
                  <dd className="text-text">{originatingRef(envelope)}</dd>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-muted">Last updated</dt>
                  <dd className="text-text">{formatTimestamp(envelope.updated_at)}</dd>
                </div>
              </dl>

              {/* Per-recipient signing status (R11.5) */}
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  Recipients
                </h3>
                {recipients.length === 0 ? (
                  <p className="text-sm text-muted">No recipients recorded.</p>
                ) : (
                  <ul className="divide-y divide-border rounded-card border border-border">
                    {recipients.map((r) => (
                      <li key={r.id || r.email} className="flex items-center justify-between gap-3 px-3 py-2.5">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-text">{r.name || r.email || '—'}</p>
                          {r.email && r.name && (
                            <p className="truncate text-xs text-muted">{r.email}</p>
                          )}
                          {r.signing_role && (
                            <p className="text-[11px] uppercase tracking-wide text-muted-2">
                              {humanizeToken(r.signing_role)}
                            </p>
                          )}
                        </div>
                        <Badge variant={recipientVariant(r.recipient_status)}>
                          {humanizeToken(r.recipient_status) || 'Pending'}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Signed document link — only when stored (R11.5) */}
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  Signed document
                </h3>
                {envelope.signed_document_url ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={onPreview}
                      >
                        Preview signed PDF
                      </Button>
                      <Button
                        variant="quiet"
                        size="sm"
                        onClick={onDownload}
                        disabled={downloading}
                        aria-busy={downloading}
                      >
                        {downloading ? 'Downloading…' : 'Download'}
                      </Button>
                    </div>
                    {downloadError && (
                      <p className="mt-2 text-sm text-danger" role="alert">
                        {downloadError}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-muted">
                    The signed document will be available here once all recipients have signed.
                  </p>
                )}
              </section>
            </>
          )}
        </div>

        {/* Footer actions — Void is a hook for Task 17.4 (confirmation modal). */}
        {!loading && !error && envelope && canVoid && (
          <div className="sticky bottom-0 border-t border-border bg-card px-6 py-4">
            <Button
              variant="danger"
              size="sm"
              onClick={onVoidRequest}
              disabled={voiding}
              aria-busy={voiding}
            >
              Void agreement
            </Button>
          </div>
        )}
      </aside>
    </div>
  )
}

/**
 * SignedDocumentPreviewModal — fetch the stored signed PDF for an envelope and
 * render it inline in a large modal (an in-app alternative to downloading).
 *
 * The PDF bytes are fetched as a blob via the org-checked
 * `downloadSignedDocument` endpoint, turned into an object URL, and shown in an
 * `<iframe>` (the browser's native PDF viewer). The object URL is revoked on
 * close/unmount and the fetch is bound to an AbortController.
 */
function SignedDocumentPreviewModal({
  envelope,
  onClose,
}: {
  envelope: EnvelopeOut
  onClose: () => void
}) {
  const [url, setUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null

    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const blob = await downloadSignedDocument(envelope.id, controller.signal)
        if (controller.signal.aborted) return
        objectUrl = window.URL.createObjectURL(blob)
        setUrl(objectUrl)
      } catch {
        if (!controller.signal.aborted) {
          setError('We could not load the signed document for preview. Please try again.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    load()
    return () => {
      controller.abort()
      if (objectUrl) window.URL.revokeObjectURL(objectUrl)
    }
  }, [envelope.id])

  return (
    <Modal
      open
      onClose={onClose}
      title={`${humanizeToken(envelope.agreement_type)} — signed document`}
      className="h-[90vh] w-[92vw] max-w-5xl"
      bodyClassName="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
    >
      {loading && (
        <div
          className="flex flex-1 items-center justify-center py-10 text-sm text-muted"
          role="status"
          aria-live="polite"
        >
          Loading signed document…
        </div>
      )}
      {!loading && error && (
        <div className="flex flex-1 items-center justify-center p-6">
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        </div>
      )}
      {!loading && !error && url && (
        <iframe
          title="Signed document preview"
          src={url}
          className="h-full w-full flex-1 border-0"
          data-testid="signed-document-preview"
        />
      )}
    </Modal>
  )
}
