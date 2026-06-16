/**
 * Rehearsals — restore-rehearsal schedule + history (Task 17.7).
 *
 * Global-Admin page mounted at /admin/backup/rehearsals. It surfaces three
 * things, all driven by the backend's `{items,total}` envelope and the
 * single-row backup config:
 *
 *   1. Schedule / cadence config — the NZ-local `rehearsal_cron` that drives the
 *      scheduled Restore_Rehearsal plus the Recovery_Time_Objective (RTO) the
 *      measured restore durations are judged against (Req 25.1/25.3/25.4).
 *   2. History table — newest first: result (passed/failed/pending), the
 *      rehearsed backup, each validation step's individual outcome, and the
 *      measured restore duration compared against the configured RTO (Req 26.4).
 *   3. "Run rehearsal now" — POSTs a rehearsal that runs in the background and
 *      returns a 202 placeholder; the row materialises in the table on refresh
 *      (Req 26.1).
 *
 * Safe-API consumption (mandatory): every response is read with `?.`/`?? []`/
 * `?? 0`; the config + history fetches run inside an AbortController aborted on
 * unmount; all calls are typed via generics — no `as any`. Loading spinners, an
 * error/retry banner, and an explicit empty state (no rehearsals yet) are all
 * handled.
 *
 * Requirements: 25.4, 26.1
 */
import { useState, useEffect, useCallback } from 'react'
import Badge from '@/components/ui/Badge'
import type { BadgeVariant } from '@/components/ui/Badge'
import Button from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import {
  listRehearsals,
  runRehearsalNow,
  getRehearsalConfig,
  updateRehearsalSchedule,
  rehearsalSteps,
  checkLabel,
  isComplete,
  isRtoMet,
  formatDuration,
  formatTimestamp,
  type Rehearsal,
  type CheckOutcome,
  type BackupConfig,
  type RehearsalScheduleUpdate,
} from '@/api/backup/rehearsals'

const PAGE_LIMIT = 50

/* ------------------------------------------------------------------ */
/*  Shared helpers                                                     */
/* ------------------------------------------------------------------ */

