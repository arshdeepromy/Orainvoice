import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Page,
  List,
  ListItem,
  Block,
  Preloader,
  Card,
  Segmented,
  SegmentedButton,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import HapticButton from '@/components/konsta/HapticButton'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface TimeEntry {
  id: string
  job_id: string | null
  job_title: string | null
  clock_in: string
  clock_out: string | null
  duration_minutes: number | null
  notes: string | null
}

type TimesheetTab = 'daily' | 'weekly'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTime(dateStr: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleTimeString('en-NZ', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr
  }
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', { weekday: 'short', day: 'numeric', month: 'short' })
  } catch {
    return dateStr
  }
}

function formatDuration(minutes: number | null): string {
  if (minutes === null || minutes === undefined) return '—'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}m`
  return `${h}h ${m}m`
}

function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}`
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function TimeTrackingContent() {
  const [activeTab, setActiveTab] = useState<TimesheetTab>('daily')
  const [isClockedIn, setIsClockedIn] = useState(false)
  const [isClockLoading, setIsClockLoading] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [timerInterval, setTimerInterval] = useState<ReturnType<typeof setInterval> | null>(null)
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null)

  const [entries, setEntries] = useState<TimeEntry[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchEntries = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<{ items?: TimeEntry[]; total?: number }>(
          '/api/v2/time-entries',
          { params: { offset: 0, limit: 50 }, signal },
        )
        setEntries(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load time entries')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchEntries(false, controller.signal)
    return () => controller.abort()
  }, [fetchEntries])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchEntries(true, controller.signal)
  }, [fetchEntries])

  const startTimer = useCallback(() => {
    const startTime = Date.now()
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startTime) / 1000))
    }, 1000)
    setTimerInterval(interval)
  }, [])

  const stopTimer = useCallback(() => {
    if (timerInterval) {
      clearInterval(timerInterval)
      setTimerInterval(null)
    }
    setElapsedSeconds(0)
  }, [timerInterval])

  const handleClockIn = useCallback(async () => {
    setIsClockLoading(true)
    try {
      const res = await apiClient.post<{ id?: string }>('/api/v2/time-entries', {
        clock_in: new Date().toISOString(),
      })
      setActiveEntryId(res.data?.id ?? null)
      setIsClockedIn(true)
      startTimer()
    } catch {
      // Error handled silently
    } finally {
      setIsClockLoading(false)
    }
  }, [startTimer])

  const handleClockOut = useCallback(async () => {
    setIsClockLoading(true)
    try {
      if (activeEntryId) {
        await apiClient.patch(`/api/v2/time-entries/${activeEntryId}`, {
          clock_out: new Date().toISOString(),
        })
      }
      setIsClockedIn(false)
      setActiveEntryId(null)
      stopTimer()
      await handleRefresh()
    } catch {
      // Error handled silently
    } finally {
      setIsClockLoading(false)
    }
  }, [activeEntryId, stopTimer, handleRefresh])

  const totalMinutes = entries.reduce((sum, e) => sum + (e.duration_minutes ?? 0), 0)

  if (isLoading && entries.length === 0) {
    return (
      <Page data-testid="time-tracking-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="time-tracking-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Clock In/Out Card */}
          <Block>
            <Card data-testid="clock-card">
              <div className="flex flex-col items-center gap-4 p-4">
                {isClockedIn && (
                  <div className="text-center">
                    <p className="text-sm text-gray-500 dark:text-gray-400">Clocked in</p>
                    <p className="text-3xl font-bold tabular-nums text-blue-600 dark:text-blue-400" data-testid="timer-display">
                      {formatElapsed(elapsedSeconds)}
                    </p>
                  </div>
                )}
                <HapticButton
                  large
                  className={isClockedIn ? 'k-color-red' : 'k-color-primary'}
                  onClick={isClockedIn ? handleClockOut : handleClockIn}
                  hapticStyle={isClockedIn ? 'heavy' : 'medium'}
                  data-testid="clock-button"
                >
                  {isClockLoading ? 'Loading…' : isClockedIn ? 'Clock Out' : 'Clock In'}
                </HapticButton>
              </div>
            </Card>
          </Block>

          {/* Total Hours */}
          <Block>
            <Card data-testid="total-hours-card">
              <div className="flex items-center justify-between p-4">
                <span className="text-sm text-gray-500 dark:text-gray-400">Total Hours</span>
                <span className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  {formatDuration(totalMinutes)}
                </span>
              </div>
            </Card>
          </Block>

          {/* Tabs */}
          <Block className="!mb-0">
            <Segmented strong>
              <SegmentedButton active={activeTab === 'daily'} onClick={() => setActiveTab('daily')} data-testid="tab-daily">
                Today
              </SegmentedButton>
              <SegmentedButton active={activeTab === 'weekly'} onClick={() => setActiveTab('weekly')} data-testid="tab-weekly">
                This Week
              </SegmentedButton>
            </Segmented>
          </Block>

          {/* Entries List */}
          {error && (
            <Block>
              <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
                {error}
              </div>
            </Block>
          )}

          {entries.length === 0 ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">No time entries</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="time-entries-list">
              {entries.map((entry) => (
                <ListItem
                  key={entry.id}
                  title={
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {entry.job_title ?? 'General'}
                    </span>
                  }
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {formatDate(entry.clock_in)} · {formatTime(entry.clock_in)}
                      {entry.clock_out ? ` – ${formatTime(entry.clock_out)}` : ' – In progress'}
                    </span>
                  }
                  after={
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {formatDuration(entry.duration_minutes)}
                    </span>
                  }
                  data-testid={`time-entry-${entry.id}`}
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}

/**
 * Time Tracking screen — clock-in/out buttons, entries list.
 * ModuleGate `time_tracking`.
 *
 * Requirements: 36.1, 36.2, 55.1
 */
export default function TimeTrackingScreen() {
  return (
    <ModuleGate moduleSlug="time_tracking">
      <TimeTrackingContent />
    </ModuleGate>
  )
}
