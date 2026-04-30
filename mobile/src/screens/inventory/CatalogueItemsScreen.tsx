import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  Preloader,
  Segmented,
  SegmentedButton,
  Chip,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface CatalogueItem {
  id: string
  name: string
  description: string | null
  default_price: number
  gst_applicable: boolean
  category: string | null
  type: string | null
}

interface LabourRate {
  id: string
  name: string
  rate: number
  description: string | null
}

interface ServiceType {
  id: string
  name: string
  description: string | null
  default_price: number | null
}

type CatalogueTab = 'items' | 'labour' | 'services'

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

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function CatalogueContent() {
  const [activeTab, setActiveTab] = useState<CatalogueTab>('items')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<CatalogueItem[]>([])
  const [labourRates, setLabourRates] = useState<LabourRate[]>([])
  const [serviceTypes, setServiceTypes] = useState<ServiceType[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = { offset: 0, limit: PAGE_SIZE }
        if (search.trim()) params.search = search.trim()

        const [itemsRes, labourRes, servicesRes] = await Promise.allSettled([
          apiClient.get<{ items?: CatalogueItem[]; total?: number }>('/api/v1/catalogue/items', { params, signal }),
          apiClient.get<{ items?: LabourRate[]; total?: number }>('/api/v1/catalogue/labour-rates', { params: { offset: 0, limit: 100 }, signal }),
          apiClient.get<{ items?: ServiceType[]; total?: number }>('/api/v1/catalogue/service-types', { params: { offset: 0, limit: 100 }, signal }),
        ])

        if (itemsRes.status === 'fulfilled') setItems(itemsRes.value.data?.items ?? [])
        if (labourRes.status === 'fulfilled') setLabourRates(labourRes.value.data?.items ?? [])
        if (servicesRes.status === 'fulfilled') setServiceTypes(servicesRes.value.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load catalogue')
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
    fetchData(false, controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchData(true, controller.signal)
  }, [fetchData])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  const TABS: { key: CatalogueTab; label: string }[] = [
    { key: 'items', label: 'Items' },
    { key: 'labour', label: 'Labour Rates' },
    { key: 'services', label: 'Service Types' },
  ]

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="catalogue-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="catalogue-page">
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

          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search catalogue…"
              data-testid="catalogue-searchbar"
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

          {/* Items Tab */}
          {activeTab === 'items' && (
            items.length === 0 ? (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">No catalogue items found</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="catalogue-items-list">
                {items.map((item) => (
                  <ListItem
                    key={item.id}
                    link
                    title={
                      <span className="font-bold text-gray-900 dark:text-gray-100">
                        {item.name ?? 'Unnamed'}
                      </span>
                    }
                    subtitle={
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {item.category ?? 'General'}
                      </span>
                    }
                    after={
                      <div className="flex flex-col items-end gap-1">
                        <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                          {formatNZD(item.default_price)}
                        </span>
                        {item.gst_applicable && (
                          <Chip className="text-xs" colors={{ fillBgIos: 'bg-blue-100', fillBgMaterial: 'bg-blue-100', fillTextIos: 'text-blue-700', fillTextMaterial: 'text-blue-700' }}>
                            GST
                          </Chip>
                        )}
                      </div>
                    }
                    data-testid={`catalogue-item-${item.id}`}
                  />
                ))}
              </List>
            )
          )}

          {/* Labour Rates Tab */}
          {activeTab === 'labour' && (
            labourRates.length === 0 ? (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">No labour rates found</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="labour-rates-list">
                {labourRates.map((rate) => (
                  <ListItem
                    key={rate.id}
                    title={
                      <span className="font-bold text-gray-900 dark:text-gray-100">
                        {rate.name ?? 'Labour'}
                      </span>
                    }
                    subtitle={
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {rate.description ?? ''}
                      </span>
                    }
                    after={
                      <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                        {formatNZD(rate.rate)}/hr
                      </span>
                    }
                    data-testid={`labour-rate-${rate.id}`}
                  />
                ))}
              </List>
            )
          )}

          {/* Service Types Tab */}
          {activeTab === 'services' && (
            serviceTypes.length === 0 ? (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">No service types found</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="service-types-list">
                {serviceTypes.map((svc) => (
                  <ListItem
                    key={svc.id}
                    title={
                      <span className="font-bold text-gray-900 dark:text-gray-100">
                        {svc.name ?? 'Service'}
                      </span>
                    }
                    subtitle={
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {svc.description ?? ''}
                      </span>
                    }
                    after={
                      svc.default_price != null ? (
                        <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                          {formatNZD(svc.default_price)}
                        </span>
                      ) : undefined
                    }
                    data-testid={`service-type-${svc.id}`}
                  />
                ))}
              </List>
            )
          )}
        </div>
      </PullRefresh>

      {/* FAB for + Add Item */}
      <KonstaFAB label="+ Add Item" onClick={() => {/* open create sheet */}} />
    </Page>
  )
}

/**
 * Catalogue Items screen — tabs: Items, Labour Rates, Service Types.
 * FAB for "+ Add Item". ModuleGate `inventory`.
 *
 * Requirements: 32.1, 32.2, 32.3, 32.4, 32.5, 55.1
 */
export default function CatalogueItemsScreen() {
  return (
    <ModuleGate moduleSlug="inventory">
      <CatalogueContent />
    </ModuleGate>
  )
}
