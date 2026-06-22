/**
 * ClockedInDrawer — admin "who is currently on the clock" panel.
 *
 * Slide-in drawer triggered from the Staff list page-head button. Lists every
 * staff member with an open `time_clock_entries` row and renders a compact
 * live elapsed timer (HH:MM:SS) per row computed CLIENT-SIDE from each entry's
 * `clock_in_at` — no per-second polling. The list refreshes on open and every
 * 30 seconds while open so newly clocked-in staff appear without a manual
 * refresh, but the second-tick of the timer never hits the network.
 *
 * Each row carries a "Clock out" action that opens an inline confirmation with
 * a REQUIRED reason note (>= 3 chars per backend schema). On confirm we POST
 * `/api/v2/staff/{staff_id}/clock/admin-clock-out/{entry_id}` which closes the
 * row + writes audit `time_clock.admin_force_clock_out` with the reason inside
 * `after_value.reason_note`.
 *
 * Follows `.kiro/steering/safe-api-consumption.md`: every API field read uses
 * `?.` + `?? []` / `?? 0`, every API call carries a typed generic, every
 * `useEffect` that hits the network registers an `AbortController` and cleans
 * up on unmount.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import apiClient from '@/api/client'
import { Modal } from '@/components/ui'
import AuthorizedAvatar from '@/components/AuthorizedAvatar'
import { staffInitials } from './staffInitials'

interface ClockedInEntry {
  time_clock_entry_id: string
  staff_id: string
  staff_name: string
  employee_id: string | null
  position: string | null
  on_file_photo_url: string | null
  clock_in_at: string
  source: string
  break_minutes: number
}

interface ClockedInListResponse {
  items: ClockedInEntry[]
  total: number
}

interface ClockedInDrawerProps {
  open: boolean
  onClose: () => void
  /** Bumped after a successful admin clock-out so the parent staff list can
   *  refresh any derived counters. Optional. */
  onClockedOut?: () => void
}

/**
 * Format an elapsed-millisecond count as a tight `HH:MM:SS` string.
 * Negative inputs (clock skew between the kiosk tablet and the server) are
 * floored at zero so the timer never reads "-00:00:01".
 */
