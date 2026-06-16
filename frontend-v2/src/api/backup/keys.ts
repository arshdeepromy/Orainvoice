/**
 * Backup key-management API client (Task 17.6).
 *
 * Uniquely-named module for the KeyRecoveryKit page — deliberately NOT a shared
 * `backup.ts` so it stays self-contained to the key endpoints (Req 16.3, 16.4,
 * 16.10, 16.12). All calls go through the shared `apiClient` (baseURL `/api/v1`),
 * so the paths here are relative to `/api/v1`.
 */
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

/** GET /backup/keys/status — current backup-key state of this deployment (Req 16.12). */
export interface KeyStatus {
  has_active_key: boolean
  /** Active key version when a key exists; null when none. */
  active_version: number | null
  setup_complete: boolean
}

/**
 * The recovery kit is an opaque, escrow JSON document the operator must store
 * offline. We treat it as an opaque record — the page never inspects its
 * contents, it only offers it for a one-time download.
 */
export type RecoveryKit = Record<string, unknown>

/** POST /backup/keys/setup — first-run setup returns the one-time kit (201). */
export interface SetupResponse {
  recovery_kit: RecoveryKit
  message: string
}

/** GET|POST /backup/keys/recovery-kit — re-export the kit (re-auth required). */
export interface RecoveryKitResponse {
  recovery_kit: RecoveryKit
}

/** POST /backup/keys/rotate — mint a new key version (Req 16.10). */
export interface RotateResponse {
  active_version: number
}

/* ------------------------------------------------------------------ */
/*  Calls                                                              */
/* ------------------------------------------------------------------ */

/** Read the deployment's backup-key status. Pass an AbortSignal for cleanup. */
export async function getKeyStatus(signal?: AbortSignal): Promise<KeyStatus> {
  const res = await apiClient.get<KeyStatus>('/backup/keys/status', { signal })
  return res.data
}

/**
 * First-run setup: generate the BMK/BDK hierarchy under the supplied passphrase
 * and return the one-time recovery kit. 422 → weak passphrase, 409 → already set up.
 */
export async function setupKey(passphrase: string): Promise<SetupResponse> {
  const res = await apiClient.post<SetupResponse>('/backup/keys/setup', { passphrase })
  return res.data
}

/** Re-export the recovery kit for the active key (server enforces re-auth). */
export async function exportRecoveryKit(): Promise<RecoveryKitResponse> {
  const res = await apiClient.post<RecoveryKitResponse>('/backup/keys/recovery-kit', {})
  return res.data
}

/** Rotate to a new active key version, retaining prior versions (Req 16.10). */
export async function rotateKey(): Promise<RotateResponse> {
  const res = await apiClient.post<RotateResponse>('/backup/keys/rotate', {})
  return res.data
}
