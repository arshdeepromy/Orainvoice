/**
 * Spacer — inserts blank vertical space between stacked components.
 */
import type { ComponentConfig } from '@puckeditor/core'

export type SpacerHeight = 'sm' | 'md' | 'lg' | 'xl'

export interface SpacerProps {
  height: SpacerHeight
}

const HEIGHT_CLASSES: Record<SpacerHeight, string> = {
  sm: 'h-4',
  md: 'h-8',
  lg: 'h-16',
  xl: 'h-32',
}

export const SpacerComponent: ComponentConfig<SpacerProps> = {
  label: 'Spacer',
  fields: {
    height: {
      type: 'select',
      label: 'Height',
      options: [
        { label: 'Small (1rem)', value: 'sm' },
        { label: 'Medium (2rem)', value: 'md' },
        { label: 'Large (4rem)', value: 'lg' },
        { label: 'Extra large (8rem)', value: 'xl' },
      ],
    },
  },
  defaultProps: {
    height: 'md',
  },
  render: ({ height }) => {
    const cls = HEIGHT_CLASSES[height] ?? HEIGHT_CLASSES.md
    return <div aria-hidden="true" className={cls} />
  },
}
