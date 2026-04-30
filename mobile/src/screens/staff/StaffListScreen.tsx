import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  Preloader,
  Chip,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface StaffMember {
  id: string
  first_name: string | null
  last_name: string | null
  email: string | null
  phone: string | null
  role: string
  branch_name: string | null
  is_active: boolean
}

const PAGE_SIZE = 25

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function displayName(s: StaffMember): string {
  const parts = [s.first_name, s.last_name].filter(Boolean)
  return parts.join(' ') || 'Unnamed'
}

function roleLabel(role: string): string {
  return (role ?? 'staff').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function roleChipColors(role: string) {
  switch (role) {
    case 'owner':
    case 'org_admin':
      return { fillBgIos: 'bg-purple-100', fillBgMaterial: 'bg-purple-100', fillTextIos: 'text-purple-700', fillTextMaterial: 'text-purple-700' }
    case 'branch_admin':
      return { fillBgIos: 'bg-blue-100', fillBgMaterial: 'bg-blue-100', fillTextIos: 'text-blue-700', fillTextMaterial: 'text-blue-700' }
    case 'salesperson':
      return { fillBgIos: 'bg-green-100', fillBgMaterial: 'bg-green-100', fillTextIos: 'text-green-700', fillTextMaterial: 'text-green-700' }
    default:
      return { fillBgIos: 'bg-gray-100', fillBgMaterial: 'bg-gray-100', fillTextIos: 'text-gray-700', fillTextMaterial: 'text-gray-700' }
  }
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function StaffContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<StaffMember[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchStaff = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = { offset: 0, limit: PAGE_SIZE }
        if (search.trim()) params.search = search.trim()

        const res = await apiClient.get<{ items?: StaffMember[]; total?: number }>(
          '/api/v2/staff',
          { params, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load staff')
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
    fetchStaff(false, controller.signal)
    return () => controller.abort()
  }, [fetchStaff])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchStaff(true, controller.signal)
  }, [fetchStaff])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="staff-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="staff-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search staff…"
              data-testid="staff-searchbar"
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
              <p className="text-sm text-gray-400 dark:text-gray-500">No staff members found</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="staff-list">
              {items.map((staff) => (
                <ListItem
                  key={staff.id}
                  link
                  onClick={() => navigate(`/staff/${staff.id}`)}
                  title={
                    <span className="font-bold text-gray-900 dark:text-gray-100">
                      {displayName(staff)}
                    </span>
                  }
                  subtitle={
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
                      {staff.branch_name && <span>{staff.branch_name}</span>}
                      {staff.email && <span>{staff.email}</span>}
                    </span>
                  }
                  after={
                    <div className="flex flex-col items-end gap-1">
                      <Chip
                        className="text-xs"
                        colors={roleChipColors(staff.role)}
                      >
                        {roleLabel(staff.role)}
                      </Chip>
                      <span className={`text-xs font-medium ${staff.is_active ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                        {staff.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  }
                  data-testid={`staff-item-${staff.id}`}
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}

/**
 * Staff screen — list with role badges (Chip), branch, status.
 * ModuleGate `staff`.
 *
 * Requirements: 33.1, 33.2, 33.3, 55.1
 */
export default function StaffListScreen() {
  return (
    <ModuleGate moduleSlug="staff">
      <StaffContent />
    </ModuleGate>
  )
}
