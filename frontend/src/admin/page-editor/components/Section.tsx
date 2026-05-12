/**
 * Section — generic container with configurable background colour,
 * padding, and max-width. Uses Puck's `slot` field so child components
 * can be dropped inside.
 */
import type { ComponentConfig, Slot } from '@puckeditor/core'

export interface SectionProps {
  background: 'white' | 'gray-50' | 'slate-900' | 'gradient-dark' | 'custom'
  customBackground: string
  padding: 'sm' | 'md' | 'lg' | 'xl'
  maxWidth: 'prose' | 'screen-md' | 'screen-lg' | 'screen-xl' | '7xl' | 'full'
  content: Slot
}

const BACKGROUND_CLASSES: Record<
  Exclude<SectionProps['background'], 'custom'>,
  string
> = {
  white: 'bg-white text-gray-900',
  'gray-50': 'bg-gray-50 text-gray-900',
  'slate-900': 'bg-slate-900 text-white',
  'gradient-dark': 'bg-gradient-to-br from-slate-900 to-indigo-900 text-white',
}

const PADDING_CLASSES: Record<SectionProps['padding'], string> = {
  sm: 'py-8',
  md: 'py-12',
  lg: 'py-16',
  xl: 'py-24',
}

const MAX_WIDTH_CLASSES: Record<SectionProps['maxWidth'], string> = {
  prose: 'max-w-prose',
  'screen-md': 'max-w-screen-md',
  'screen-lg': 'max-w-screen-lg',
  'screen-xl': 'max-w-screen-xl',
  '7xl': 'max-w-7xl',
  full: 'max-w-full',
}

// Matches /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/
const HEX_COLOUR_RE = /^#(?:[0-9a-fA-F]{3}){1,2}$/

export const SectionComponent: ComponentConfig<SectionProps> = {
  label: 'Section',
  fields: {
    background: {
      type: 'select',
      label: 'Background',
      options: [
        { label: 'White', value: 'white' },
        { label: 'Gray 50', value: 'gray-50' },
        { label: 'Slate 900 (dark)', value: 'slate-900' },
        { label: 'Gradient (dark)', value: 'gradient-dark' },
        { label: 'Custom hex colour', value: 'custom' },
      ],
    },
    customBackground: {
      type: 'text',
      label: 'Custom hex colour (used when Background = Custom)',
      placeholder: '#1e293b',
    },
    padding: {
      type: 'select',
      label: 'Vertical padding',
      options: [
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
        { label: 'Extra large', value: 'xl' },
      ],
    },
    maxWidth: {
      type: 'select',
      label: 'Max width',
      options: [
        { label: 'Prose (~65ch)', value: 'prose' },
        { label: 'Medium', value: 'screen-md' },
        { label: 'Large', value: 'screen-lg' },
        { label: 'Extra large', value: 'screen-xl' },
        { label: '7xl (default marketing)', value: '7xl' },
        { label: 'Full width', value: 'full' },
      ],
    },
    content: { type: 'slot' },
  },
  defaultProps: {
    background: 'white',
    customBackground: '',
    padding: 'lg',
    maxWidth: '7xl',
    content: [],
  },
  render: ({ background, customBackground, padding, maxWidth, content: Content }) => {
    const bgClass =
      background === 'custom'
        ? 'text-gray-900'
        : BACKGROUND_CLASSES[background] ?? BACKGROUND_CLASSES.white
    const paddingClass = PADDING_CLASSES[padding] ?? PADDING_CLASSES.lg
    const maxWidthClass = MAX_WIDTH_CLASSES[maxWidth] ?? MAX_WIDTH_CLASSES['7xl']
    const inlineStyle =
      background === 'custom' && HEX_COLOUR_RE.test(customBackground ?? '')
        ? { backgroundColor: customBackground }
        : undefined
    return (
      <section
        className={`${bgClass} px-4 ${paddingClass} sm:px-6 lg:px-8`}
        style={inlineStyle}
      >
        <div className={`mx-auto ${maxWidthClass}`}>
          <Content />
        </div>
      </section>
    )
  },
}
