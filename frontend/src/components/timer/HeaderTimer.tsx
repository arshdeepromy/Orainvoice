/**
 * Enhanced timer component for the app header.
 *
 * V2 features:
 * - Project/task selection before starting timer
 * - Task switching without stopping timer (automatic split entries)
 * - Displays active project/task context
 *
 * Validates: Requirements 7.1, 7.2
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'

const STORAGE_KEY = 'orainvoice_active_timer'

interface TimerState {
  entryId: string
  startTime: string
  description: string | null
  projectId: string | null
  projectName: string | null
  jobId: string | null
  jobName: string | null
}

interface ProjectOption {
  id: string
  name: string
}

interface JobOption {
  id: string
  title: string
}

function formatElapsed(startIso: string): string {
  const elapsed = Math.floor((Date.now() - new Date(startIso).getTime()) / 1000)
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function HeaderTimer() {
  const projectLabel = useTerm('project', 'Project')
  const jobLabel = useTerm('job', 'Job')
  const timeTrackingEnabled = useFlag('time_tracking_v2')

  const [timer, setTimer] = useState<TimerState | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      return stored ? JSON.parse(stored) : null
    } catch {
      return null
    }
  })
  const [display, setDisplay] = useState('00:00:00')
  const [loading, setLoading] = useState(false)
  const [showSelector, setShowSelector] = useState(false)
  const [projects, setProjects] = useState<ProjectOption[]>([])
  const [jobs, setJobs] = useState<JobOption[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string>('')
  const [selectedJobId, setSelectedJobId] = useState<string>('')
  const [description, setDescription] = useState('')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Persist timer state to localStorage
  useEffect(() => {
    if (timer) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(timer))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [timer])

  // Tick the display every second when timer is active
  useEffect(() => {
    if (timer) {
      const tick = () => setDisplay(formatElapsed(timer.startTime))
      tick()
      intervalRef.current = setInterval(tick, 1000)
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current)
      }
    } else {
      setDisplay('00:00:00')
    }
  }, [timer])

  // Sync with backend on mount
  useEffect(() => {
    const syncTimer = async () => {
      try {
        const res = await apiClient.get('/api/v2/time-entries/timer/active')
        if (res.data) {
          setTimer({
            entryId: res.data.id,
            startTime: res.data.start_time,
            description: res.data.description,
            projectId: res.data.project_id,
            projectName: null,
            jobId: res.data.job_id,
            jobName: null,
          })
        } else {
          setTimer(null)
        }
      } catch {
        // Keep local state if backend unavailable
      }
    }
    syncTimer()
  }, [])

  // Fetch projects and jobs for the selector
  const fetchOptions = useCallback(async () => {
    try {
      const [projRes, jobRes] = await Promise.all([
        apiClient.get('/api/v2/projects', { params: { page_size: 100 } }),
        apiClient.get('/api/v2/jobs', { params: { page_size: 100 } }),
      ])
      setProjects(
        (projRes.data.projects ?? projRes.data.items ?? []).map((p: any) => ({
          id: p.id,
          name: p.name ?? p.title ?? 'Unnamed',
        })),
      )
      setJobs(
        (jobRes.data.jobs ?? jobRes.data.items ?? []).map((j: any) => ({
          id: j.id,
          title: j.title ?? j.name ?? 'Unnamed',
        })),
      )
    } catch {
      // Non-critical — selector will be empty
    }
  }, [])

  const openSelector = useCallback(() => {
    setShowSelector(true)
    fetchOptions()
  }, [fetchOptions])

  const handleStart = useCallback(async () => {
    setLoading(true)
    try {
      const payload: Record<string, any> = {}
      if (selectedProjectId) payload.project_id = selectedProjectId
      if (selectedJobId) payload.job_id = selectedJobId
      if (description.trim()) payload.description = description.trim()
      const res = await apiClient.post('/api/v2/time-entries/timer/start', payload)
      const proj = projects.find((p) => p.id === selectedProjectId)
      const job = jobs.find((j) => j.id === selectedJobId)
      setTimer({
        entryId: res.data.id,
        startTime: res.data.start_time,
        description: res.data.description,
        projectId: res.data.project_id,
        projectName: proj?.name ?? null,
        jobId: res.data.job_id,
        jobName: job?.title ?? null,
      })
      setShowSelector(false)
      setDescription('')
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? 'Failed to start timer')
    } finally {
      setLoading(false)
    }
  }, [selectedProjectId, selectedJobId, description, projects, jobs])

  const handleStop = useCallback(async () => {
    setLoading(true)
    try {
      await apiClient.post('/api/v2/time-entries/timer/stop')
      setTimer(null)
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? 'Failed to stop timer')
    } finally {
      setLoading(false)
    }
  }, [])

  /**
   * Switch task without stopping the timer.
   * Stops the current timer and immediately starts a new one
   * with the new project/job — creating an automatic split entry.
   * Validates: Requirement 7.2
   */
  const handleSwitchTask = useCallback(async () => {
    setLoading(true)
    try {
      await apiClient.post('/api/v2/time-entries/timer/stop')
      const payload: Record<string, any> = {}
      if (selectedProjectId) payload.project_id = selectedProjectId
      if (selectedJobId) payload.job_id = selectedJobId
      if (description.trim()) payload.description = description.trim()
      const res = await apiClient.post('/api/v2/time-entries/timer/start', payload)
      const proj = projects.find((p) => p.id === selectedProjectId)
      const job = jobs.find((j) => j.id === selectedJobId)
      setTimer({
        entryId: res.data.id,
        startTime: res.data.start_time,
        description: res.data.description,
        projectId: res.data.project_id,
        projectName: proj?.name ?? null,
        jobId: res.data.job_id,
        jobName: job?.title ?? null,
      })
      setShowSelector(false)
      setDescription('')
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? 'Failed to switch task')
    } finally {
      setLoading(false)
    }
  }, [selectedProjectId, selectedJobId, description, projects, jobs])

  if (!timeTrackingEnabled) return null

  return (
    <div
      role="timer"
      aria-label="Time tracker"
      style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', position: 'relative' }}
    >
      <span aria-live="polite" aria-label="Elapsed time">{display}</span>
      {timer && (
        <span style={{ fontSize: '0.85em', color: '#666', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {timer.projectName || timer.jobName || timer.description || ''}
        </span>
      )}
      {timer ? (
        <>
          <button
            onClick={() => { openSelector() }}
            disabled={loading}
            aria-label="Switch task"
            data-testid="switch-task-btn"
            style={{ background: '#f39c12', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', minWidth: 44, minHeight: 44 }}
          >
            Switch
          </button>
          <button
            onClick={handleStop}
            disabled={loading}
            aria-label="Stop timer"
            data-testid="stop-timer-btn"
            style={{ background: '#e74c3c', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', minWidth: 44, minHeight: 44 }}
          >
            Stop
          </button>
        </>
      ) : (
        <button
          onClick={openSelector}
          disabled={loading}
          aria-label="Start timer"
          data-testid="start-timer-btn"
          style={{ background: '#27ae60', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', minWidth: 44, minHeight: 44 }}
        >
          Start
        </button>
      )}

      {/* Project/Task selector dropdown */}
      {showSelector && (
        <div
          data-testid="timer-selector"
          style={{
            position: 'absolute', top: '100%', right: 0, zIndex: 1000,
            background: '#fff', border: '1px solid #ddd', borderRadius: 8,
            padding: '1rem', minWidth: 280, boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          }}
        >
          <div style={{ marginBottom: '0.75rem' }}>
            <label htmlFor="timer-project" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>
              {projectLabel}
            </label>
            <select
              id="timer-project"
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              aria-label={`Select ${projectLabel}`}
              style={{ width: '100%', padding: '8px', minHeight: 44 }}
            >
              <option value="">— None —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: '0.75rem' }}>
            <label htmlFor="timer-job" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>
              {jobLabel}
            </label>
            <select
              id="timer-job"
              value={selectedJobId}
              onChange={(e) => setSelectedJobId(e.target.value)}
              aria-label={`Select ${jobLabel}`}
              style={{ width: '100%', padding: '8px', minHeight: 44 }}
            >
              <option value="">— None —</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>{j.title}</option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: '0.75rem' }}>
            <label htmlFor="timer-desc" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>
              Description
            </label>
            <input
              id="timer-desc"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What are you working on?"
              aria-label="Timer description"
              style={{ width: '100%', padding: '8px', minHeight: 44 }}
            />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {timer ? (
              <button
                onClick={handleSwitchTask}
                disabled={loading}
                aria-label="Confirm switch task"
                data-testid="confirm-switch-btn"
                style={{ flex: 1, background: '#f39c12', color: '#fff', border: 'none', borderRadius: 4, padding: '8px', cursor: 'pointer', minHeight: 44 }}
              >
                Switch Task
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={loading}
                aria-label="Confirm start timer"
                data-testid="confirm-start-btn"
                style={{ flex: 1, background: '#27ae60', color: '#fff', border: 'none', borderRadius: 4, padding: '8px', cursor: 'pointer', minHeight: 44 }}
              >
                Start Timer
              </button>
            )}
            <button
              onClick={() => setShowSelector(false)}
              aria-label="Cancel"
              style={{ background: '#ccc', border: 'none', borderRadius: 4, padding: '8px 16px', cursor: 'pointer', minHeight: 44 }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
