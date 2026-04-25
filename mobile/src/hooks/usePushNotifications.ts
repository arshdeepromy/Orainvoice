import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Capacitor plugin types (stubbed for web/test environments)         */
/* ------------------------------------------------------------------ */

interface PushNotificationToken {
  value: string
}

interface PushNotificationActionPerformed {
  notification: {
    data?: Record<string, string>
  }
}

interface PushNotificationsPlugin {
  requestPermissions: () => Promise<{ receive: string }>
  register: () => Promise<void>
  addListener: (
    event: string,
    callback: (data: PushNotificationToken | PushNotificationActionPerformed) => void,
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
 * Safely get the PushNotifications plugin from Capacitor.
 * Returns null in web/test environments where Capacitor is not available.
 */
async function getPushPlugin(): Promise<PushNotificationsPlugin | null> {
  if (!isNativePlatform()) return null
  try {
    const mod = await import('@capacitor/push-notifications')
    return (mod.PushNotifications ?? null) as PushNotificationsPlugin | null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Hook                                                               */
/* ------------------------------------------------------------------ */

export interface UsePushNotificationsResult {
  /** Whether push notification permission has been granted */
  isPermissionGranted: boolean
  /** The FCM token (null if not registered) */
  token: string | null
  /** Whether registration is in progress */
  isLoading: boolean
  /** Error message from the last operation */
  error: string | null
  /** Request permission and register for push notifications */
  register: () => Promise<void>
}

/**
 * FCM registration via Capacitor — permission request, token submission
 * to backend.
 *
 * Requirements: 12.1, 12.2, 12.4
 */
export function usePushNotifications(
  onNotificationTap?: (data: Record<string, string>) => void,
): UsePushNotificationsResult {
  const [isPermissionGranted, setIsPermissionGranted] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const registerPush = useCallback(async () => {
    const plugin = await getPushPlugin()
    if (!plugin) {
      setError('Push notifications not available on this device')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      // Request permission
      const permResult = await plugin.requestPermissions()
      if (permResult.receive !== 'granted') {
        setError('Push notification permission denied')
        setIsLoading(false)
        return
      }

      setIsPermissionGranted(true)

      // Register with FCM
      await plugin.register()
    } catch (err: unknown) {
      setError('Failed to register for push notifications')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Listen for registration token and notification taps
  useEffect(() => {
    const listeners: Array<{ remove: () => void }> = []
    let cancelled = false

    async function setup() {
      const plugin = await getPushPlugin()
      if (!plugin || cancelled) return

      try {
        // Token received
        const regListener = await plugin.addListener('registration', (data) => {
          const tokenData = data as PushNotificationToken
          const fcmToken = tokenData.value
          setToken(fcmToken)

          // Submit token to backend
          apiClient
            .post('/api/v1/notifications/push-token', { token: fcmToken })
            .catch(() => {
              // Non-blocking — token submission failure is not critical
            })
        })
        if (!cancelled) listeners.push(regListener)
        else regListener.remove()

        // Notification tap handler
        const tapListener = await plugin.addListener('pushNotificationActionPerformed', (data) => {
          const action = data as PushNotificationActionPerformed
          const notifData = action.notification?.data ?? {}
          onNotificationTap?.(notifData)
        })
        if (!cancelled) listeners.push(tapListener)
        else tapListener.remove()
      } catch {
        // Listener setup failed — no-op
      }
    }

    setup()

    return () => {
      cancelled = true
      listeners.forEach((l) => l.remove())
    }
  }, [onNotificationTap])

  return {
    isPermissionGranted,
    token,
    isLoading,
    error,
    register: registerPush,
  }
}
