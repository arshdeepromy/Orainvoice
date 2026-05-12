/**
 * Divider — horizontal rule with an optional centred label.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface DividerProps {
  label: string
}

export const DividerComponent: ComponentConfig<DividerProps> = {
  label: 'Divider',
  fields: {
    label: { type: 'text', label: 'Label (optional)' },
  },
  defaultProps: {
    label: '',
  },
  render: ({ label }) => {
    if (!label) {
      return <hr className="mx-auto my-8 max-w-7xl border-t border-gray-200" />
    }
    return (
      <div className="mx-auto my-8 flex max-w-7xl items-center gap-4">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          {label}
        </span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>
    )
  },
}
