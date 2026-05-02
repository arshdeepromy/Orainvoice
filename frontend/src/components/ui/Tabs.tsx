import { useState, useRef, useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

interface Tab {
  id: string
  label: string
  content: React.ReactNode
}

interface TabsProps {
  tabs: Tab[]
  defaultTab?: string
  className?: string
  /** When true, syncs the active tab with the URL ?tab= search param */
  urlPersist?: boolean
}

export function Tabs({ tabs, defaultTab, className = '', urlPersist = false }: TabsProps) {
  const [searchParams, setSearchParams] = useSearchParams()

  const urlTab = urlPersist ? searchParams.get('tab') : null
  const initial = (urlTab && tabs.some((t) => t.id === urlTab)) ? urlTab : (defaultTab || tabs[0]?.id || '')

  const [activeTab, setActiveTab] = useState(initial)
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map())

  // Sync from URL changes (browser back/forward)
  useEffect(() => {
    if (!urlPersist) return
    const paramTab = searchParams.get('tab')
    if (paramTab && tabs.some((t) => t.id === paramTab) && paramTab !== activeTab) {
      setActiveTab(paramTab)
    }
  }, [searchParams, urlPersist, tabs]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectTab = useCallback(
    (id: string) => {
      setActiveTab(id)
      if (urlPersist) {
        setSearchParams((prev: URLSearchParams) => {
          const next = new URLSearchParams(prev)
          next.set('tab', id)
          return next
        }, { replace: true })
      }
    },
    [urlPersist, setSearchParams],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const currentIndex = tabs.findIndex((t) => t.id === activeTab)
      let nextIndex = currentIndex

      if (e.key === 'ArrowRight') {
        nextIndex = (currentIndex + 1) % tabs.length
      } else if (e.key === 'ArrowLeft') {
        nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
      } else if (e.key === 'Home') {
        nextIndex = 0
      } else if (e.key === 'End') {
        nextIndex = tabs.length - 1
      } else {
        return
      }

      e.preventDefault()
      const nextTab = tabs[nextIndex]
      selectTab(nextTab.id)
      tabRefs.current.get(nextTab.id)?.focus()
    },
    [activeTab, tabs, selectTab],
  )

  const activeContent = tabs.find((t) => t.id === activeTab)?.content

  return (
    <div className={className}>
      <div role="tablist" aria-label="Tabs" className="flex border-b border-gray-200 no-print">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            ref={(el) => {
              if (el) tabRefs.current.set(tab.id, el)
            }}
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`tabpanel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => selectTab(tab.id)}
            onKeyDown={handleKeyDown}
            className={`px-4 py-2 text-sm font-medium transition-colors
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset
              ${
                activeTab === tab.id
                  ? 'border-b-2 text-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            style={activeTab === tab.id ? {
              borderBottomColor: 'var(--portal-accent, #2563eb)',
              color: 'var(--portal-accent, #2563eb)',
            } : undefined}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`tabpanel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        tabIndex={0}
        className="py-4"
      >
        {activeContent}
      </div>
    </div>
  )
}
