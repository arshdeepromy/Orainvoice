import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'

/* ── Types ── */

export interface PlatformOverview {
  total_orgs: number
  active_orgs: number
  mrr: number
  churn_rate: number
}

export interface TradeDistributionFamily {
  slug: string
  display_name: string
  org_count: number
}

export interface TradeDistributionCategory {
  slug: string
  display_name: string
  family_slug: string
  org_count: number
}

export interface TradeDistribution {
  by_family: TradeDistributionFamily[]
  by_category: TradeDistributionCategory[]
}

export interface ModuleAdoptionEntry {
  family_slug: string
  family_name: string
  module_slug: string
  enabled_count: number
  total_orgs: number
  adoption_pct: number
}

export interface GeographicEntry {
  country_code: string
  org_count: number
}

export interface RegionEntry {
  region: string
  org_count: number
}

export interface GeographicDistribution {
  by_country: GeographicEntry[]
  by_region: RegionEntry[]
}

export interface RevenuePlanMetrics {
  plan_name: string
  org_count: number
  mrr: number
  arr: number
  arpu: number
  estimated_ltv: number
}

export interface RevenueMetrics {
  by_plan: RevenuePlanMetrics[]
  total_mrr: number
  total_arr: number
  total_orgs: number
  overall_arpu: number
}

export interface FunnelStage {
  stage: string
  count: number
  rate: number
}

export interface ConversionFunnel {
  stages: FunnelStage[]
}

/* ── Helpers ── */

const STAGE_LABELS: Record<string, string> = {
  signup: 'Signup',
  wizard_complete: 'Wizard Complete',
  first_invoice: 'First Invoice',
  paid_subscription: 'Paid Subscription',
}

