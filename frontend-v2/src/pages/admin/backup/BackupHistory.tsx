/**
 * BackupHistory — backup catalog history table + live job progress (Task 17.4).
 *
 * Global-Admin page mounted at /admin/backup/history. Renders the committed
 * Full_Backup catalog as a `{items,total}` table (created_at, scope, size,
 * file count, consistency level, destinations, prune status) with a client-side
 * search box over the loaded page, offset/limit pagination, and per-row View /
 * Restore actions. A freshly-triggered backup job (passed via the `?job_id=`
 * query param, e.g. from the dashboard "Run backup now") is tracked in a live
 * progress banner that polls the job-status endpoint every 2 seconds and offers
 * a Cancel control while the job is still running (Req 9.1, 13.3).
 *
 * Safe-API consumption (mandatory): every response is read with `?.`/`?? []`/
 * `?? 0`; the catalog fetch and every status poll run inside an AbortController
 * that is aborted on unmount; the 2s poll interval is cleared on unmount and
 * each tick uses a fresh AbortController. All calls are typed — no `as any`.
 */
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import Badge from '@/components/ui/Badge'
import type { BadgeVariant } from '@/components/ui/Badge'
import Button from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Pagination } from '@/components/ui/Pagination'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  listBackups,
  getBackupJob,
  cancelBackupJob,
  requestBackupDeletion,
  confirmBackupDeletion,
  getBackupDeleteJob,
  isTerminalStatus,
  scopeLabel,
  consistencyLabel,
  pruneLabel,
  formatBytes,
  formatTimestamp,
  type Backup,
  type JobStatus,
  type DeletionChallenge,
} from '@/api/backup/history'

const PAGE_SIZE = 20
const POLL_INTERVAL_MS = 2000

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Map a job lifecycle state onto a status-pill variant. */
function jobStatusVariant(status: string | null | undefined): BadgeVariant {
  switch (status) {
    case 'completed':
      return 'completed'
    case 'running':
      return 'inprogress'
    case 'queued':
      return 'pending'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'neutral'
    default:
      return 'neutral'
  }
}

/** Map a prune status onto a status-pill variant. */
function pruneVariant(status: string | null | undefined): BadgeVariant {
  switch (status) {
    case 'retained':
      return 'success'
    case 'pruned':
      return 'neutral'
    case 'prune_failed':
      return 'danger'
    default:
      return 'neutral'
  }
}

