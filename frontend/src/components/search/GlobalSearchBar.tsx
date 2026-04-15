import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'

/* ── Types ── */

interface CustomerResult {
  id: string
  first_name: string
  last_name: string
  email?: string
  phone?: string
}

interface VehicleResult {
  id: string
  rego: string
  make?: string
  model?: string
  year?: number
}

interface InvoiceResult {
  id: string
  invoice_number: string
  customer_name?: string
  rego?: string
  total: number
  status: string
}

interface SearchResults {
  customers: CustomerResult[]
  vehicles: VehicleResult[]
  invoices: InvoiceResult[]
}

interface FlatItem {
  type: 'customer' | 'vehicle' | 'invoice'
  id: string
  label: string
  detail: string
  path: string
}

/* ── Helpers ── */

function flattenResults(results: SearchResults): FlatItem[] {
  const items: FlatItem[] = []

  for (const c of results.customers) {
    items.push({
      type: 'customer',
      id: c.id,
      label: `${c.first_name} ${c.last_name}`,
      detail: [c.phone, c.email].filter(Boolean).join(' · '),
      path: `/customers/${c.id}`,
    })
  }

  for (const v of results.vehicles) {
    items.push({
      type: 'vehicle',
      id: v.id,
      label: v.rego,
      detail: [v.make, v.model, v.year].filter(Boolean).join(' '),
      path: `/vehicles/${v.id}`,
    })
  }

  for (const inv of results.invoices) {
    items.push({
      type: 'invoice',
      id: inv.id,
      label: inv.invoice_number,
      detail: [inv.customer_name, inv.rego, inv.status].filter(Boolean).join(' · '),
      path: `/invoices/${inv.id}`,
    })
  }

  return items
}

const sectionLabels: Record<FlatItem['type'], string> = {
  customer: 'Customers',
  vehicle: 'Vehicles',
  invoice: 'Invoices',
}

const sectionIcons: Record<FlatItem['type'], string> = {
  customer: '👤',
  vehicle: '🚗',
  invoice: '📄',
}

/* ── Component ── */