function formatElapsed(ms: number): string {
  const safe = ms < 0 ? 0 : ms
  const totalSeconds = Math.floor(safe / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

/**
 * Format an ISO timestamp as a kiosk-style `HH:MM` clock-in label.
 * Returns an em-dash on parse failure so the cell never shows `Invalid Date`.
 */
function formatClockInTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/**
 * Source-label mapping — the DB column is one of `kiosk` /
 * `self_service_mobile` / `self_service_web` / `admin_manual`. We render a
 * shorter label so the table cell stays compact.
 */
const SOURCE_LABELS: Record<string, string> = {
  kiosk: 'Kiosk',
  self_service_mobile: 'Mobile',
  self_service_web: 'Web',
  admin_manual: 'Manual',
}

interface LiveTimerProps {
  /** ISO timestamp the timer counts from. */
  fromIso: string
  /** Force a re-render every 1s — the parent owns the tick so every row re-
   *  renders on the same animation frame (single setInterval, less jank). */
  nowMs: number
}

function LiveTimer({ fromIso, nowMs }: LiveTimerProps) {
  const startMs = useMemo(() => {
    const t = new Date(fromIso).getTime()
    return Number.isNaN(t) ? nowMs : t
  }, [fromIso, nowMs])
  return (
    <span
      className="mono inline-flex items-center gap-1.5 rounded-full bg-ok-soft px-2.5 py-0.5 text-xs font-semibold text-ok"
      aria-label={`Clocked in for ${formatElapsed(nowMs - startMs)}`}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full bg-ok"
        aria-hidden="true"
      />
      {formatElapsed(nowMs - startMs)}
    </span>
  )
}

export default function ClockedInDrawer({
  open,
  onClose,
  onClockedOut,
}: ClockedInDrawerProps) {
  const [items, setItems] = useState<ClockedInEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())

  // Confirmation modal state — populated when the user clicks "Clock out".
  const [pendingClockOut, setPendingClockOut] = useState<ClockedInEntry | null>(null)
  const [reasonNote, setReasonNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  /** One global tick drives every row's timer — single setInterval, single
   *  React re-render per second across N rows. */
  useEffect(() => {
    if (!open) return
    const id = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [open])

  /** Fetch the current list. Called on open + every 30s while open + after
   *  a successful clock-out so the row disappears immediately. */
  const fetchList = useCallback(async (signal: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<ClockedInListResponse>(
        '/time-clock/clocked-in',
        { baseURL: '/api/v2', signal },
      )
      if (signal.aborted) return
      setItems(res.data?.items ?? [])
    } catch (err: unknown) {
      if (signal.aborted) return
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        setError("You don't have permission to view clocked-in staff.")
      } else if (status === 404) {
        setError('Staff management is not enabled for this organisation.')
      } else {
        setError("Couldn't load clocked-in staff. Please try again.")
      }
      setItems([])
    } finally {
      if (!signal.aborted) setLoading(false)
    }
  }, [])

  /** Initial load + 30s refresh while open. */
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    fetchList(controller.signal)
    const id = window.setInterval(() => {
      if (!controller.signal.aborted) {
        // Each refresh runs under the same abort controller so unmount
        // cancels both the initial fetch and any pending refresh.
        fetchList(controller.signal)
      }
    }, 30_000)
    return () => {
      controller.abort()
      window.clearInterval(id)
    }
  }, [open, fetchList])

  const handleConfirmClockOut = useCallback(async () => {
    if (!pendingClockOut) return
    const trimmed = reasonNote.trim()
    if (trimmed.length < 3) {
      setSubmitError('Please enter a reason note (at least 3 characters).')
      return
    }
    setSubmitting(true)
    setSubmitError(null)
    try {
      await apiClient.post(
        `/time-clock/admin-clock-out/${pendingClockOut.time_clock_entry_id}`,
        { reason_note: trimmed },
        { baseURL: '/api/v2' },
      )
      // Drop the row from the local list optimistically, then trigger a
      // background refresh in case other rows have been clocked in/out
      // during this user's confirmation step.
      setItems((prev) =>
        prev.filter(
          (row) => row.time_clock_entry_id !== pendingClockOut.time_clock_entry_id,
        ),
      )
      setPendingClockOut(null)
      setReasonNote('')
      onClockedOut?.()
      const controller = new AbortController()
      fetchList(controller.signal)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail = (err as {
        response?: { data?: { detail?: { detail?: string } | string } }
      })?.response?.data?.detail
      const detailStr =
        typeof detail === 'string' ? detail : detail?.detail ?? ''
      if (status === 403 && detailStr === 'forbidden_scope') {
        setSubmitError(
          "This staff member is outside your branch scope — you can't clock them out.",
        )
      } else if (status === 409 && detailStr === 'already_clocked_out') {
        setSubmitError('This entry was already clocked out by someone else.')
      } else if (status === 409 && detailStr === 'timesheet_locked') {
        setSubmitError(
          "Can't close — this shift's week is already approved. Reopen the timesheet first.",
        )
      } else if (
        status === 404 ||
        detailStr === 'time_clock_entry_not_found'
      ) {
        setSubmitError('That entry could not be found. It may have been deleted.')
      } else {
        setSubmitError("Couldn't clock the user out. Please try again.")
      }
    } finally {
      setSubmitting(false)
    }
  }, [pendingClockOut, reasonNote, onClockedOut, fetchList])

  const cancelClockOut = useCallback(() => {
    setPendingClockOut(null)
    setReasonNote('')
    setSubmitError(null)
  }, [])

  if (!open) return null

  return (
    <>
      {/* Slide-in drawer (right side, full-height, narrow on tablet) */}
      <div
        className="fixed inset-0 z-40 flex justify-end"
        role="dialog"
        aria-modal="true"
        aria-label="Clocked-in staff"
      >
        {/* Scrim */}
        <div
          className="absolute inset-0 bg-ink/40"
          onClick={onClose}
          aria-hidden="true"
        />

        {/* Panel */}
        <aside className="relative flex h-full w-full max-w-[480px] flex-col bg-card shadow-pop">
          {/* Header */}
          <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
            <div className="flex items-center gap-2">
              <span
                className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-ok-soft text-ok"
                aria-hidden="true"
              >
                <svg
                  className="h-5 w-5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 7v5l3 2" />
                </svg>
              </span>
              <div>
                <h2 className="text-[15px] font-semibold text-text">
                  Clocked in now
                </h2>
                <p className="text-[12px] text-muted-2">
                  {loading
                    ? 'Loading…'
                    : `${items.length} staff currently on the clock`}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 w-9 items-center justify-center rounded-ctl text-muted-2 hover:bg-canvas hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
              aria-label="Close"
            >
              ✕
            </button>
          </header>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {error && (
              <div
                role="alert"
                className="mb-4 rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
              >
                {error}
              </div>
            )}

            {!loading && items.length === 0 && !error && (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
                <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-canvas text-muted-2">
                  <svg
                    className="h-7 w-7"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 7v5l3 2" />
                  </svg>
                </span>
                <p className="text-sm font-medium text-text">
                  No one is clocked in.
                </p>
                <p className="text-xs text-muted-2">
                  Staff who tap clock-in at the kiosk will appear here.
                </p>
              </div>
            )}

            {items.length > 0 && (
              <ul className="space-y-2.5">
                {items.map((row) => (
                  <li
                    key={row.time_clock_entry_id}
                    className="flex items-start justify-between gap-3 rounded-card border border-border bg-canvas px-3.5 py-3"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <AuthorizedAvatar
                        src={row.on_file_photo_url}
                        initials={staffInitials(
                          row.staff_name.split(' ')[0] ?? row.staff_name,
                          row.staff_name.split(' ').slice(1).join(' ') || null,
                        )}
                        className="h-10 w-10 shrink-0 rounded-full border border-border bg-accent-soft"
                        fallbackClassName="text-[12px] font-semibold uppercase text-accent"
                        alt=""
                      />

                      <div className="min-w-0">
                        <p className="truncate text-[13.5px] font-semibold text-text">
                          {row.staff_name}
                        </p>
                        <p className="truncate text-[12px] text-muted-2">
                          {row.position ?? 'Staff'}
                          {row.employee_id ? ` · ${row.employee_id}` : ''}
                        </p>
                        <div className="mt-1 flex items-center gap-2">
                          <LiveTimer
                            fromIso={row.clock_in_at}
                            nowMs={nowMs}
                          />
                          <span className="text-[11px] text-muted-2">
                            since {formatClockInTime(row.clock_in_at)}
                            {SOURCE_LABELS[row.source]
                              ? ` · ${SOURCE_LABELS[row.source]}`
                              : ''}
                          </span>
                        </div>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        setPendingClockOut(row)
                        setReasonNote('')
                        setSubmitError(null)
                      }}
                      className="shrink-0 rounded-ctl border border-danger/30 bg-danger-soft px-3 py-1.5 text-[12.5px] font-medium text-danger hover:border-danger/60 focus:outline-none focus:ring-2 focus:ring-danger"
                    >
                      Clock out
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Footer note */}
          <footer className="border-t border-border px-5 py-3 text-[11.5px] text-muted-2">
            Live timer updates every second. List refreshes every 30s.
          </footer>
        </aside>
      </div>

      {/* Manual clock-out confirmation */}
      <Modal
        open={pendingClockOut !== null}
        onClose={cancelClockOut}
        title={
          pendingClockOut
            ? `Clock out ${pendingClockOut.staff_name}?`
            : 'Clock out'
        }
      >
        {pendingClockOut && (
          <div className="space-y-4">
            <div className="rounded-card border border-border bg-canvas px-3.5 py-3 text-[13px] text-text">
              <p className="font-medium">
                {pendingClockOut.staff_name}
                {pendingClockOut.position
                  ? ` · ${pendingClockOut.position}`
                  : ''}
              </p>
              <p className="mt-1 text-muted-2">
                Clocked in{' '}
                {formatClockInTime(pendingClockOut.clock_in_at)} ·{' '}
                <span className="mono">
                  {formatElapsed(
                    nowMs - new Date(pendingClockOut.clock_in_at).getTime(),
                  )}
                </span>
              </p>
            </div>

            <p className="text-[13px] text-muted">
              This will close their open shift and record this time as the
              clock-out. The reason note is saved on the audit log for record
              keeping.
            </p>

            <div>
              <label
                htmlFor="reason-note"
                className="mb-1 block text-[12.5px] font-medium text-text"
              >
                Reason note <span className="text-danger">*</span>
              </label>
              <textarea
                id="reason-note"
                value={reasonNote}
                onChange={(e) => setReasonNote(e.target.value)}
                rows={3}
                maxLength={500}
                placeholder="e.g. Forgot to tap out at end of shift"
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                autoFocus
              />
              <p className="mt-1 text-[11px] text-muted-2">
                {reasonNote.trim().length}/500 — minimum 3 characters
              </p>
            </div>

            {submitError && (
              <div
                role="alert"
                className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
              >
                {submitError}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
              <button
                type="button"
                onClick={cancelClockOut}
                disabled={submitting}
                className="rounded-ctl border border-border px-3.5 py-2 text-[13px] font-medium text-text hover:bg-canvas disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmClockOut}
                disabled={submitting || reasonNote.trim().length < 3}
                className="rounded-ctl bg-danger px-3.5 py-2 text-[13px] font-medium text-white shadow-card hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? 'Clocking out…' : 'Clock out'}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
