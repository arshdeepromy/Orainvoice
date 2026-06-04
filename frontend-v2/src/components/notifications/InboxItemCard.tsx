import { useCallback } from 'react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InboxItemData {
  id: string
  category: string
  severity: string
  title: string
  body: string | null
  link_url: string | null
  entity_type: string | null
  entity_id: string | null
  metadata: Record<string, unknown>
  created_at: string
  is_read: boolean
  read_at: string | null
}

export interface InboxItemCardProps {
  item: InboxItemData
  onClick?: (item: InboxItemData) => void
  onDismiss?: (item: InboxItemData) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Simple relative time formatter — no external dependency. */
function formatRelativeTime(isoDate: string): string {
  const now = Date.now()
  const then = new Date(isoDate).getTime()
  if (isNaN(then)) return ''
  const diffSec = Math.max(0, Math.round((now - then) / 1000))

  if (diffSec < 60) return 'just now'
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`
  return new Date(isoDate).toLocaleDateString()
}

/** Returns design-token classes for the severity icon container. */
function severityClasses(severity: string): { bg: string; text: string } {
  switch (severity) {
    case 'error':
      return { bg: 'bg-danger-soft', text: 'text-danger' }
    case 'warning':
      return { bg: 'bg-warn-soft', text: 'text-warn' }
    case 'success':
      return { bg: 'bg-ok-soft', text: 'text-ok' }
    default:
      return { bg: 'bg-accent-soft', text: 'text-accent' }
  }
}

// ---------------------------------------------------------------------------
// Severity Icons (inline SVG per design §6.5)
// ---------------------------------------------------------------------------

function InformationCircleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  )
}

function CheckCircleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  )
}

function ExclamationTriangleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
      />
    </svg>
  )
}

function XCircleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  )
}

/** Renders the appropriate severity icon inside a coloured circle. */
function SeverityIcon({ severity }: { severity: string }) {
  const { bg, text } = severityClasses(severity)
  const containerCls = `h-6 w-6 flex-shrink-0 flex items-center justify-center rounded-full ${bg}`
  const iconCls = `h-4 w-4 ${text}`

  switch (severity) {
    case 'error':
      return (
        <span className={containerCls} aria-hidden="true">
          <XCircleIcon className={iconCls} />
        </span>
      )
    case 'warning':
      return (
        <span className={containerCls} aria-hidden="true">
          <ExclamationTriangleIcon className={iconCls} />
        </span>
      )
    case 'success':
      return (
        <span className={containerCls} aria-hidden="true">
          <CheckCircleIcon className={iconCls} />
        </span>
      )
    default:
      return (
        <span className={containerCls} aria-hidden="true">
          <InformationCircleIcon className={iconCls} />
        </span>
      )
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * A notification inbox item card showing severity icon, title, body preview,
 * relative time, unread indicator, and a dismiss button.
 *
 * Used in both the InboxBellDropdown and the full InboxPage.
 *
 * Validates: Requirements 6.1.4, 6.2.3
 */
export default function InboxItemCard({ item, onClick, onDismiss }: InboxItemCardProps) {
  const handleClick = useCallback(() => {
    onClick?.(item)
  }, [onClick, item])

  const handleDismiss = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      onDismiss?.(item)
    },
    [onDismiss, item],
  )

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleClick()
        }
      }}
      className={`relative flex w-full items-start gap-3 px-4 py-3 text-left transition-colors cursor-pointer hover:bg-canvas ${
        !item.is_read ? 'bg-accent-soft' : ''
      }`}
    >
      {/* Unread indicator dot */}
      {!item.is_read && (
        <span
          className="absolute left-1.5 top-1/2 -translate-y-1/2 h-2 w-2 rounded-full bg-accent"
          aria-label="Unread"
        />
      )}

      {/* Severity icon */}
      <SeverityIcon severity={item.severity} />

      {/* Content */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-text truncate">
          {item.title}
        </p>
        {item.body && (
          <p className="mt-0.5 text-xs text-muted line-clamp-2">
            {item.body}
          </p>
        )}
        {/* Dismiss button */}
        {onDismiss && (
          <button
            type="button"
            onClick={handleDismiss}
            className="mt-1 text-xs font-medium text-muted-2 hover:text-danger transition-colors"
          >
            Dismiss
          </button>
        )}
      </div>

      {/* Relative time */}
      <span className="flex-shrink-0 text-xs text-muted-2 whitespace-nowrap">
        {formatRelativeTime(item.created_at)}
      </span>
    </div>
  )
}
