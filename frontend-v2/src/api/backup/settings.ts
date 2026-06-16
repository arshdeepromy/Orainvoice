/**
 * Cloud Backup & Restore — settings API client (Task 17.3).
 *
 * Uniquely-named module (NOT a shared backup.ts) so parallel frontend tasks
 * never edit the same file. Every call is typed via generics, routes through
 * the shared `apiClient` (baseURL `/api/v1`, so paths are `/backup/...`), and
 * forwards an optional `AbortSignal` so the consuming page can cancel in-flight
 * requests on unmount.
 *
 * Backend surface: app/modules/backup_restore/router.py + schemas.py.
 * Credentials are masked in every response (`mask_config`); a masked value
 * submitted back on edit is preserved by the backend (`is_masked_value`).
 */
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type ProviderType = 'google_drive' | 'onedrive' | 's3' | 'nas'

/** Standard list envelope — arrays are always `{ items, total }`. */
export interface ListResponse<T> {
  items: T[]
  total: number
}

/** A destination's provider config with credential fields masked. */
export type DestinationConfig = Record<string, unknown>

export interface Destination {
  id: string
  provider_type: ProviderType | string
  display_name: string
  is_primary: boolean
  is_immutable_copy: boolean
  connection_state: string
  residency: string
  lock_window_days: number | null
  config: DestinationConfig
  created_at: string | null
  updated_at: string | null
}

export interface DestinationCreate {
  provider_type: ProviderType
  display_name: string
  config: DestinationConfig
  residency?: string | null
  is_immutable_copy?: boolean
  lock_window_days?: number | null
}

export interface DestinationEdit {
  display_name?: string
  is_immutable_copy?: boolean
  lock_window_days?: number | null
  config?: DestinationConfig
}

export interface ConnectionTestResult {
  state: string
  detail: string
}

export interface ResidencyNotice {
  residency: string
  destination_label: string
  offshore_warning: boolean
  requires_acknowledgement: boolean
  headline: string
  body: string
  biometric_notice: string
  text: string
  acknowledged: boolean
}

export interface ResidencyAck {
  destination_id: string
  acknowledged: boolean
  acknowledged_at: string | null
}

export interface OAuthConnect {
  authorization_url: string
  state: string
}

/** The single-row backup configuration (schedule / retention / notifications). */
export interface BackupConfig {
  id: string
  schedule_cron: string | null
  backup_window_start: string | null
  backup_window_end: string | null
  retention_count: number | null
  retention_days: number | null
  default_scope: string
  rpo_seconds: number
  rto_seconds: number
  notify_backup_failure: boolean
  notify_backup_success: boolean
  notify_restore_failure: boolean
  notify_restore_success: boolean
  webhook_url: string | null
  sms_enabled: boolean
  email_enabled: boolean
  notification_emails: string[]
  notification_sms_numbers: string[]
  orphan_gc_grace_hours: number
  perorg_export_size_cap_bytes: number | null
  rehearsal_cron: string | null
  restore_maintenance_active: boolean
}

export interface ConfigUpdate {
  schedule_cron?: string | null
  backup_window_start?: string | null
  backup_window_end?: string | null
  retention_count?: number | null
  retention_days?: number | null
  default_scope?: string
  rpo_seconds?: number
  rto_seconds?: number
  notify_backup_failure?: boolean
  notify_backup_success?: boolean
  notify_restore_failure?: boolean
  notify_restore_success?: boolean
  webhook_url?: string | null
  sms_enabled?: boolean
  email_enabled?: boolean
  notification_emails?: string[]
  notification_sms_numbers?: string[]
}

export interface ConfigUpdateResult {
  config: BackupConfig
  warnings: string[]
}

export interface ChannelResult {
  channel: string
  ok: boolean
  detail: string
}

export interface NotificationTestResult {
  results: ChannelResult[]
}

/* ------------------------------------------------------------------ */
/*  Destinations                                                       */
/* ------------------------------------------------------------------ */

export async function listDestinations(
  signal?: AbortSignal,
): Promise<ListResponse<Destination>> {
  const res = await apiClient.get<ListResponse<Destination>>('/backup/destinations', {
    signal,
    params: { offset: 0, limit: 500 },
  })
  return res.data
}

export async function createDestination(
  body: DestinationCreate,
  signal?: AbortSignal,
): Promise<Destination> {
  const res = await apiClient.post<Destination>('/backup/destinations', body, { signal })
  return res.data
}

export async function editDestination(
  id: string,
  body: DestinationEdit,
  signal?: AbortSignal,
): Promise<Destination> {
  const res = await apiClient.put<Destination>(`/backup/destinations/${id}`, body, { signal })
  return res.data
}

export async function setPrimaryDestination(
  id: string,
  signal?: AbortSignal,
): Promise<ListResponse<Destination>> {
  const res = await apiClient.post<ListResponse<Destination>>(
    `/backup/destinations/${id}/set-primary`,
    {},
    { signal },
  )
  return res.data
}

export async function deleteDestination(id: string, signal?: AbortSignal): Promise<void> {
  await apiClient.delete(`/backup/destinations/${id}`, { signal })
}

export async function testDestination(
  id: string,
  signal?: AbortSignal,
): Promise<ConnectionTestResult> {
  const res = await apiClient.post<ConnectionTestResult>(
    `/backup/destinations/${id}/test`,
    {},
    { signal },
  )
  return res.data
}

