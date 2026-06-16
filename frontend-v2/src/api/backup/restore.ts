/**
 * Cloud Backup & Restore — Restore Wizard API client (Task 17.5).
 *
 * Thin, typed wrappers around the Global-Admin restore surface mounted at
 * `/api/v1/backup` (see app/modules/backup_restore/router.py). Kept in a
 * uniquely-named module (NOT a shared backup.ts) so it can evolve with the
 * wizard without colliding with the other backup pages.
 *
 * Every call uses `apiClient` (baseURL `/api/v1`), takes an AbortSignal where
 * the caller drives a useEffect/poll, and returns a typed payload. List
 * endpoints are always shaped `{ items, total }`.
 *
 * Backend limitation (documented): there is NO read-only
 * `GET /restore/jobs/{job_id}` status endpoint — only
 * `POST /restore/jobs/{job_id}/cancel`. The live progress modal therefore shows
 * the accepted/queued state plus the cancel control, and reflects a 409 from
 * cancel (apply already started / job terminal) by disabling the control.
 */
import type { AxiosError } from 'axios'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Shared response shapes (mirror schemas.py)                         */
/* ------------------------------------------------------------------ */

export interface ListResponse<T> {
  items: T[]
  total: number
}

export interface KeyStatus {
  has_active_key: boolean
  active_version: number | null
  setup_complete: boolean
}

