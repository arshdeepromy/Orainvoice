import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  BlockTitle,
  Preloader,
  Segmented,
  SegmentedButton,
  Card,
  Sheet,
  Button,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface StockItem {
  id: string
  name: string
  sku: string | null
  stock_level: number
  sell_price: number
  brand: string | null
  category: string | null
  reorder_level: number | null
  supplier: string | null
  description: string | null
  unit_price: number
}

type InventoryTab = 'stock' | 'usage' | 'log' | 'reorder' | 'suppliers'

const PAGE_SIZE = 25

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function stockColor(level: number): string {
  if (level <= 0) return 'text-red-600 dark:text-red-400'
  if (level <= 5) return 'text-amber-600 dark:text-amber-400'
  return 'text-green-600 dark:text-green-400'
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function InventoryContent() {
  const [activeTab, setActiveTab] = useState<InventoryTab>('stock')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<StockItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedItem, setSelectedItem] = useState<StockItem | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  const fetchStock = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = {
          offset: 0,
          limit: PAGE_SIZE,
        }
        if (search.trim()) params.search = search.trim()

        const res = await apiClient.get<{ items?: StockItem[]; total?: number }>(
          '/api/v1/inventory/stock-items',
          { params, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load inventory')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [search],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchStock(false, controller.signal)
    return () => controller.abort()
  }, [fetchStock])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchStock(true, controller.signal)
  }, [fetchStock])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  const openDetail = useCallback((item: StockItem) => {
    setSelectedItem(item)
    setDetailOpen(true)
  }, [])

  const TABS: { key: InventoryTab; label: string }[] = [
    { key: 'stock', label: 'Stock' },
    { key: 'usage', label: 'Usage' },
    { key: 'log', label: 'Log' },
    { key: 'reorder', label: 'Alerts' },
    { key: 'suppliers', label: 'Suppliers' },
  ]

  if (isLoading && items.length === 0 && activeTab === 'stock') {
    return (
      <Page data-testid="inventory-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="inventory-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Tabs */}
          <Block className="!mt-2 !mb-0">
            <Segmented strong>
              {TABS.map((tab) => (
                <SegmentedButton
                  key={tab.key}
                  active={activeTab === tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  data-testid={`tab-${tab.key}`}
                >
                  {tab.label}
                </SegmentedButton>
              ))}
            </Segmented>
          </Block>

          {/* Stock Levels Tab */}
          {activeTab === 'stock' && (
            <>
              <div className="px-4 pt-3">
                <Searchbar
                  value={search}
                  onChange={handleSearchChange}
                  onClear={handleSearchClear}
                  placeholder="Search stock items…"
                  data-testid="inventory-searchbar"
                />
              </div>

              {error && (
                <Block>
                  <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
                    {error}
                    <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">Retry</button>
                  </div>
                </Block>
              )}

              {items.length === 0 && !isLoading ? (
                <Block className="text-center">
                  <p className="text-sm text-gray-400 dark:text-gray-500">No stock items found</p>
                </Block>
              ) : (
                <List strongIos outlineIos dividersIos data-testid="stock-list">
                  {items.map((item) => (
                    <ListItem
                      key={item.id}
                      link
                      onClick={() => openDetail(item)}
                      title={
                        <span className="font-bold text-gray-900 dark:text-gray-100">
                          {item.name ?? 'Unnamed Item'}
                        </span>
                      }
                      subtitle={
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {item.brand ?? ''}{item.brand && item.sku ? ' · ' : ''}{item.sku ? `SKU: ${item.sku}` : ''}
                        </span>
                      }
                      after={
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                            {formatNZD(item.sell_price ?? item.unit_price)}
                          </span>
                          <span className={`text-xs font-medium ${stockColor(item.stock_level ?? 0)}`}>
                            {(item.stock_level ?? 0) <= 0 ? 'Out of stock' : `${item.stock_level} in stock`}
                          </span>
                        </div>
                      }
                      data-testid={`stock-item-${item.id}`}
                    />
                  ))}
                </List>
              )}
            </>
          )}

          {/* Usage History Tab */}
          {activeTab === 'usage' && (
            <Block>
              <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="usage-tab">
                Usage history shows stock consumption across jobs and invoices.
              </p>
            </Block>
          )}

          {/* Update Log Tab */}
          {activeTab === 'log' && (
            <Block>
              <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="log-tab">
                Stock update log tracks all adjustments and changes.
              </p>
            </Block>
          )}

          {/* Reorder Alerts Tab */}
          {activeTab === 'reorder' && (
            <>
              <BlockTitle data-testid="reorder-tab">Reorder Alerts</BlockTitle>
              {items.filter((i) => (i.stock_level ?? 0) <= (i.reorder_level ?? 0)).length === 0 ? (
                <Block className="text-center">
                  <p className="text-sm text-gray-400 dark:text-gray-500">No reorder alerts</p>
                </Block>
              ) : (
                <div className="px-4 flex flex-col gap-2">
                  {items
                    .filter((i) => (i.stock_level ?? 0) <= (i.reorder_level ?? 0))
                    .map((item) => (
                      <Card key={item.id} className="border-2 border-red-300 dark:border-red-700" data-testid={`reorder-alert-${item.id}`}>
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{item.name}</p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">
                              Stock: {item.stock_level ?? 0} / Reorder at: {item.reorder_level ?? 0}
                            </p>
                          </div>
                          {item.supplier && (
                            <span className="text-xs text-gray-500 dark:text-gray-400">{item.supplier}</span>
                          )}
                        </div>
                      </Card>
                    ))}
                </div>
              )}
            </>
          )}

          {/* Suppliers Tab */}
          {activeTab === 'suppliers' && (
            <Block>
              <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="suppliers-tab">
                Supplier directory for inventory procurement.
              </p>
            </Block>
          )}
        </div>
      </PullRefresh>

      {/* Stock Item Detail Sheet */}
      <Sheet
        opened={detailOpen}
        onBackdropClick={() => setDetailOpen(false)}
        data-testid="stock-detail-sheet"
      >
        {selectedItem && (
          <div className="p-4">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                {selectedItem.name}
              </h2>
              <button type="button" onClick={() => setDetailOpen(false)} className="text-sm text-blue-600 dark:text-blue-400">
                Close
              </button>
            </div>
            <div className="flex flex-col gap-3 text-sm">
              {selectedItem.sku && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">SKU</span>
                  <span className="text-gray-900 dark:text-gray-100">{selectedItem.sku}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Stock Level</span>
                <span className={`font-medium ${stockColor(selectedItem.stock_level ?? 0)}`}>
                  {selectedItem.stock_level ?? 0}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Sell Price</span>
                <span className="text-gray-900 dark:text-gray-100">{formatNZD(selectedItem.sell_price ?? selectedItem.unit_price)}</span>
              </div>
              {selectedItem.brand && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Brand</span>
                  <span className="text-gray-900 dark:text-gray-100">{selectedItem.brand}</span>
                </div>
              )}
              {selectedItem.category && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Category</span>
                  <span className="text-gray-900 dark:text-gray-100">{selectedItem.category}</span>
                </div>
              )}
              {selectedItem.supplier && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Supplier</span>
                  <span className="text-gray-900 dark:text-gray-100">{selectedItem.supplier}</span>
                </div>
              )}
              {selectedItem.description && (
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Description</span>
                  <p className="mt-1 text-gray-700 dark:text-gray-300">{selectedItem.description}</p>
                </div>
              )}
            </div>
            <div className="mt-4">
              <Button large className="k-color-primary" data-testid="adjust-stock-btn">
                Adjust Stock
              </Button>
            </div>
          </div>
        )}
      </Sheet>
    </Page>
  )
}

/**
 * Inventory screen — Konsta tabs: Stock Levels, Usage History, Update Log,
 * Reorder Alerts, Suppliers. ModuleGate `inventory`.
 *
 * Requirements: 31.1, 31.2, 31.3, 31.4, 31.5, 55.1
 */
export default function InventoryListScreen() {
  return (
    <ModuleGate moduleSlug="inventory">
      <InventoryContent />
    </ModuleGate>
  )
}