function errorDetail(err: unknown, fallback: string): string {
  if (err && typeof err === 'object') {
    const resp = (err as { response?: { data?: { detail?: unknown } } }).response
    const detail = resp?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

function isAbort(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false
  const name = (err as { name?: string }).name
  const code = (err as { code?: string }).code
  return name === 'CanceledError' || name === 'AbortError' || code === 'ERR_CANCELED'
}

/** Map a rehearsal result onto a status-pill variant. */
function resultVariant(result: string | null | undefined): BadgeVariant {
  if (result === 'passed') return 'success'
  if (result === 'failed') return 'failed'
  return 'pending'
}

function resultLabel(result: string | null | undefined): string {
  if (result === 'passed') return 'Passed'
  if (result === 'failed') return 'Failed'
  return 'Pending'
}

/** Map a per-step outcome onto a status-pill variant. */
function stepVariant(outcome: CheckOutcome | null): BadgeVariant {
  if (!outcome || outcome.passed == null) return 'neutral'
  return outcome.passed ? 'success' : 'failed'
}

/** Convert RTO seconds into a friendly target string. */
function rtoTarget(rtoSeconds: number | null | undefined): string {
  if (rtoSeconds == null || rtoSeconds <= 0) return 'not set'
  return formatDuration(rtoSeconds)
}

/* ------------------------------------------------------------------ */
/*  Schedule / cadence config card                                     */
/* ------------------------------------------------------------------ */

function ScheduleCard({
  config,
  onSaved,
  addToast,
}: {
  config: BackupConfig
  onSaved: (c: BackupConfig) => void
  addToast: (variant: 'success' | 'error' | 'warning', message: string) => void
}) {
  const [cron, setCron] = useState(config.rehearsal_cron ?? '')
  const [rto, setRto] = useState(config.rto_seconds != null ? String(config.rto_seconds) : '')
  const [saving, setSaving] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setWarnings([])
    const trimmedRto = rto.trim()
    const rtoNum = trimmedRto === '' ? undefined : Number(trimmedRto)
    const body: RehearsalScheduleUpdate = {
      rehearsal_cron: cron.trim() || null,
      ...(rtoNum != null && Number.isFinite(rtoNum) ? { rto_seconds: rtoNum } : {}),
    }
    try {
      const result = await updateRehearsalSchedule(body)
      if (result?.config) {
        onSaved(result.config)
        setCron(result.config.rehearsal_cron ?? '')
        setRto(result.config.rto_seconds != null ? String(result.config.rto_seconds) : '')
      }
      setWarnings(result?.warnings ?? [])
      addToast('success', 'Rehearsal schedule saved.')
    } catch (err) {
      addToast('error', errorDetail(err, 'Could not save the rehearsal schedule.'))
    } finally {
      setSaving(false)
    }
  }, [cron, rto, onSaved, addToast])

  return (
    <section className="rounded-card border border-border bg-card p-5 shadow-card">
      <h2 className="text-[15px] font-semibold text-text">Rehearsal schedule</h2>
      <p className="mt-1 text-[12.5px] text-muted">
        Automated restore rehearsals run on this cadence (NZ time) and restore a recent backup
        into an isolated scratch environment. The measured restore duration is compared against
        your Recovery Time Objective.
      </p>

      {warnings.length > 0 && (
        <div className="mt-4">
          <AlertBanner variant="warning" title="Recovery objective warning">
            <ul className="list-disc space-y-1 pl-5">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </AlertBanner>
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input
          label="Rehearsal schedule (cron)"
          value={cron}
          onChange={(e) => setCron(e.target.value)}
          placeholder="0 3 * * 0"
          helperText="Standard 5-field cron (NZ time). Example: “0 3 * * 0” runs weekly, Sunday 03:00. Leave blank to disable."
        />
        <Input
          label="Recovery Time Objective (RTO, seconds)"
          type="number"
          min={0}
          value={rto}
          onChange={(e) => setRto(e.target.value)}
          helperText={`Target maximum time to restore. Current target: ${rtoTarget(config.rto_seconds)}.`}
        />
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="text-[12.5px] text-muted">
          {cron.trim() ? (
            <>
              Cadence: <span className="mono text-text">{cron.trim()}</span>
            </>
          ) : (
            'No automated rehearsal scheduled — run rehearsals manually.'
          )}
        </span>
        <Button variant="primary" size="sm" onClick={handleSave} loading={saving} disabled={saving}>
          Save schedule
        </Button>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/*  Per-step outcome badges                                            */
/* ------------------------------------------------------------------ */

function StepBadges({ rehearsal }: { rehearsal: Rehearsal }) {
  const steps = rehearsalSteps(rehearsal)
  const anyRecorded = steps.some((s) => s.outcome && s.outcome.passed != null)
  if (!anyRecorded) {
    return <span className="text-[13px] text-muted">—</span>
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {steps.map((step) => (
        <Badge
          key={step.name}
          variant={stepVariant(step.outcome)}
          dot={false}
          title={step.outcome?.detail ?? undefined}
        >
          {checkLabel(step.name)}
        </Badge>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Duration vs RTO cell                                               */
/* ------------------------------------------------------------------ */

function DurationCell({
  rehearsal,
  rtoSeconds,
}: {
  rehearsal: Rehearsal
  rtoSeconds: number | null
}) {
  const measured = rehearsal.measured_duration_seconds
  if (measured == null) {
    return <span className="text-[13px] text-muted">—</span>
  }
  const met = isRtoMet(measured, rtoSeconds)
  return (
    <div className="flex flex-col gap-1">
      <span className="mono text-[13.5px] text-text">{formatDuration(measured)}</span>
      {met == null ? (
        <span className="text-[12px] text-muted">RTO {rtoTarget(rtoSeconds)}</span>
      ) : (
        <Badge variant={met ? 'success' : 'danger'} dot={false}>
          {met ? 'Within RTO' : 'RTO exceeded'}
        </Badge>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Details modal                                                      */
/* ------------------------------------------------------------------ */

function RehearsalDetailsModal({
  rehearsal,
  rtoSeconds,
  onClose,
}: {
  rehearsal: Rehearsal
  rtoSeconds: number | null
  onClose: () => void
}) {
  const steps = rehearsalSteps(rehearsal)
  const met = isRtoMet(rehearsal.measured_duration_seconds, rtoSeconds)
  return (
    <Modal open onClose={onClose} title="Rehearsal details" className="max-w-lg">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12.5px]">
          <span className="text-muted">Run at</span>
          <span className="text-right text-text">{formatTimestamp(rehearsal.created_at)}</span>

          <span className="text-muted">Result</span>
          <span className="text-right">
            <Badge variant={resultVariant(rehearsal.result)} dot={false}>
              {resultLabel(rehearsal.result)}
            </Badge>
          </span>

          <span className="text-muted">Rehearsed backup</span>
          <span className="mono break-all text-right text-text">{rehearsal.backup_id ?? '—'}</span>

          <span className="text-muted">Measured duration</span>
          <span className="mono text-right text-text">
            {formatDuration(rehearsal.measured_duration_seconds)}
            {met != null && (
              <span className={met ? 'text-ok' : 'text-danger'}>
                {' '}
                ({met ? 'within' : 'exceeds'} RTO {rtoTarget(rtoSeconds)})
              </span>
            )}
          </span>

          <span className="text-muted">Scratch environment</span>
          <span className="mono break-all text-right text-text">{rehearsal.scratch_env_id ?? '—'}</span>

          <span className="text-muted">Teardown</span>
          <span className="text-right text-text">{rehearsal.teardown_status ?? '—'}</span>
        </div>

        <div>
          <p className="mb-2 text-[12.5px] font-semibold text-text">Validation steps</p>
          <div className="divide-y divide-border rounded-ctl border border-border">
            {steps.map((step) => (
              <div key={step.name} className="flex items-start justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-text">{checkLabel(step.name)}</p>
                  {step.outcome?.detail && (
                    <p className="mt-0.5 text-[12px] text-muted">{step.outcome.detail}</p>
                  )}
                </div>
                <Badge variant={stepVariant(step.outcome)} dot={false}>
                  {step.outcome?.passed == null
                    ? 'Pending'
                    : step.outcome.passed
                      ? 'Passed'
                      : 'Failed'}
                </Badge>
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export function Rehearsals() {
  const { toasts, addToast, dismissToast } = useToast()

  const [config, setConfig] = useState<BackupConfig | null>(null)
  const [rehearsals, setRehearsals] = useState<Rehearsal[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [running, setRunning] = useState(false)
  const [detail, setDetail] = useState<Rehearsal | null>(null)

  /* ---- Load config + history together (AbortController-cleaned) ---- */
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    Promise.all([
      getRehearsalConfig(controller.signal),
      listRehearsals(0, PAGE_LIMIT, controller.signal),
    ])
      .then(([cfg, history]) => {
        setConfig(cfg)
        setRehearsals(history?.items ?? [])
        setTotal(history?.total ?? 0)
      })
      .catch((err) => {
        if (!isAbort(err)) setError(true)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [refreshKey])

  const handleRunNow = useCallback(async () => {
    setRunning(true)
    try {
      await runRehearsalNow()
      addToast(
        'success',
        'Rehearsal started. It runs in the background; refresh to see the result when it completes.',
      )
      setRefreshKey((k) => k + 1)
    } catch (err) {
      addToast('error', errorDetail(err, 'Could not start a rehearsal.'))
    } finally {
      setRunning(false)
    }
  }, [addToast])

  const rtoSeconds = config?.rto_seconds ?? null

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-text">Restore Rehearsals</h1>
        <Button variant="primary" size="sm" onClick={handleRunNow} loading={running} disabled={running}>
          Run rehearsal now
        </Button>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner label="Loading rehearsals" />
        </div>
      ) : error ? (
        <AlertBanner variant="error" title="Error">
          <div className="flex items-center justify-between gap-4">
            <span>Could not load restore rehearsals.</span>
            <Button variant="ghost" size="sm" onClick={() => setRefreshKey((k) => k + 1)}>
              Retry
            </Button>
          </div>
        </AlertBanner>
      ) : (
        <div className="space-y-6">
          {config && (
            <ScheduleCard
              config={config}
              onSaved={(c) => setConfig(c)}
              addToast={addToast}
            />
          )}

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold text-text">History</h2>
              <span className="text-[12.5px] text-muted">
                {total > 0 ? (
                  <>
                    <span className="mono text-text">{total}</span> rehearsal{total === 1 ? '' : 's'}
                  </>
                ) : (
                  'No rehearsals'
                )}
              </span>
            </div>

            {rehearsals.length === 0 ? (
              <AlertBanner variant="info" title="No rehearsals yet">
                No restore rehearsals have run. Set a schedule above, or use “Run rehearsal now” to
                verify a recent backup actually restores.
              </AlertBanner>
            ) : (
              <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
                <table className="w-full border-collapse" role="grid">
                  <caption className="sr-only">Restore rehearsal history</caption>
                  <thead>
                    <tr>
                      {['Run at', 'Result', 'Backup', 'Per-step outcomes', 'Duration vs RTO', 'Teardown', 'Actions'].map(
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
                    {rehearsals.map((rehearsal) => (
                      <tr
                        key={rehearsal.id}
                        className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas"
                      >
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          {formatTimestamp(rehearsal.created_at)}
                        </td>
                        <td className="px-5 py-3">
                          <Badge variant={resultVariant(rehearsal.result)} dot={false}>
                            {resultLabel(rehearsal.result)}
                          </Badge>
                        </td>
                        <td className="mono px-5 py-3 text-[12.5px] text-text">
                          {rehearsal.backup_id
                            ? `${rehearsal.backup_id.slice(0, 8)}…`
                            : '—'}
                        </td>
                        <td className="px-5 py-3">
                          <StepBadges rehearsal={rehearsal} />
                        </td>
                        <td className="px-5 py-3">
                          <DurationCell rehearsal={rehearsal} rtoSeconds={rtoSeconds} />
                        </td>
                        <td className="px-5 py-3 text-[13.5px] text-text">
                          {rehearsal.teardown_status ?? '—'}
                        </td>
                        <td className="px-5 py-3">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDetail(rehearsal)}
                            disabled={!isComplete(rehearsal) && rehearsalSteps(rehearsal).every((s) => s.outcome?.passed == null)}
                            aria-label={`View rehearsal from ${formatTimestamp(rehearsal.created_at)}`}
                          >
                            View
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {detail && (
        <RehearsalDetailsModal
          rehearsal={detail}
          rtoSeconds={rtoSeconds}
          onClose={() => setDetail(null)}
        />
      )}
    </div>
  )
}
