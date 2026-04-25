import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '@/api/client'

export interface UseTimerOptions {
  /** Job ID to track time for */
  jobId: string
}

export interface UseTimerResult {
  /** Whether the timer is currently running */
  isRunning: boolean
  /** Elapsed time in seconds since timer started */
  elapsedSeconds: number
  /** Start the timer (creates a time entry via API) */
  start: () => Promise<void>
  /** Stop the timer (closes the time entry via API) */
  stop: () => Promise<void>
  /** Whether a start/stop API call is in progress */
  isLoading: boolean
  /** Error message from the last API call */
  error: string | null
}

/**
 * Format elapsed seconds into HH:MM:SS display string.
 * Exported for testing.
 */
export function formatElapsedTime(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

/**
 * Job time tracking timer hook with start/stop, elapsed time display,
 * and API integration.
 *
 * Requirements: 10.4
 */
export function useTimer({ jobId }: UseTimerOptions): UseTimerResult {
  const [isRunning, setIsRunning] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [timeEntryId, setTimeEntryId] = useState<string | null>(null)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number | null>(null)

  // Tick the elapsed time every second while running
  useEffect(() => {
    if (isRunning) {
      startTimeRef.current = Date.now() - elapsedSeconds * 1000
      intervalRef.current = setInterval(() => {
        if (startTimeRef.current !== null) {
          const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000)
          setElapsedSeconds(elapsed)
        }
      }, 1000)
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
    // Only re-run when isRunning changes, not on every elapsedSeconds change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunning])

  const start = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const res = await apiClient.post<{ id?: string }>(
        `/api/v2/time-entries/timer/start`,
        { job_id: jobId },
      )
      const entryId = res.data?.id ?? null
      setTimeEntryId(entryId)
      setElapsedSeconds(0)
      startTimeRef.current = Date.now()
      setIsRunning(true)
    } catch {
      setError('Failed to start timer')
    } finally {
      setIsLoading(false)
    }
  }, [jobId])

  const stop = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      if (timeEntryId) {
        await apiClient.post(`/api/v2/time-entries/timer/stop`, {})
      }
      setIsRunning(false)
      setTimeEntryId(null)
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    } catch {
      setError('Failed to stop timer')
    } finally {
      setIsLoading(false)
    }
  }, [timeEntryId])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [])

  return {
    isRunning,
    elapsedSeconds,
    start,
    stop,
    isLoading,
    error,
  }
}
