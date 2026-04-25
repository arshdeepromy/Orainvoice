import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'

const BIOMETRIC_ENABLED_KEY = 'biometric_auth_enabled'

export interface BiometricContextValue {
  /** Whether the device supports biometric authentication */
  isAvailable: boolean
  /** Whether the user has enabled biometric auth */
  isEnabled: boolean
  /** Enable or disable biometric authentication */
  setEnabled: (enabled: boolean) => void
  /** Trigger biometric verification. Returns true on success, false on failure. */
  verify: () => Promise<boolean>
  /** Whether a biometric check is currently in progress */
  isVerifying: boolean
}

const BiometricContext = createContext<BiometricContextValue | null>(null)

export function useBiometric(): BiometricContextValue {
  const ctx = useContext(BiometricContext)
  if (!ctx) throw new Error('useBiometric must be used within BiometricProvider')
  return ctx
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
 * Attempt to dynamically import capacitor-native-biometric.
 * Returns null if the plugin is not available (e.g. in browser/test environments).
 */
async function getNativeBiometric(): Promise<{
  isAvailable: () => Promise<{ isAvailable: boolean }>
  verifyIdentity: (opts: { reason: string; title: string }) => Promise<void>
} | null> {
  if (!isNativePlatform()) return null
  try {
    const mod = await import('capacitor-native-biometric')
    return (mod.NativeBiometric as any) ?? null
  } catch {
    return null
  }
}

/**
 * BiometricProvider — full implementation using capacitor-native-biometric.
 *
 * - Detects device biometric capability on mount
 * - Persists enabled/disabled state in localStorage
 * - Wraps all native calls in try/catch for graceful degradation
 *   in browser/test environments
 * - Hides biometric option if device doesn't support it
 *
 * Requirements: 4.1, 4.4, 4.5
 */
export function BiometricProvider({ children }: { children: ReactNode }) {
  const [isAvailable, setIsAvailable] = useState(false)
  const [isEnabled, setIsEnabledState] = useState(false)
  const [isVerifying, setIsVerifying] = useState(false)

  // Check device capability on mount
  useEffect(() => {
    let cancelled = false

    async function checkAvailability() {
      try {
        const biometric = await getNativeBiometric()
        if (!biometric || cancelled) {
          if (!cancelled) setIsAvailable(false)
          return
        }

        const result = await biometric.isAvailable()
        if (!cancelled) {
          setIsAvailable(result.isAvailable)
        }
      } catch {
        if (!cancelled) setIsAvailable(false)
      }
    }

    checkAvailability()

    return () => {
      cancelled = true
    }
  }, [])

  // Restore enabled state from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem(BIOMETRIC_ENABLED_KEY)
      if (stored === 'true') {
        setIsEnabledState(true)
      }
    } catch {
      // localStorage may not be available in some environments
    }
  }, [])

  const setEnabled = useCallback((enabled: boolean) => {
    setIsEnabledState(enabled)
    try {
      if (enabled) {
        localStorage.setItem(BIOMETRIC_ENABLED_KEY, 'true')
      } else {
        localStorage.removeItem(BIOMETRIC_ENABLED_KEY)
      }
    } catch {
      // localStorage may not be available
    }
  }, [])

  const verify = useCallback(async (): Promise<boolean> => {
    setIsVerifying(true)
    try {
      const biometric = await getNativeBiometric()
      if (!biometric) {
        return false
      }

      await biometric.verifyIdentity({
        reason: 'Unlock OraInvoice',
        title: 'Biometric Authentication',
      })
      return true
    } catch {
      // Verification failed or was cancelled
      return false
    } finally {
      setIsVerifying(false)
    }
  }, [])

  const value = useMemo<BiometricContextValue>(
    () => ({
      isAvailable,
      isEnabled,
      setEnabled,
      verify,
      isVerifying,
    }),
    [isAvailable, isEnabled, setEnabled, verify, isVerifying],
  )

  return (
    <BiometricContext.Provider value={value}>
      {children}
    </BiometricContext.Provider>
  )
}
