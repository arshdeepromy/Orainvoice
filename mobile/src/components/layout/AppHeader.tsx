import { useTenant } from '@/contexts/TenantContext'
import { BranchBadge } from '@/components/layout/BranchBadge'
import { OfflineIndicator } from '@/components/layout/OfflineIndicator'

/**
 * AppHeader — top app bar with organisation branding, branch badge, and offline indicator.
 *
 * - Displays org logo (if available) and org name from TenantContext
 * - Shows BranchBadge for multi-branch orgs (requirement 44.5)
 * - Shows OfflineIndicator when device is offline (requirement 30.1)
 * - Respects safe area insets for notched devices
 * - Dark mode support
 *
 * Requirements: 1.7, 44.5, 30.1
 */
export function AppHeader() {
  const { branding } = useTenant()

  return (
    <header className="sticky top-0 z-40 border-b border-gray-200 bg-white pt-[env(safe-area-inset-top)] dark:border-gray-700 dark:bg-gray-900">
      <div className="flex min-h-[48px] items-center justify-between gap-2 px-3 py-2">
        {/* Left: Org branding */}
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {branding?.logo_url ? (
            <img
              src={branding.logo_url}
              alt={`${branding.name} logo`}
              className="h-8 w-8 flex-shrink-0 rounded-md object-contain"
            />
          ) : (
            <div
              className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-blue-600 text-sm font-bold text-white"
              aria-hidden="true"
            >
              {branding?.name?.charAt(0)?.toUpperCase() ?? 'O'}
            </div>
          )}
          <span className="truncate text-sm font-semibold text-gray-900 dark:text-white">
            {branding?.name ?? 'OraInvoice'}
          </span>
        </div>

        {/* Right: Branch badge + offline indicator */}
        <div className="flex flex-shrink-0 items-center gap-2">
          <OfflineIndicator />
          <BranchBadge />
        </div>
      </div>
    </header>
  )
}
