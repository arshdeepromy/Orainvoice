import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  Card,
  Button,
  Preloader,
} from 'konsta/react'
import type { Job } from '@shared/types/job'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import HapticButton from '@/components/konsta/HapticButton'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { useHaptics } from '@/hooks/useHaptics'
import { useGeolocation } from '@/hooks/useGeolocation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface ActiveJob extends Job {
  timer_started_at?: string | null
  timer_running?: boolean
}

/* ------------------------------------------------------------------ */
/* Timer display helper                                               */
/* ------------------------------------------------------------------ */

function formatTimer(startedAt: string | null | undefined): string {
  if (!startedAt) return '00:00:00'
  const start = new Date(startedAt).getTime()
  const now = Date.now()
  const diff = Math.max(0, Math.floor((now - start) / 1000))
  const h = Math.floor(diff / 3600)
  const m = Math.floor((diff % 3600) / 60)
  const s = diff % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/* ------------------------------------------------------------------ */
/* Exported helpers for testing                                       */
/* ------------------------------------------------------------------ */

export { formatTimer }

/**
 * Convert raw Job API data to BoardJob items for backward compatibility.
 */
export interface BoardJob {
  id: string
  columnId: string
  title: string
  customerName: string
  assignedStaffName: string | null
}

export function jobsToBoardItems(jobs: Job[]): BoardJob[] {
  return jobs.map((job) => ({
    id: job.id,
    columnId: job.status ?? 'pending',
    title: job.title ?? 'Untitled Job',
    customerName: job.customer_name ?? 'Unknown',
    assignedStaffName: job.assigned_staff_name ?? null,
  }))
}

export async function startTimer(
  jobId: string,
  geo: { lat: number; lng: number } | null,
): Promise<boolean> {
  try {
    await apiClient.post(`/api/v1/job-cards/${jobId}/start-timer`, {
      latitude: geo?.lat,
      longitude: geo?.lng,
    })
    return true
  } catch {
    return false
  }
}

export async function stopTimer(jobId: string): Promise<boolean> {
  try {
    await apiClient.post(`/api/v1/job-cards/${jobId}/stop-timer`)
    return true
  } catch {
    return false
  }
}

export async function updateJobStatus(
  jobId: string,
  newStatus: string,
): Promise<boolean> {
  try {
    await apiClient.patch(`/api/v2/jobs/${jobId}`, { status: newStatus })
    return true
  } catch {
    return false
  }
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Active Jobs Board — card-based view of in-progress and open jobs.
 * Each card: customer, vehicle, live timer (HH:MM:SS).
 * Buttons: Start/Stop Timer, Assign to Me, Confirm Done.
 * Timer start calls POST /job-cards/:id/start-timer + optional GPS.
 * Timer stop calls POST /job-cards/:id/stop-timer.
 * Haptics on timer start/stop.
 *
 * Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7, 51.1, 51.4
 */
export default function JobBoardScreen() {
  const navigate = useNavigate()
  const haptics = useHaptics()
  const { getCurrentPosition } = useGeolocation()
  const { user } = useAuth()

  const [jobs, setJobs] = useState<ActiveJob[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [, setTimerTick] = useState(0)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})

  const abortRef = useRef<AbortController | null>(null)

  // ── Fetch jobs ─────────────────────────────────────────────────────
  const fetchJobs = useCallback(
    async (signal: AbortSignal, refresh = false) => {
      if (refresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<{ items?: ActiveJob[]; jobs?: ActiveJob[]; total?: number }>(
          '/api/v2/jobs',
          { params: { limit: 100 }, signal },
        )
        const allJobs = res.data?.items ?? res.data?.jobs ?? []
        // Show only in_progress and pending/open jobs
        const activeJobs = allJobs.filter(
          (j) => j.status === 'in_progress' || j.status === 'pending',
        )
        setJobs(activeJobs)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load jobs')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [],
  )

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchJobs(controller.signal)
    return () => controller.abort()
  }, [fetchJobs])

  // ── Live timer tick (every second) ─────────────────────────────────
  useEffect(() => {
    const hasRunningTimer = jobs.some((j) => j.timer_running)
    if (!hasRunningTimer) return

    const interval = setInterval(() => {
      setTimerTick((t) => t + 1)
    }, 1000)
    return () => clearInterval(interval)
  }, [jobs])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchJobs(controller.signal, true)
  }, [fetchJobs])

  // ── Timer actions ──────────────────────────────────────────────────
  const handleStartTimer = useCallback(
    async (jobId: string) => {
      setActionLoading((prev) => ({ ...prev, [jobId]: true }))
      void haptics.medium()
      // Get GPS silently — non-blocking
      const geo = await getCurrentPosition()
      const ok = await startTimer(jobId, geo)
      if (ok) await handleRefresh()
      setActionLoading((prev) => ({ ...prev, [jobId]: false }))
    },
    [haptics, getCurrentPosition, handleRefresh],
  )

  const handleStopTimer = useCallback(
    async (jobId: string) => {
      setActionLoading((prev) => ({ ...prev, [jobId]: true }))
      void haptics.medium()
      const ok = await stopTimer(jobId)
      if (ok) await handleRefresh()
      setActionLoading((prev) => ({ ...prev, [jobId]: false }))
    },
    [haptics, handleRefresh],
  )

  const handleAssignToMe = useCallback(
    async (jobId: string) => {
      setActionLoading((prev) => ({ ...prev, [jobId]: true }))
      try {
        await apiClient.patch(`/api/v2/jobs/${jobId}`, {
          assigned_staff_id: user?.id,
        })
        await handleRefresh()
      } catch {
        // Silently fail
      }
      setActionLoading((prev) => ({ ...prev, [jobId]: false }))
    },
    [user?.id, handleRefresh],
  )

  const handleConfirmDone = useCallback(
    async (jobId: string) => {
      setActionLoading((prev) => ({ ...prev, [jobId]: true }))
      void haptics.heavy()
      await updateJobStatus(jobId, 'completed')
      await handleRefresh()
      setActionLoading((prev) => ({ ...prev, [jobId]: false }))
    },
    [haptics, handleRefresh],
  )

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading && jobs.length === 0) {
    return (
      <ModuleGate moduleSlug="jobs">
        <Page data-testid="job-board-page">
          <KonstaNavbar title="Active Jobs" />
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  return (
    <ModuleGate moduleSlug="jobs">
      <Page data-testid="job-board-page">
        <KonstaNavbar
          title="Active Jobs"
          rightActions={
            <Button
              onClick={() => navigate('/job-cards')}
              clear
              small
              className="text-primary"
            >
              List View
            </Button>
          }
        />

        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col gap-3 px-4 pb-24 pt-2">
            {/* Error */}
            {error && (
              <div
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              >
                {error}
                <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">
                  Retry
                </button>
              </div>
            )}

            {/* Empty state */}
            {jobs.length === 0 && !isLoading && (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">No active jobs</p>
              </Block>
            )}

            {/* ── Job Cards ─────────────────────────────────────────── */}
            {jobs.map((job) => {
              const isRunning = job.timer_running
              const loading = actionLoading[job.id] ?? false

              return (
                <Card
                  key={job.id}
                  className="overflow-hidden"
                  data-testid={`job-board-card-${job.id}`}
                >
                  {/* Header */}
                  <div
                    className="cursor-pointer"
                    onClick={() => navigate(`/jobs/${job.id}`)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1">
                        <p className="font-bold text-gray-900 dark:text-gray-100">
                          {job.customer_name ?? 'Unknown'}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {job.title ?? 'Untitled Job'}
                        </p>
                        {job.assigned_staff_name && (
                          <p className="text-xs text-gray-400 dark:text-gray-500">
                            Assigned: {job.assigned_staff_name}
                          </p>
                        )}
                      </div>
                      <StatusBadge status={job.status} size="sm" />
                    </div>
                  </div>

                  {/* Timer display */}
                  <div className="mt-3 flex items-center justify-center rounded-lg bg-gray-50 py-3 dark:bg-gray-800">
                    <span
                      className={`font-mono text-2xl font-bold tabular-nums ${
                        isRunning
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-gray-400 dark:text-gray-500'
                      }`}
                      data-testid={`timer-display-${job.id}`}
                    >
                      {/* Force re-render on timerTick */}
                      {isRunning ? formatTimer(job.timer_started_at) : '00:00:00'}
                    </span>
                  </div>

                  {/* Action buttons */}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {isRunning ? (
                      <HapticButton
                        hapticStyle="medium"
                        small
                        onClick={() => handleStopTimer(job.id)}
                        disabled={loading}
                        colors={{
                          fillBgIos: 'bg-red-600',
                          fillBgMaterial: 'bg-red-600',
                          fillTextIos: 'text-white',
                          fillTextMaterial: 'text-white',
                        }}
                        className="flex-1"
                      >
                        Stop Timer
                      </HapticButton>
                    ) : (
                      <HapticButton
                        hapticStyle="medium"
                        small
                        onClick={() => handleStartTimer(job.id)}
                        disabled={loading}
                        colors={{
                          fillBgIos: 'bg-green-600',
                          fillBgMaterial: 'bg-green-600',
                          fillTextIos: 'text-white',
                          fillTextMaterial: 'text-white',
                        }}
                        className="flex-1"
                      >
                        Start Timer
                      </HapticButton>
                    )}
                    <Button
                      small
                      outline
                      onClick={() => handleAssignToMe(job.id)}
                      disabled={loading}
                      className="flex-1"
                    >
                      Assign to Me
                    </Button>
                    <HapticButton
                      hapticStyle="heavy"
                      small
                      outline
                      onClick={() => handleConfirmDone(job.id)}
                      disabled={loading}
                      className="flex-1"
                    >
                      Done
                    </HapticButton>
                  </div>
                </Card>
              )
            })}
          </div>
        </PullRefresh>
      </Page>
    </ModuleGate>
  )
}
