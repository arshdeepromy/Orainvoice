/**
 * BackupDashboard — Cloud Backup admin landing (Task 17.2).
 *
 * At-a-glance DR status for Global Admins: last backup outcome + time, next
 * scheduled run (from the NZ-tz cron), destinations health (from each
 * destination's connection_state), and the configured Recovery objectives
 * (RPO/RTO). A "Run backup now" button opens a scope-picker modal that POSTs
 * an on-demand backup (Req 8.8) and toasts the accepted job. Empty-state CTAs
 * cover "no destinations configured" (→ Settings) and "no backups yet"
 * (→ run one).
 *
 * Requirements: 8.8 (manual on-demand backup), 9.1 (most-recent backup +
 * empty state), 25.2 (surface RPO/RTO objectives).
 *
 * Safe consumption (project rule + steering): every API field is read with
 * `?.` / `?? []` / `?? 0`, and every effect that calls the API uses an
 * AbortController and returns `() => controller.abort()`.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'
import Button, { buttonClasses } from '@/components/ui/Button'
import Card, { CardHead, CardBody } from '@/components/ui/Card'
import Badge from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  getConfig,
  listDestinations,
  listBackups,
  runBackupNow,
  getBackupJobStatus,
  cancelBackupJob,
  type BackupConfig,
  type Destination,
  type Backup,
  type BackupScope,
  type JobStatus,
} from '@/api/backup/dashboard'

/* ------------------------------------------------------------------ */
/*  Formatting helpers                                                 */
/* ------------------------------------------------------------------ */

/** Human-readable duration from a seconds count (e.g. 86400 → "24 hours"). */
function formatDuration(seconds: number | null | undefined): string {
  const s = seconds ?? 0
  if (s <= 0) return '—'
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const parts: string[] = []
  if (days > 0) parts.push(`${days} ${days === 1 ? 'day' : 'days'}`)
  if (hours > 0) parts.push(`${hours} ${hours === 1 ? 'hour' : 'hours'}`)
  if (minutes > 0 && days === 0) parts.push(`${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`)
  return parts.length > 0 ? parts.join(' ') : `${s} seconds`
}

