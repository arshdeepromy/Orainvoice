/**
 * JobTimer — live timer component for a job card.
 *
 * Displays elapsed time for an active timer, total accumulated time,
 * and Start/Stop controls subject to role-based visibility rules.
 *
 * Pure helpers `formatElapsedTime` and `calculateAccumulatedMinutes` are
 * exported for property-based testing (Task 9.2).
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { Button, Spinner, useToast, ToastContainer } from '@/components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface JobTimerProps {
  jobCardId: string
  assignedTo: string | null
  assignedToName: string | null
  status: 'open' | 'in_progress' | 'completed' | 'invoiced'
  onStatusChange: () => void
}

export interface TimeEntry {
  id: string
  started_at: string
  stopped_at: string | null
  duration_minutes: number | null
}

interface TimerResponse {
  entries: TimeEntry[]
  is_active: boolean
}

/* ------------------------------------------------------------------ */
/*  Pure helpers (exported for property tests)                         */
/* ------------------------------------------------------------------ */

/**
 * Format elapsed seconds into HH:MM:SS display string.
 * Accepts the difference in milliseconds between `now` and `startedAt`.
 */
export function formatElapsedTime(startedAtIso: string, now: Date): string {
  const elapsedMs = now.getTime() - new Date(startedAtIso).getTime()
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000))
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/**
 * Calculate total accumulated minutes from completed time entries.
 * Only entries with a non-null `duration_minutes` are summed.
 */
export function calculateAccumulatedMinutes(entries: TimeEntry[]): number {
  return entries.reduce((sum, e) => {
    if (e.stopped_at != null && e.duration_minutes != null) {
      return sum + e.duration_minutes
    }
    return sum
  }, 0)
}

/** Format total minutes as "Xh Ym" display string. */
function formatTotalTime(totalMinutes: number): string {
  if (totalMinutes <= 0) return '0m'
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function JobTimer({
  jobCardId,
  assignedTo,
  assignedToName,
  status,
  onStatusChange,
}: JobTimerProps) {
  const { user, isOrgAdmin } = useAuth()
  const { toasts, addToast, dismissToast } = useToast()

  const [entries, setEntries] = useState<TimeEntry[]>([])
  const [isActive, setIsActive] = useState(false)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [elapsed, setElapsed] = useState('00:00:00')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  /* ---- Determine role-based access ---- */
  const currentUserId = user?.id ?? null
  const isAssigned = assignedTo != null && currentUserId === assignedTo
  const canControl = isOrgAdmin || isAssigned
  const isJobActive = status === 'open' || status === 'in_progress'

  /* ---- Fetch timer state ---- */
  const fetchTimer = useCallback(async () => {
    try {
      const res = await apiClient.get<TimerResponse>(
        `/job-cards/${jobCardId}/timer`,
      )
      setEntries(res.data?.entries ?? [])
      setIsActive(res.data?.is_active ?? false)
    } catch {
      // Silently handle — timer section will show empty state
    } finally {
      setLoading(false)
    }
  }, [jobCardId])

  useEffect(() => {
    fetchTimer()
  }, [fetchTimer])

  /* ---- Re-fetch on visibility change (tab wake) ---- */
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        fetchTimer()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [fetchTimer])

  /* ---- Live elapsed counter ---- */
  const activeEntry = entries.find((e) => e.stopped_at == null)

  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    if (isActive && activeEntry) {
      const tick = () => setElapsed(formatElapsedTime(activeEntry.started_at, new Date()))
      tick()
      intervalRef.current = setInterval(tick, 1000)
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current)
      }
    } else {
      setElapsed('00:00:00')
    }
  }, [isActive, activeEntry])

  /* ---- Actions ---- */
  const handleStart = async () => {
    setActionLoading(true)
    try {
      await apiClient.post(`/job-cards/${jobCardId}/timer/start`)
      addToast('success', 'Timer started')
      await fetchTimer()
      onStatusChange()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to start timer')
    } finally {
      setActionLoading(false)
    }
  }

  const handleStop = async () => {
    setActionLoading(true)
    try {
      await apiClient.post(`/job-cards/${jobCardId}/timer/stop`)
      addToast('success', 'Timer stopped')
      await fetchTimer()
      onStatusChange()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to stop timer')
    } finally {
      setActionLoading(false)
    }
  }

  const handleAssignToMe = async () => {
    if (!currentUserId) return
    setActionLoading(true)
    try {
      await apiClient.put(`/job-cards/${jobCardId}/assign`, {
        new_assignee_id: currentUserId,
      })
      addToast('success', 'Job assigned to you')
      onStatusChange()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast('error', detail ?? 'Failed to assign job')
    } finally {
      setActionLoading(false)
    }
  }

  /* ---- Accumulated time ---- */
  const totalMinutes = calculateAccumulatedMinutes(entries)

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2" role="status" aria-label="Loading timer">
        <Spinner size="sm" />
        <span className="text-sm text-gray-500">Loading timer…</span>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-3" data-testid="job-timer">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Elapsed / accumulated display */}
      <div className="flex items-center gap-4 mb-2">
        {isActive && activeEntry && (
          <div className="flex items-center gap-2">
            <span
              className="text-lg font-mono font-semibold text-green-700"
              aria-live="polite"
              aria-label="Elapsed time"
              data-testid="elapsed-time"
            >
              {elapsed}
            </span>
            <span className="inline-block h-2 w-2 rounded-full bg-green-500 animate-pulse" aria-hidden="true" />
          </div>
        )}
        {totalMinutes > 0 && (
          <span className="text-sm text-gray-600" data-testid="total-time">
            Total: {formatTotalTime(totalMinutes)}
          </span>
        )}
      </div>

      {/* Controls — role-based */}
      {canControl && isJobActive && (
        <div className="flex items-center gap-2">
          {isActive ? (
            <Button
              size="sm"
              variant="danger"
              onClick={handleStop}
              loading={actionLoading}
              disabled={actionLoading}
              data-testid="stop-timer-btn"
            >
              Stop Timer
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              onClick={handleStart}
              loading={actionLoading}
              disabled={actionLoading}
              data-testid="start-timer-btn"
            >
              Start Timer
            </Button>
          )}
        </div>
      )}

      {/* Non-admin, not assigned — job is assigned to someone else */}
      {!isOrgAdmin && !isAssigned && assignedTo != null && isJobActive && (
        <div className="text-sm text-gray-600" data-testid="assigned-message">
          <p className="mb-1">
            This job is assigned to {assignedToName ?? 'another staff member'}.
            Assign it to yourself to start working.
          </p>
          <Button
            size="sm"
            variant="secondary"
            onClick={onStatusChange}
            data-testid="take-over-btn"
          >
            Take Over Job
          </Button>
        </div>
      )}

      {/* Non-admin, unassigned job */}
      {!isOrgAdmin && assignedTo == null && isJobActive && (
        <div className="text-sm text-gray-600" data-testid="unassigned-message">
          <p className="mb-1">
            This job is not assigned. Assign it to yourself to start working.
          </p>
          <Button
            size="sm"
            variant="primary"
            onClick={handleAssignToMe}
            loading={actionLoading}
            disabled={actionLoading}
            data-testid="assign-to-me-btn"
          >
            Assign to Me
          </Button>
        </div>
      )}

      {/* Completed/invoiced — read-only */}
      {!isJobActive && totalMinutes === 0 && !isActive && (
        <p className="text-sm text-gray-500">No time recorded.</p>
      )}
    </div>
  )
}
