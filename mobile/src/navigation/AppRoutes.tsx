import { StackRoutes } from '@/navigation/StackRoutes'
import { PushNotificationHandler } from '@/components/common/PushNotificationHandler'

/**
 * Check if we're running inside a native Capacitor shell (not plain web).
 * Uses the runtime global — avoids bundler issues with require().
 */
function isNativePlatform(): boolean {
  return !!(window as any).Capacitor?.isNativePlatform?.()
}

/**
 * AppRoutes — delegates to StackRoutes for all routing.
 * Wraps with PushNotificationHandler ONLY on native platforms to avoid
 * "not implemented on web" errors from Capacitor push notification plugins.
 * This file is the entry point referenced by App.tsx.
 */
export function AppRoutes() {
  if (isNativePlatform()) {
    return (
      <PushNotificationHandler>
        <StackRoutes />
      </PushNotificationHandler>
    )
  }

  return <StackRoutes />
}
