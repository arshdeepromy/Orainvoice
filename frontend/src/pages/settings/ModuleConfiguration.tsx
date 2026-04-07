import { useState, useEffect, useMemo, useCallback } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { useModules } from '@/contexts/ModuleContext'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'
import apiClient from '@/api/client'
import { cascadeDisable, autoEnableDependencies, isComingSoon } from '@/utils/moduleCalcs'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ModuleDefinition {
  slug: string
  name: string
  description: string
  category: string
  is_enabled: boolean
  in_plan: boolean
  dependencies: string[]
  dependents: string[]
  status: 'available' | 'coming_soon'
  expected_date?: string
}

/* ------------------------------------------------------------------ */
/*  Toggle Switch (44×44px touch target)                               */
/* ------------------------------------------------------------------ */

function ModuleToggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean
  onChange: (val: boolean) => void
  disabled?: boolean
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      data-testid={`module-toggle-${label.replace(/\s+/g, '-').toLowerCase()}`}
      onClick={() => onChange(!checked)}
      style={{ minHeight: 44, minWidth: 44 }}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
        disabled:opacity-50 disabled:cursor-not-allowed
        ${checked ? 'bg-blue-600' : 'bg-gray-300'}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform
          ${checked ? 'translate-x-5' : 'translate-x-0'}`}
      />
    </button>
  )
}


/* ------------------------------------------------------------------ */
/*  Module Card                                                        */
/* ------------------------------------------------------------------ */

function ModuleCard({
  mod,
  allModules,
  onToggle,
  toggling,
}: {
  mod: ModuleDefinition
  allModules: ModuleDefinition[]
  onToggle: (mod: ModuleDefinition) => void
  toggling: boolean
}) {
  const comingSoon = isComingSoon(mod)
  const notInPlan = !mod.in_plan
  const depNames = mod.dependencies
    .map((slug) => allModules.find((m) => m.slug === slug)?.name ?? slug)
  const dependentNames = mod.dependents
    .map((slug) => allModules.find((m) => m.slug === slug)?.name ?? slug)

  return (
    <div
      className={`border rounded-lg p-4 transition-colors ${
        notInPlan ? 'border-gray-200 bg-gray-50 opacity-60' :
        comingSoon ? 'border-gray-200 bg-gray-50 opacity-75' : 'border-gray-200 bg-white'
      }`}
      data-testid={`module-card-${mod.slug}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900">{mod.name}</span>
            {notInPlan && (
              <Badge variant="neutral" data-testid={`not-in-plan-badge-${mod.slug}`}>
                Not in plan
              </Badge>
            )}
            {comingSoon && !notInPlan && (
              <Badge variant="info" data-testid={`coming-soon-badge-${mod.slug}`}>
                Coming Soon
              </Badge>
            )}
            {mod.is_enabled && !comingSoon && !notInPlan && (
              <Badge variant="success">Enabled</Badge>
            )}
          </div>
          {mod.description && (
            <p className="text-sm text-gray-500 mt-1">{mod.description}</p>
          )}
          {notInPlan && (
            <p className="text-xs text-amber-600 mt-1">
              Contact your administrator to add this module to your plan.
            </p>
          )}
        </div>
        <ModuleToggle
          checked={mod.is_enabled}
          onChange={() => onToggle(mod)}
          disabled={toggling || comingSoon || notInPlan}
          label={`Toggle ${mod.name}`}
        />
      </div>

      {/* Dependency / Dependent lists */}
      <div className="mt-3 flex flex-col gap-1 text-xs text-gray-500">
        {depNames.length > 0 && (
          <div data-testid={`module-deps-${mod.slug}`}>
            <span className="font-medium text-gray-600">Requires:</span>{' '}
            {depNames.join(', ')}
          </div>
        )}
        {dependentNames.length > 0 && (
          <div data-testid={`module-dependents-${mod.slug}`}>
            <span className="font-medium text-gray-600">Required by:</span>{' '}
            {dependentNames.join(', ')}
          </div>
        )}
      </div>

      {comingSoon && mod.expected_date && (
        <p className="text-xs text-blue-600 mt-2" data-testid={`expected-date-${mod.slug}`}>
          Expected: {mod.expected_date}
        </p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Category Section                                                   */
/* ------------------------------------------------------------------ */

function CategorySection({
  category,
  modules,
  allModules,
  onToggle,
  togglingSlug,
}: {
  category: string
  modules: ModuleDefinition[]
  allModules: ModuleDefinition[]
  onToggle: (mod: ModuleDefinition) => void
  togglingSlug: string | null
}) {
  const [expanded, setExpanded] = useState(true)
  const enabledCount = modules.filter((m) => m.is_enabled).length

  return (
    <div
      className="border border-gray-200 rounded-lg overflow-hidden"
      data-testid={`module-category-${category.replace(/\s+/g, '-').toLowerCase()}`}
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        style={{ minHeight: 44 }}
        className="flex w-full items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
        aria-expanded={expanded}
        data-testid={`module-category-toggle-${category.replace(/\s+/g, '-').toLowerCase()}`}
      >
        <span className="font-semibold text-gray-900">{category}</span>
        <span className="text-sm text-gray-500">
          {enabledCount}/{modules.length} enabled
        </span>
      </button>

      {expanded && (
        <div className="p-4 grid gap-3 sm:grid-cols-1 md:grid-cols-2">
          {modules.map((mod) => (
            <ModuleCard
              key={mod.slug}
              mod={mod}
              allModules={allModules}
              onToggle={onToggle}
              toggling={togglingSlug === mod.slug}
            />
          ))}
        </div>
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Dependency Graph (visual)                                          */
/* ------------------------------------------------------------------ */

function DependencyGraph({ modules }: { modules: ModuleDefinition[] }) {
  const enabledSlugs = new Set(modules.filter((m) => m.is_enabled).map((m) => m.slug))

  // Build edges: dependency → dependent
  const edges: { from: string; to: string }[] = []
  for (const mod of modules) {
    for (const dep of mod.dependencies) {
      edges.push({ from: dep, to: mod.slug })
    }
  }

  if (edges.length === 0) {
    return (
      <p className="text-center text-gray-500 py-8" data-testid="dep-graph-empty">
        No module dependencies to display.
      </p>
    )
  }

  const nameMap = new Map(modules.map((m) => [m.slug, m.name]))

  return (
    <div className="space-y-3" data-testid="dependency-graph">
      <h3 className="text-lg font-semibold text-gray-900">Module Dependencies</h3>
      <div className="overflow-x-auto">
        <div className="flex flex-wrap gap-4 p-4 bg-gray-50 rounded-lg min-w-[300px]">
          {modules
            .filter((m) => m.dependencies.length > 0 || m.dependents.length > 0)
            .map((mod) => (
              <div
                key={mod.slug}
                className={`border-2 rounded-lg p-3 min-w-[140px] text-center text-sm transition-colors ${
                  enabledSlugs.has(mod.slug)
                    ? 'border-blue-400 bg-blue-50 text-blue-900'
                    : isComingSoon(mod)
                      ? 'border-gray-300 bg-gray-100 text-gray-500'
                      : 'border-gray-300 bg-white text-gray-700'
                }`}
                data-testid={`dep-graph-node-${mod.slug}`}
              >
                <div className="font-medium">{mod.name}</div>
                {mod.dependencies.length > 0 && (
                  <div className="text-xs mt-1 text-gray-500">
                    ← {mod.dependencies.map((d) => nameMap.get(d) ?? d).join(', ')}
                  </div>
                )}
                {mod.dependents.length > 0 && (
                  <div className="text-xs mt-1 text-gray-500">
                    → {mod.dependents.map((d) => nameMap.get(d) ?? d).join(', ')}
                  </div>
                )}
              </div>
            ))}
        </div>
      </div>
      {/* Legend */}
      <div className="flex gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-blue-400 bg-blue-50" /> Enabled
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded border-2 border-gray-300 bg-white" /> Disabled
        </span>
        <span className="flex items-center gap-1">
          ← Depends on &nbsp; → Required by
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Cascade Disable Confirmation Dialog                                */
/* ------------------------------------------------------------------ */

function CascadeDisableDialog({
  open,
  onClose,
  onConfirm,
  moduleName,
  affectedModules,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  moduleName: string
  affectedModules: string[]
}) {
  return (
    <Modal open={open} onClose={onClose} title="Disable Module?">
      <div className="space-y-4" data-testid="cascade-disable-dialog">
        <p className="text-gray-700">
          Disabling <span className="font-semibold">{moduleName}</span> will also disable
          the following dependent modules:
        </p>
        <ul className="list-disc list-inside space-y-1" data-testid="cascade-affected-list">
          {affectedModules.map((name) => (
            <li key={name} className="text-gray-600">{name}</li>
          ))}
        </ul>
        <div className="flex justify-end gap-3 pt-2">
          <Button
            variant="secondary"
            onClick={onClose}
            style={{ minHeight: 44, minWidth: 44 }}
            data-testid="cascade-cancel-btn"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            style={{ minHeight: 44, minWidth: 44 }}
            data-testid="cascade-confirm-btn"
          >
            Disable All
          </Button>
        </div>
      </div>
    </Modal>
  )
}


/* ------------------------------------------------------------------ */
/*  Branch Management Disable Confirmation Dialog                      */
/* ------------------------------------------------------------------ */

function BranchDisableDialog({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  return (
    <Modal open={open} onClose={onClose} title="Disable Branch Management?">
      <div className="space-y-4" data-testid="branch-disable-dialog">
        <p className="text-gray-700">
          Disabling Branch Management will hide all branch features. Your existing
          branch data will be preserved but branch scoping will be suspended. Users
          with the branch_admin role will lose branch-specific access.
        </p>
        <p className="text-sm text-amber-600">
          You will need to manually reassign any users currently holding the
          branch_admin role.
        </p>
        <div className="flex justify-end gap-3 pt-2">
          <Button
            variant="secondary"
            onClick={onClose}
            style={{ minHeight: 44, minWidth: 44 }}
            data-testid="branch-disable-cancel-btn"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            style={{ minHeight: 44, minWidth: 44 }}
            data-testid="branch-disable-confirm-btn"
          >
            Disable Branch Management
          </Button>
        </div>
      </div>
    </Modal>
  )
}


/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export function ModuleConfiguration() {
  // Context integration (Req 12.6, 12.7)
  void useFlag('module_management')
  const { refetch: refetchModuleContext } = useModules()
  const modulesLabel = useTerm('module', 'Module')

  const [modules, setModules] = useState<ModuleDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [togglingSlug, setTogglingSlug] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'config' | 'graph'>('config')
  const { addToast, toasts, dismissToast } = useToast()

  // Cascade disable dialog state
  const [cascadeDialog, setCascadeDialog] = useState<{
    open: boolean
    mod: ModuleDefinition | null
    affected: string[]
  }>({ open: false, mod: null, affected: [] })

  // Branch management disable confirmation dialog state
  const [branchDisableDialog, setBranchDisableDialog] = useState<{
    open: boolean
    mod: ModuleDefinition | null
  }>({ open: false, mod: null })

  const fetchModules = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/modules')
      const data = res.data
      const rawModules = Array.isArray(data) ? data : (data?.modules ?? [])
      if (rawModules.length > 0 || Array.isArray(data?.modules)) {
        // Normalise: ensure dependencies/dependents arrays exist
        const normalised: ModuleDefinition[] = rawModules.map((m: Record<string, unknown>) => ({
          slug: String(m.slug ?? ''),
          name: String(m.name ?? m.display_name ?? m.slug ?? ''),
          description: String(m.description ?? ''),
          category: String(m.category ?? 'General'),
          is_enabled: Boolean(m.is_enabled),
          in_plan: m.in_plan !== false,
          dependencies: Array.isArray(m.dependencies) ? m.dependencies : [],
          dependents: Array.isArray(m.dependents) ? m.dependents : [],
          status: m.status === 'coming_soon' ? 'coming_soon' : 'available',
          expected_date: typeof m.expected_date === 'string' ? m.expected_date : undefined,
        }))
        setModules(normalised)
      }
    } catch {
      setError('Failed to load modules')
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    fetchModules().finally(() => setLoading(false))
  }, [fetchModules])

  /* ---- Filtering ---- */

  const filteredModules = useMemo(() => {
    if (!search.trim()) return modules
    const lower = search.toLowerCase()
    return modules.filter(
      (m) =>
        m.name.toLowerCase().includes(lower) ||
        m.slug.toLowerCase().includes(lower) ||
        m.description.toLowerCase().includes(lower) ||
        m.category.toLowerCase().includes(lower),
    )
  }, [modules, search])

  const grouped = useMemo(() => {
    const groups: Record<string, ModuleDefinition[]> = {}
    for (const mod of filteredModules) {
      const cat = mod.category || 'General'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(mod)
    }
    return Object.fromEntries(
      Object.entries(groups).sort(([a], [b]) => a.localeCompare(b)),
    )
  }, [filteredModules])

  /* ---- Toggle logic ---- */

  const handleToggle = useCallback(
    async (mod: ModuleDefinition) => {
      if (isComingSoon(mod)) return
      if (!mod.in_plan) return

      const newEnabled = !mod.is_enabled

      if (!newEnabled) {
        // Special case: branch_management disable — check active branch count
        if (mod.slug === 'branch_management') {
          try {
            const res = await apiClient.get<{ branches: Array<{ is_active: boolean }> }>('/org/branches')
            const activeBranches = (res.data?.branches ?? []).filter((b) => b.is_active)
            if (activeBranches.length > 1) {
              setBranchDisableDialog({ open: true, mod })
              return
            }
          } catch {
            // If we can't fetch branches, still show the dialog as a safeguard
            setBranchDisableDialog({ open: true, mod })
            return
          }
        }

        // Disabling: check for cascade
        const affected = cascadeDisable(mod.slug, modules)
        const enabledAffected = affected.filter((slug) =>
          modules.find((m) => m.slug === slug)?.is_enabled,
        )

        if (enabledAffected.length > 0) {
          const affectedNames = enabledAffected.map(
            (slug) => modules.find((m) => m.slug === slug)?.name ?? slug,
          )
          setCascadeDialog({ open: true, mod, affected: affectedNames })
          return
        }
      } else {
        // Enabling: check for auto-enable dependencies
        const deps = autoEnableDependencies(mod.slug, modules)
        const disabledDeps = deps.filter(
          (slug) => !modules.find((m) => m.slug === slug)?.is_enabled,
        )

        if (disabledDeps.length > 0) {
          const depNames = disabledDeps.map(
            (slug) => modules.find((m) => m.slug === slug)?.name ?? slug,
          )
          addToast(
            'info',
            `Auto-enabling dependencies: ${depNames.join(', ')}`,
          )
        }
      }

      performToggle(mod, newEnabled)
    },
    [modules, addToast],
  )

  const performToggle = useCallback(
    async (mod: ModuleDefinition, newEnabled: boolean, force = false) => {
      setTogglingSlug(mod.slug)

      // Optimistic update
      setModules((prev) =>
        prev.map((m) => {
          if (m.slug === mod.slug) return { ...m, is_enabled: newEnabled }
          if (!newEnabled) {
            // Cascade disable dependents
            const affected = cascadeDisable(mod.slug, prev)
            if (affected.includes(m.slug)) return { ...m, is_enabled: false }
          } else {
            // Auto-enable dependencies
            const deps = autoEnableDependencies(mod.slug, prev)
            if (deps.includes(m.slug)) return { ...m, is_enabled: true }
          }
          return m
        }),
      )

      try {
        const action = newEnabled ? 'enable' : 'disable'
        const query = force ? '?force=true' : ''
        await apiClient.put(`/api/v2/modules/${mod.slug}/${action}${query}`)
        await refetchModuleContext()
        addToast('success', `${mod.name} ${newEnabled ? 'enabled' : 'disabled'}`)
      } catch {
        // Revert on error
        await fetchModules()
        addToast('error', `Failed to update "${mod.name}"`)
      } finally {
        setTogglingSlug(null)
      }
    },
    [addToast, refetchModuleContext, fetchModules],
  )

  const handleCascadeConfirm = useCallback(() => {
    if (cascadeDialog.mod) {
      performToggle(cascadeDialog.mod, false, true)
    }
    setCascadeDialog({ open: false, mod: null, affected: [] })
  }, [cascadeDialog.mod, performToggle])

  const handleBranchDisableConfirm = useCallback(() => {
    if (branchDisableDialog.mod) {
      performToggle(branchDisableDialog.mod, false, true)
    }
    setBranchDisableDialog({ open: false, mod: null })
  }, [branchDisableDialog.mod, performToggle])

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="module-config-loading">
        <Spinner label={`Loading ${modulesLabel.toLowerCase()}s`} />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" data-testid="module-config-error">
        {error}
      </AlertBanner>
    )
  }

  return (
    <div data-testid="module-configuration">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">{modulesLabel} Configuration</h1>
        <Button
          variant="secondary"
          onClick={() => {
            setLoading(true)
            fetchModules().finally(() => setLoading(false))
          }}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="module-refresh-btn"
        >
          Refresh
        </Button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200 mb-6" role="tablist">
        <button
          role="tab"
          aria-selected={activeTab === 'config'}
          onClick={() => setActiveTab('config')}
          style={{ minHeight: 44 }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors
            ${activeTab === 'config'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          data-testid="tab-config"
        >
          Configuration
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'graph'}
          onClick={() => setActiveTab('graph')}
          style={{ minHeight: 44 }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors
            ${activeTab === 'graph'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          data-testid="tab-graph"
        >
          Dependency Graph
        </button>
      </div>

      {activeTab === 'config' && (
        <div className="space-y-4" data-testid="module-config-list">
          {/* Search */}
          <div className="max-w-md">
            <label htmlFor="module-search" className="text-sm font-medium text-gray-700 block mb-1">
              Search modules
            </label>
            <input
              id="module-search"
              type="search"
              placeholder="Search by name, slug, or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="module-search-input"
              style={{ minHeight: 44 }}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
                placeholder:text-gray-400
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
          </div>

          {/* Category Sections */}
          {Object.keys(grouped).length === 0 ? (
            <p className="text-center text-gray-500 py-8" data-testid="module-config-empty">
              No modules match your search.
            </p>
          ) : (
            Object.entries(grouped).map(([category, catModules]) => (
              <CategorySection
                key={category}
                category={category}
                modules={catModules}
                allModules={modules}
                onToggle={handleToggle}
                togglingSlug={togglingSlug}
              />
            ))
          )}
        </div>
      )}

      {activeTab === 'graph' && <DependencyGraph modules={modules} />}

      {/* Cascade disable confirmation dialog */}
      <CascadeDisableDialog
        open={cascadeDialog.open}
        onClose={() => setCascadeDialog({ open: false, mod: null, affected: [] })}
        onConfirm={handleCascadeConfirm}
        moduleName={cascadeDialog.mod?.name ?? ''}
        affectedModules={cascadeDialog.affected}
      />

      {/* Branch management disable confirmation dialog */}
      <BranchDisableDialog
        open={branchDisableDialog.open}
        onClose={() => setBranchDisableDialog({ open: false, mod: null })}
        onConfirm={handleBranchDisableConfirm}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
