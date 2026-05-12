/**
 * Badge — small coloured pill for labels like "New", "Coming Soon",
 * "NZ exclusive", etc.
 */
import type { ComponentConfig } from '@puckeditor/core'

export type BadgeVariant =
  | 'blue'
  | 'green'
  | 'amber'
  | 'red'
  | 'gray'
  | 'purple'

export interface BadgeProps {
  text: string
  variant: BadgeVariant
}

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  blue: 'bg-blue-100 text-blue-800',
  green: 'bg-emerald-100 text-emerald-800',
  amber: 'bg-amber-100 text-amber-800',
  red: 'bg-red-100 text-red-800',
  gray: 'bg-gray-100 text-gray-800',
  purple: 'bg-purple-100 text-purple-800',
}

export const BadgeComponent: ComponentConfig<BadgeProps> = {
  label: 'Badge',
  fields: {
    text: { type: 'text', label: 'Text' },
    variant: {
      type: 'select',
      label: 'Colour',
      options: [
        { label: 'Blue', value: 'blue' },
        { label: 'Green', value: 'green' },
        { label: 'Amber', value: 'amber' },
        { label: 'Red', value: 'red' },
        { label: 'Gray', value: 'gray' },
        { label: 'Purple', value: 'purple' },
      ],
    },
  },
  defaultProps: {
    text: 'New',
    variant: 'blue',
  },
  render: ({ text, variant }) => {
    const cls = VARIANT_CLASSES[variant] ?? VARIANT_CLASSES.gray
    return (
      <span
        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}
      >
        {text}
      </span>
    )
  },
}
