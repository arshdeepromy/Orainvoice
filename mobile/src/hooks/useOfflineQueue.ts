/**
 * Offline mutation queue — stores mutations when offline, replays on reconnect.
 *
 * Pure functions are exported for property-based testing.
 *
 * Requirements: 30.3, 30.4, 30.5, 30.6, 30.7
 */

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export type OfflineMutationType = 'create' | 'update' | 'delete'
export type OfflineMutationMethod = 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface OfflineMutation {
  id: string
  timestamp: number
  type: OfflineMutationType
  endpoint: string
  method: OfflineMutationMethod
  body: Record<string, unknown> | null
  entityType: string
  entityLabel: string
  status: 'pending' | 'syncing' | 'synced' | 'failed'
  errorMessage?: string
  retryCount: number
}

export interface OfflineQueueState {
  mutations: OfflineMutation[]
}

const STORAGE_KEY = 'offline_queue'
const MAX_RETRIES = 3

/* ------------------------------------------------------------------ */
/* Pure functions — exported for property-based testing                */
/* ------------------------------------------------------------------ */

/**
 * Generate a simple unique ID for mutations.
 */
export function generateMutationId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/**
 * Add a mutation to the queue. Returns a new queue state.
 * Mutations are appended with monotonically non-decreasing timestamps.
 *
 * **Validates: Requirements 30.3**
 */
export function addMutation(
  queue: OfflineQueueState,
  mutation: Omit<OfflineMutation, 'id' | 'status' | 'retryCount'>,
): OfflineQueueState {
  const lastTimestamp = queue.mutations.length > 0
    ? queue.mutations[queue.mutations.length - 1].timestamp
    : 0

  const newMutation: OfflineMutation = {
    ...mutation,
    id: generateMutationId(),
    // Ensure monotonically non-decreasing timestamps
    timestamp: Math.max(mutation.timestamp, lastTimestamp),
    status: 'pending',
    retryCount: 0,
  }

  return {
    mutations: [...queue.mutations, newMutation],
  }
}

/**
 * Get mutations sorted in chronological order for replay.
 * Returns a new array sorted by timestamp (non-decreasing).
 *
 * **Validates: Requirements 30.4**
 */
export function getReplayOrder(queue: OfflineQueueState): OfflineMutation[] {
  return [...queue.mutations]
    .filter((m) => m.status === 'pending' || m.status === 'failed')
    .sort((a, b) => a.timestamp - b.timestamp)
}

/**
 * Mark a mutation as synced. Returns a new queue state.
 */
export function markSynced(
  queue: OfflineQueueState,
  mutationId: string,
): OfflineQueueState {
  return {
    mutations: queue.mutations.map((m) =>
      m.id === mutationId ? { ...m, status: 'synced' as const } : m,
    ),
  }
}

/**
 * Mark a mutation as failed with an error message and increment retry count.
 */
export function markFailed(
  queue: OfflineQueueState,
  mutationId: string,
  errorMessage: string,
): OfflineQueueState {
  return {
    mutations: queue.mutations.map((m) =>
      m.id === mutationId
        ? { ...m, status: 'failed' as const, errorMessage, retryCount: m.retryCount + 1 }
        : m,
    ),
  }
}

/**
 * Remove synced mutations from the queue. Returns a new queue state.
 */
export function purgeSynced(queue: OfflineQueueState): OfflineQueueState {
  return {
    mutations: queue.mutations.filter((m) => m.status !== 'synced'),
  }
}

/**
 * Remove mutations that have exceeded max retries.
 */
export function purgeExhausted(queue: OfflineQueueState): OfflineQueueState {
  return {
    mutations: queue.mutations.filter((m) => m.retryCount < MAX_RETRIES),
  }
}

/**
 * Calculate exponential backoff delay in milliseconds.
 * delay = min(1000 * 2^retryCount, 30000)
 */
export function getBackoffDelay(retryCount: number): number {
  return Math.min(1000 * Math.pow(2, retryCount), 30_000)
}

/**
 * Serialize queue state to a JSON string for persistence.
 *
 * **Validates: Requirements 30.7**
 */
export function serializeQueue(queue: OfflineQueueState): string {
  return JSON.stringify(queue)
}

/**
 * Deserialize queue state from a JSON string.
 * Returns an empty queue if parsing fails.
 *
 * **Validates: Requirements 30.7**
 */
export function deserializeQueue(json: string): OfflineQueueState {
  try {
    const parsed = JSON.parse(json)
    if (
      parsed &&
      typeof parsed === 'object' &&
      Array.isArray(parsed.mutations)
    ) {
      return parsed as OfflineQueueState
    }
    return { mutations: [] }
  } catch {
    return { mutations: [] }
  }
}

/* ------------------------------------------------------------------ */
/* Capacitor Preferences plugin (stubbed for web/test)                */
/* ------------------------------------------------------------------ */

interface PreferencesPlugin {
  get: (opts: { key: string }) => Promise<{ value: string | null }>
  set: (opts: { key: string; value: string }) => Promise<void>
}

/**
 * Check if we're running inside a native Capacitor shell (not plain web).
 * Uses the runtime global injected by Capacitor — avoids bundler issues
 * with require() / static imports that Vite resolves at build time.
 */
function isNativePlatform(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

async function getPreferencesPlugin(): Promise<PreferencesPlugin | null> {
  if (!isNativePlatform()) return null
  try {
    const mod = await import('@capacitor/preferences')
    return (mod.Preferences ?? null) as PreferencesPlugin | null
  } catch {
    return null
  }
}

/**
 * Persist queue to storage (Capacitor Preferences or localStorage fallback).
 */
export async function persistQueue(queue: OfflineQueueState): Promise<void> {
  const json = serializeQueue(queue)
  const plugin = await getPreferencesPlugin()
  if (plugin) {
    await plugin.set({ key: STORAGE_KEY, value: json })
  } else {
    localStorage.setItem(STORAGE_KEY, json)
  }
}

/**
 * Load queue from storage.
 */
export async function loadQueue(): Promise<OfflineQueueState> {
  const plugin = await getPreferencesPlugin()
  let json: string | null = null
  if (plugin) {
    const result = await plugin.get({ key: STORAGE_KEY })
    json = result.value
  } else {
    json = localStorage.getItem(STORAGE_KEY)
  }
  if (!json) return { mutations: [] }
  return deserializeQueue(json)
}
