import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  List,
  ListItem,
  Block,
  Preloader,
  Progressbar,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import StatusBadge from '@/components/konsta/StatusBadge'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface Project {
  id: string
  name: string
  status: string
  budget: number
  spent: number
  budget_utilisation: number | null
}

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

function ProjectsContent() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchProjects = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = { offset: 0, limit: PAGE_SIZE }
        if (search.trim()) params.search = search.trim()

        const res = await apiClient.get<{ items?: Project[]; total?: number }>(
          '/api/v2/projects',
          { params, signal },
        )
        setItems(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load projects')
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
    fetchProjects(false, controller.signal)
    return () => controller.abort()
  }, [fetchProjects])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchProjects(true, controller.signal)
  }, [fetchProjects])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  if (isLoading && items.length === 0) {
    return (
      <Page data-testid="projects-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="projects-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search projects…"
              data-testid="projects-searchbar"
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
              <p className="text-sm text-gray-400 dark:text-gray-500">No projects found</p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos data-testid="projects-list">
              {items.map((project) => {
                const utilisation = project.budget_utilisation ?? (project.budget > 0 ? Math.round((project.spent / project.budget) * 100) : 0)
                const progressValue = Math.min(utilisation, 100) / 100

                return (
                  <ListItem
                    key={project.id}
                    link
                    onClick={() => navigate(`/projects/${project.id}`)}
                    title={
                      <span className="font-bold text-gray-900 dark:text-gray-100">
                        {project.name ?? 'Project'}
                      </span>
                    }
                    subtitle={
                      <div className="mt-1 flex flex-col gap-1">
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          Budget: {formatNZD(project.budget)} · {utilisation}% used
                        </span>
                        <Progressbar progress={progressValue} data-testid={`progress-${project.id}`} />
                      </div>
                    }
                    after={
                      <StatusBadge status={project.status ?? 'active'} size="sm" />
                    }
                    data-testid={`project-item-${project.id}`}
                  />
                )
              })}
            </List>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}

/**
 * Projects screen — list with progress bar (Progressbar).
 * ModuleGate `projects`.
 *
 * Requirements: 34.1, 34.2, 34.3, 55.1
 */
export default function ProjectListScreen() {
  return (
    <ModuleGate moduleSlug="projects">
      <ProjectsContent />
    </ModuleGate>
  )
}
