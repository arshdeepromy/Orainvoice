import { useState, useRef, useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Tabs — accessible tablist primitive (Task 23 port of
 * frontend/src/components/ui/Tabs).
 *
 * PUBLIC API + ALL behaviour are copied VERBATIM from the original: the
 * { id, label, content } tab model, `defaultTab`, optional `urlPersist`
 * (?tab= sync with browser back/forward), and the full roving-tabindex
 * keyboard model (ArrowLeft/ArrowRight/Home/End, Enter/Space implicit via
 * button activation). Only the markup styling is remapped to the prototype's
 * tab language from OraInvoice_Handoff/app/ds.css:
 *   .tabs  flex, gap 4, bottom border.
 *   .tab   11px/14px padding, 13.5px/500 muted text, 2px transparent bottom
 *          border, -1px margin; hover → text; `.on` → accent text + accent
 *          underline. `.tab .n` count → mono, 11px, muted-2.
 */
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
      <div role="tablist" aria-label="Tabs" className="flex gap-1 border-b border-border no-print">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              ref={(el) => {
                if (el) tabRefs.current.set(tab.id, el)
              }}
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => selectTab(tab.id)}
              onKeyDown={handleKeyDown}
              className={`-mb-px border-b-2 px-3.5 py-[11px] text-[13.5px] font-medium transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset
                ${
                  isActive
                    ? 'border-accent text-accent'
                    : 'border-transparent text-muted hover:text-text'
                }`}
            >
              {tab.label}
            </button>
          )
        })}
      </div>
      <div
        role="tabpanel"
        id={`tabpanel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        tabIndex={0}
        className="py-4 focus:outline-none"
      >
        {activeContent}
      </div>
    </div>
  )
}

export default Tabs
