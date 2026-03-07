import { useState, useRef, useEffect, useCallback } from 'react'

interface DropdownItem {
  id: string
  label: string
  onClick: () => void
  disabled?: boolean
}

interface DropdownProps {
  trigger: React.ReactNode
  items: DropdownItem[]
  label: string
  className?: string
}

export function Dropdown({ trigger, items, label, className = '' }: DropdownProps) {
  const [open, setOpen] = useState(false)
  const [focusedIndex, setFocusedIndex] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])

  const close = useCallback(() => {
    setOpen(false)
    setFocusedIndex(-1)
  }, [])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close()
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open, close])

  useEffect(() => {
    if (focusedIndex >= 0 && itemRefs.current[focusedIndex]) {
      itemRefs.current[focusedIndex]?.focus()
    }
  }, [focusedIndex])

  const handleTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setOpen(true)
      setFocusedIndex(0)
    }
  }

  const handleMenuKeyDown = (e: React.KeyboardEvent) => {
    const enabledItems = items.map((item, i) => ({ item, i })).filter(({ item }) => !item.disabled)

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      const currentEnabledIdx = enabledItems.findIndex(({ i }) => i === focusedIndex)
      const next = enabledItems[(currentEnabledIdx + 1) % enabledItems.length]
      setFocusedIndex(next.i)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const currentEnabledIdx = enabledItems.findIndex(({ i }) => i === focusedIndex)
      const prev = enabledItems[(currentEnabledIdx - 1 + enabledItems.length) % enabledItems.length]
      setFocusedIndex(prev.i)
    } else if (e.key === 'Escape') {
      close()
    } else if (e.key === 'Home') {
      e.preventDefault()
      if (enabledItems.length) setFocusedIndex(enabledItems[0].i)
    } else if (e.key === 'End') {
      e.preventDefault()
      if (enabledItems.length) setFocusedIndex(enabledItems[enabledItems.length - 1].i)
    }
  }

  return (
    <div ref={containerRef} className={`relative inline-block ${className}`}>
      <button
        onClick={() => setOpen(!open)}
        onKeyDown={handleTriggerKeyDown}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={label}
        className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          onKeyDown={handleMenuKeyDown}
          className="absolute right-0 z-40 mt-1 min-w-[10rem] rounded-md border border-gray-200 bg-white py-1 shadow-lg"
        >
          {items.map((item, i) => (
            <button
              key={item.id}
              ref={(el) => { itemRefs.current[i] = el }}
              role="menuitem"
              tabIndex={focusedIndex === i ? 0 : -1}
              disabled={item.disabled}
              onClick={() => {
                item.onClick()
                close()
              }}
              className="w-full px-4 py-2 text-left text-sm text-gray-700
                hover:bg-gray-100 focus-visible:bg-gray-100
                focus-visible:outline-none
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
