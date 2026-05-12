/**
 * useAutoSave — auto-save hook for the visual page editor.
 *
 * Periodically sends the current Puck_Data draft to the backend while the
 * document is dirty. Designed around the following rules from the design doc:
 *
 *   1. Auto-save fires every `intervalMs` (default 30 s) while `isDirty`
 *      and not `paused`.
 *   2. A save is skipped if a save is already in-flight (prevents request
 *      pile-up if the network is slow).
 *   3. `paused` takes priority — used by the parent to suspend auto-save
 *      while a manual "Save Draft" request is in-flight so the manual save
 *      is never racing with an auto-save for the same pageKey.
 *   4. A 409 response means another editor session saved a newer draft.
 *      The hook calls `onConflict` so the parent can show DraftConflictBanner.
 *   5. The backend refreshes the Redis editor lock on every successful
 *      `save_draft` call — nothing extra for the frontend to do.
 *
 * Requirements: 3.7, 3.12
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import apiClient from '../../../api/client'

export interface UseAutoSaveOptions {
  /** Page key to save under — e.g. "landing" or a UUID for editor-created pages. */
  pageKey: string
  /** Current Puck_Data content. Most recent value is used at save time. */
  content: Record<string, unknown> | null
  /** True when content has changed since the last successful save. */
  isDirty: boolean
  /** Auto-save interval in milliseconds. Defaults to 30 000 (30 s). */
  intervalMs?: number
  /** Called after a successful auto-save or manual `saveNow()`. */
  onSaved?: () => void
  /** Called when the server returns HTTP 409 (draft conflict). */
  onConflict?: () => void
  /** Called on any other save error (network, 4xx, 5xx). */
  onError?: (error: unknown) => void
  /** When true, auto-save is paused (e.g. while manual save is in-flight). */
  paused?: boolean
}

export interface UseAutoSaveReturn {
  /** True while a save request is in-flight (auto or manual). */
  autoSaving: boolean
  /** Timestamp of the last successful save, or null if none yet. */
  lastSavedAt: Date | null
  /**
   * Manually trigger a save. Used by the toolbar "Save Draft" button.
   * Resolves when the save completes (success or handled error). Never rejects.
   */
  saveNow: () => Promise<void>
}

/**
 * Shape of an axios error we care about — kept local to avoid pulling axios
 * types into the hook's public surface.
 */
interface AxiosErrorLike {
  name?: string
  code?: string
  response?: { status?: number }
}

function getErrorStatus(err: unknown): number | undefined {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as AxiosErrorLike).response
    if (response && typeof response.status === 'number') return response.status
  }
  return undefined
}

function isAbortError(err: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true
  if (!err || typeof err !== 'object') return false
  const { name, code } = err as AxiosErrorLike
  return name === 'CanceledError' || name === 'AbortError' || code === 'ERR_CANCELED'
}

export function useAutoSave(options: UseAutoSaveOptions): UseAutoSaveReturn {
  const {
    pageKey,
    content,
    isDirty,
    intervalMs = 30_000,
    onSaved,
    onConflict,
    onError,
    paused = false,
  } = options

  const [autoSaving, setAutoSaving] = useState(false)
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null)

  // Latest content/flags held in refs so the interval closure always sees
  // current values without resetting the timer on every content change.
  const latestContentRef = useRef<Record<string, unknown> | null>(content)
  const isDirtyRef = useRef(isDirty)
  const pausedRef = useRef(paused)
  const savingRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  // Callbacks held in refs so consumers may pass inline functions without
  // causing the effect to re-subscribe and restart the timer.
  const onSavedRef = useRef(onSaved)
  const onConflictRef = useRef(onConflict)
  const onErrorRef = useRef(onError)

  useEffect(() => {
    latestContentRef.current = content
  }, [content])

  useEffect(() => {
    isDirtyRef.current = isDirty
  }, [isDirty])

  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  useEffect(() => {
    onSavedRef.current = onSaved
    onConflictRef.current = onConflict
    onErrorRef.current = onError
  }, [onSaved, onConflict, onError])

  const doSave = useCallback(async (): Promise<void> => {
    // Single-flight: skip if a save is already in-flight.
    if (savingRef.current) return

    const currentContent = latestContentRef.current
    if (!currentContent) return

    const controller = new AbortController()
    abortRef.current = controller
    savingRef.current = true
    setAutoSaving(true)

    try {
      await apiClient.put(
        `/api/v2/admin/page-editor/pages/${encodeURIComponent(pageKey)}/draft`,
        { content: currentContent },
        { signal: controller.signal },
      )
      setLastSavedAt(new Date())
      onSavedRef.current?.()
    } catch (err) {
      if (isAbortError(err, controller.signal)) return
      const status = getErrorStatus(err)
      if (status === 409) {
        onConflictRef.current?.()
      } else {
        onErrorRef.current?.(err)
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
      }
      savingRef.current = false
      setAutoSaving(false)
    }
  }, [pageKey])

  // Auto-save interval. Only active when dirty and not paused.
  useEffect(() => {
    if (!isDirty || paused) return

    const interval = window.setInterval(() => {
      if (savingRef.current) return
      if (!isDirtyRef.current || pausedRef.current) return
      void doSave()
    }, intervalMs)

    return () => {
      window.clearInterval(interval)
    }
  }, [isDirty, paused, intervalMs, doSave])

  // Abort any in-flight auto-save when the hook unmounts.
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const saveNow = useCallback((): Promise<void> => doSave(), [doSave])

  return {
    autoSaving,
    lastSavedAt,
    saveNow,
  }
}

export default useAutoSave
