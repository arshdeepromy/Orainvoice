/**
 * Typed API wrappers for the In-App Notifications inbox endpoints.
 *
 * Uses /api/v2/notifications/inbox (mobile prefers v2 per mobile-app.md).
 * All responses are guarded with optional chaining and fallback defaults
 * per safe-api-consumption rules.
 *
 * Requirements: 7
 */

import apiClient from '@/api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InboxItem {
  id: string
  category: string
  severity: string
  title: string
  body: string | null
  link_url: string | null
  entity_type: string | null
  entity_id: string | null
  metadata: Record<string, unknown>
  created_at: string
  is_read: boolean
  read_at: string | null
}

export interface InboxResponse {
  items: InboxItem[]
  total: number
  unread_count: number
}

export interface UnreadCountResponse {
  count: number
}

export interface GetInboxParams {
  limit?: number
  offset?: number
  unread_only?: boolean
  category?: string
  severity?: string
}

interface MarkReadResponse {
  success: boolean
}

interface MarkAllReadResponse {
  count: number
}

interface DismissResponse {
  success: boolean
}

interface DismissAllReadResponse {
  count: number
}

// ---------------------------------------------------------------------------
// API Functions
// ---------------------------------------------------------------------------

const BASE = '/api/v2/notifications/inbox'

/**
 * Fetch paginated inbox notifications with optional filters.
 */
export async function getInbox(
  params: GetInboxParams = {},
  signal?: AbortSignal,
): Promise<InboxResponse> {
  const queryParams: Record<string, string | number | boolean> = {}
  if (params.limit != null) queryParams.limit = params.limit
  if (params.offset != null) queryParams.offset = params.offset
  if (params.unread_only) queryParams.unread_only = true
  if (params.category) queryParams.category = params.category
  if (params.severity) queryParams.severity = params.severity

  const res = await apiClient.get<InboxResponse>(BASE, {
    params: queryParams,
    signal,
  })
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    unread_count: res.data?.unread_count ?? 0,
  }
}

/**
 * Get the current unread notification count (for badge polling).
 */
export async function getUnreadCount(signal?: AbortSignal): Promise<number> {
  const res = await apiClient.get<UnreadCountResponse>(
    `${BASE}/unread-count`,
    { signal },
  )
  return res.data?.count ?? 0
}

/**
 * Mark a single notification as read.
 */
export async function markRead(
  id: string,
  signal?: AbortSignal,
): Promise<boolean> {
  const res = await apiClient.post<MarkReadResponse>(
    `${BASE}/${id}/read`,
    null,
    { signal },
  )
  return res.data?.success ?? true
}

/**
 * Mark all visible notifications as read for the current user.
 */
export async function markAllRead(signal?: AbortSignal): Promise<number> {
  const res = await apiClient.post<MarkAllReadResponse>(
    `${BASE}/mark-all-read`,
    null,
    { signal },
  )
  return res.data?.count ?? 0
}

/**
 * Dismiss a single notification (hides it from the inbox).
 */
export async function dismiss(
  id: string,
  signal?: AbortSignal,
): Promise<boolean> {
  const res = await apiClient.post<DismissResponse>(
    `${BASE}/${id}/dismiss`,
    null,
    { signal },
  )
  return res.data?.success ?? true
}

/**
 * Dismiss all read notifications for the current user.
 */
export async function dismissAllRead(signal?: AbortSignal): Promise<number> {
  const res = await apiClient.post<DismissAllReadResponse>(
    `${BASE}/dismiss-all-read`,
    null,
    { signal },
  )
  return res.data?.count ?? 0
}
