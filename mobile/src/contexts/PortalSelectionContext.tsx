import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export type PortalType = 'org' | 'employee' | 'fleet'

/**
 * A persisted choice of which portal (and, where relevant, which
 * organisation) the mobile app should target. Stored as JSON under the
 * Capacitor Preferences key `"portal_selection"` so it survives app restart.
 *
 * - `portal_type` — which login/session surface to route to.
 * - `org_id` — resolved organisation identifier (employee/fleet portals).
 * - `slug` — the org slug used in the branded portal URL.
 * - `api_base` — the resolved API base/origin for the selected portal, so
 *   requests deterministically target the chosen backend surface on restart.
 */
export interface PortalSelection {
  portal_type: PortalType
  org_id?: string
  slug?: string
  api_base: string
}

/** The Preferences key the selection is persisted under. */
export const PORTAL_SELECTION_KEY = 'portal_selection'

const PORTAL_TYPES: readonly PortalType[] = ['org', 'employee', 'fleet']

/* ------------------------------------------------------------------ */
/* Pure parse / serialise helpers (no side effects — property-testable) */
/* ------------------------------------------------------------------ */

/**
 * Serialise a PortalSelection to its canonical JSON string form. Only the
 * known fields are written, and optional fields are omitted when absent so
 * the round-trip (serialise → parse) yields an equal value.
 *
 * Pure: no I/O, no Capacitor, deterministic for a given input.
 */
export function serializePortalSelection(sel: PortalSelection): string {
  const out: PortalSelection = {
    portal_type: sel.portal_type,
    api_base: sel.api_base,
  }
  if (sel.org_id !== undefined) out.org_id = sel.org_id
  if (sel.slug !== undefined) out.slug = sel.slug
  return JSON.stringify(out)
}

/**
 * Parse a raw stored blob into a PortalSelection.
 *
 * Returns `null` ("no selection") for absent (`null`/empty), malformed
 * (non-JSON), or garbage (wrong shape / invalid field types) input rather
 * than throwing — so a corrupt blob results in the selector being shown
 * instead of a crash (R11.4).
 *
 * Pure: no I/O, no Capacitor, never throws.
 */
export function parsePortalSelection(raw: string | null | undefined): PortalSelection | null {
  if (!raw) return null
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null

  const obj = data as Record<string, unknown>

  // portal_type must be one of the known values
  if (typeof obj.portal_type !== 'string' || !PORTAL_TYPES.includes(obj.portal_type as PortalType)) {
    return null
  }
  // api_base must be a non-empty string
  if (typeof obj.api_base !== 'string' || obj.api_base.length === 0) {
    return null
  }
  // optional fields, when present, must be strings
  if (obj.org_id !== undefined && typeof obj.org_id !== 'string') return null
  if (obj.slug !== undefined && typeof obj.slug !== 'string') return null

  const sel: PortalSelection = {
    portal_type: obj.portal_type as PortalType,
    api_base: obj.api_base,
  }
  if (typeof obj.org_id === 'string') sel.org_id = obj.org_id
  if (typeof obj.slug === 'string') sel.slug = obj.slug
  return sel
}

/* ------------------------------------------------------------------ */
/* Capacitor Preferences plugin (stubbed for web/test environments)    */
/* ------------------------------------------------------------------ */

