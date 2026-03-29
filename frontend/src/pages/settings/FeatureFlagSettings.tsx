import { useState, useEffect, useMemo, useCallback } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Tabs } from '@/components/ui/Tabs'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { useFeatureFlags, useFlag } from '@/contexts/FeatureFlagContext'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/api/client'
import {
  canOverrideFlag,
  groupFlagsByCategory,
  validateFlagCategory,
} from '@/utils/featureFlagCalcs'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface OrgFeatureFlag {
  key: string
  name: string
  description: string
  category: string
  enabled: boolean
  source: 'explicit' | 'trade_category' | 'plan_tier' | 'rollout'
  can_override: boolean
}

interface RolloutMetric {
  flag_key: string
  flag_name: string
  adoption_percent: number
  trend: 'up' | 'down' | 'stable'
  error_rate: number
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const SOURCE_LABELS: Record<string, string> = {
  explicit: 'Org Override',
  trade_category: 'Trade Category',
  plan_tier: 'Plan Tier',
  rollout: 'Percentage Rollout',
}

const SOURCE_VARIANTS: Record<string, 'info' | 'warning' | 'neutral' | 'success'> = {
  explicit: 'success',
  trade_category: 'info',
  plan_tier: 'warning',
  rollout: 'neutral',
}

/* ------------------------------------------------------------------ */
/*  Toggle Switch (44×44px touch target)                               */
/* ------------------------------------------------------------------ */

function FlagToggle({
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
      data-testid={`flag-toggle-${label.replace(/\s+/g, '-').toLowerCase()}`}
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
/*  Flag Row                                                           */
/* ------------------------------------------------------------------ */

function FlagRow({
  flag,
  onToggle,
  toggling,
}: {
  flag: OrgFeatureFlag
  onToggle: (flag: OrgFeatureFlag) => void
  toggling: boolean
}) {
  const overridable = canOverrideFlag(flag)

  return (
    <div
      className="flex items-center gap-4 px-4 py-3"
      data-testid={`flag-row-${flag.key}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-gray-900">{flag.name}</span>
          <Badge variant="neutral">{flag.key}</Badge>
          <Badge variant={SOURCE_VARIANTS[flag.source] ?? 'neutral'}>
            {SOURCE_LABELS[flag.source] ?? flag.source}
          </Badge>
          {!overridable && (
            <Badge variant="warning">Read-only</Badge>
          )}
        </div>
        {flag.description && (
          <p className="text-sm text-gray-500 mt-0.5">{flag.description}</p>
        )}
      </div>
      <FlagToggle
        checked={flag.enabled}
        onChange={() => onToggle(flag)}
        disabled={toggling || !overridable}
        label={`Toggle ${flag.name}`}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Category Section (expandable)                                      */
/* ------------------------------------------------------------------ */

function CategorySection({
  category,
  flags,
  onToggle,
  togglingKey,
}: {
  category: string
  flags: OrgFeatureFlag[]
  onToggle: (flag: OrgFeatureFlag) => void
  togglingKey: string | null
}) {
  const [expanded, setExpanded] = useState(true)
  const enabledCount = flags.filter((f) => f.enabled).length

  return (
    <div
      className="border border-gray-200 rounded-lg overflow-hidden"
      data-testid={`flag-category-${category.replace(/\s+/g, '-').toLowerCase()}`}
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        style={{ minHeight: 44 }}
        className="flex w-full items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
        aria-expanded={expanded}
        data-testid={`flag-category-toggle-${category.replace(/\s+/g, '-').toLowerCase()}`}
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
              key={flag.key}
              flag={flag}
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
/*  Rollout Monitoring (Global_Admin only)                             */
/* ------------------------------------------------------------------ */

function RolloutMonitoring({ metrics }: { metrics: RolloutMetric[] }) {
  if (metrics.length === 0) {
    return (
      <p className="text-center text-gray-500 py-8" data-testid="rollout-empty">
        No rollout data available.
      </p>
    )
  }

  const trendIcon = (trend: string) => {
    if (trend === 'up') return '↑'
    if (trend === 'down') return '↓'
    return '→'
  }

  const trendColor = (trend: string) => {
    if (trend === 'up') return 'text-green-600'
    if (trend === 'down') return 'text-red-600'
    return 'text-gray-500'
  }

  return (
    <div className="space-y-4" data-testid="rollout-monitoring">
      <h3 className="text-lg font-semibold text-gray-900">Rollout Monitoring</h3>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Flag</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Adoption %</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Trend</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Error Rate</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {metrics.map((m) => (
              <tr key={m.flag_key} data-testid={`rollout-row-${m.flag_key}`}>
                <td className="px-4 py-3 text-sm font-medium text-gray-900">{m.flag_name}</td>
                <td className="px-4 py-3 text-sm text-gray-700">
                  <div className="flex items-center gap-2">
                    <div className="w-24 bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-blue-600 h-2 rounded-full"
                        style={{ width: `${Math.min(m.adoption_percent ?? 0, 100)}%` }}
                      />
                    </div>
                    <span>{(m.adoption_percent ?? 0).toFixed(1)}%</span>
                  </div>
                </td>
                <td className={`px-4 py-3 text-sm font-medium ${trendColor(m.trend)}`}>
                  {trendIcon(m.trend)} {m.trend}
                </td>
                <td className="px-4 py-3 text-sm">
                  <span className={m.error_rate > 5 ? 'text-red-600 font-medium' : 'text-gray-700'}>
                    {(m.error_rate ?? 0).toFixed(2)}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export function FeatureFlagSettings() {
  // Context integration (Req 11.6)
  void useFlag('feature_flags')
  void useModules()
  const { refetch: refetchContext } = useFeatureFlags()
  const { isGlobalAdmin } = useAuth()

  const [flags, setFlags] = useState<OrgFeatureFlag[]>([])
  const [rolloutMetrics, setRolloutMetrics] = useState<RolloutMetric[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [togglingKey, setTogglingKey] = useState<string | null>(null)
  const { addToast, toasts, dismissToast } = useToast()

  const fetchFlags = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/flags')
      // The API returns { flags: [{ key, enabled }, ...] } for the org context.
      const data = res.data
      if (data && Array.isArray(data.flags)) {
        // Structured response: { flags: [{ key, enabled }, ...] }
        const mapped: OrgFeatureFlag[] = data.flags.map((f: { key: string; enabled: boolean }) => ({
          key: f.key,
          name: f.key.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
          description: '',
          category: 'General',
          enabled: Boolean(f.enabled),
          source: 'explicit' as const,
          can_override: false,
        }))
        setFlags(mapped)
      } else if (Array.isArray(data)) {
        setFlags(data)
      } else if (typeof data === 'object' && data !== null) {
        // Convert flat map to OrgFeatureFlag array (backwards compat)
        const mapped: OrgFeatureFlag[] = Object.entries(data).map(([key, enabled]) => ({
          key,
          name: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
          description: '',
          category: 'General',
          enabled: Boolean(enabled),
          source: 'explicit' as const,
          can_override: false,
        }))
        setFlags(mapped)
      }
    } catch {
      setError('Failed to load feature flags')
    }
  }, [])

  const fetchRolloutMetrics = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/admin/flags/rollout-metrics')
      setRolloutMetrics(res.data ?? [])
    } catch {
      // Non-critical — silently ignore
      setRolloutMetrics([])
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetchFlags(),
      isGlobalAdmin ? fetchRolloutMetrics() : Promise.resolve(),
    ]).finally(() => setLoading(false))
  }, [fetchFlags, fetchRolloutMetrics, isGlobalAdmin])

  /* ---- Filtering ---- */

  const filteredFlags = useMemo(() => {
    if (!search.trim()) return flags
    const lower = search.toLowerCase()
    return flags.filter(
      (f) =>
        f.name.toLowerCase().includes(lower) ||
        f.key.toLowerCase().includes(lower) ||
        f.description.toLowerCase().includes(lower),
    )
  }, [flags, search])

  const grouped = useMemo(() => {
    const groups = groupFlagsByCategory(
      filteredFlags.map((f) => ({
        ...f,
        category: f.category || 'Uncategorized',
      })),
    )
    // Sort categories alphabetically
    return Object.fromEntries(
      Object.entries(groups).sort(([a], [b]) => a.localeCompare(b)),
    )
  }, [filteredFlags])

  /* ---- Toggle logic ---- */

  const handleToggle = useCallback(
    async (flag: OrgFeatureFlag) => {
      if (!canOverrideFlag(flag)) return

      if (!validateFlagCategory(flag)) {
        addToast('error', 'Invalid flag configuration')
        return
      }

      const newEnabled = !flag.enabled
      setTogglingKey(flag.key)

      // Optimistic update
      setFlags((prev) =>
        prev.map((f) => (f.key === flag.key ? { ...f, enabled: newEnabled } : f)),
      )

      try {
        await apiClient.put(`/api/v2/flags/${flag.key}`, { enabled: newEnabled })
        await refetchContext()
        addToast('success', `${flag.name} ${newEnabled ? 'enabled' : 'disabled'}`)
      } catch {
        // Revert on error
        setFlags((prev) =>
          prev.map((f) => (f.key === flag.key ? { ...f, enabled: flag.enabled } : f)),
        )
        addToast('error', `Failed to update "${flag.name}"`)
      } finally {
        setTogglingKey(null)
      }
    },
    [addToast, refetchContext],
  )

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="flag-settings-loading">
        <Spinner label="Loading feature flags" />
      </div>
    )
  }

  if (error) {
    return (
      <AlertBanner variant="error" data-testid="flag-settings-error">
        {error}
      </AlertBanner>
    )
  }

  const tabs = [
    {
      id: 'flags',
      label: 'Feature Flags',
      content: (
        <div className="space-y-4" data-testid="flag-settings-list">
          {/* Search */}
          <div className="max-w-md">
            <label htmlFor="flag-search" className="text-sm font-medium text-gray-700 block mb-1">
              Search flags
            </label>
            <input
              id="flag-search"
              type="search"
              placeholder="Search by name, key, or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="flag-search-input"
              style={{ minHeight: 44 }}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
                placeholder:text-gray-400
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
            />
          </div>

          {/* Category Sections */}
          {Object.keys(grouped).length === 0 ? (
            <p className="text-center text-gray-500 py-8" data-testid="flag-settings-empty">
              No flags match your search.
            </p>
          ) : (
            Object.entries(grouped).map(([category, catFlags]) => (
              <CategorySection
                key={category}
                category={category}
                flags={catFlags}
                onToggle={handleToggle}
                togglingKey={togglingKey}
              />
            ))
          )}
        </div>
      ),
    },
  ]

  // Add rollout monitoring tab for Global_Admin (Req 11.5)
  if (isGlobalAdmin) {
    tabs.push({
      id: 'rollout',
      label: 'Rollout Monitoring',
      content: <RolloutMonitoring metrics={rolloutMetrics} />,
    })
  }

  return (
    <div data-testid="feature-flag-settings">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Feature Flags</h1>
        <Button
          variant="secondary"
          onClick={() => {
            setLoading(true)
            Promise.all([
              fetchFlags(),
              isGlobalAdmin ? fetchRolloutMetrics() : Promise.resolve(),
            ]).finally(() => setLoading(false))
          }}
          style={{ minHeight: 44, minWidth: 44 }}
          data-testid="flag-refresh-btn"
        >
          Refresh
        </Button>
      </div>

      <Tabs tabs={tabs} />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
