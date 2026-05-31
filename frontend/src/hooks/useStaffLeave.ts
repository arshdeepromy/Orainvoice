/**
 * useStaffLeave — single source of truth for the per-staff Leave tab.
 *
 * Fetches balances + ledger + requests for one staff member in
 * parallel and exposes a unified `loading` / `error` / `refresh()`
 * surface. Every fetch respects an `AbortController` so unmounts and
 * StrictMode double-mounts don't leak in-flight requests
 * (`.kiro/steering/safe-api-consumption.md` Pattern 7).
 *
 * Returned arrays are guaranteed to be arrays (never `undefined`) so
 * callers can `.map()` directly without per-render guards.
 *
 * **Validates: Staff Management Phase 2 task D9**
 *
 * Usage:
 *
 *   const { balances, ledger, requests, loading, error, refresh } =
 *     useStaffLeave(staffId)
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import {
  listStaffBalances,
  listStaffLedger,
  listStaffRequests,
  type LeaveBalance,
  type LeaveLedgerEntry,
  type LeaveRequest,
} from '../api/leave'

export interface UseStaffLeaveResult {
  balances: LeaveBalance[]
  ledger: LeaveLedgerEntry[]
  requests: LeaveRequest[]
  loading: boolean
  error: string | null
  /** Re-run all three fetches; aborts any in-flight previous calls. */
  refresh: () => void
}

/**
 * Pull a friendly error message out of an Axios error envelope. Falls
 * back to the raw `error.message` and finally to a static string so
 * the UI never renders `[object Object]`.
 */
function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'detail' in detail) {
      const inner = (detail as { detail?: unknown }).detail
      if (typeof inner === 'string') return inner
    }
    if (err.message) return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return 'Failed to load leave data'
}

/** True if an axios error was caused by `AbortController.abort()`. */
function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

export default function useStaffLeave(staffId: string): UseStaffLeaveResult {
  const [balances, setBalances] = useState<LeaveBalance[]>([])
  const [ledger, setLedger] = useState<LeaveLedgerEntry[]>([])
  const [requests, setRequests] = useState<LeaveRequest[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  /**
   * Bumped by `refresh()` so the fetching effect re-runs. We use a
   * counter (rather than a timestamp) to avoid coalescing
   * back-to-back refresh calls into a single value.
   */
  const [refreshKey, setRefreshKey] = useState<number>(0)

  const refresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  useEffect(() => {
    if (!staffId) {
      setBalances([])
      setLedger([])
      setRequests([])
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    let cancelled = false

    const run = async () => {
      setLoading(true)
      setError(null)
      try {
        const [balRes, ledRes, reqRes] = await Promise.all([
          listStaffBalances(staffId, controller.signal),
          listStaffLedger(staffId, { limit: 100 }, controller.signal),
          listStaffRequests(staffId, { limit: 100 }, controller.signal),
        ])
        if (cancelled || controller.signal.aborted) return
        setBalances(balRes.items ?? [])
        setLedger(ledRes.items ?? [])
        setRequests(reqRes.items ?? [])
      } catch (err) {
        if (cancelled || controller.signal.aborted || isAbortError(err)) {
          return
        }
        setError(extractErrorMessage(err))
      } finally {
        if (!cancelled && !controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    void run()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [staffId, refreshKey])

  return useMemo<UseStaffLeaveResult>(
    () => ({ balances, ledger, requests, loading, error, refresh }),
    [balances, ledger, requests, loading, error, refresh],
  )
}