export function GlobalSearchBar() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResults | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const abortRef = useRef<AbortController>(undefined)
  const navigate = useNavigate()

  const flatItems = useMemo(
    () => (results ? flattenResults(results) : []),
    [results],
  )

  /* ── Keyboard shortcut: Ctrl/Cmd+K ── */
  useEffect(() => {
    function handleGlobalKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    document.addEventListener('keydown', handleGlobalKey)
    return () => document.removeEventListener('keydown', handleGlobalKey)
  }, [])

  /* ── Focus input when opened ── */
  useEffect(() => {
    if (open) {
      // Small delay so the DOM is ready
      requestAnimationFrame(() => inputRef.current?.focus())
    } else {
      setQuery('')
      setResults(null)
      setActiveIndex(0)
    }
  }, [open])

  /* ── Debounced search ── */
  const search = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults(null)
      setLoading(false)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)

    try {
      const [customers, vehicles, invoices] = await Promise.all([
        apiClient
          .get<CustomerResult[]>('/customers', {
            params: { search: q, limit: 5 },
            signal: controller.signal,
          })
          .then((r) => r.data)
          .catch(() => [] as CustomerResult[]),
        apiClient
          .get<VehicleResult[]>('/vehicles', {
            params: { search: q, limit: 5 },
            signal: controller.signal,
          })
          .then((r) => r.data)
          .catch(() => [] as VehicleResult[]),
        apiClient
          .get<InvoiceResult[]>('/invoices', {
            params: { search: q, limit: 5 },
            signal: controller.signal,
          })
          .then((r) => r.data)
          .catch(() => [] as InvoiceResult[]),
      ])

      if (!controller.signal.aborted) {
        setResults({ customers, vehicles, invoices })
        setActiveIndex(0)
      }
    } catch {
      // aborted or network error — ignore
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [])

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value)
      clearTimeout(debounceRef.current)
      if (value.trim().length < 2) {
        setResults(null)
        setLoading(false)
        return
      }
      setLoading(true)
      debounceRef.current = setTimeout(() => search(value), 300)
    },
    [search],
  )

  /* ── Cleanup on unmount ── */
  useEffect(() => {
    return () => {
      clearTimeout(debounceRef.current)
      abortRef.current?.abort()
    }
  }, [])

  /* ── Navigate to result ── */
  const selectItem = useCallback(
    (item: FlatItem) => {
      setOpen(false)
      navigate(item.path)
    },
    [navigate],
  )

  /* ── Keyboard navigation inside the list ── */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        return
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIndex((i) => Math.min(i + 1, flatItems.length - 1))
        return
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIndex((i) => Math.max(i - 1, 0))
        return
      }

      if (e.key === 'Enter' && flatItems[activeIndex]) {
        e.preventDefault()
        selectItem(flatItems[activeIndex])
      }
    },
    [flatItems, activeIndex, selectItem],
  )

  /* ── Scroll active item into view ── */
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${activeIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (!open) return null

  /* ── Build grouped sections for rendering ── */
  const sections: { type: FlatItem['type']; items: FlatItem[]; startIndex: number }[] = []
  let idx = 0
  for (const type of ['customer', 'vehicle', 'invoice'] as const) {
    const items = flatItems.filter((i) => i.type === type)
    if (items.length > 0) {
      sections.push({ type, items, startIndex: idx })
      idx += items.length
    }
  }

  const listboxId = 'global-search-listbox'
  const activeItemId = flatItems[activeIndex]
    ? `search-item-${flatItems[activeIndex].type}-${flatItems[activeIndex].id}`
    : undefined

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/50"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      {/* Search dialog */}
      <div
        className="fixed inset-x-0 top-[15%] z-50 mx-auto w-full max-w-lg px-4"
        role="dialog"
        aria-label="Global search"
        aria-modal="true"
      >
        <div className="overflow-hidden rounded-xl bg-white shadow-2xl ring-1 ring-gray-200">
          {/* Input */}
          <div className="flex items-center gap-3 border-b border-gray-200 px-4">
            <SearchIcon />
            <input
              ref={inputRef}
              type="text"
              className="flex-1 border-0 bg-transparent py-3 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none"
              placeholder="Search customers, vehicles, invoices…"
              value={query}
              onChange={(e) => handleQueryChange(e.target.value)}
              onKeyDown={handleKeyDown}
              role="combobox"
              aria-expanded={flatItems.length > 0}
              aria-controls={listboxId}
              aria-activedescendant={activeItemId}
              aria-autocomplete="list"
              aria-label="Search"
            />
            {loading && <Spinner size="sm" label="Searching" />}
            <kbd className="rounded border border-gray-300 bg-gray-50 px-1.5 py-0.5 text-xs text-gray-400">
              Esc
            </kbd>
          </div>

          {/* Results */}
          <ul
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label="Search results"
            className="max-h-80 overflow-y-auto"
          >
            {sections.map((section) => (
              <li key={section.type} role="presentation">
                <div className="sticky top-0 bg-gray-50 px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  {sectionIcons[section.type]} {sectionLabels[section.type]}
                </div>
                <ul role="group" aria-label={sectionLabels[section.type]}>
                  {section.items.map((item, i) => {
                    const globalIdx = section.startIndex + i
                    const isActive = globalIdx === activeIndex
                    return (
                      <li
                        key={`${item.type}-${item.id}`}
                        id={`search-item-${item.type}-${item.id}`}
                        role="option"
                        aria-selected={isActive}
                        data-index={globalIdx}
                        className={`flex cursor-pointer items-center gap-3 px-4 py-2 text-sm transition-colors ${
                          isActive ? 'bg-blue-50 text-blue-900' : 'text-gray-700 hover:bg-gray-100'
                        }`}
                        onClick={() => selectItem(item)}
                        onMouseEnter={() => setActiveIndex(globalIdx)}
                      >
                        <span className="font-medium truncate">{item.label}</span>
                        {item.detail && (
                          <span className="truncate text-gray-400">{item.detail}</span>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </li>
            ))}
          </ul>

          {/* Empty / idle states */}
          {!loading && query.trim().length >= 2 && flatItems.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-gray-500">
              No results found for "{query}"
            </div>
          )}

          {!loading && query.trim().length < 2 && (
            <div className="px-4 py-6 text-center text-sm text-gray-400">
              Type at least 2 characters to search
            </div>
          )}

          {/* Footer hint */}
          <div className="flex items-center gap-4 border-t border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-400">
            <span>
              <kbd className="rounded border border-gray-300 bg-white px-1 py-0.5">↑↓</kbd> navigate
            </span>
            <span>
              <kbd className="rounded border border-gray-300 bg-white px-1 py-0.5">↵</kbd> select
            </span>
            <span>
              <kbd className="rounded border border-gray-300 bg-white px-1 py-0.5">esc</kbd> close
            </span>
          </div>
        </div>
      </div>
    </>
  )
}

/* ── Inline icon ── */

function SearchIcon() {
  return (
    <svg
      className="h-5 w-5 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
      />
    </svg>
  )
}