export interface BackupRow {
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

export interface DestinationRow {
  id: string
  provider_type: string
  display_name: string
  is_primary: boolean
  is_immutable_copy: boolean
  connection_state: string
  residency: string
  lock_window_days: number | null
  config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface BrowseEntity {
  entity_type: string
  record_count: number
}

export interface BrowseOrg {
  org_id: string
  org_name: string | null
  entities: BrowseEntity[]
  logical_export_emitted: boolean
}

export interface DryRunStep {
  name: string
  outcome: string
  detail: string
}

export interface DryRunResult {
  overall: string
  checksum_ok: boolean
  older_schema: boolean
  backup_version: string | null
  target_version: string | null
  schema_outcome: string | null
  schema_decision: string | null
  elapsed_seconds: number
  steps: DryRunStep[]
}

export interface JobAccepted {
  job_id: string
  status: string
}

export interface JobStatus {
  id: string
  status: string
  progress_pct: number
  elapsed_seconds: number
  seconds_since_last_update: number
  // Terminal detail, populated once the job finishes (null while queued/running).
  outcome_summary?: string | null
  error_message?: string | null
  backup_id?: string | null
}

/** Recovery Kit is an opaque JSON object (uploaded from the kit file). */
export type RecoveryKit = Record<string, unknown>

export type ConflictPolicy = 'restore_as_new' | 'skip' | 'overwrite'

/* ------------------------------------------------------------------ */
/*  Calls                                                              */
/* ------------------------------------------------------------------ */

export async function fetchKeyStatus(signal?: AbortSignal): Promise<KeyStatus> {
  const res = await apiClient.get<KeyStatus>('/backup/keys/status', { signal })
  const data = res.data
  return {
    has_active_key: data?.has_active_key ?? false,
    active_version: data?.active_version ?? null,
    setup_complete: data?.setup_complete ?? false,
  }
}

export async function fetchBackups(
  signal?: AbortSignal,
  offset = 0,
  limit = 100,
): Promise<ListResponse<BackupRow>> {
  const res = await apiClient.get<ListResponse<BackupRow>>('/backup/backups', {
    params: { offset, limit },
    signal,
  })
  return { items: res.data?.items ?? [], total: res.data?.total ?? 0 }
}

export async function fetchDestinations(
  signal?: AbortSignal,
): Promise<ListResponse<DestinationRow>> {
  const res = await apiClient.get<ListResponse<DestinationRow>>('/backup/destinations', {
    params: { offset: 0, limit: 500 },
    signal,
  })
  return { items: res.data?.items ?? [], total: res.data?.total ?? 0 }
}

export async function bootstrapKey(
  recoveryKit: RecoveryKit,
  passphrase: string,
  version: number | null,
  signal?: AbortSignal,
): Promise<KeyStatus> {
  const res = await apiClient.post<KeyStatus>(
    '/backup/keys/bootstrap',
    { recovery_kit: recoveryKit, passphrase, version: version ?? undefined },
    { signal },
  )
  const data = res.data
  return {
    has_active_key: data?.has_active_key ?? false,
    active_version: data?.active_version ?? null,
    setup_complete: data?.setup_complete ?? false,
  }
}

export async function browseBackup(
  backupId: string,
  signal?: AbortSignal,
  offset = 0,
  limit = 500,
): Promise<ListResponse<BrowseOrg>> {
  const res = await apiClient.get<ListResponse<BrowseOrg>>('/backup/restore/browse', {
    params: { backup_id: backupId, offset, limit },
    signal,
  })
  return { items: res.data?.items ?? [], total: res.data?.total ?? 0 }
}

/**
 * True when an Axios error is a transient transport failure (no HTTP response
 * arrived) — e.g. Chrome's `ERR_NETWORK_CHANGED`, a dropped/reset connection, or
 * a timeout. These are safe to retry for read-only calls. A real HTTP error
 * (4xx/5xx, which carries `response`) and a caller-driven abort are NOT retried.
 */
function isTransientNetworkError(err: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return false
  const ax = err as AxiosError
  if (ax?.code === 'ERR_CANCELED' || ax?.name === 'CanceledError') return false
  // No `response` means the request never completed at the HTTP layer.
  return !ax?.response
}

export async function runDryRun(
  backupId: string,
  recoveryKit: RecoveryKit | null,
  passphrase: string | null,
  signal?: AbortSignal,
): Promise<DryRunResult> {
  const body = {
    backup_id: backupId,
    recovery_kit: recoveryKit ?? undefined,
    passphrase: passphrase ?? undefined,
  }
  // The dry-run is a single long (~seconds) read-only request that downloads +
  // decrypts the dump to verify the checksum. Over a TLS-terminating tunnel
  // (Cloudflare) a long-held connection can be dropped mid-flight
  // (ERR_NETWORK_CHANGED). It writes nothing, so transparently retry transient
  // transport drops a few times before surfacing the failure.
  const MAX_ATTEMPTS = 3
  let lastErr: unknown
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const res = await apiClient.post<DryRunResult>('/backup/restore/dry-run', body, { signal })
      const d = res.data
      return {
        overall: d?.overall ?? 'unknown',
        checksum_ok: d?.checksum_ok ?? false,
        older_schema: d?.older_schema ?? false,
        backup_version: d?.backup_version ?? null,
        target_version: d?.target_version ?? null,
        schema_outcome: d?.schema_outcome ?? null,
        schema_decision: d?.schema_decision ?? null,
        elapsed_seconds: d?.elapsed_seconds ?? 0,
        steps: d?.steps ?? [],
      }
    } catch (err) {
      lastErr = err
      if (attempt >= MAX_ATTEMPTS || !isTransientNetworkError(err, signal)) {
        throw err
      }
      // Brief backoff before retrying the dropped read-only request.
      await new Promise((resolve) => setTimeout(resolve, 600 * attempt))
    }
  }
  throw lastErr
}

export async function submitFullRestore(
  backupId: string,
  confirmOlderSchema: boolean,
  recoveryKit: RecoveryKit | null,
  passphrase: string | null,
  signal?: AbortSignal,
): Promise<JobAccepted> {
  const res = await apiClient.post<JobAccepted>(
    '/backup/restore/full',
    {
      backup_id: backupId,
      confirm_older_schema: confirmOlderSchema,
      recovery_kit: recoveryKit ?? undefined,
      passphrase: passphrase ?? undefined,
    },
    { signal },
  )
  return { job_id: res.data?.job_id ?? '', status: res.data?.status ?? 'queued' }
}

