import { useState, useId } from 'react'

interface CollapsibleProps {
  label: string
  defaultOpen?: boolean
  children: React.ReactNode
  className?: string
}

export function Collapsible({
  label,
  defaultOpen = false,
  children,
  className = '',
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  const contentId = `${id}-content`

  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-controls={contentId}
        className="flex w-full items-center justify-between rounded-md px-4 py-3 text-left text-sm font-medium text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 transition-colors"
      >
        <span>{label}</span>
        <svg
          className={`h-5 w-5 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>
      <div
        id={contentId}
        role="region"
        aria-labelledby={undefined}
        hidden={!open}
        className="px-4 pb-3 pt-1"
      >
        {children}
      </div>
    </div>
  )
}
