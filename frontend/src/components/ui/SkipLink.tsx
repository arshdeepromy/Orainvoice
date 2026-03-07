import { skipToContent } from '../../utils/accessibility'

interface SkipLinkProps {
  /** The id of the target element to skip to. Defaults to "main-content". */
  targetId?: string
  /** Link text. Defaults to "Skip to main content". */
  children?: React.ReactNode
}

/**
 * A skip navigation link that becomes visible on focus.
 * Allows keyboard users to bypass repetitive navigation.
 *
 * Validates: Requirements 57.1
 */
export function SkipLink({ targetId = 'main-content', children = 'Skip to main content' }: SkipLinkProps) {
  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    skipToContent(targetId)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      skipToContent(targetId)
    }
  }

  return (
    <a
      href={`#${targetId}`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[9999]
        focus:rounded-md focus:bg-blue-600 focus:px-4 focus:py-2 focus:text-white focus:shadow-lg
        focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
    >
      {children}
    </a>
  )
}