export async function submitPerOrgRestore(
  backupId: string,
  orgId: string,
  conflictPolicy: ConflictPolicy,
  selectedTables: string[] | null,
  restoreFiles: boolean,
  recoveryKit: RecoveryKit | null,
  passphrase: string | null,
  signal?: AbortSignal,
): Promise<JobAccepted> {
  const res = await apiClient.post<JobAccepted>(
    '/backup/restore/per-org',
    {
      backup_id: backupId,
      org_id: orgId,
      conflict_policy: conflictPolicy,
      selected_tables: selectedTables ?? undefined,
      restore_files: restoreFiles,
      recovery_kit: recoveryKit ?? undefined,
      passphrase: passphrase ?? undefined,
    },
    { signal },
  )
  return { job_id: res.data?.job_id ?? '', status: res.data?.status ?? 'queued' }
}

/** Result of a cancel attempt; `applyStarted` is true when the backend
 * refused the cancel (HTTP 409) because the destructive apply has begun or the
 * job is already terminal (Req 12.16, 12.17). */
export interface CancelOutcome {
  cancelled: boolean
  applyStarted: boolean
  status: JobStatus | null
  detail: string | null
}

/** Terminal restore-job statuses that stop polling. */
export const TERMINAL_RESTORE_STATUSES = ['completed', 'failed', 'cancelled'] as const

/**
 * Poll a launched restore job's live status (GET /restore/jobs/{id}).
 *
 * Returns the full status snapshot, including the terminal `outcome_summary` /
 * `error_message` once the job finishes, so the wizard can show success or the
 * actual failure reason instead of leaving the operator blind. Transient
 * transport errors (e.g. ERR_NETWORK_CHANGED over the tunnel) are retried so a
 * dropped poll does not abort the watch.
 */
export async function getRestoreJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const MAX_ATTEMPTS = 3
  let lastErr: unknown
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const res = await apiClient.get<JobStatus>(`/backup/restore/jobs/${jobId}`, { signal })
      return res.data
    } catch (err) {
      lastErr = err
      if (!isTransientNetworkError(err, signal) || attempt === MAX_ATTEMPTS) throw err
      await new Promise((r) => setTimeout(r, 400 * attempt))
    }
  }
  throw lastErr
}

export async function cancelRestoreJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<CancelOutcome> {
  try {
    const res = await apiClient.post<JobStatus>(
      `/backup/restore/jobs/${jobId}/cancel`,
      {},
      { signal },
    )
    return { cancelled: true, applyStarted: false, status: res.data ?? null, detail: null }
  } catch (err) {
    const axiosErr = err as AxiosError<{ detail?: string }>
    if (axiosErr?.response?.status === 409) {
      return {
        cancelled: false,
        applyStarted: true,
        status: null,
        detail: axiosErr.response?.data?.detail ?? 'The restore can no longer be cancelled.',
      }
    }
    throw err
  }
}

/** Extract a clean detail string from an Axios error (no stack traces). */
export function errorDetail(err: unknown, fallback: string): string {
  const axiosErr = err as AxiosError<{ detail?: string }>
  return axiosErr?.response?.data?.detail ?? fallback
}

/**
 * Upload a portable bundle + recovery kit + passphrase and trigger a full
 * destructive restore from it. Returns a job id that can be polled with
 * `getRestoreJobStatus`. This is the fast-DR path: no destination setup needed.
 */
export async function uploadAndRestore(
  bundle: File,
  recoveryKit: string,
  passphrase: string,
  confirmOlderSchema: boolean,
  signal?: AbortSignal,
): Promise<JobAccepted> {
  const form = new FormData()
  form.append('bundle', bundle)
  form.append('recovery_kit', recoveryKit)
  form.append('passphrase', passphrase)
  form.append('confirm_older_schema', String(confirmOlderSchema))
  const res = await apiClient.post<JobAccepted>('/backup/restore/upload', form, {
    signal,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 0, // no client-side timeout for large uploads
  })
  return res.data
}
