/**
 * Cloud Backup & Restore — restore-rehearsal API client (Task 17.7).
 *
 * Uniquely-named module (NOT a shared backup.ts) so parallel frontend tasks
 * never edit the same file. Every call is typed via generics, routes through
 * the shared `apiClient` (baseURL `/api/v1`, so paths are `/backup/...`), and
 * forwards an optional `AbortSignal` so the consuming page can cancel in-flight
 * requests on unmount / before re-polling.
 *
 * Backend surface: app/modules/backup_restore/router.py + schemas.py
 *   GET  /backup/rehearsals?offset=&limit=  → { items, total } rehearsal history (Req 26.1)
 *   POST /backup/rehearsals                  → 202: run a rehearsal now (Req 26.1)
 *   GET  /backup/config                      → schedule/cadence config incl. rehearsal_cron + RTO (Req 25)
 *   PUT  /backup/config                      → update the rehearsal cadence / RTO (Req 25.1/25.3)
 *
 * Requirements: 25.4 (rehearsal cadence + measured duration vs RTO), 26.1 (history).
 */
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

/** Standard list envelope — arrays are always `{ items, total }`. */
export interface ListResponse<T> {
  items: T[]
  total: number
}

/** Result of a completed rehearsal (`passed`/`failed`); `null` while pending. */
export type RehearsalResult = 'passed' | 'failed'

/**
 * A single validation step's recorded outcome (Req 26.3/26.4). Mirrors the
 * `CheckOutcome.to_dict()` JSONB shape persisted on the rehearsal row:
 * `{ name, passed, detail, data? }`.
 */
export interface CheckOutcome {
  name?: string
  passed?: boolean
  detail?: string
  data?: Record<string, unknown>
}

/**
 * A recorded restore-rehearsal result. Mirrors `RehearsalResponse` in
 * app/modules/backup_restore/schemas.py. Every field except `id`/`created_at`
 * is optional/nullable because a just-queued "run now" placeholder row carries
 * only the identifier and timestamp until the background run completes.
 */
export interface Rehearsal {
  id: string
  backup_id: string | null
  result: RehearsalResult | string | null
  measured_duration_seconds: number | null
  scratch_env_id: string | null
  teardown_status: string | null
  created_at: string
  schema_check: CheckOutcome | null
  rowcount_check: CheckOutcome | null
  file_check: CheckOutcome | null
  smoke_check: CheckOutcome | null
}

/**
 * The single-row backup configuration, of which the rehearsal page reads the
 * cadence (`rehearsal_cron`) and the recovery-time objective (`rto_seconds`)
 * the measured durations are judged against. Mirrors `ConfigResponse`.
 */
export interface BackupConfig {
  id: string
  rehearsal_cron: string | null
  rto_seconds: number
  rpo_seconds: number
  restore_maintenance_active: boolean
}

/** Partial config update — the rehearsal page only edits cadence + RTO. */
export interface RehearsalScheduleUpdate {
  rehearsal_cron?: string | null
  rto_seconds?: number
}

/** A config update result with any non-blocking RPO/RTO warnings (Req 25.2). */
export interface ConfigUpdateResult {
  config: BackupConfig
  warnings: string[]
}

/* ------------------------------------------------------------------ */
/*  Calls                                                              */
/* ------------------------------------------------------------------ */

/** Rehearsal history `{items,total}` page, newest first (Req 26.1). */
export async function listRehearsals(
  offset: number,
  limit: number,
  signal?: AbortSignal,
): Promise<ListResponse<Rehearsal>> {
  const res = await apiClient.get<ListResponse<Rehearsal>>('/backup/rehearsals', {
    signal,
    params: { offset, limit },
  })
  return res.data
}

/**
 * Run a restore rehearsal now (Req 26.1). The backend returns 202 with a
 * placeholder record immediately; the full result appears in the history list
 * once the background rehearsal completes.
 */
export async function runRehearsalNow(signal?: AbortSignal): Promise<Rehearsal> {
  const res = await apiClient.post<Rehearsal>('/backup/rehearsals', {}, { signal })
  return res.data
}

/** Read the schedule/cadence config (rehearsal cron + RTO objective) (Req 25). */
export async function getRehearsalConfig(signal?: AbortSignal): Promise<BackupConfig> {
  const res = await apiClient.get<BackupConfig>('/backup/config', { signal })
  return res.data
}

/** Update the rehearsal cadence / RTO objective (Req 25.1/25.3). */
export async function updateRehearsalSchedule(
  body: RehearsalScheduleUpdate,
  signal?: AbortSignal,
): Promise<ConfigUpdateResult> {
  const res = await apiClient.put<ConfigUpdateResult>('/backup/config', body, { signal })
  return res.data
}

/* ------------------------------------------------------------------ */
/*  Display helpers                                                    */
/* ------------------------------------------------------------------ */

/** The four validation steps in the order they run / are evaluated (Req 26.3). */
export const CHECK_ORDER = ['schema', 'row_count', 'file_consistency', 'smoke'] as const
export type CheckName = (typeof CHECK_ORDER)[number]

/** Human-readable label for each validation step. */
export const CHECK_LABELS: Record<string, string> = {
  schema: 'Schema',
  row_count: 'Row counts',
  file_consistency: 'File consistency',
  smoke: 'Smoke test',
}

export function checkLabel(name: string): string {
  return CHECK_LABELS[name] ?? name
}

/** Pull the per-step outcomes off a rehearsal row in canonical order. */
export function rehearsalSteps(
  rehearsal: Rehearsal,
): { name: CheckName; outcome: CheckOutcome | null }[] {
  return [
    { name: 'schema', outcome: rehearsal.schema_check ?? null },
    { name: 'row_count', outcome: rehearsal.rowcount_check ?? null },
    { name: 'file_consistency', outcome: rehearsal.file_check ?? null },
    { name: 'smoke', outcome: rehearsal.smoke_check ?? null },
  ]
}

/** True when the rehearsal has produced a final pass/fail result. */
export function isComplete(rehearsal: Rehearsal): boolean {
  return rehearsal.result === 'passed' || rehearsal.result === 'failed'
}

/** True when the measured restore duration exceeded the configured RTO (Req 25.5). */
export function isRtoMet(
  measuredSeconds: number | null | undefined,
  rtoSeconds: number | null | undefined,
): boolean | null {
  if (measuredSeconds == null || rtoSeconds == null || rtoSeconds <= 0) return null
  return measuredSeconds <= rtoSeconds
}

/** Format a duration in seconds as a compact `Xh Ym Zs` / `Ym Zs` / `Zs` string. */
export function formatDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round(seconds ?? 0))
  if ((seconds ?? null) == null) return '—'
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

/** Format an ISO timestamp for display; falls back to the raw string. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
