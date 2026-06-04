import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import { useOffline } from '@/hooks/useOffline'
import apiClient from '@/api/client'
import {
  getAllItems,
  putItem,
  deleteItem,
  cacheRecords,
} from '@/utils/offlineStorage'
import type { PendingSyncItem } from '@/utils/offlineStorage'

/* ── Types ── */

export interface SyncConflict {
  id: string
  store: 'invoices' | 'customers' | 'vehicles'
  localVersion: Record<string, unknown>
  serverVersion: Record<string, unknown>
  pendingItemId: string
}

interface OfflineContextValue {
  /** Current network status */
  isOnline: boolean
  /** Number of items waiting to sync */
  pendingSyncCount: number
  /** Whether a sync is currently in progress */
  isSyncing: boolean
  /** Active conflicts requiring user resolution */
  conflicts: SyncConflict[]
  /** Save data locally for later sync */
  saveOffline: (
    store: 'invoices' | 'customers' | 'vehicles',
    action: 'create' | 'update',
    data: Record<string, unknown>,
    serverVersion?: number,
  ) => Promise<void>
  /** Resolve a conflict by choosing local or server version */
  resolveConflict: (conflictId: string, choice: 'local' | 'server') => Promise<void>
  /** Manually trigger a sync attempt */
  triggerSync: () => Promise<void>
  /** Cache server data locally for offline viewing */
  cacheForOffline: (
    store: 'invoices' | 'customers' | 'vehicles',
    records: Record<string, unknown>[],
  ) => Promise<void>
  /** Last successful sync timestamp */
  lastSyncAt: string | null
}

const OfflineContext = createContext<OfflineContextValue | null>(null)

export function useOfflineContext(): OfflineContextValue {
  const ctx = useContext(OfflineContext)
  if (!ctx) throw new Error('useOfflineContext must be used within OfflineProvider')
  return ctx
}

/* ── API endpoint mapping ── */

const SYNC_ENDPOINTS: Record<string, { create: string; update: (id: string) => string }> = {
  invoices: {
    create: '/invoices',
    update: (id: string) => `/invoices/${id}`,
  },
  customers: {
    create: '/customers',
    update: (id: string) => `/customers/${id}`,
  },
  vehicles: {
    create: '/vehicles/manual',
    update: (id: string) => `/vehicles/${id}`,
  },
}

/* ── Provider ── */

