import { Chip } from 'konsta/react'
import { STATUS_CONFIG } from '@/utils/statusConfig'

export interface StatusBadgeProps {
  /** Invoice or job status key (e.g. 'draft', 'paid', 'overdue') */
  status: string
  /** Badge size — controls font size and padding */
  size?: 'sm' | 'md'
}

const SIZE_CLASSES: Record<'sm' | 'md', string> = {
  sm: 'text-xs px-2 py-0.5',
  md: 'text-sm px-3 py-1',
}

/**
 * Renders a status chip using the centralised STATUS_CONFIG colour map.
 * Falls back to a neutral gray style for unknown status keys.
 */
export default function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? {
    label: status?.toUpperCase() ?? 'UNKNOWN',
    color: 'text-gray-500',
    bg: 'bg-gray-100',
  }

  return (
    <Chip
      className={`${config.color} ${config.bg} ${SIZE_CLASSES[size]} rounded-full font-medium`}
      colors={{
        fillBgIos: config.bg,
        fillBgMaterial: config.bg,
        fillTextIos: config.color,
        fillTextMaterial: config.color,
      }}
    >
      {config.label}
    </Chip>
  )
}
