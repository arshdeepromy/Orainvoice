/**
 * Button — single-link CTA button with style, target, and optional
 * `rel="nofollow"` support.
 *
 * Renders as an `<a>` (not `<button>`) because every Puck-editor Button
 * is link-like. Internal paths use React Router's semantics naturally
 * via anchor navigation; hash-only URLs scroll to the anchor.
 */
import type { ComponentConfig } from '@puckeditor/core'

export type ButtonStyle = 'primary' | 'secondary' | 'ghost'
export type ButtonTarget = 'same-tab' | 'new-tab'

export interface ButtonProps {
  label: string
  url: string
  style: ButtonStyle
  target: ButtonTarget
  nofollow: boolean
  align: 'left' | 'center' | 'right'
}

const STYLE_CLASSES: Record<ButtonStyle, string> = {
  primary:
    'inline-flex items-center rounded-lg bg-blue-600 px-6 py-3 text-base font-semibold text-white shadow transition-colors hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2',
  secondary:
    'inline-flex items-center rounded-lg border border-gray-300 bg-white px-6 py-3 text-base font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2',
  ghost:
    'inline-flex items-center rounded-lg px-4 py-3 text-base font-medium text-blue-700 underline-offset-4 transition-colors hover:text-blue-900 hover:underline',
}

const ALIGN_CLASSES: Record<ButtonProps['align'], string> = {
  left: 'justify-start',
  center: 'justify-center',
  right: 'justify-end',
}

export const ButtonComponent: ComponentConfig<ButtonProps> = {
  label: 'Button',
  fields: {
    label: { type: 'text', label: 'Label' },
    url: { type: 'text', label: 'URL' },
    style: {
      type: 'select',
      label: 'Style',
      options: [
        { label: 'Primary', value: 'primary' },
        { label: 'Secondary', value: 'secondary' },
        { label: 'Ghost', value: 'ghost' },
      ],
    },
    target: {
      type: 'radio',
      label: 'Target',
      options: [
        { label: 'Same tab', value: 'same-tab' },
        { label: 'New tab', value: 'new-tab' },
      ],
    },
    nofollow: {
      type: 'radio',
      label: 'Add rel="nofollow"',
      options: [
        { label: 'No', value: false },
        { label: 'Yes', value: true },
      ],
    },
    align: {
      type: 'radio',
      label: 'Align',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Centre', value: 'center' },
        { label: 'Right', value: 'right' },
      ],
    },
  },
  defaultProps: {
    label: 'Get Started',
    url: '/signup',
    style: 'primary',
    target: 'same-tab',
    nofollow: false,
    align: 'left',
  },
  render: ({ label, url, style, target, nofollow, align }) => {
    const styleClass = STYLE_CLASSES[style] ?? STYLE_CLASSES.primary
    const alignClass = ALIGN_CLASSES[align] ?? ALIGN_CLASSES.left
    const isNewTab = target === 'new-tab'
    const relParts: string[] = []
    if (isNewTab) relParts.push('noopener', 'noreferrer')
    if (nofollow) relParts.push('nofollow')
    return (
      <div className={`flex ${alignClass}`}>
        <a
          href={url || '#'}
          className={styleClass}
          target={isNewTab ? '_blank' : undefined}
          rel={relParts.length > 0 ? relParts.join(' ') : undefined}
        >
          {label}
        </a>
      </div>
    )
  },
}
