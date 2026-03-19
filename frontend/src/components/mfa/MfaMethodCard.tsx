import type { MfaMethodStatus } from '@/pages/settings/MfaSettings'

interface MfaMethodCardProps {
  method: string
  label: string
  description: string
  status: MfaMethodStatus | undefined
  onEnable: () => void
  onDisable: () => void
  onSetDefault: () => void
}

export function MfaMethodCard({ method, label, description, status, onEnable, onDisable, onSetDefault }: MfaMethodCardProps) {
  const enabled = status?.enabled ?? false
  const isDefault = status?.is_default ?? false

  return (
    <div
      className={`flex items-center justify-between rounded-lg border bg-white p-4 ${
        isDefault ? 'border-blue-300 ring-1 ring-blue-100' : 'border-gray-200'
      }`}
      data-testid={`mfa-method-card-${method}`}
      data-method={method}
    >
      <div className="min-w-0 flex-1 mr-4">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-gray-900">{label}</p>
          {isDefault && (
            <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
              Default
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500">{description}</p>
        {enabled && status?.phone_number && (
          <p className="text-xs text-gray-400 mt-1">Phone: {status.phone_number}</p>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
            enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
          }`}
          role="status"
          aria-label={`${label} is ${enabled ? 'enabled' : 'disabled'}`}
        >
          {enabled ? 'Enabled' : 'Disabled'}
        </span>
        {enabled && !isDefault && (
          <button
            onClick={onSetDefault}
            aria-label={`Set ${label} as default`}
            className="rounded-md border border-blue-200 px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 min-h-[36px]"
          >
            Set default
          </button>
        )}
        {enabled ? (
          <button
            onClick={onDisable}
            aria-label={`Disable ${label}`}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 min-h-[36px]"
          >
            Disable
          </button>
        ) : (
          <button
            onClick={onEnable}
            aria-label={`Enable ${label}`}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 min-h-[36px]"
          >
            Enable
          </button>
        )}
      </div>
    </div>
  )
}
