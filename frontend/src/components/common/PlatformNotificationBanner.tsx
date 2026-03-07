import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

/* ── Types ── */

export interface ActiveNotification {
  id: string
  notification_type: 'maintenance' | 'alert' | 'feature' | 'info'
  title: string
  message: string
  severity: 'info' | 'warning' | 'critical'
  published_at: string | null
  expires_at: string | null
  maintenance_start: string | null
  maintenance_end: string | null
}

/* ── Severity styling ── */

const SEVERITY_STYLES: Record<string, { bg: string; border: string; icon: string }> = {
  info: { bg: 'bg-blue-50', border: 'border-blue-300', icon: 'ℹ️' },
  warning: { bg: 'bg-yellow-50', border: 'border-yellow-300', icon: '⚠️' },
  critical: { bg: 'bg-red-50', border: 'border-red-300', icon: '🚨' },
}

/* ── Countdown helper ── */

function formatCountdown(targetDate: string): string {
  const diff = new Date(targetDate).getTime() - Date.now()
  if (diff <= 0) return 'now'
  const hours = Math.floor(diff / (1000 * 60 * 60))
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

/* ── Single notification banner ── */

interface BannerItemProps {
  notification: ActiveNotification
  onDismiss: (id: string) => void
}

function BannerItem({ notification, onDismiss }: BannerItemProps) {
  const [countdown, setCountdown] = useState<string | null>(null)
  const style = SEVERITY_STYLES[notification.severity] || SEVERITY_STYLES.info

  useEffect(() => {
    if (notification.notification_type !== 'maintenance' || !notification.maintenance_start) {
      return
    }

    const update = () => setCountdown(formatCountdown(notification.maintenance_start!))
    update()
    const interval = setInterval(update, 60_000)
    return () => clearInterval(interval)
  }, [notification.notification_type, notification.maintenance_start])

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-center justify-between px-4 py-3 border-b ${style.bg} ${style.border}`}
      data-testid={`notification-banner-${notification.id}`}
    >
      <div className="flex items-center gap-2 flex-1">
        <span aria-hidden="true">{style.icon}</span>
        <div>
          <strong className="text-sm font-semibold">{notification.title}</strong>
          <span className="text-sm ml-2">{notification.message}</span>
          {countdown && notification.notification_type === 'maintenance' && (
            <span className="text-sm ml-2 font-mono" data-testid="maintenance-countdown">
              (starts in {countdown})
            </span>
          )}
        </div>
      </div>
      <button
        onClick={() => onDismiss(notification.id)}
        className="ml-4 text-gray-500 hover:text-gray-700 text-lg leading-none"
        aria-label={`Dismiss notification: ${notification.title}`}
        data-testid={`dismiss-btn-${notification.id}`}
      >
        ✕
      </button>
    </div>
  )
}

/* ── Main banner component ── */

export default function PlatformNotificationBanner() {
  const [notifications, setNotifications] = useState<ActiveNotification[]>([])
  const [loading, setLoading] = useState(true)

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/notifications/active')
      setNotifications(res.data.notifications || [])
    } catch {
      // Silently fail — notifications are non-critical
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchNotifications()
    // Refresh every 5 minutes
    const interval = setInterval(fetchNotifications, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchNotifications])

  const handleDismiss = useCallback(async (notificationId: string) => {
    // Optimistically remove from UI
    setNotifications(prev => prev.filter(n => n.id !== notificationId))
    try {
      await apiClient.post('/api/v2/notifications/dismiss', {
        notification_id: notificationId,
      })
    } catch {
      // If dismiss fails, re-fetch to restore
      fetchNotifications()
    }
  }, [fetchNotifications])

  if (loading || notifications.length === 0) return null

  return (
    <div data-testid="platform-notification-banner" role="region" aria-label="Platform notifications">
      {notifications.map(notif => (
        <BannerItem key={notif.id} notification={notif} onDismiss={handleDismiss} />
      ))}
    </div>
  )
}
