/**
 * Cloud Backup & Restore — backup history API client (Task 17.4).
 *
 * Uniquely-named module (NOT a shared backup.ts) so parallel frontend tasks
 * never edit the same file. Every call is typed via generics, routes through
 * the shared `apiClient` (baseURL `/api/v1`, so paths are `/backup/...`), and
 * forwards an optional `AbortSignal` so the consuming page can cancel in-flight
 * requests on unmount / before re-polling.
 *
 * Backend surface: app/modules/backup_restore/router.py + schemas.py
 *   GET  /backup/backups?offset=&limit=        → { items, total } catalog
 *   GET  /backup/backups/jobs/{job_id}         → live job status (Req 13.3)
 *   POST /backup/backups/jobs/{job_id}/cancel  → cancel a running job (Req 13.1)
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

/**
 * A committed Full_Backup catalog row (cleartext catalog fields only).
 * Mirrors `BackupResponse` in app/modules/backup_restore/schemas.py.
 *
 * `destinations` is not part of the current backend response; it is declared
 * optional so the table renders it defensively when/if the backend supplies it.
 */
export interface Backup {
  id: string
  created_at: string
  scope: string
  app_version?: string | null
  schema_version?: string | null
  key_version?: number | null
  dump_size_bytes?: number | null
  dump_checksum?: string | null
  file_count?: number | null
  file_bytes?: number | null
  consistency_level?: string | null
  prune_status: string
  destinations?: string[] | null
  /** True when this backup was created by a manual run — only these are
   *  operator-deletable (the backend gates deletion to manual-origin backups). */
  is_manual?: boolean
}

/** Lifecycle status of a backup / restore job (Req 13.1). */
export type JobStatusValue =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

/** A point-in-time job status view (Req 13.3). Mirrors `JobStatusResponse`. */
export interface JobStatus {
  id: string
  status: JobStatusValue | string
  progress_pct: number
  elapsed_seconds: number
  seconds_since_last_update: number
}

/* ------------------------------------------------------------------ */
/*  Calls                                                              */
/* ------------------------------------------------------------------ */

/** Backup history `{items,total}` page, newest first (Req 9.1). */
export async function listBackups(
  offset: number,
  limit: number,
  signal?: AbortSignal,
): Promise<ListResponse<Backup>> {
  const res = await apiClient.get<ListResponse<Backup>>('/backup/backups', {
    signal,
    params: { offset, limit },
  })
  return res.data
}

/** Live status of a single backup job (Req 13.3). */
export async function getBackupJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const res = await apiClient.get<JobStatus>(`/backup/backups/jobs/${jobId}`, {
    signal,
  })
  return res.data
}

/** Cancel a backup job — 200 with the new status, 409 if already terminal. */
export async function cancelBackupJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const res = await apiClient.post<JobStatus>(
    `/backup/backups/jobs/${jobId}/cancel`,
    {},
    { signal },
  )
  return res.data
}

/* ------------------------------------------------------------------ */
/*  Manual deletion (verification-code gated)                          */
/* ------------------------------------------------------------------ */

export interface DeletionChallenge {
  challenge_id: string
  expires_at: string
  recipient: string
  backup_count: number
}

export interface DeletionResult {
  requested: number
  deleted: number
  failed: number
  blobs_deleted: number
  failed_ids: string[]
}

/** Background deletion job acceptance (202) + its pollable status. */
export interface DeletionJobAccepted {
  job_id: string
  requested: number
  status: string
}

export interface DeletionJobStatus {
  status: string // running | completed | failed
  requested: number
  deleted: number
  failed: number
  blobs_deleted: number
  error?: string | null
}

/**
 * Step 1 — request a 6-digit verification code (emailed to the admin) for
 * deleting the given backups, or all manual backups when `allManual` is true.
 */
export async function requestBackupDeletion(
  params: { backupIds?: string[]; allManual?: boolean },
  signal?: AbortSignal,
): Promise<DeletionChallenge> {
  const res = await apiClient.post<DeletionChallenge>(
    '/backup/backups/delete/request',
    { backup_ids: params.backupIds ?? null, all_manual: params.allManual ?? false },
    { signal },
  )
  return res.data
}

/** Step 2 — confirm with the emailed code. Deletion runs in the background;
 *  poll `getBackupDeleteJob` for the outcome. */
export async function confirmBackupDeletion(
  challengeId: string,
  code: string,
  signal?: AbortSignal,
): Promise<DeletionJobAccepted> {
  const res = await apiClient.post<DeletionJobAccepted>(
    '/backup/backups/delete/confirm',
    { challenge_id: challengeId, code },
    { signal },
  )
  return res.data
}

/** Poll a background deletion job until `status` is terminal. */
export async function getBackupDeleteJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<DeletionJobStatus> {
  const res = await apiClient.get<DeletionJobStatus>(
    `/backup/backups/delete/jobs/${jobId}`,
    { signal },
  )
  return res.data
}

/* ------------------------------------------------------------------ */
/*  Display helpers                                                    */
/* ------------------------------------------------------------------ */

/** The lifecycle states that mean a job will never change again. */
export const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
  'completed',
  'failed',
  'cancelled',
])

export function isTerminalStatus(status: string | null | undefined): boolean {
  return status != null && TERMINAL_JOB_STATUSES.has(status)
}

/** Human-readable scope label (server stores the raw enum). */
export const SCOPE_LABELS: Record<string, string> = {
  settings_only: 'Settings only',
  organisations_only: 'Organisations only',
  both: 'Full platform',
}

export function scopeLabel(scope: string | null | undefined): string {
  if (!scope) return '—'
  return SCOPE_LABELS[scope] ?? scope
}

/** Consistency level: `A` (atomic snapshot) or `C` (crash-consistent). */
export const CONSISTENCY_LABELS: Record<string, string> = {
  A: 'Atomic',
  C: 'Crash-consistent',
}

export function consistencyLabel(level: string | null | undefined): string {
  if (!level) return '—'
  return CONSISTENCY_LABELS[level] ?? level
}

/** Prune status badge tone mapping (`retained`/`pruned`/`prune_failed`). */
export const PRUNE_LABELS: Record<string, string> = {
  retained: 'Retained',
  pruned: 'Pruned',
  prune_failed: 'Prune failed',
}

export function pruneLabel(status: string | null | undefined): string {
  if (!status) return '—'
  return PRUNE_LABELS[status] ?? status
}

/** Format a byte count into a human-readable size; `null`/`0` safe. */
export function formatBytes(bytes: number | null | undefined): string {
  const value = bytes ?? 0
  if (value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const exponent = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  )
  const size = value / Math.pow(1024, exponent)
  const rounded = size >= 100 || exponent === 0 ? Math.round(size) : size.toFixed(1)
  return `${rounded} ${units[exponent]}`
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
