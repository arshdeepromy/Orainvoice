import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import type { ReactNode } from 'react'

/* ------------------------------------------------------------------ */
/* Capacitor Network plugin types (stubbed for web/test environments) */
/* ------------------------------------------------------------------ */

interface NetworkStatus {
  connected: boolean
  connectionType: string
}

interface NetworkPlugin {
  getStatus: () => Promise<NetworkStatus>
  addListener: (
    event: string,
    callback: (status: NetworkStatus) => void,
  ) => Promise<{ remove: () => void }>
}

/**
 * Check if we're running inside a native Capacitor shell (not plain web).
 * Uses the runtime global injected by Capacitor — avoids bundler issues
 * with require() / static imports that Vite resolves at build time.
 */
function isNativePlatform(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

/**
 * Safely get the Network plugin from Capacitor.
 * Returns null in web/test environments.
 */
async function getNetworkPlugin(): Promise<NetworkPlugin | null> {
  if (!isNativePlatform()) return null
  try {
    const mod = await import('@capacitor/network')
    return (mod.Network ?? null) as NetworkPlugin | null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Context                                                            */
/* ------------------------------------------------------------------ */

export interface OfflineContextValue {
  /** Whether the device currently has network connectivity */
  isOnline: boolean
  /** Number of mutations waiting to be synced */
  pendingCount: number
  /** Whether the queue is currently syncing */
  isSyncing: boolean
  /** Timestamp of last successful sync */
  lastSyncAt: number | null
  /** Increment pending count (called by offline queue) */
  setPendingCount: (count: number) => void
  /** Update syncing state */
  setIsSyncing: (syncing: boolean) => void
  /** Update last sync timestamp */
  setLastSyncAt: (ts: number | null) => void
}

const OfflineContext = createContext<OfflineContextValue | null>(null)

export function useOffline(): OfflineContextValue {
  const ctx = useContext(OfflineContext)
  if (!ctx) throw new Error('useOffline must be used within OfflineProvider')
  return ctx
}

/**
 * OfflineProvider — monitors network status via @capacitor/network,
 * exposes online/offline state and offline queue metadata.
 *
 * Falls back to navigator.onLine in web/test environments.
 *
 * Requirements: 30.1, 30.2
 */
export function OfflineProvider({ children }: { children: ReactNode }) {
  const [isOnline, setIsOnline] = useState(true)
  const [pendingCount, setPendingCount] = useState(0)
  const [isSyncing, setIsSyncing] = useState(false)
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null)

  useEffect(() => {
    let listener: { remove: () => void } | null = null
    let cancelled = false

    // Web fallback handlers (always registered, removed if Capacitor takes over)
    const handleOnline = () => { if (!cancelled) setIsOnline(true) }
    const handleOffline = () => { if (!cancelled) setIsOnline(false) }

    async function setup() {
      const plugin = await getNetworkPlugin()

      if (cancelled) return

      if (plugin) {
        // Use Capacitor Network plugin
        try {
          const status = await plugin.getStatus()
          if (!cancelled) setIsOnline(status.connected)
        } catch {
          if (!cancelled) setIsOnline(typeof navigator !== 'undefined' ? navigator.onLine : true)
        }

        try {
          const l = await plugin.addListener('networkStatusChange', (status: NetworkStatus) => {
            if (!cancelled) setIsOnline(status.connected)
          })
          if (!cancelled) listener = l
          else l.remove()
        } catch {
          // Listener setup failed — fall through to web fallback
        }
      } else {
        // Web fallback: use navigator.onLine + events
        if (!cancelled) {
          setIsOnline(typeof navigator !== 'undefined' ? navigator.onLine : true)
          window.addEventListener('online', handleOnline)
          window.addEventListener('offline', handleOffline)
        }
      }
    }

    setup()

    return () => {
      cancelled = true
      listener?.remove()
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  const setPendingCountCb = useCallback((count: number) => setPendingCount(count), [])
  const setIsSyncingCb = useCallback((syncing: boolean) => setIsSyncing(syncing), [])
  const setLastSyncAtCb = useCallback((ts: number | null) => setLastSyncAt(ts), [])

  const value = useMemo<OfflineContextValue>(
    () => ({
      isOnline,
      pendingCount,
      isSyncing,
      lastSyncAt,
      setPendingCount: setPendingCountCb,
      setIsSyncing: setIsSyncingCb,
      setLastSyncAt: setLastSyncAtCb,
    }),
    [isOnline, pendingCount, isSyncing, lastSyncAt, setPendingCountCb, setIsSyncingCb, setLastSyncAtCb],
  )

  return (
    <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>
  )
}
