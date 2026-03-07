/**
 * Timer component for the app header showing elapsed time.
 *
 * Persists timer state via localStorage so it survives page refreshes
 * and browser restarts. Syncs with the backend active timer endpoint.
 *
 * Validates: Requirement 13.2
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

const STORAGE_KEY = 'orainvoice_active_timer'

interface TimerState {
  entryId: string
  startTime: string
  description: string | null
}

function formatElapsed(startIso: string): string {
  const elapsed = Math.floor((Date.now() - new Date(startIso).getTime()) / 1000)
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function HeaderTimer() {
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

  const handleStart = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.post('/api/v2/time-entries/timer/start', {})
      setTimer({
        entryId: res.data.id,
        startTime: res.data.start_time,
        description: res.data.description,
      })
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? 'Failed to start timer')
    } finally {
      setLoading(false)
    }
  }, [])

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

  return (
    <div
      role="timer"
      aria-label="Time tracker"
      style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
    >
      <span aria-live="polite" aria-label="Elapsed time">{display}</span>
      {timer?.description && (
        <span style={{ fontSize: '0.85em', color: '#666' }}>
          {timer.description}
        </span>
      )}
      {timer ? (
        <button
          onClick={handleStop}
          disabled={loading}
          aria-label="Stop timer"
          style={{ background: '#e74c3c', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer' }}
        >
          Stop
        </button>
      ) : (
        <button
          onClick={handleStart}
          disabled={loading}
          aria-label="Start timer"
          style={{ background: '#27ae60', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer' }}
        >
          Start
        </button>
      )}
    </div>
  )
}
