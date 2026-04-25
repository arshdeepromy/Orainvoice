import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { InventoryItem } from '@shared/types/inventory'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function stockLabel(level: number): string {
  if (level <= 0) return 'Out of stock'
  if (level <= 5) return `Low: ${level}`
  return `${level} in stock`
}

function stockColor(level: number): string {
  if (level <= 0) return 'text-red-600 dark:text-red-400'
  if (level <= 5) return 'text-amber-600 dark:text-amber-400'
  return 'text-green-600 dark:text-green-400'
}

/**
 * Inventory list screen — searchable list with name, SKU, stock level, price.
 * Pull-to-refresh. Wrapped in ModuleGate at the route level.
 *
 * Requirements: 17.1, 17.2, 17.4
 */
export default function InventoryListScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<InventoryItem>({
    endpoint: '/api/v1/inventory',
    dataKey: 'items',
  })

  const handleTap = useCallback(
    (item: InventoryItem) => {
      navigate(`/inventory/${item.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (item: InventoryItem) => {
      const stock = item.stock_level ?? 0

      return (
        <MobileListItem
          title={item.name ?? 'Unnamed Item'}
          subtitle={item.sku ? `SKU: ${item.sku}` : undefined}
          trailing={
            <div className="flex flex-col items-end gap-1">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {formatCurrency(item.unit_price)}
              </span>
              <span className={`text-xs font-medium ${stockColor(stock)}`}>
                {stockLabel(stock)}
              </span>
            </div>
          }
          onTap={() => handleTap(item)}
        />
      )
    },
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Inventory
          </h1>
        </div>

        <MobileList<InventoryItem>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No inventory items found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search by name or SKU…"
          keyExtractor={(item) => item.id}
        />
      </div>
    </PullRefresh>
  )
}