/** A destination's storage quota/usage; fields are null when not reported. */
export interface StorageUsage {
  reported: boolean
  total_bytes: number | null
  used_bytes: number | null
  available_bytes: number | null
}

export async function getDestinationStorage(
  id: string,
  signal?: AbortSignal,
): Promise<StorageUsage> {
  const res = await apiClient.get<StorageUsage>(`/backup/destinations/${id}/storage`, {
    signal,
  })
  return res.data
}

export async function getResidencyNotice(
  id: string,
  signal?: AbortSignal,
): Promise<ResidencyNotice> {
  const res = await apiClient.get<ResidencyNotice>(`/backup/destinations/${id}/residency`, {
    signal,
  })
  return res.data
}

export async function acknowledgeResidency(
  id: string,
  signal?: AbortSignal,
): Promise<ResidencyAck> {
  const res = await apiClient.post<ResidencyAck>(
    `/backup/destinations/${id}/residency`,
    {},
    { signal },
  )
  return res.data
}

export async function oauthConnect(id: string, signal?: AbortSignal): Promise<OAuthConnect> {
  const res = await apiClient.get<OAuthConnect>(`/backup/destinations/${id}/oauth/connect`, {
    signal,
  })
  return res.data
}

/* ------------------------------------------------------------------ */
/*  Config (schedule / retention / notifications)                      */
/* ------------------------------------------------------------------ */

export async function getConfig(signal?: AbortSignal): Promise<BackupConfig> {
  const res = await apiClient.get<BackupConfig>('/backup/config', { signal })
  return res.data
}

export async function updateConfig(
  body: ConfigUpdate,
  signal?: AbortSignal,
): Promise<ConfigUpdateResult> {
  const res = await apiClient.put<ConfigUpdateResult>('/backup/config', body, { signal })
  return res.data
}

export async function testNotifications(
  signal?: AbortSignal,
): Promise<NotificationTestResult> {
  const res = await apiClient.post<NotificationTestResult>(
    '/backup/config/notifications/test',
    {},
    { signal },
  )
  return res.data
}

/* ------------------------------------------------------------------ */
/*  Provider metadata (form field definitions)                         */
/* ------------------------------------------------------------------ */

export interface ProviderFieldDef {
  key: string
  label: string
  /** Credential fields are masked in responses and preserved on round-trip. */
  secret?: boolean
  type?: 'text' | 'password' | 'select'
  options?: { value: string; label: string }[]
  placeholder?: string
  helperText?: string
  required?: boolean
}

export const PROVIDER_LABELS: Record<string, string> = {
  google_drive: 'Google Drive',
  onedrive: 'OneDrive',
  s3: 'Amazon S3 / S3-compatible',
  nas: 'NAS / SMB share',
}

export function isOAuthProvider(provider: string): boolean {
  return provider === 'google_drive' || provider === 'onedrive'
}

/**
 * Per-provider Add/Edit form field definitions. OAuth providers collect the
 * client credentials up front (connect happens afterward via popup).
 */
export const PROVIDER_FIELDS: Record<ProviderType, ProviderFieldDef[]> = {
  google_drive: [
    { key: 'client_id', label: 'OAuth Client ID', secret: true, required: true },
    { key: 'client_secret', label: 'OAuth Client Secret', secret: true, type: 'password', required: true },
    { key: 'folder_path', label: 'Folder path', placeholder: '/OraInvoiceBackups' },
  ],
  onedrive: [
    { key: 'client_id', label: 'OAuth Client ID', secret: true, required: true },
    { key: 'client_secret', label: 'OAuth Client Secret', secret: true, type: 'password', required: true },
    { key: 'folder_path', label: 'Folder path', placeholder: '/OraInvoiceBackups' },
  ],
  s3: [
    { key: 'access_key_id', label: 'Access Key ID', secret: true, required: true },
    { key: 'secret_access_key', label: 'Secret Access Key', secret: true, type: 'password', required: true },
    { key: 'bucket', label: 'Bucket', required: true },
    { key: 'region', label: 'Region', placeholder: 'us-east-1' },
    {
      key: 'endpoint_url',
      label: 'Endpoint URL',
      placeholder: 'https://s3.example.com (leave blank for AWS)',
      helperText: 'Set for S3-compatible providers (MinIO, Wasabi, Backblaze B2).',
    },
    {
      key: 'addressing_style',
      label: 'Addressing style',
      type: 'select',
      options: [
        { value: 'auto', label: 'Auto' },
        { value: 'virtual', label: 'Virtual-hosted' },
        { value: 'path', label: 'Path-style' },
      ],
    },
  ],
  nas: [
    { key: 'share_path', label: 'Share path', placeholder: '//server/share', required: true },
    {
      key: 'access_mode',
      label: 'Access mode',
      type: 'select',
      options: [
        { value: 'smb', label: 'SMB / CIFS' },
        { value: 'local', label: 'Local mount' },
      ],
    },
    { key: 'target_dir', label: 'Target directory', placeholder: 'orainvoice/backups' },
    { key: 'username', label: 'Username', secret: true },
    { key: 'password', label: 'Password', secret: true, type: 'password' },
  ],
}
