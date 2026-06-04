/**
 * Heading — renders H1 through H6 with configurable alignment.
 *
 * Single-H1 enforcement (Requirement 7.4):
 * - The first Heading component in a page render that requests level=1
 *   emits `<h1>`; every subsequent component requesting level=1 is
 *   silently demoted to `<h2>` at render time.
 * - H2–H6 requests always render at their requested level.
 * - State is tracked via the `headingCounter` module; PageShell
 *   resets it at the start of each render.
 */
import type { ComponentConfig } from '@puckeditor/core'
import { markH1Seen, shouldEmitH1 } from './headingCounter'

export type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6
export type HeadingAlign = 'left' | 'center' | 'right'

export interface HeadingProps {
  level: HeadingLevel
  text: string
  align: HeadingAlign
}

const ALIGN_CLASSES: Record<HeadingAlign, string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
}

const LEVEL_CLASSES: Record<HeadingLevel, string> = {
  1: 'text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl',
  2: 'text-3xl font-bold tracking-tight sm:text-4xl',
  3: 'text-2xl font-bold sm:text-3xl',
  4: 'text-xl font-semibold sm:text-2xl',
  5: 'text-lg font-semibold',
  6: 'text-base font-semibold uppercase tracking-wider',
}

export const HeadingComponent: ComponentConfig<HeadingProps> = {
  label: 'Heading',
  fields: {
    level: {
      type: 'select',
      label: 'Level',
      options: [
        { label: 'H1', value: 1 },
        { label: 'H2', value: 2 },
        { label: 'H3', value: 3 },
        { label: 'H4', value: 4 },
        { label: 'H5', value: 5 },
        { label: 'H6', value: 6 },
      ],
    },
    text: { type: 'text', label: 'Heading text' },
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
    level: 2,
    text: 'Heading',
    align: 'left',
  },
  render: ({ level, text, align }) => {
    // Enforce single H1: if this heading requests H1 but one has already
    // been emitted this render, demote to H2.
    let effectiveLevel: HeadingLevel = level
    if (level === 1) {
      if (shouldEmitH1()) {
        markH1Seen()
      } else {
        effectiveLevel = 2
      }
    }
    const alignClass = ALIGN_CLASSES[align] ?? ALIGN_CLASSES.left
    const sizeClass = LEVEL_CLASSES[effectiveLevel] ?? LEVEL_CLASSES[2]
    const className = `${sizeClass} ${alignClass} text-gray-900`

    switch (effectiveLevel) {
      case 1:
        return <h1 className={className}>{text}</h1>
      case 2:
        return <h2 className={className}>{text}</h2>
      case 3:
        return <h3 className={className}>{text}</h3>
      case 4:
        return <h4 className={className}>{text}</h4>
      case 5:
        return <h5 className={className}>{text}</h5>
      case 6:
        return <h6 className={className}>{text}</h6>
    }
  },
}
