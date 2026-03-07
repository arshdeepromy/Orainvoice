import { useState } from 'react'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { useOfflineContext } from '@/contexts/OfflineContext'
import { ConflictResolutionModal } from './ConflictResolutionModal'

/**
 * Displays offline status banner, sync progress, and conflict resolution UI.
 * Validates: Requirements 77.1, 77.2, 77.3, 77.4
 */
export function OfflineBanner() {
  const {
    isOnline,
    pendingSyncCount,
    isSyncing,
    conflicts,
    resolveConflict,
    lastSyncAt,
  } = useOfflineContext()

  const [activeConflictIndex, setActiveConflictIndex] = useState(0)
  const [dismissedSync, setDismissedSync] = useState(false)

  const activeConflict = conflicts[activeConflictIndex] ?? null

  const handleResolve = (conflictId: string, choice: 'local' | 'server') => {
    resolveConflict(conflictId, choice)
    // Move to next conflict or close
    if (activeConflictIndex >= conflicts.length - 1) {
      setActiveConflictIndex(0)
    }
  }

  return (
    <>
      {/* Offline banner */}
      {!isOnline && (
        <AlertBanner variant="warning" title="You're offline">
          You can still view cached data and create new invoices.
          Changes will sync when you're back online.
          {pendingSyncCount > 0 && (
            <span className="ml-1 font-medium">
              ({pendingSyncCount} pending {pendingSyncCount === 1 ? 'change' : 'changes'})
            </span>
          )}
        </AlertBanner>
      )}

      {/* Syncing indicator */}
      {isSyncing && (
        <AlertBanner variant="info" title="Syncing">
          Syncing your offline changes with the server…
        </AlertBanner>
      )}

      {/* Sync complete notification */}
      {isOnline &&
        !isSyncing &&
        lastSyncAt &&
        pendingSyncCount === 0 &&
        conflicts.length === 0 &&
        !dismissedSync && (
          <AlertBanner
            variant="success"
            title="Sync complete"
            onDismiss={() => setDismissedSync(true)}
          >
            All offline changes have been synced successfully.
          </AlertBanner>
        )}

      {/* Conflicts notification */}
      {conflicts.length > 0 && (
        <AlertBanner variant="warning" title="Sync conflicts">
          {conflicts.length} {conflicts.length === 1 ? 'record has' : 'records have'} conflicting
          changes that need your attention.
        </AlertBanner>
      )}

      {/* Conflict resolution modal */}
      <ConflictResolutionModal
        conflict={activeConflict}
        onResolve={handleResolve}
        onClose={() => setActiveConflictIndex((i) => Math.min(i + 1, conflicts.length))}
      />
    </>
  )
}
