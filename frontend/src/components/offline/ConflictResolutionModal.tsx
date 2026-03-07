import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import type { SyncConflict } from '@/contexts/OfflineContext'

interface ConflictResolutionModalProps {
  conflict: SyncConflict | null
  onResolve: (conflictId: string, choice: 'local' | 'server') => void
  onClose: () => void
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

/** Display key fields for a record, filtering out internal metadata */
function RecordSummary({ data, label }: { data: Record<string, unknown>; label: string }) {
  const displayKeys = Object.keys(data).filter(
    (k) => !['id', 'org_id', 'created_at', 'version', 'force'].includes(k),
  )

  return (
    <div className="flex-1 rounded-md border border-gray-200 p-4">
      <h4 className="mb-2 text-sm font-semibold text-gray-700">{label}</h4>
      <dl className="space-y-1 text-sm">
        {displayKeys.slice(0, 10).map((key) => (
          <div key={key} className="flex gap-2">
            <dt className="font-medium text-gray-500 min-w-[100px]">{key}:</dt>
            <dd className="text-gray-900 break-all">{formatValue(data[key])}</dd>
          </div>
        ))}
        {displayKeys.length > 10 && (
          <p className="text-xs text-gray-400">
            +{displayKeys.length - 10} more fields
          </p>
        )}
      </dl>
    </div>
  )
}

export function ConflictResolutionModal({
  conflict,
  onResolve,
  onClose,
}: ConflictResolutionModalProps) {
  if (!conflict) return null

  const storeLabel = conflict.store.charAt(0).toUpperCase() + conflict.store.slice(1, -1)

  return (
    <Modal
      open={!!conflict}
      onClose={onClose}
      title={`Sync Conflict — ${storeLabel}`}
      className="max-w-2xl"
    >
      <p className="mb-4 text-sm text-gray-600">
        This record was modified on another device while you were offline.
        Choose which version to keep.
      </p>

      <div className="mb-6 flex flex-col gap-4 sm:flex-row">
        <RecordSummary data={conflict.localVersion} label="Your version (local)" />
        <RecordSummary data={conflict.serverVersion} label="Server version" />
      </div>

      <div className="flex justify-end gap-3">
        <Button
          variant="secondary"
          onClick={() => onResolve(conflict.id, 'server')}
        >
          Keep server version
        </Button>
        <Button
          variant="primary"
          onClick={() => onResolve(conflict.id, 'local')}
        >
          Keep my version
        </Button>
      </div>
    </Modal>
  )
}
