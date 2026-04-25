import { useCallback, type ReactNode } from 'react'
import { usePushNotifications } from '@/hooks/usePushNotifications'
import { useDeepLink } from '@/hooks/useDeepLink'

/**
 * Wires push notification tap handler to deep link navigation.
 *
 * When a user taps a push notification, the notification data is inspected
 * for a `url` or `deep_link` field, which is then resolved via the deep
 * link router and navigated to.
 *
 * Requirements: 12.3
 */
export function PushNotificationHandler({ children }: { children: ReactNode }) {
  const { handleDeepLink } = useDeepLink()

  const onNotificationTap = useCallback(
    (data: Record<string, string>) => {
      // Look for a deep link URL in the notification payload
      const url = data.url ?? data.deep_link ?? data.link ?? null
      if (url) {
        handleDeepLink(url)
      }
    },
    [handleDeepLink],
  )

  // Register push notifications with the tap handler
  usePushNotifications(onNotificationTap)

  return <>{children}</>
}