interface PreferencesPlugin {
  get: (opts: { key: string }) => Promise<{ value: string | null }>
  set: (opts: { key: string; value: string }) => Promise<void>
  remove: (opts: { key: string }) => Promise<void>
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
 * Safely get the Preferences plugin from Capacitor.
 * Returns null in web/test environments or if the import fails.
 */
async function getPreferencesPlugin(): Promise<PreferencesPlugin | null> {
  if (!isNativePlatform()) return null
  try {
    const mod = await import('@capacitor/preferences')
    return (mod.Preferences ?? null) as PreferencesPlugin | null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Storage operations (guarded, never throw)                          */
/* ------------------------------------------------------------------ */

/**
 * Read the persisted selection. Returns `null` ("no selection") for absent,
 * malformed, or garbage blobs — never throws/crashes. All Capacitor calls are
 * guarded by `isNativePlatform()` + try/catch with a localStorage fallback.
 */
export async function loadPortalSelection(): Promise<PortalSelection | null> {
  let json: string | null = null
  try {
    const plugin = await getPreferencesPlugin()
    if (plugin) {
      const result = await plugin.get({ key: PORTAL_SELECTION_KEY })
      json = result.value
    } else if (typeof localStorage !== 'undefined') {
      json = localStorage.getItem(PORTAL_SELECTION_KEY)
    }
  } catch {
    return null
  }
  return parsePortalSelection(json)
}

/**
 * Persist a selection as JSON. Returns `true` on success, `false` if storage
 * failed (so the caller can warn the user the selection was not saved, R11.2).
 * Never throws.
 */
export async function savePortalSelection(sel: PortalSelection): Promise<boolean> {
  const json = serializePortalSelection(sel)
  try {
    const plugin = await getPreferencesPlugin()
    if (plugin) {
      await plugin.set({ key: PORTAL_SELECTION_KEY, value: json })
    } else if (typeof localStorage !== 'undefined') {
      localStorage.setItem(PORTAL_SELECTION_KEY, json)
    } else {
      return false
    }
    return true
  } catch {
    return false
  }
}

/**
 * Remove the persisted selection. Never throws.
 */
export async function clearPortalSelection(): Promise<void> {
  try {
    const plugin = await getPreferencesPlugin()
    if (plugin) {
      await plugin.remove({ key: PORTAL_SELECTION_KEY })
    } else if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(PORTAL_SELECTION_KEY)
    }
  } catch {
    /* ignore — clearing is best-effort */
  }
}

/* ------------------------------------------------------------------ */
/* Context                                                            */
/* ------------------------------------------------------------------ */

export interface PortalSelectionContextValue {
  /** The current persisted selection, or null when none/cleared. */
  selection: PortalSelection | null
  /** True while the initial load from storage is in flight. */
  isLoading: boolean
  /** Re-read the selection from storage. Returns the loaded value. */
  load: () => Promise<PortalSelection | null>
  /** Persist a selection. Returns false if storage failed (R11.2). */
  save: (sel: PortalSelection) => Promise<boolean>
  /** Clear the persisted selection (e.g. logout / switch portal). */
  clear: () => Promise<void>
}

const PortalSelectionContext = createContext<PortalSelectionContextValue | null>(null)

export function usePortalSelection(): PortalSelectionContextValue {
  const ctx = useContext(PortalSelectionContext)
  if (!ctx) {
    throw new Error('usePortalSelection must be used within PortalSelectionProvider')
  }
  return ctx
}

/**
 * PortalSelectionProvider — owns the persisted PortalSelection via Capacitor
 * Preferences (key `"portal_selection"`). On mount it loads the selection;
 * an absent/malformed/garbage blob resolves to `null` so the Portal_Type_Selector
 * is shown rather than crashing (R11.1, R11.4).
 *
 * Requirements: 11.1, 11.4
 */
export function PortalSelectionProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<PortalSelection | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    loadPortalSelection()
      .then((sel) => {
        if (!cancelled) setSelection(sel)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const load = useCallback(async (): Promise<PortalSelection | null> => {
    const sel = await loadPortalSelection()
    setSelection(sel)
    return sel
  }, [])

  const save = useCallback(async (sel: PortalSelection): Promise<boolean> => {
    const ok = await savePortalSelection(sel)
    if (ok) setSelection(sel)
    return ok
  }, [])

  const clear = useCallback(async (): Promise<void> => {
    await clearPortalSelection()
    setSelection(null)
  }, [])

  const value = useMemo<PortalSelectionContextValue>(
    () => ({ selection, isLoading, load, save, clear }),
    [selection, isLoading, load, save, clear],
  )

  return (
    <PortalSelectionContext.Provider value={value}>
      {children}
    </PortalSelectionContext.Provider>
  )
}
