import React from 'react'

interface VisuallyHiddenProps {
  /** Content visible only to screen readers */
  children: React.ReactNode
  /** Render as a different element. Defaults to "span". */
  as?: keyof React.JSX.IntrinsicElements
}

/**
 * Renders content that is visually hidden but accessible to screen readers.
 * Uses the standard sr-only technique (clip-rect) rather than display:none
 * so assistive technology can still read the content.
 *
 * Validates: Requirements 57.2
 */
export function VisuallyHidden({ children, as: Tag = 'span' }: VisuallyHiddenProps) {
  return (
    <Tag
      className="sr-only"
      style={{
        position: 'absolute',
        width: '1px',
        height: '1px',
        padding: 0,
        margin: '-1px',
        overflow: 'hidden',
        clip: 'rect(0, 0, 0, 0)',
        whiteSpace: 'nowrap',
        borderWidth: 0,
      }}
    >
      {children}
    </Tag>
  )
}