/** Human-readable byte size (e.g. 1536 → "1.5 KB"). */
function formatBytes(bytes: number | null | undefined): string {
  const b = bytes ?? 0
  if (b <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = b
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`
}

/** Absolute + relative timestamp (e.g. "26 May 2026, 02:00 (3 hours ago)"). */
function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const absolute = date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
  return `${absolute} (${formatRelative(date)})`
}

/** Coarse relative time ("3 hours ago", "in 2 days"). */
function formatRelative(date: Date): string {
  const diffMs = date.getTime() - Date.now()
  const future = diffMs >= 0
  const abs = Math.abs(diffMs)
  const minutes = Math.round(abs / 60000)
  const hours = Math.round(abs / 3600000)
  const days = Math.round(abs / 86400000)
  let phrase: string
  if (minutes < 1) phrase = 'just now'
  else if (minutes < 60) phrase = `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`
  else if (hours < 24) phrase = `${hours} ${hours === 1 ? 'hour' : 'hours'}`
  else phrase = `${days} ${days === 1 ? 'day' : 'days'}`
  if (phrase === 'just now') return phrase
  return future ? `in ${phrase}` : `${phrase} ago`
}

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/**
 * Best-effort human description of a standard 5-field cron expression
 * (`min hour dom mon dow`), e.g. "Daily at 02:00". Falls back to the raw
 * expression for patterns it does not specifically recognise. Schedules are
 * evaluated in the New Zealand timezone server-side (Req 8.1).
 */
function describeCron(cron: string | null | undefined): string {
  if (!cron) return ''
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hour, dom, mon, dow] = parts

  const atTime =
    /^\d+$/.test(min) && /^\d+$/.test(hour)
      ? `${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
      : null

  // Every N minutes / hours.
  if (min.startsWith('*/') && hour === '*' && dom === '*' && mon === '*' && dow === '*') {
    return `Every ${min.slice(2)} minutes`
  }
  if (/^\d+$/.test(min) && hour.startsWith('*/') && dom === '*' && mon === '*' && dow === '*') {
    return `Every ${hour.slice(2)} hours`
  }

  // Specific day-of-week.
  if (atTime && dom === '*' && mon === '*' && /^\d$/.test(dow)) {
    const day = DOW[Number(dow) % 7]
    return `Weekly on ${day} at ${atTime}`
  }
  // Specific day-of-month.
  if (atTime && /^\d+$/.test(dom) && mon === '*' && dow === '*') {
    return `Monthly on day ${dom} at ${atTime}`
  }
  // Daily.
  if (atTime && dom === '*' && mon === '*' && dow === '*') {
    return `Daily at ${atTime}`
  }
  return cron
}

const SCOPE_OPTIONS: { value: BackupScope; label: string; description: string }[] = [
  {
    value: 'settings_only',
    label: 'Settings only',
    description: 'Platform settings and configuration — a fast, lightweight backup.',
  },
  {
    value: 'organisations_only',
    label: 'Organisations only',
    description: 'All organisation data, excluding platform settings.',
  },
  {
    value: 'both',
    label: 'Everything',
    description: 'Full platform backup — settings and all organisation data.',
  },
]

function scopeLabel(scope: string | null | undefined): string {
  return SCOPE_OPTIONS.find((o) => o.value === scope)?.label ?? scope ?? '—'
}

/** Map a destination connection_state to a Badge tone. */
function stateBadge(state: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  switch (state) {
    case 'connected':
      return 'ok'
    case 'error':
      return 'danger'
    case 'disconnected':
      return 'warn'
    default:
      return 'neutral'
  }
}

/* ------------------------------------------------------------------ */
/*  Status card primitive                                              */
/* ------------------------------------------------------------------ */

function StatusCard({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <Card className="flex flex-col">
      <CardHead title={title} />
      <CardBody className="flex flex-1 flex-col gap-1.5">{children}</CardBody>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  Scope picker modal                                                 */
/* ------------------------------------------------------------------ */

function ScopePickerModal({
  open,
  onClose,
  onConfirm,
  defaultScope,
  submitting,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (scope: BackupScope) => void
  defaultScope: BackupScope
  submitting: boolean
}) {
  const [scope, setScope] = useState<BackupScope>(defaultScope)

  // Reset to the configured default each time the modal opens.
  useEffect(() => {
    if (open) setScope(defaultScope)
  }, [open, defaultScope])

  return (
    <Modal open={open} onClose={onClose} title="Run backup now">
      <div className="space-y-4">
        <p className="text-sm text-muted">
          Choose what this on-demand backup should capture.
        </p>
        <fieldset className="space-y-2" disabled={submitting}>
          <legend className="sr-only">Backup scope</legend>
          {SCOPE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex cursor-pointer items-start gap-3 rounded-ctl border p-3 transition-colors
                ${scope === opt.value ? 'border-accent bg-accent-soft' : 'border-border hover:bg-canvas'}`}
            >
              <input
                type="radio"
                name="backup-scope"
                value={opt.value}
                checked={scope === opt.value}
                onChange={() => setScope(opt.value)}
                className="mt-0.5 h-4 w-4 accent-[var(--color-accent,#2563eb)]"
              />
              <span className="flex flex-col">
                <span className="text-sm font-medium text-text">{opt.label}</span>
                <span className="text-[12.5px] text-muted">{opt.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="flex justify-end gap-3 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" loading={submitting} onClick={() => onConfirm(scope)}>
            Start backup
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  Live backup-progress modal                                         */
/* ------------------------------------------------------------------ */

/**
 * Phase narrative derived from the backend's progress milestones (the backup
 * pipeline advances progress_pct at fixed steps: 5 start, 30 dump complete,
 * 55 file capture, 65 manifest, 85 fan-out upload, 100 done). We map the
 * current % to the phase that is in flight.
 */
const RUNNING_PHASES: { upTo: number; label: string }[] = [
  { upTo: 30, label: 'Dumping the database' },
  { upTo: 55, label: 'Capturing files' },
  { upTo: 65, label: 'Assembling the manifest' },
  { upTo: 85, label: 'Uploading to destination(s)' },
  { upTo: 101, label: 'Finalising' },
]

function phaseLabel(status: string, pct: number): string {
  if (status === 'queued') return 'Queued — waiting to start'
  if (status === 'completed') return 'Completed'
  if (status === 'failed') return 'Failed'
  if (status === 'cancelled') return 'Cancelled'
  for (const p of RUNNING_PHASES) {
    if (pct < p.upTo) return p.label
  }
  return 'Finalising'
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

function BackupProgressModal({
  jobId,
  scopeText,
  onClose,
  onFinished,
}: {
  jobId: string
  scopeText: string
  onClose: () => void
  onFinished: () => void
}) {
  const [job, setJob] = useState<JobStatus | null>(null)
  const [finishedBackup, setFinishedBackup] = useState<Backup | null>(null)
  const [pollError, setPollError] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const finishedRef = useRef(false)

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | null = null

    async function poll() {
      try {
        const s = await getBackupJobStatus(jobId, controller.signal)
        if (!active) return
        setJob(s)
        setPollError(false)
        if (TERMINAL.has(s.status)) {
          if (!finishedRef.current) {
            finishedRef.current = true
            onFinished()
            if (s.status === 'completed') {
              try {
                const backups = await listBackups(controller.signal)
                if (active) setFinishedBackup((backups?.items ?? [])[0] ?? null)
              } catch {
                /* size is best-effort; ignore */
              }
            }
          }
          return // stop polling on terminal state
        }
      } catch (err) {
        if (controller.signal.aborted || !active) return
        setPollError(true)
      }
      if (active) timer = setTimeout(poll, 1500)
    }

    poll()
    return () => {
      active = false
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [jobId, onFinished])

  const handleCancel = useCallback(async () => {
    setCancelling(true)
    try {
      await cancelBackupJob(jobId)
    } catch {
      /* the next poll surfaces the real state */
    } finally {
      setCancelling(false)
    }
  }, [jobId])

  const status = job?.status ?? 'queued'
  const pct = Math.max(0, Math.min(100, job?.progress_pct ?? 0))
  const elapsed = job?.elapsed_seconds ?? 0
  const isTerminal = TERMINAL.has(status)
  const isRunning = status === 'running' || status === 'queued'
  const stalled = isRunning && (job?.seconds_since_last_update ?? 0) > 60

  const barColor =
    status === 'failed'
      ? 'var(--color-danger, #dc2626)'
      : status === 'cancelled'
        ? 'var(--color-warn, #d97706)'
        : 'var(--color-accent, #2563eb)'

  const title =
    status === 'completed'
      ? 'Backup complete'
      : status === 'failed'
        ? 'Backup failed'
        : status === 'cancelled'
          ? 'Backup cancelled'
          : 'Backup in progress'

  return (
    <Modal open onClose={onClose} title={title}>
      <div className="space-y-4">
        {/* Phase + status */}
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-text">{phaseLabel(status, pct)}</p>
            <p className="text-[12.5px] text-muted">Scope: {scopeText}</p>
          </div>
          <Badge
            variant={
              status === 'completed'
                ? 'ok'
                : status === 'failed'
                  ? 'danger'
                  : status === 'cancelled'
                    ? 'warn'
                    : 'neutral'
            }
          >
            {status === 'queued'
              ? 'Queued'
              : status === 'running'
                ? 'Running'
                : status.charAt(0).toUpperCase() + status.slice(1)}
          </Badge>
        </div>

        {/* Progress bar */}
        <div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-canvas">
            <div
              className="h-full rounded-full transition-[width] duration-500 ease-out"
              style={{
                width: `${status === 'completed' ? 100 : pct}%`,
                backgroundColor: barColor,
              }}
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[12.5px] text-muted">
            <span>{status === 'completed' ? 100 : pct}%</span>
            <span>Elapsed {formatDuration(Math.round(elapsed)) === '—' ? '0 seconds' : formatDuration(Math.round(elapsed))}</span>
          </div>
        </div>

        {/* Live working / stalled hint */}
        {isRunning && !pollError && (
          <div className="flex items-center gap-2 text-[12.5px] text-muted">
            {stalled ? (
              <span className="text-[var(--color-warn,#d97706)]">
                No update for over 60s — the job may be stalled; it will be auto-failed if it
                doesn&apos;t recover.
              </span>
            ) : (
              <>
                <Spinner size="sm" />
                <span>Working… this can take a while for large datasets.</span>
              </>
            )}
          </div>
        )}

        {pollError && !isTerminal && (
          <p className="text-[12.5px] text-[var(--color-warn,#d97706)]">
            Lost contact with the job status briefly — retrying…
          </p>
        )}

        {/* Terminal: success */}
        {status === 'completed' && (
          <AlertBanner variant="success" title="Backup completed successfully">
            {finishedBackup ? (
              <span>
                {formatBytes(finishedBackup.dump_size_bytes)} database dump
                {(finishedBackup.file_count ?? 0) > 0
                  ? ` · ${finishedBackup.file_count} ${finishedBackup.file_count === 1 ? 'file' : 'files'}`
                  : ''}
                {(finishedBackup.file_bytes ?? 0) > 0
                  ? ` (${formatBytes(finishedBackup.file_bytes)})`
                  : ''}
                {finishedBackup.consistency_level
                  ? ` · consistency ${finishedBackup.consistency_level}`
                  : ''}
                .
              </span>
            ) : (
              <span>{job?.outcome_summary ?? 'The encrypted backup was stored at all destinations.'}</span>
            )}
          </AlertBanner>
        )}

        {/* Terminal: failure */}
        {status === 'failed' && (
          <AlertBanner variant="error" title="Backup failed">
            {job?.error_message || job?.outcome_summary || 'The backup did not complete.'}
          </AlertBanner>
        )}

        {/* Terminal: cancelled */}
        {status === 'cancelled' && (
          <AlertBanner variant="warning" title="Backup cancelled">
            {job?.outcome_summary || 'The backup was cancelled before completion.'}
          </AlertBanner>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 pt-1">
          {isTerminal ? (
            <Link to="/admin/backup/history" className="text-[12.5px] font-medium text-accent underline">
              View backup history
            </Link>
          ) : (
            <span className="text-[12.5px] text-muted">
              You can close this — the backup keeps running in the background.
            </span>
          )}
          <div className="flex gap-2">
            {!isTerminal && status === 'running' && (
              <Button variant="danger" size="sm" onClick={handleCancel} loading={cancelling} disabled={cancelling}>
                Cancel backup
              </Button>
            )}
            <Button variant={isTerminal ? 'primary' : 'ghost'} size="sm" onClick={onClose}>
              {isTerminal ? 'Done' : 'Close'}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export function BackupDashboard() {
  const [config, setConfig] = useState<BackupConfig | null>(null)
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [lastBackup, setLastBackup] = useState<Backup | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [activeJob, setActiveJob] = useState<{ id: string; scope: BackupScope } | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal

    async function load() {
      setLoading(true)
      setError(false)
      try {
        const [cfg, dests, backups] = await Promise.all([
          getConfig(signal),
          listDestinations(signal),
          listBackups(signal),
        ])
        setConfig(cfg ?? null)
        setDestinations(dests?.items ?? [])
        setLastBackup((backups?.items ?? [])[0] ?? null)
      } catch (err) {
        // Ignore cancellations from unmount / reload; surface real failures.
        if (axios.isCancel(err) || (err as { name?: string })?.name === 'CanceledError') {
          return
        }
        setError(true)
      } finally {
        setLoading(false)
      }
    }

    load()
    return () => controller.abort()
  }, [reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  const handleConfirmRun = useCallback(
    async (scope: BackupScope) => {
      setSubmitting(true)
      try {
        const job = await runBackupNow(scope)
        setModalOpen(false)
        if (job?.job_id) {
          // Open the live progress modal and watch the job through to completion.
          setActiveJob({ id: job.job_id, scope })
        } else {
          addToast('success', `Backup started (${scopeLabel(scope)}).`)
        }
      } catch {
        addToast('error', 'Could not start the backup. Please try again.')
      } finally {
        setSubmitting(false)
      }
    },
    [addToast],
  )

  /* ---- Loading / error ----
     Only take over the whole view on the INITIAL load (no data yet). A reload
     triggered by `reloadKey` (e.g. after a backup finishes) must NOT unmount the
     page — otherwise the live progress modal unmounts and remounts, its
     finished-guard resets, and it re-fires onFinished()→reload() in an infinite
     loop (request storm + flicker). With data present we keep rendering the
     dashboard and refresh in the background. */

  if (loading && !config) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading backup status" />
      </div>
    )
  }

  if (error && !config) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-text">Cloud Backup</h1>
        <AlertBanner variant="error" title="Could not load backup status">
          Something went wrong loading the backup dashboard.{' '}
          <button onClick={reload} className="font-medium underline">
            Retry
          </button>
        </AlertBanner>
      </div>
    )
  }

  /* ---- Derived view-model (safe reads) ---- */

  const destList = destinations ?? []
  const hasDestinations = destList.length > 0
  const connectedCount = destList.filter((d) => d?.connection_state === 'connected').length
  const erroredCount = destList.filter((d) => d?.connection_state === 'error').length
  const primary = destList.find((d) => d?.is_primary) ?? null
  const defaultScope = (config?.default_scope as BackupScope) ?? 'both'
  const scheduleText = describeCron(config?.schedule_cron)

  /* ---- Empty state: no destinations configured (Req 9.2 / design) ---- */

  if (!hasDestinations) {
    return (
      <div className="space-y-6">
        <Header onRunNow={() => setModalOpen(true)} runDisabled />
        <ToastContainer toasts={toasts} onDismiss={dismissToast} />
        <Card>
          <CardBody className="flex flex-col items-center gap-3 py-12 text-center">
            <h2 className="text-lg font-semibold text-text">No backup destination configured</h2>
            <p className="max-w-md text-sm text-muted">
              Connect a cloud storage destination (Google Drive, OneDrive, S3 or NAS) before
              you can run or schedule backups.
            </p>
            <Link to="/admin/backup/settings" className={buttonClasses({ variant: 'primary' })}>
              Configure a destination
            </Link>
          </CardBody>
        </Card>
      </div>
    )
  }

  /* ---- Full dashboard ---- */

  return (
    <div className="space-y-6">
      <Header onRunNow={() => setModalOpen(true)} />
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {/* Last backup outcome + time */}
        <StatusCard title="Last backup">
          {lastBackup ? (
            <>
              <div className="flex items-center gap-2">
                <Badge variant="ok">Succeeded</Badge>
                <span className="text-sm text-muted">{scopeLabel(lastBackup.scope)}</span>
              </div>
              <p className="text-sm text-text">{formatTimestamp(lastBackup.created_at)}</p>
              <p className="text-[12.5px] text-muted">
                {formatBytes(lastBackup.dump_size_bytes)}
                {(lastBackup.file_count ?? 0) > 0
                  ? ` · ${lastBackup.file_count} ${lastBackup.file_count === 1 ? 'file' : 'files'}`
                  : ''}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-muted">No backups yet.</p>
              <button
                onClick={() => setModalOpen(true)}
                className="self-start text-[12.5px] font-medium text-accent underline"
              >
                Run your first backup
              </button>
            </>
          )}
        </StatusCard>

        {/* Next scheduled */}
        <StatusCard title="Next scheduled">
          {scheduleText ? (
            <>
              <p className="text-sm font-medium text-text">{scheduleText}</p>
              <p className="text-[12.5px] text-muted">New Zealand time</p>
            </>
          ) : (
            <>
              <p className="text-sm text-muted">No automatic schedule set.</p>
              <Link
                to="/admin/backup/settings"
                className="text-[12.5px] font-medium text-accent underline"
              >
                Set a schedule
              </Link>
            </>
          )}
        </StatusCard>

        {/* Destinations health */}
        <StatusCard title="Destinations">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={erroredCount > 0 ? 'danger' : connectedCount > 0 ? 'ok' : 'warn'}>
              {connectedCount}/{destList.length} connected
            </Badge>
            {erroredCount > 0 && <Badge variant="danger">{erroredCount} error</Badge>}
          </div>
          {primary && (
            <p className="text-[12.5px] text-muted">
              Primary: <span className="text-text">{primary.display_name ?? '—'}</span>{' '}
              <Badge variant={stateBadge(primary.connection_state ?? '')} dot={false}>
                {primary.connection_state ?? 'unknown'}
              </Badge>
            </p>
          )}
          <Link
            to="/admin/backup/settings"
            className="mt-auto self-start text-[12.5px] font-medium text-accent underline"
          >
            Manage destinations
          </Link>
        </StatusCard>

        {/* RPO / RTO objectives (Req 25.2) */}
        <StatusCard title="Recovery objectives">
          <p className="text-sm text-text">
            <span className="font-medium">RPO:</span> {formatDuration(config?.rpo_seconds)}
          </p>
          <p className="text-sm text-text">
            <span className="font-medium">RTO:</span> {formatDuration(config?.rto_seconds)}
          </p>
          <p className="text-[12.5px] text-muted">
            Maximum tolerated data loss (RPO) and time to recover (RTO).
          </p>
        </StatusCard>
      </div>

      <ScopePickerModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onConfirm={handleConfirmRun}
        defaultScope={defaultScope}
        submitting={submitting}
      />

      {activeJob && (
        <BackupProgressModal
          jobId={activeJob.id}
          scopeText={scopeLabel(activeJob.scope)}
          onClose={() => setActiveJob(null)}
          onFinished={reload}
        />
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Header                                                             */
/* ------------------------------------------------------------------ */

function Header({ onRunNow, runDisabled = false }: { onRunNow: () => void; runDisabled?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-text">Cloud Backup</h1>
        <p className="text-sm text-muted">Platform disaster-recovery status and controls.</p>
      </div>
      <Button variant="primary" onClick={onRunNow} disabled={runDisabled}>
        Run backup now
      </Button>
    </div>
  )
}

export default BackupDashboard
