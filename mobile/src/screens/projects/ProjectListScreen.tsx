import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileCard, MobileBadge, MobileSearchBar, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface Project {
  id: string
  name: string
  status: string
  budget: number
  spent: number
  budget_utilisation: number | null
}

const statusVariant: Record<string, BadgeVariant> = {
  active: 'paid',
  planning: 'draft',
  completed: 'info',
  on_hold: 'sent',
  cancelled: 'cancelled',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function ProjectListContent() {
  const navigate = useNavigate()
  const { items, isLoading, isRefreshing, search, setSearch, refresh, hasMore, loadMore } =
    useApiList<Project>({ endpoint: '/api/v2/projects', dataKey: 'items' })

  if (isLoading && items.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Projects</h1>
      <MobileSearchBar value={search} onChange={setSearch} placeholder="Search projects..." />
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <MobileList
          items={items}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          onRefresh={refresh}
          onLoadMore={loadMore}
          emptyMessage="No projects found"
          renderItem={(p) => {
            const utilisation = p.budget_utilisation ?? (p.budget > 0 ? Math.round((p.spent / p.budget) * 100) : 0)
            return (
              <MobileCard
                key={p.id}
                onClick={() => navigate(`/projects/${p.id}`)}
                className="cursor-pointer"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {p.name ?? 'Project'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      Budget: {formatCurrency(p.budget)} · {utilisation}% used
                    </p>
                  </div>
                  <MobileBadge
                    label={(p.status ?? 'active').replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                    variant={statusVariant[p.status] ?? 'info'}
                  />
                </div>
              </MobileCard>
            )
          }}
        />
      </PullRefresh>
    </div>
  )
}

/**
 * Project list — name, status, budget utilisation.
 *
 * Requirements: 36.1, 36.3
 */
export default function ProjectListScreen() {
  return (
    <ModuleGate moduleSlug="projects">
      <ProjectListContent />
    </ModuleGate>
  )
}
