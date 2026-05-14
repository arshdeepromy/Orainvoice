/**
 * Shared hook encapsulating inbox API interactions.
 *
 * Provides list, mark-read, dismiss, mark-all-read, and dismiss-all-read
 * operations with AbortController cleanup for safe API consumption.
 *
 * Validates: Requirements 6.2
 */

import { useCallback, useRef } from 'react'
import apiClient from '../../api/client'
import type { InboxItemData } from '@/components/notifications/InboxItemCard'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InboxResponse {
  items: InboxItemData[]
  total: number
  unread_count: number
}

export interface FetchInboxParams {
  limit?: number
  offset?: number
  unread_only?: boolean
  category?: string
  severity?: string
}

export interface UseInboxReturn {
  /** Fetch paginated inbox list with optional filters. Caller provides AbortSignal. */
  fetchInbox: (params: FetchInboxParams, signal?: AbortSignal) => Promise<InboxResponse>
  /** Mark a single notification as read. */
  markRead: (id: string, signal?: AbortSignal) => Promise<boolean>
  /** Mark all visible notifications as read for the current user. */
  markAllRead: (signal?: AbortSignal) => Promise<boolean>
  /** Dismiss a single notification for the current user. */
  dismiss: (id: string, signal?: AbortSignal) => Promise<boolean>
  /** Dismiss all read notifications for the current user. */
  dismissAllRead: (signal?: AbortSignal) => Promise<boolean>
  /** Abort any in-flight requests managed by this hook. */
  abort: () => void
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useInbox(): UseInboxReturn {
  const controllerRef = useRef<AbortController>(undefined)

  /**
   * Create a fresh AbortController linked to the hook's internal ref.
   * If a signal is provided by the caller, we use that instead.
   */
  const getSignal = useCallback((externalSignal?: AbortSignal): AbortSignal => {
    if (externalSignal) return externalSignal
    // Abort any previous in-flight request
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    return controller.signal
  }, [])

  const fetchInbox = useCallback(
    async (params: FetchInboxParams, signal?: AbortSignal): Promise<InboxResponse> => {
      const effectiveSignal = getSignal(signal)
      const queryParams: Record<string, string | number | boolean> = {}
      if (params.limit != null) queryParams.limit = params.limit
      if (params.offset != null) queryParams.offset = params.offset
      if (params.unread_only) queryParams.unread_only = true
      if (params.category) queryParams.category = params.category
      if (params.severity) queryParams.severity = params.severity

      const res = await apiClient.get<InboxResponse>('/notifications/inbox', {
        params: queryParams,
        signal: effectiveSignal,
      })
      return {
        items: res.data?.items ?? [],
        total: res.data?.total ?? 0,
        unread_count: res.data?.unread_count ?? 0,
      }
    },
    [getSignal],
  )

  const markRead = useCallback(
    async (id: string, signal?: AbortSignal): Promise<boolean> => {
      const effectiveSignal = getSignal(signal)
      try {
        await apiClient.post(`/notifications/inbox/${id}/read`, null, {
          signal: effectiveSignal,
        })
        return true
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return false
        return false
      }
    },
    [getSignal],
  )

  const markAllRead = useCallback(
    async (signal?: AbortSignal): Promise<boolean> => {
      const effectiveSignal = getSignal(signal)
      try {
        await apiClient.post('/notifications/inbox/mark-all-read', null, {
          signal: effectiveSignal,
        })
        return true
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return false
        return false
      }
    },
    [getSignal],
  )

  const dismiss = useCallback(
    async (id: string, signal?: AbortSignal): Promise<boolean> => {
      const effectiveSignal = getSignal(signal)
      try {
        await apiClient.post(`/notifications/inbox/${id}/dismiss`, null, {
          signal: effectiveSignal,
        })
        return true
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return false
        return false
      }
    },
    [getSignal],
  )

  const dismissAllRead = useCallback(
    async (signal?: AbortSignal): Promise<boolean> => {
      const effectiveSignal = getSignal(signal)
      try {
        await apiClient.post('/notifications/inbox/dismiss-all-read', null, {
          signal: effectiveSignal,
        })
        return true
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return false
        return false
      }
    },
    [getSignal],
  )

  const abort = useCallback(() => {
    controllerRef.current?.abort()
  }, [])

  return {
    fetchInbox,
    markRead,
    markAllRead,
    dismiss,
    dismissAllRead,
    abort,
  }
}

export default useInbox