function formatCurrency(value: number): string {
  return `$${value.toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function pctColor(pct: number): string {
  if (pct >= 75) return '#22c55e'
  if (pct >= 50) return '#eab308'
  if (pct >= 25) return '#f97316'
  return '#ef4444'
}

/* ── Sub-components ── */

function OverviewCards({ data }: { data: PlatformOverview | null }) {
  if (!data) return null
  const cards = [
    { label: 'Total Organisations', value: data.total_orgs.toLocaleString() },
    { label: 'Active Organisations', value: data.active_orgs.toLocaleString() },
    { label: 'Monthly Recurring Revenue', value: formatCurrency(data.mrr) },
    { label: 'Churn Rate (30d)', value: `${data.churn_rate}%` },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="overview-cards">
      {cards.map((c) => (
        <div key={c.label} className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">{c.label}</p>
          <p className="text-2xl font-semibold mt-1">{c.value}</p>
        </div>
      ))}
    </div>
  )
}

function TradeDistributionChart({ data }: { data: TradeDistribution | null }) {
  if (!data || data.by_family.length === 0) return <p>No trade distribution data.</p>
  const total = data.by_family.reduce((s, f) => s + f.org_count, 0) || 1
  return (
    <div data-testid="trade-distribution">
      <h3 className="text-lg font-medium mb-3">Trade Distribution</h3>
      <div className="space-y-2">
        {data.by_family.map((f) => {
          const pct = Math.round((f.org_count / total) * 100)
          return (
            <div key={f.slug} className="flex items-center gap-2">
              <span className="w-40 text-sm truncate">{f.display_name}</span>
              <div className="flex-1 bg-gray-200 rounded h-5 relative">
                <div
                  className="bg-blue-500 h-5 rounded"
                  style={{ width: `${pct}%` }}
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${f.display_name}: ${pct}%`}
                />
              </div>
              <span className="text-sm w-16 text-right">{f.org_count} ({pct}%)</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ModuleHeatmap({ data }: { data: ModuleAdoptionEntry[] }) {
  if (data.length === 0) return <p>No module adoption data.</p>

  const families = [...new Set(data.map((d) => d.family_name))]
  const modules = [...new Set(data.map((d) => d.module_slug).filter(Boolean))]

  return (
    <div data-testid="module-heatmap">
      <h3 className="text-lg font-medium mb-3">Module Adoption Heatmap</h3>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm" role="table">
          <thead>
            <tr>
              <th className="text-left p-2">Trade Family</th>
              {modules.map((m) => (
                <th key={m} className="text-center p-2 capitalize">{m?.replace(/_/g, ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {families.map((fam) => (
              <tr key={fam}>
                <td className="p-2 font-medium">{fam}</td>
                {modules.map((mod) => {
                  const entry = data.find((d) => d.family_name === fam && d.module_slug === mod)
                  const pct = entry?.adoption_pct ?? 0
                  return (
                    <td
                      key={mod}
                      className="text-center p-2"
                      style={{ backgroundColor: `${pctColor(pct)}20` }}
                      title={`${pct}% adoption`}
                    >
                      {pct}%
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function GeographicMap({ data }: { data: GeographicDistribution | null }) {
  if (!data || data.by_country.length === 0) return <p>No geographic data.</p>
  return (
    <div data-testid="geographic-distribution">
      <h3 className="text-lg font-medium mb-3">Geographic Distribution</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {data.by_country.map((c) => (
          <div key={c.country_code} className="bg-white rounded shadow p-3 flex justify-between">
            <span className="font-medium">{c.country_code}</span>
            <span>{c.org_count} orgs</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function RevenueChart({ data }: { data: RevenueMetrics | null }) {
  if (!data || data.by_plan.length === 0) return <p>No revenue data.</p>
  return (
    <div data-testid="revenue-chart">
      <h3 className="text-lg font-medium mb-3">Revenue by Plan</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="bg-white rounded shadow p-3">
          <p className="text-xs text-gray-500">Total MRR</p>
          <p className="text-lg font-semibold">{formatCurrency(data.total_mrr)}</p>
        </div>
        <div className="bg-white rounded shadow p-3">
          <p className="text-xs text-gray-500">Total ARR</p>
          <p className="text-lg font-semibold">{formatCurrency(data.total_arr)}</p>
        </div>
        <div className="bg-white rounded shadow p-3">
          <p className="text-xs text-gray-500">Active Orgs</p>
          <p className="text-lg font-semibold">{data.total_orgs}</p>
        </div>
        <div className="bg-white rounded shadow p-3">
          <p className="text-xs text-gray-500">Overall ARPU</p>
          <p className="text-lg font-semibold">{formatCurrency(data.overall_arpu)}</p>
        </div>
      </div>
      <table className="min-w-full text-sm" role="table">
        <thead>
          <tr>
            <th className="text-left p-2">Plan</th>
            <th className="text-right p-2">Orgs</th>
            <th className="text-right p-2">MRR</th>
            <th className="text-right p-2">ARR</th>
            <th className="text-right p-2">ARPU</th>
            <th className="text-right p-2">Est. LTV</th>
          </tr>
        </thead>
        <tbody>
          {data.by_plan.map((p) => (
            <tr key={p.plan_name}>
              <td className="p-2">{p.plan_name}</td>
              <td className="p-2 text-right">{p.org_count}</td>
              <td className="p-2 text-right">{formatCurrency(p.mrr)}</td>
              <td className="p-2 text-right">{formatCurrency(p.arr)}</td>
              <td className="p-2 text-right">{formatCurrency(p.arpu)}</td>
              <td className="p-2 text-right">{formatCurrency(p.estimated_ltv)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ConversionFunnelChart({ data }: { data: ConversionFunnel | null }) {
  if (!data || data.stages.length === 0) return <p>No funnel data.</p>
  const maxCount = data.stages[0]?.count || 1
  return (
    <div data-testid="conversion-funnel">
      <h3 className="text-lg font-medium mb-3">Conversion Funnel</h3>
      <div className="space-y-3">
        {data.stages.map((s) => {
          const widthPct = Math.max((s.count / maxCount) * 100, 5)
          return (
            <div key={s.stage} className="flex items-center gap-3">
              <span className="w-36 text-sm">{STAGE_LABELS[s.stage] ?? s.stage}</span>
              <div className="flex-1 bg-gray-200 rounded h-8 relative">
                <div
                  className="bg-indigo-500 h-8 rounded flex items-center px-2"
                  style={{ width: `${widthPct}%` }}
                  role="progressbar"
                  aria-valuenow={s.rate}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${STAGE_LABELS[s.stage] ?? s.stage}: ${s.count}`}
                >
                  <span className="text-white text-xs font-medium">{s.count}</span>
                </div>
              </div>
              <span className="text-sm w-16 text-right">{s.rate}%</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── Main Component ── */

export function AnalyticsDashboard() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [overview, setOverview] = useState<PlatformOverview | null>(null)
  const [tradeDistribution, setTradeDistribution] = useState<TradeDistribution | null>(null)
  const [moduleAdoption, setModuleAdoption] = useState<ModuleAdoptionEntry[]>([])
  const [geographic, setGeographic] = useState<GeographicDistribution | null>(null)
  const [revenue, setRevenue] = useState<RevenueMetrics | null>(null)
  const [funnel, setFunnel] = useState<ConversionFunnel | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [overviewRes, tradeRes, moduleRes, geoRes, revRes, funnelRes] = await Promise.all([
        apiClient.get('/api/v2/admin/analytics/overview'),
        apiClient.get('/api/v2/admin/analytics/trade-distribution'),
        apiClient.get('/api/v2/admin/analytics/module-adoption'),
        apiClient.get('/api/v2/admin/analytics/geographic'),
        apiClient.get('/api/v2/admin/analytics/revenue'),
        apiClient.get('/api/v2/admin/analytics/conversion-funnel'),
      ])
      setOverview(overviewRes.data)
      setTradeDistribution(tradeRes.data)
      setModuleAdoption(moduleRes.data.heatmap ?? [])
      setGeographic(geoRes.data)
      setRevenue(revRes.data)
      setFunnel(funnelRes.data)
    } catch (err: any) {
      setError(err?.message ?? 'Failed to load analytics data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12" data-testid="analytics-loading">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" role="status">
          <span className="sr-only">Loading analytics...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 text-red-600" data-testid="analytics-error">
        <p>Error loading analytics: {error}</p>
        <button onClick={fetchData} className="mt-2 text-blue-600 underline">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-8" data-testid="analytics-dashboard">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Platform Analytics</h2>
        <button
          onClick={fetchData}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Refresh
        </button>
      </div>

      <OverviewCards data={overview} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="bg-gray-50 rounded-lg p-4">
          <TradeDistributionChart data={tradeDistribution} />
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <GeographicMap data={geographic} />
        </div>
      </div>

      <div className="bg-gray-50 rounded-lg p-4">
        <ModuleHeatmap data={moduleAdoption} />
      </div>

      <div className="bg-gray-50 rounded-lg p-4">
        <RevenueChart data={revenue} />
      </div>

      <div className="bg-gray-50 rounded-lg p-4">
        <ConversionFunnelChart data={funnel} />
      </div>
    </div>
  )
}

export default AnalyticsDashboard
