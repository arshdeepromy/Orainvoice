import { useOffline } from '@/contexts/OfflineContext'

/**
 * OfflineIndicator — banner displayed in the app header when the device is offline.
 *
 * - Shows a compact warning banner with an icon and message
 * - Hidden when the device is online
 * - Includes pending sync count when mutations are queued
 *
 * Requirements: 30.1
 */
export function OfflineIndicator() {
  const { isOnline, pendingCount } = useOffline()

  if (isOnline) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
    >
      {/* Offline icon */}
      <svg
        className="h-3.5 w-3.5 flex-shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <line x1="2" y1="2" x2="22" y2="22" />
        <path d="M8.5 16.5a5 5 0 0 1 7 0" />
        <path d="M2 8.82a15 15 0 0 1 4.17-2.65" />
        <path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76" />
        <path d="M16.85 11.25a10 10 0 0 1 2.22 1.68" />
        <path d="M5 12.86a10 10 0 0 1 5.17-2.86" />
        <line x1="12" y1="20" x2="12.01" y2="20" />
      </svg>
      <span>
        Offline
        {pendingCount > 0 && (
          <span className="ml-1">({pendingCount} pending)</span>
        )}
      </span>
    </div>
  )
}
