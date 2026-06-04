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
      className={`flex items-center justify-between rounded-card border bg-card p-4 ${
        isDefault ? 'border-accent ring-1 ring-accent-soft' : 'border-border'
      }`}
      data-testid={`mfa-method-card-${method}`}
      data-method={method}
    >
      <div className="min-w-0 flex-1 mr-4">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-text">{label}</p>
          {isDefault && (
            <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
              Default
            </span>
          )}
        </div>
        <p className="text-xs text-muted-2">{description}</p>
        {enabled && status?.phone_number && (
          <p className="text-xs text-muted-2 mt-1">Phone: {status.phone_number}</p>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
            enabled ? 'bg-ok-soft text-ok' : 'bg-canvas text-muted-2'
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
            className="rounded-ctl border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent-soft min-h-[36px]"
          >
            Set default
          </button>
        )}
        {enabled ? (
          <button
            onClick={onDisable}
            aria-label={`Disable ${label}`}
            className="rounded-ctl border border-border px-3 py-1.5 text-sm text-muted hover:bg-canvas min-h-[36px]"
          >
            Disable
          </button>
        ) : (
          <button
            onClick={onEnable}
            aria-label={`Enable ${label}`}
            className="rounded-ctl bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-press min-h-[36px]"
          >
            Enable
          </button>
        )}
      </div>
    </div>
  )
}