/** Client-side search across the catalog row's displayed fields. */
function matchesSearch(backup: Backup, term: string): boolean {
  const lower = term.trim().toLowerCase()
  if (!lower) return true
  const haystack = [
    backup.id,
    scopeLabel(backup.scope),
    consistencyLabel(backup.consistency_level),
    pruneLabel(backup.prune_status),
    backup.app_version ?? '',
    backup.schema_version ?? '',
    formatTimestamp(backup.created_at),
    ...(backup.destinations ?? []),
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(lower)
}

/* ------------------------------------------------------------------ */
/*  Live progress banner                                               */
/* ------------------------------------------------------------------ */

function LiveJobBanner({
  job,
  loading,
  onCancel,
  cancelling,
}: {
  job: JobStatus | null
  loading: boolean
  onCancel: () => void
  cancelling: boolean
}) {
  if (loading && !job) {
    return (
      <div className="mb-5 flex items-center gap-3 rounded-card border border-border bg-card px-4 py-3 shadow-card">
        <Spinner size="sm" label="Loading job status" />
        <span className="text-[13.5px] text-muted">Loading backup job status…</span>
      </div>
    )
  }

  if (!job) return null

  const terminal = isTerminalStatus(job.status)
  const active = job.status === 'queued' || job.status === 'running'
  const pct = Math.max(0, Math.min(100, job.progress_pct ?? 0))

  return (
    <div className="mb-5 rounded-card border border-border bg-card px-4 py-3 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[13.5px] font-medium text-text">
            {terminal ? 'Latest backup job' : 'Backup in progress'}
          </span>
          <Badge variant={jobStatusVariant(job.status)}>{job.status}</Badge>
        </div>
        {active && (
          <Button variant="danger" size="sm" onClick={onCancel} loading={cancelling} disabled={cancelling}>
            Cancel
          </Button>
        )}
      </div>

      {/* Progress bar */}
      <div className="mt-3" aria-hidden="true">
        <div className="h-2 w-full overflow-hidden rounded-full bg-canvas">
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[12.5px] text-muted">
        <span>
          Progress: <span className="mono text-text">{pct}%</span>
        </span>
        <span>
          Elapsed: <span className="mono text-text">{Math.round(job.elapsed_seconds ?? 0)}s</span>
        </span>
        <span>
          Last update:{' '}
          <span className="mono text-text">{Math.round(job.seconds_since_last_update ?? 0)}s ago</span>
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Details modal                                                      */
/* ------------------------------------------------------------------ */

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1.5">
      <span className="text-[12.5px] text-muted">{label}</span>
      <span className="mono text-right text-[12.5px] text-text break-all">{value}</span>
    </div>
  )
}

function BackupDetailsModal({ backup, onClose }: { backup: Backup; onClose: () => void }) {
  const destinations = backup.destinations ?? []
  return (
    <Modal open onClose={onClose} title="Backup details">
      <div className="divide-y divide-border">
        <DetailRow label="ID" value={backup.id} />
        <DetailRow label="Created" value={formatTimestamp(backup.created_at)} />
        <DetailRow label="Scope" value={scopeLabel(backup.scope)} />
        <DetailRow label="Size" value={formatBytes(backup.dump_size_bytes)} />
        <DetailRow label="File count" value={(backup.file_count ?? 0).toLocaleString()} />
        <DetailRow label="File bytes" value={formatBytes(backup.file_bytes)} />
        <DetailRow label="Consistency" value={consistencyLabel(backup.consistency_level)} />
        <DetailRow label="Prune status" value={pruneLabel(backup.prune_status)} />
        <DetailRow label="App version" value={backup.app_version ?? '—'} />
        <DetailRow label="Schema version" value={backup.schema_version ?? '—'} />
        <DetailRow label="Key version" value={backup.key_version ?? '—'} />
        <DetailRow
          label="Destinations"
          value={destinations.length > 0 ? destinations.join(', ') : '—'}
        />
        <DetailRow label="Checksum" value={backup.dump_checksum ?? '—'} />
      </div>
      <div className="mt-4 flex justify-end">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  Delete verification modal (6-digit code, MFA-style)                */
/* ------------------------------------------------------------------ */

function extractError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail
    if (detail) return detail
  }
  return fallback
}

function DeleteVerificationModal({
  count,
  allManual,
  backupIds,
  onClose,
  onDeleted,
}: {
  count: number
  allManual: boolean
  backupIds: string[]
  onClose: () => void
  onDeleted: (deleted: number, failed: number) => void
}) {
  const [step, setStep] = useState<'confirm' | 'code'>('confirm')
  const [challenge, setChallenge] = useState<DeletionChallenge | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const noun = count === 1 ? 'backup' : 'backups'

  const sendCode = useCallback(async () => {
    setBusy(true)
    setError(null)
    const controller = new AbortController()
    try {
      const ch = await requestBackupDeletion(
        allManual ? { allManual: true } : { backupIds },
        controller.signal,
      )
      setChallenge(ch)
      setStep('code')
    } catch (err) {
      setError(extractError(err, 'Could not send the verification code.'))
    } finally {
      setBusy(false)
    }
  }, [allManual, backupIds])

  const confirm = useCallback(async () => {
    if (!challenge) return
    setBusy(true)
    setError(null)
    const controller = new AbortController()
    try {
      // Verify the code; the actual deletion runs in the background.
      const accepted = await confirmBackupDeletion(
        challenge.challenge_id,
        code.trim(),
        controller.signal,
      )
      // Poll the background job until it finishes (handles many backups /
      // "select all" without the request dropping over the tunnel).
      let attempts = 0
      const maxAttempts = 150 // ~5 minutes at 2s
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const status = await getBackupDeleteJob(accepted.job_id, controller.signal)
        if (status.status === 'completed') {
          onDeleted(status.deleted, status.failed)
          return
        }
        if (status.status === 'failed') {
          setError(status.error || 'The deletion failed. No partial state was left.')
          setBusy(false)
          return
        }
        attempts += 1
        if (attempts >= maxAttempts) {
          // Stop waiting but the job continues server-side; the list refresh
          // will reflect the result.
          onDeleted(accepted.requested, 0)
          return
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    } catch (err) {
      setError(extractError(err, 'Could not delete the backups.'))
      setBusy(false)
    }
  }, [challenge, code, onDeleted])

  return (
    <Modal open onClose={onClose} title="Delete backups">
      <div className="flex flex-col gap-4">
        {step === 'confirm' ? (
          <>
            <AlertBanner variant="warning">
              You are about to permanently delete <strong>{count}</strong> {noun}.
              This cannot be undone. For security, we&rsquo;ll email you a 6-digit
              verification code to confirm.
            </AlertBanner>
            {error && <AlertBanner variant="error">{error}</AlertBanner>}
            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button variant="danger" onClick={sendCode} loading={busy}>
                Send verification code
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="text-[13.5px] text-text">
              We emailed a 6-digit code to{' '}
              <span className="font-medium">{challenge?.recipient}</span>. Enter it
              below to permanently delete {count} {noun}. The code expires in 10
              minutes.
            </p>
            <input
              type="text"
              inputMode="numeric"
              autoFocus
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              placeholder="000000"
              className="mono h-[48px] w-full rounded-ctl border border-border bg-card px-3 text-center text-[24px]
                tracking-[8px] text-text placeholder:text-muted-2
                focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
            {error && <AlertBanner variant="error">{error}</AlertBanner>}
            <div className="flex items-center justify-between gap-2">
              <Button variant="ghost" onClick={sendCode} disabled={busy}>
                Resend code
              </Button>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={onClose} disabled={busy}>
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirm}
                  loading={busy}
                  disabled={code.length !== 6}
                >
                  Delete {count} {noun}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export function BackupHistory() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const jobId = searchParams.get('job_id')

  const { toasts, addToast, dismissToast } = useToast()

  /* ---- Catalog state ---- */
  const [backups, setBackups] = useState<Backup[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1) // 1-based
  const [refreshKey, setRefreshKey] = useState(0)

  /* ---- Live job state ---- */
  const [job, setJob] = useState<JobStatus | null>(null)
  const [jobLoading, setJobLoading] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  /* ---- Details modal ---- */
  const [detailBackup, setDetailBackup] = useState<Backup | null>(null)

  /* ---- Selection + delete state ---- */
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleteModal, setDeleteModal] = useState<
    { allManual: boolean; ids: string[]; count: number } | null
  >(null)

  const offset = (page - 1) * PAGE_SIZE
  const totalPages = Math.max(1, Math.ceil((total || 0) / PAGE_SIZE))

  /* ---- Fetch the catalog page (AbortController-cleaned) ---- */
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    listBackups(offset, PAGE_SIZE, controller.signal)
      .then((data) => {
        setBackups(data?.items ?? [])
        setTotal(data?.total ?? 0)
      })
      .catch((err) => {
        if (controller.signal.aborted || axios.isCancel(err)) return
        setError(true)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [offset, refreshKey])

  /* ---- Poll the live job every 2s (fresh AbortController per tick) ---- */
  useEffect(() => {
    if (!jobId) {
      setJob(null)
      return
    }
    let active = true
    let controller: AbortController | null = null
    let timer: ReturnType<typeof setInterval> | null = null

    const stop = () => {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    }

    const tick = async () => {
      controller?.abort()
      controller = new AbortController()
      try {
        const status = await getBackupJob(jobId, controller.signal)
        if (!active) return
        setJob(status)
        if (isTerminalStatus(status.status)) {
          stop()
          // The job finished — pull the freshly-committed backup into the table.
          setRefreshKey((k) => k + 1)
        }
      } catch (err) {
        if (!active || axios.isCancel(err)) return
        // A missing job will never appear — stop polling. Transient errors keep going.
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          stop()
        }
      } finally {
        if (active) setJobLoading(false)
      }
    }

    setJobLoading(true)
    tick()
    timer = setInterval(tick, POLL_INTERVAL_MS)

    return () => {
      active = false
      stop()
      controller?.abort()
    }
  }, [jobId])

  /* ---- Cancel the live job ---- */
  const handleCancelConfirm = useCallback(async () => {
    if (!jobId) return
    setCancelling(true)
    const controller = new AbortController()
    try {
      const status = await cancelBackupJob(jobId, controller.signal)
      setJob(status)
      addToast('success', 'Backup job cancelled.')
      setRefreshKey((k) => k + 1)
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        addToast('warning', 'This job has already finished and can no longer be cancelled.')
      } else {
        addToast('error', 'Could not cancel the backup job.')
      }
    } finally {
      setCancelling(false)
      setCancelOpen(false)
    }
  }, [jobId, addToast])

  /* ---- Row actions ---- */
  const handleRestore = useCallback(
    (backup: Backup) => {
      navigate(`/admin/backup/restore?backup_id=${encodeURIComponent(backup.id)}`)
    },
    [navigate],
  )

  /* ---- Client-side search over the loaded page ---- */
  const visibleBackups = useMemo(
    () => backups.filter((b) => matchesSearch(b, search)),
    [backups, search],
  )

  /* ---- Selection (only manual, not-yet-pruned backups are deletable) ---- */
  const isDeletable = useCallback(
    (b: Backup) => !!b.is_manual && b.prune_status !== 'pruned',
    [],
  )
  const selectableVisible = useMemo(
    () => visibleBackups.filter(isDeletable),
    [visibleBackups, isDeletable],
  )
  const allVisibleSelected =
    selectableVisible.length > 0 &&
    selectableVisible.every((b) => selected.has(b.id))

  const toggleOne = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleAllVisible = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev)
      const allOn = selectableVisible.every((b) => next.has(b.id))
      if (allOn) selectableVisible.forEach((b) => next.delete(b.id))
      else selectableVisible.forEach((b) => next.add(b.id))
      return next
    })
  }, [selectableVisible])

  // Clear any stale selection when the page or data set changes.
  useEffect(() => {
    setSelected(new Set())
  }, [offset, refreshKey])

  /* ---- Render ---- */
  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-text">Backup History</h1>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Live job progress (only when a job id is supplied) */}
      {jobId && (
        <LiveJobBanner
          job={job}
          loading={jobLoading}
          cancelling={cancelling}
          onCancel={() => setCancelOpen(true)}
        />
      )}

      {/* Search */}
      <div className="mb-5 max-w-md">
        <label htmlFor="backup-search" className="mb-1 block text-[12.5px] font-medium text-text">
          Search
        </label>
        <input
          id="backup-search"
          type="search"
          placeholder="Search by scope, status, version, date…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text
            placeholder:text-muted-2
            focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
        />
      </div>

      {/* Delete toolbar (manual backups only) */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span className="text-[12.5px] text-muted">
          {selected.size > 0
            ? `${selected.size} selected`
            : 'Select manually-created backups to delete'}
        </span>
        <Button
          variant="danger"
          size="sm"
          disabled={selected.size === 0}
          onClick={() =>
            setDeleteModal({
              allManual: false,
              ids: Array.from(selected),
              count: selected.size,
            })
          }
        >
          Delete selected
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setDeleteModal({ allManual: true, ids: [], count: 0 })}
        >
          Delete all manual backups
        </Button>
      </div>

      {/* Catalog */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner label="Loading backup history" />
        </div>
      ) : error ? (
        <AlertBanner variant="error" title="Error">
          <div className="flex items-center justify-between gap-4">
            <span>Could not load the backup history.</span>
            <Button variant="ghost" size="sm" onClick={() => setRefreshKey((k) => k + 1)}>
              Retry
            </Button>
          </div>
        </AlertBanner>
      ) : (
        <>
          <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
            <table className="w-full border-collapse" role="grid">
              <caption className="sr-only">Backup history</caption>
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="border-b border-border px-4 py-[11px] text-left"
                  >
                    <input
                      type="checkbox"
                      aria-label="Select all manual backups on this page"
                      checked={allVisibleSelected}
                      disabled={selectableVisible.length === 0}
                      onChange={toggleAllVisible}
                      className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                    />
                  </th>
                  {['Created', 'Scope', 'Size', 'Files', 'Consistency', 'Destinations', 'Prune', 'Actions'].map(
                    (h) => (
                      <th
                        key={h}
                        scope="col"
                        className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {visibleBackups.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-5 py-10 text-center text-[13px] text-muted">
                      {search.trim()
                        ? 'No backups match your search.'
                        : 'No backups available yet.'}
                    </td>
                  </tr>
                ) : (
                  visibleBackups.map((backup) => {
                    const destinations = backup.destinations ?? []
                    return (
                      <tr
                        key={backup.id}
                        className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                      >
                        <td className="px-4 py-3 align-middle">
                          {isDeletable(backup) ? (
                            <input
                              type="checkbox"
                              aria-label={`Select backup from ${formatTimestamp(backup.created_at)}`}
                              checked={selected.has(backup.id)}
                              onChange={() => toggleOne(backup.id)}
                              className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                            />
                          ) : (
                            <span
                              className="text-[11px] text-muted-2"
                              title="Only manually-created backups can be deleted"
                            >
                              —
                            </span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          {formatTimestamp(backup.created_at)}
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">{scopeLabel(backup.scope)}</td>
                        <td className="mono px-5 py-3 text-[13.5px] text-text">
                          {formatBytes(backup.dump_size_bytes)}
                        </td>
                        <td className="mono px-5 py-3 text-[13.5px] text-text">
                          {(backup.file_count ?? 0).toLocaleString()}
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          {consistencyLabel(backup.consistency_level)}
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          {destinations.length > 0 ? destinations.join(', ') : '—'}
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          <Badge variant={pruneVariant(backup.prune_status)} dot={false}>
                            {pruneLabel(backup.prune_status)}
                          </Badge>
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          <div className="flex items-center gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setDetailBackup(backup)}
                              aria-label={`View backup from ${formatTimestamp(backup.created_at)}`}
                            >
                              View
                            </Button>
                            <Button
                              variant="primary"
                              size="sm"
                              onClick={() => handleRestore(backup)}
                              aria-label={`Restore backup from ${formatTimestamp(backup.created_at)}`}
                            >
                              Restore
                            </Button>
                            {backup.prune_status !== 'pruned' && (
                              <a
                                href={`/api/v1/backup/backups/${backup.id}/bundle`}
                                download
                                className="inline-flex h-[30px] items-center rounded-ctl border border-border bg-card px-2.5 text-[12.5px] font-medium text-text hover:bg-canvas transition-colors"
                                aria-label={`Download bundle for backup from ${formatTimestamp(backup.created_at)}`}
                              >
                                Bundle
                              </a>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination footer (offset/limit) */}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <span className="text-[12.5px] text-muted">
              {total > 0 ? (
                <>
                  Showing{' '}
                  <span className="mono text-text">{Math.min(offset + 1, total)}</span>–
                  <span className="mono text-text">{Math.min(offset + backups.length, total)}</span> of{' '}
                  <span className="mono text-text">{total}</span>
                </>
              ) : (
                'No backups'
              )}
            </span>
            <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        </>
      )}

      {/* Details modal */}
      {detailBackup && (
        <BackupDetailsModal backup={detailBackup} onClose={() => setDetailBackup(null)} />
      )}

      {/* Delete verification modal (6-digit code) */}
      {deleteModal && (
        <DeleteVerificationModal
          allManual={deleteModal.allManual}
          backupIds={deleteModal.ids}
          count={deleteModal.count}
          onClose={() => setDeleteModal(null)}
          onDeleted={(deleted, failed) => {
            setDeleteModal(null)
            setSelected(new Set())
            if (failed > 0) {
              addToast(
                'warning',
                `Deleted ${deleted} backup(s); ${failed} could not be removed and will be retried.`,
              )
            } else {
              addToast('success', `Deleted ${deleted} backup(s).`)
            }
            setRefreshKey((k) => k + 1)
          }}
        />
      )}

      {/* Cancel confirmation */}
      <ConfirmDialog
        open={cancelOpen}
        title="Cancel backup job?"
        message="This stops the in-progress backup. Any partial upload is cleaned up. This cannot be undone."
        confirmLabel="Cancel job"
        cancelLabel="Keep running"
        variant="danger"
        loading={cancelling}
        onConfirm={handleCancelConfirm}
        onCancel={() => setCancelOpen(false)}
      />
    </div>
  )
}
