import { useState, useEffect } from 'react'

/**
 * useTabHash - sync the active tab with `window.location.hash`.
 *
 * Reads the hash on first render and falls back to `defaultTab` when the hash
 * does not match one of the supplied valid tab values. Calling the returned
 * setter both updates local state and writes the new tab to the URL hash so
 * the active tab survives a page refresh and is shareable via URL.
 *
 * Also listens for `hashchange` so browser back/forward navigation keeps the
 * UI in sync.
 */
export function useTabHash<T extends string>(
  defaultTab: T,
  validTabs: T[]
): [T, (tab: T) => void] {
  const [activeTab, setActiveTab] = useState<T>(() => {
    const hash = window.location.hash.replace('#', '') as T
    return validTabs.includes(hash) ? hash : defaultTab
  })

  // Sync hash when tab changes
  const updateTab = (tab: T) => {
    setActiveTab(tab)
    if (validTabs.includes(tab)) {
      window.location.hash = tab
    }
  }

  // Listen for browser back/forward
  useEffect(() => {
    const handler = () => {
      const hash = window.location.hash.replace('#', '') as T
      if (validTabs.includes(hash)) {
        setActiveTab(hash)
      } else {
        setActiveTab(defaultTab)
      }
    }
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultTab, JSON.stringify(validTabs)])

  return [activeTab, updateTab]
}
