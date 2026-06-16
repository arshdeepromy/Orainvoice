/**
 * Cloud Backup & Restore — dashboard API client (Task 17.2).
 *
 * Uniquely-named module (NOT a shared backup.ts) so parallel frontend tasks
 * never edit the same file. Every call is typed via generics, routes through
 * the shared `apiClient` (baseURL `/api/v1`, so paths are `/backup/...`), and
 * forwards an optional `AbortSignal` so the consuming page can cancel in-flight
 * requests on unmount.
 *
 * Shared response types (`BackupConfig`, `Destination`, `ListResponse`) are
 * re-used from the sibling `settings.ts` helper rather than re-declared, so the
 * two pages stay in lock-step with the backend schemas
 * (app/modules/backup_restore/schemas.py).
 */
import apiClient from '@/api/client'
import type { BackupConfig, Destination, ListResponse } from './settings'

export type { BackupConfig, Destination, ListResponse } from './settings'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

/** Selectable backup scope (Req 6). */
export type BackupScope = 'settings_only' | 'organisations_only' | 'both'

/** A committed Full_Backup catalog row (cleartext catalog fields only). */
export interface Backup {
  id: string
  created_at: string
  scope: string
  app_version: string | null
  schema_version: string | null
  key_version: number | null
  dump_size_bytes: number | null
  dump_checksum: string | null
  file_count: number | null
  file_bytes: number | null
  consistency_level: string | null
  prune_status: string
}

/** Response to POST /backups — a background job was accepted (HTTP 202). */
export interface JobAccepted {
  job_id: string
  status: string
}

/** Live status of a backup job (Req 13.3) + terminal detail once finished. */
export interface JobStatus {
  id: string
  status: string
  progress_pct: number
  elapsed_seconds: number
  seconds_since_last_update: number
  outcome_summary: string | null
  error_message: string | null
  backup_id: string | null
}

/* ------------------------------------------------------------------ */
/*  Calls                                                              */
/* ------------------------------------------------------------------ */

/** Fetch the single-row backup configuration (schedule / RPO / RTO). */
export async function getConfig(signal?: AbortSignal): Promise<BackupConfig> {
  const res = await apiClient.get<BackupConfig>('/backup/config', { signal })
  return res.data
}

/** List all configured destinations ({items,total}). */
export async function listDestinations(
  signal?: AbortSignal,
): Promise<ListResponse<Destination>> {
  const res = await apiClient.get<ListResponse<Destination>>('/backup/destinations', {
    signal,
    params: { offset: 0, limit: 500 },
  })
  return res.data
}

/**
 * List committed backups ({items,total}), ordered by creation timestamp
 * descending — so the first item is the most recent backup (Req 9.1).
 */
export async function listBackups(
  signal?: AbortSignal,
): Promise<ListResponse<Backup>> {
  const res = await apiClient.get<ListResponse<Backup>>('/backup/backups', {
    signal,
    params: { offset: 0, limit: 1 },
  })
  return res.data
}

/**
 * Trigger a manual on-demand backup (Req 8.8). Returns the accepted job
 * descriptor (HTTP 202). When `scope` is omitted the backend uses the
 * configured `default_scope`.
 */
export async function runBackupNow(
  scope: BackupScope,
  signal?: AbortSignal,
): Promise<JobAccepted> {
  const res = await apiClient.post<JobAccepted>('/backup/backups', { scope }, { signal })
  return res.data
}

/** Poll a backup job's live status (Req 13.3). */
export async function getBackupJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const res = await apiClient.get<JobStatus>(`/backup/backups/jobs/${jobId}`, { signal })
  return res.data
}

/** Cancel a running/queued backup job (best-effort). */
export async function cancelBackupJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const res = await apiClient.post<JobStatus>(`/backup/backups/jobs/${jobId}/cancel`, {}, { signal })
  return res.data
}
