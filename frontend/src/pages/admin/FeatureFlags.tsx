import { useState, useEffect, useMemo, useCallback } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Modal } from '@/components/ui/Modal'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { useFeatureFlags } from '@/contexts/FeatureFlagContext'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface FeatureFlag {
  id: string
  key: string
  display_name: string
  description: string | null
  category: string
  access_level: string
  dependencies: string[]
  default_value: boolean
  is_active: boolean
  targeting_rules: unknown[]
  created_by: string | null
  updated_by: string | null
  created_at: string
  updated_at: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const ACCESS_LEVEL_LABELS: Record<string, string> = {
  all_users: 'All Users',
  admin_only: 'Admin Only',
}

function matchesSearch(flag: FeatureFlag, term: string): boolean {
  const lower = term.toLowerCase()
  return (
    flag.display_name.toLowerCase().includes(lower) ||
    flag.key.toLowerCase().includes(lower) ||
    (flag.description ?? '').toLowerCase().includes(lower)
  )
}

function matchesFilters(
  flag: FeatureFlag,
  categoryFilter: string,
  accessFilter: string,
  statusFilter: string,
): boolean {
  if (categoryFilter && flag.category !== categoryFilter) return false
  if (accessFilter && flag.access_level !== accessFilter) return false
  if (statusFilter === 'enabled' && !flag.is_active) return false
  if (statusFilter === 'disabled' && flag.is_active) return false
  return true
}

/* ------------------------------------------------------------------ */
/*  Dependency Warning Modal                                           */
/* ------------------------------------------------------------------ */

function DependencyWarningModal({
  open,
  onClose,
  onConfirm,
  flagKey,
  dependents,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  flagKey: string
  dependents: string[]
}) {
  return (
    <Modal open={open} onClose={onClose} title="Dependency Warning">
      <div className="space-y-4">
        <p className="text-sm text-gray-700">
          Disabling <span className="font-semibold">{flagKey}</span> may affect the
          following enabled flags that depend on it:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          {dependents.map((d) => (
            <li key={d} className="text-sm text-gray-600">{d}</li>
          ))}
        </ul>
        <div className="flex justify-end gap-3 pt-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={onConfirm}>Disable Anyway</Button>
        </div>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/*  Toggle Switch                                                      */
/* ------------------------------------------------------------------ */

function ToggleSwitch({
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
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors
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
/*  Category Section                                                   */
/* ------------------------------------------------------------------ */

function CategorySection({
  category,
  flags,
  allFlags,
  onToggle,
  togglingKey,
}: {
  category: string
  flags: FeatureFlag[]
  allFlags: FeatureFlag[]
  onToggle: (flag: FeatureFlag) => void
  togglingKey: string | null
}) {
  const [expanded, setExpanded] = useState(true)
  const enabledCount = flags.filter((f) => f.is_active).length

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
        aria-expanded={expanded}
      >
        <span className="font-semibold text-gray-900">{category}</span>
        <span className="text-sm text-gray-500">
          {enabledCount}/{flags.length} enabled
        </span>
      </button>

      {expanded && (
        <div className="divide-y divide-gray-100">
          {flags.map((flag) => (
            <FlagRow
              key={flag.id}
              flag={flag}
              allFlags={allFlags}
              onToggle={onToggle}
              toggling={togglingKey === flag.key}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Flag Row                                                           */
/* ------------------------------------------------------------------ */

function FlagRow({
  flag,
  allFlags,
  onToggle,
  toggling,
}: {
  flag: FeatureFlag
  allFlags: FeatureFlag[]
  onToggle: (flag: FeatureFlag) => void
  toggling: boolean
}) {
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-gray-900">{flag.display_name}</span>
          <Badge variant="neutral">{flag.key}</Badge>
          <Badge variant={flag.access_level === 'admin_only' ? 'warning' : 'info'}>
            {ACCESS_LEVEL_LABELS[flag.access_level] ?? flag.access_level}
          </Badge>
        </div>
        {flag.description && (
          <p className="text-sm text-gray-500 mt-0.5">{flag.description}</p>
        )}
        {flag.dependencies.length > 0 && (
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className="text-xs text-gray-400">Depends on:</span>
            {flag.dependencies.map((dep) => {
              const depFlag = allFlags.find((f) => f.key === dep)
              const depActive = depFlag?.is_active ?? false
              return (
                <span
                  key={dep}
                  className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium
                    ${depActive ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}
                >
                  {dep}
                </span>
              )
            })}
          </div>
        )}
      </div>
      <ToggleSwitch
        checked={flag.is_active}
        onChange={() => onToggle(flag)}
        disabled={toggling}
        label={`Toggle ${flag.display_name}`}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export function FeatureFlags() {
  const [flags, setFlags] = useState<FeatureFlag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [accessFilter, setAccessFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [togglingKey, setTogglingKey] = useState<string | null>(null)
  const [warningModal, setWarningModal] = useState<{ flag: FeatureFlag; dependents: string[] } | null>(null)
  const { toasts, addToast, dismissToast } = useToast()
  const { refetch: refetchContext } = useFeatureFlags()

  const fetchFlags = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await apiClient.get('/api/v2/admin/flags')
      setFlags(res.data.flags ?? [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchFlags()
  }, [fetchFlags])

  /* ---- Filtering ---- */

  const filteredFlags = useMemo(() => {
    return flags.filter(
      (f) => matchesSearch(f, search) && matchesFilters(f, categoryFilter, accessFilter, statusFilter),
    )
  }, [flags, search, categoryFilter, accessFilter, statusFilter])

  const groupedByCategory = useMemo(() => {
    const groups: Record<string, FeatureFlag[]> = {}
    for (const flag of filteredFlags) {
      const cat = flag.category || 'Uncategorized'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(flag)
    }
    // Sort categories alphabetically
    return Object.fromEntries(
      Object.entries(groups).sort(([a], [b]) => a.localeCompare(b)),
    )
  }, [filteredFlags])

  const categories = useMemo(() => {
    const cats = new Set(flags.map((f) => f.category || 'Uncategorized'))
    return Array.from(cats).sort()
  }, [flags])

  const accessLevels = useMemo(() => {
    const levels = new Set(flags.map((f) => f.access_level))
    return Array.from(levels).sort()
  }, [flags])

  /* ---- Toggle logic ---- */

  const findDependents = useCallback(
    (flagKey: string): string[] => {
      return flags
        .filter((f) => f.is_active && f.dependencies.includes(flagKey))
        .map((f) => f.display_name)
    },
    [flags],
  )

  const performToggle = useCallback(
    async (flag: FeatureFlag) => {
      const newActive = !flag.is_active
      setTogglingKey(flag.key)

      // Optimistic update
      setFlags((prev) =>
        prev.map((f) => (f.key === flag.key ? { ...f, is_active: newActive } : f)),
      )

      try {
        await apiClient.put(`/api/v2/admin/flags/${flag.key}`, { is_active: newActive })
        await refetchContext()
      } catch {
        // Revert on error
        setFlags((prev) =>
          prev.map((f) => (f.key === flag.key ? { ...f, is_active: flag.is_active } : f)),
        )
        addToast('error', `Failed to update "${flag.display_name}"`)
      } finally {
        setTogglingKey(null)
      }
    },
    [addToast, refetchContext],
  )

  const handleToggle = useCallback(
    (flag: FeatureFlag) => {
      // If disabling, check for dependents
      if (flag.is_active) {
        const dependents = findDependents(flag.key)
        if (dependents.length > 0) {
          setWarningModal({ flag, dependents })
          return
        }
      }
      performToggle(flag)
    },
    [findDependents, performToggle],
  )

  const handleWarningConfirm = useCallback(() => {
    if (warningModal) {
      performToggle(warningModal.flag)
      setWarningModal(null)
    }
  }, [warningModal, performToggle])

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading feature flags" />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" title="Error">
        Could not load feature flags.
      </AlertBanner>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Feature Flags</h1>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Search and Filters */}
      <div className="flex flex-wrap items-end gap-3 mb-6">
        <div className="flex-1 min-w-[200px]">
          <label htmlFor="flag-search" className="text-sm font-medium text-gray-700 block mb-1">
            Search
          </label>
          <input
            id="flag-search"
            type="search"
            placeholder="Search by name, key, or description…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
              placeholder:text-gray-400
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="filter-category" className="text-sm font-medium text-gray-700 block mb-1">
            Category
          </label>
          <select
            id="filter-category"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="filter-access" className="text-sm font-medium text-gray-700 block mb-1">
            Access Level
          </label>
          <select
            id="filter-access"
            value={accessFilter}
            onChange={(e) => setAccessFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            <option value="">All levels</option>
            {accessLevels.map((l) => (
              <option key={l} value={l}>{ACCESS_LEVEL_LABELS[l] ?? l}</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="filter-status" className="text-sm font-medium text-gray-700 block mb-1">
            Status
          </label>
          <select
            id="filter-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            <option value="">All statuses</option>
            <option value="enabled">Enabled</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
      </div>

      {/* Category Sections */}
      <div className="space-y-4">
        {Object.keys(groupedByCategory).length === 0 ? (
          <p className="text-center text-gray-500 py-8">No flags match your filters.</p>
        ) : (
          Object.entries(groupedByCategory).map(([category, catFlags]) => (
            <CategorySection
              key={category}
              category={category}
              flags={catFlags}
              allFlags={flags}
              onToggle={handleToggle}
              togglingKey={togglingKey}
            />
          ))
        )}
      </div>

      {/* Dependency Warning Modal */}
      {warningModal && (
        <DependencyWarningModal
          open
          onClose={() => setWarningModal(null)}
          onConfirm={handleWarningConfirm}
          flagKey={warningModal.flag.key}
          dependents={warningModal.dependents}
        />
      )}
    </div>
  )
}
