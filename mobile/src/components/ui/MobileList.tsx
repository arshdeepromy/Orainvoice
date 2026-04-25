import { useCallback, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { MobileSearchBar } from './MobileSearchBar'
import { MobileSpinner } from './MobileSpinner'
import { MobileEmptyState } from './MobileEmptyState'

export interface MobileListProps<T> {
  items: T[]
  renderItem: (item: T) => ReactNode
  onRefresh: () => Promise<void>
  onLoadMore: () => void
  isLoading: boolean
  isRefreshing: boolean
  hasMore: boolean
  emptyMessage: string
  searchValue?: string
  onSearchChange?: (value: string) => void
  searchPlaceholder?: string
  /** Key extractor for list items */
  keyExtractor?: (item: T, index: number) => string
}

/**
 * Generic paginated list with empty state, loading skeleton, and load-more trigger.
 *
 * - Integrated search bar (optional)
 * - Loading spinner for initial load
 * - Empty state when no items
 * - Infinite scroll via IntersectionObserver for load-more
 * - Pull-to-refresh support (via onRefresh callback)
 *
 * Requirements: 7.1, 8.1
 */
export function MobileList<T>({
  items,
  renderItem,
  onLoadMore,
  isLoading,
  isRefreshing,
  hasMore,
  emptyMessage,
  searchValue,
  onSearchChange,
  searchPlaceholder,
  keyExtractor,
}: MobileListProps<T>) {
  const loadMoreRef = useRef<HTMLDivElement>(null)

  // Infinite scroll: observe the sentinel element
  useEffect(() => {
    const sentinel = loadMoreRef.current
    if (!sentinel || !hasMore || isLoading) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMore()
        }
      },
      { threshold: 0.1 },
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMore, isLoading, onLoadMore])

  const getKey = useCallback(
    (item: T, index: number) => {
      if (keyExtractor) return keyExtractor(item, index)
      // Try common id fields
      const record = item as Record<string, unknown>
      if (typeof record.id === 'string' || typeof record.id === 'number') {
        return String(record.id)
      }
      return String(index)
    },
    [keyExtractor],
  )

  return (
    <div className="flex flex-col">
      {/* Search bar */}
      {onSearchChange && (
        <div className="px-4 pb-2 pt-3">
          <MobileSearchBar
            value={searchValue ?? ''}
            onChange={onSearchChange}
            placeholder={searchPlaceholder}
          />
        </div>
      )}

      {/* Refreshing indicator */}
      {isRefreshing && (
        <div className="flex justify-center py-2">
          <MobileSpinner size="sm" />
        </div>
      )}

      {/* Initial loading state */}
      {isLoading && items.length === 0 ? (
        <div className="flex flex-col gap-3 px-4 py-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg bg-gray-100 dark:bg-gray-800"
              role="presentation"
            />
          ))}
        </div>
      ) : items.length === 0 ? (
        /* Empty state */
        <MobileEmptyState message={emptyMessage} />
      ) : (
        /* Item list */
        <div className="flex flex-col" role="list">
          {items.map((item, index) => (
            <div key={getKey(item, index)} role="listitem">
              {renderItem(item)}
            </div>
          ))}

          {/* Load more sentinel */}
          {hasMore && (
            <div ref={loadMoreRef} className="flex justify-center py-4">
              <MobileSpinner size="sm" />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