export function OfflineProvider({ children }: { children: ReactNode }) {
  const { isOnline, justReconnected, clearReconnected } = useOffline()
  const [pendingSyncCount, setPendingSyncCount] = useState(0)
  const [isSyncing, setIsSyncing] = useState(false)
  const [conflicts, setConflicts] = useState<SyncConflict[]>([])
  const [lastSyncAt, setLastSyncAt] = useState<string | null>(null)

  // Refresh pending count from IndexedDB
  const refreshPendingCount = useCallback(async () => {
    try {
      const items = await getAllItems<PendingSyncItem>('pendingSync')
      setPendingSyncCount(items.length)
    } catch {
      // IndexedDB may not be available
    }
  }, [])

  // Load pending count on mount
  useEffect(() => {
    refreshPendingCount()
  }, [refreshPendingCount])

  // Save data locally for later sync
  const saveOffline = useCallback(
    async (
      store: 'invoices' | 'customers' | 'vehicles',
      action: 'create' | 'update',
      data: Record<string, unknown>,
      serverVersion?: number,
    ) => {
      const item: PendingSyncItem = {
        id: crypto.randomUUID(),
        store,
        action,
        data,
        createdAt: new Date().toISOString(),
        serverVersion,
      }
      await putItem('pendingSync', item)

      // Also cache the record locally for offline viewing
      if (data.id) {
        await putItem(store, data)
      }

      await refreshPendingCount()
    },
    [refreshPendingCount],
  )

  // Cache server records for offline viewing
  const cacheForOffline = useCallback(
    async (
      store: 'invoices' | 'customers' | 'vehicles',
      records: Record<string, unknown>[],
    ) => {
      await cacheRecords(store, records)
    },
    [],
  )

  // Sync a single pending item to the server
  const syncItem = useCallback(
    async (item: PendingSyncItem): Promise<SyncConflict | null> => {
      const endpoints = SYNC_ENDPOINTS[item.store]
      if (!endpoints) return null

      try {
        if (item.action === 'create') {
          await apiClient.post(endpoints.create, item.data)
        } else {
          const recordId = item.data.id as string
          // Check for conflicts on updates
          if (item.serverVersion !== undefined) {
            try {
              const current = await apiClient.get(
                endpoints.update(recordId),
              )
              const serverData = current.data as Record<string, unknown>
              const serverVer =
                typeof serverData.version === 'number'
                  ? serverData.version
                  : undefined

              if (serverVer !== undefined && serverVer !== item.serverVersion) {
                // Conflict detected — server version changed since local save
                return {
                  id: crypto.randomUUID(),
                  store: item.store,
                  localVersion: item.data,
                  serverVersion: serverData,
                  pendingItemId: item.id,
                }
              }
            } catch {
              // If we can't fetch the current version, try the update anyway
            }
          }
          await apiClient.put(endpoints.update(recordId), item.data)
        }

        // Success — remove from pending queue
        await deleteItem('pendingSync', item.id)
        return null
      } catch (err: unknown) {
        const status =
          err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { status?: number } }).response?.status
            : undefined

        if (status === 409) {
          // Server reported conflict
          try {
            const recordId = item.data.id as string
            const current = await apiClient.get(
              endpoints.update(recordId),
            )
            return {
              id: crypto.randomUUID(),
              store: item.store,
              localVersion: item.data,
              serverVersion: current.data as Record<string, unknown>,
              pendingItemId: item.id,
            }
          } catch {
            // Can't fetch server version — leave in queue for retry
          }
        }
        // Other errors — leave in queue for retry
        return null
      }
    },
    [],
  )

  // Sync all pending items
  const triggerSync = useCallback(async () => {
    if (isSyncing || !isOnline) return

    setIsSyncing(true)
    const newConflicts: SyncConflict[] = []

    try {
      const pendingItems = await getAllItems<PendingSyncItem>('pendingSync')

      for (const item of pendingItems) {
        const conflict = await syncItem(item)
        if (conflict) {
          newConflicts.push(conflict)
        }
      }

      if (newConflicts.length > 0) {
        setConflicts((prev) => [...prev, ...newConflicts])
      }

      setLastSyncAt(new Date().toISOString())
    } finally {
      setIsSyncing(false)
      await refreshPendingCount()
    }
  }, [isSyncing, isOnline, syncItem, refreshPendingCount])

  // Resolve a conflict
  const resolveConflict = useCallback(
    async (conflictId: string, choice: 'local' | 'server') => {
      const conflict = conflicts.find((c) => c.id === conflictId)
      if (!conflict) return

      const endpoints = SYNC_ENDPOINTS[conflict.store]
      if (!endpoints) return

      try {
        if (choice === 'local') {
          // Push local version to server
          const recordId = conflict.localVersion.id as string
          await apiClient.put(
            endpoints.update(recordId),
            { ...conflict.localVersion, force: true },
          )
        }
        // For 'server' choice, we just accept the server version (no action needed)

        // Update local cache with the chosen version
        const chosen = choice === 'local' ? conflict.localVersion : conflict.serverVersion
        await putItem(conflict.store, chosen)

        // Remove the pending sync item
        await deleteItem('pendingSync', conflict.pendingItemId)
      } finally {
        setConflicts((prev) => prev.filter((c) => c.id !== conflictId))
        await refreshPendingCount()
      }
    },
    [conflicts, refreshPendingCount],
  )

  // Auto-sync when coming back online
  useEffect(() => {
    if (justReconnected && isOnline) {
      triggerSync()
      clearReconnected()
    }
  }, [justReconnected, isOnline, triggerSync, clearReconnected])

  const value = useMemo<OfflineContextValue>(
    () => ({
      isOnline,
      pendingSyncCount,
      isSyncing,
      conflicts,
      saveOffline,
      resolveConflict,
      triggerSync,
      cacheForOffline,
      lastSyncAt,
    }),
    [
      isOnline,
      pendingSyncCount,
      isSyncing,
      conflicts,
      saveOffline,
      resolveConflict,
      triggerSync,
      cacheForOffline,
      lastSyncAt,
    ],
  )

  return (
    <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>
  )
}
