import { useState, useEffect, useCallback } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { Tabs } from '@/components/ui/Tabs'
import { DataTable, type Column } from '@/components/ui/DataTable'
import DateRangeFilter, { type DateRange } from '../reports/DateRangeFilter'
import ExportButtons from '../reports/ExportButtons'
import SimpleBarChart from '../reports/SimpleBarChart'
import apiClient from '@/api/client'

/* ── Types ── */

export interface MrrPlanBreakdown {
  plan: string
  mrr: number
  org_count: number
}

export interface MrrTrend {
  month: string
  mrr: number
}

export interface MrrData {
  total_mrr: number
  plan_breakdown: MrrPlanBreakdown[]
  trend: MrrTrend[]
}

export interface MrrApiResponse {
  total_mrr_nzd: number
  plan_breakdown: Array<{ plan_name: string; mrr_nzd: number; active_orgs: number }>
  month_over_month: Array<{ month: string; mrr_nzd: number }>
}

export interface OrgOverviewRow {
  id: string
  name: string
  plan: string
  signup_date: string
  trial_status: string | null
  billing_status: string
  storage_used_gb: number
  storage_quota_gb: number
  carjam_usage: number
  last_login: string | null
}

export interface CarjamCostData {
  total_cost: number
  total_revenue: number
  net: number
  monthly_breakdown: { month: string; cost: number; revenue: number }[]
}

export interface VehicleDbStatsData {
  total_records: number
  cache_hit_rate: number
  total_lookups: number
}

export interface ChurnRow {
  id: string
  name: string
  plan: string
  status: string
  cancelled_at: string
  subscription_duration_days: number
}

/* ── Helpers ── */

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
}

/* ── MRR Tab ── */

function MrrTab() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<MrrData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<MrrApiResponse>('/admin/reports/mrr', {
        params: { from: range.from, to: range.to },
      })
      const raw = res.data
      setData({
        total_mrr: raw.total_mrr_nzd ?? 0,
        plan_breakdown: (raw.plan_breakdown ?? []).map((p) => ({
          plan: p.plan_name,
          mrr: p.mrr_nzd,
          org_count: p.active_orgs,
        })),
        trend: (raw.month_over_month ?? []).map((m) => ({
          month: m.month,
          mrr: m.mrr_nzd,
        })),
      })
    } catch {
      setError('Failed to load MRR report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">Platform Monthly Recurring Revenue with plan breakdown and trend.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6">
        <DateRangeFilter value={range} onChange={setRange} />
        <ExportButtons endpoint="/admin/reports/mrr" params={{ from: range.from, to: range.to }} />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading MRR report" /></div>}

      {!loading && data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-1 gap-4 mb-6">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total MRR</p>
              <p className="text-2xl font-semibold text-gray-900">{fmt(data.total_mrr)}</p>
            </div>
          </div>

          {/* Plan breakdown table */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
            <h3 className="text-sm font-medium text-gray-700 mb-3">MRR by Plan</h3>
            <DataTable
              caption="MRR breakdown by plan"
              columns={[
                { key: 'plan', header: 'Plan', sortable: true },
                { key: 'org_count', header: 'Organisations', sortable: true },
                { key: 'mrr', header: 'MRR', sortable: true, render: (r) => fmt((r as unknown as MrrPlanBreakdown).mrr) },
              ] as Column<Record<string, unknown>>[]}
              data={data.plan_breakdown as unknown as Record<string, unknown>[]}
              keyField="plan"
            />
          </div>

          {/* Month-over-month trend chart */}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Month-over-Month Trend</h3>
            <SimpleBarChart
              title="MRR month-over-month trend"
              items={data.trend.map((t) => ({ label: t.month, value: t.mrr }))}
              formatValue={fmt}
            />
          </div>
        </>
      )}
    </div>
  )
}

/* ── Organisations Tab ── */

function OrganisationsTab() {
  const [data, setData] = useState<OrgOverviewRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [range, setRange] = useState<DateRange>(defaultRange)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{
        organisations: Array<Record<string, any>>
        total: number
      }>('/admin/reports/organisations', {
        params: { from: range.from, to: range.to },
      })
      setData((res.data.organisations ?? []).map((o) => ({
        id: o.organisation_id,
        name: o.organisation_name,
        plan: o.plan_name,
        signup_date: o.signup_date,
        trial_status: o.trial_status,
        billing_status: o.billing_status,
        storage_used_gb: Math.round((o.storage_used_bytes ?? 0) / (1024 * 1024 * 1024) * 10) / 10,
        storage_quota_gb: o.storage_quota_gb,
        carjam_usage: o.carjam_lookups_this_month ?? 0,
        last_login: o.last_login_at,
      })))
    } catch {
      setError('Failed to load organisation overview.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  const columns: Column<Record<string, unknown>>[] = [
    { key: 'name', header: 'Organisation', sortable: true },
    { key: 'plan', header: 'Plan', sortable: true },
    { key: 'signup_date', header: 'Signup Date', sortable: true, render: (r) => formatDate(r.signup_date as string) },
    {
      key: 'trial_status',
      header: 'Trial',
      sortable: true,
      render: (r) => {
        const v = r.trial_status as string | null
        if (!v) return '—'
        return <Badge variant={v === 'active' ? 'info' : 'neutral'}>{v}</Badge>
      },
    },
    {
      key: 'billing_status',
      header: 'Billing',
      sortable: true,
      render: (r) => {
        const v = r.billing_status as string
        const variant = v === 'active' ? 'success' : v === 'suspended' ? 'error' : 'warning'
        return <Badge variant={variant}>{v}</Badge>
      },
    },
    {
      key: 'storage_used_gb',
      header: 'Storage',
      sortable: true,
      render: (r) => `${(r.storage_used_gb as number).toFixed(1)} / ${r.storage_quota_gb} GB`,
    },
    { key: 'carjam_usage', header: 'Carjam Usage', sortable: true },
    { key: 'last_login', header: 'Last Login', sortable: true, render: (r) => formatDate(r.last_login as string | null) },
  ]

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">Overview of all organisations on the platform.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6">
        <DateRangeFilter value={range} onChange={setRange} />
        <ExportButtons endpoint="/admin/reports/organisations" params={{ from: range.from, to: range.to }} />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading organisation overview" /></div>}

      {!loading && (
        <DataTable
          caption="Organisation overview"
          columns={columns}
          data={data as unknown as Record<string, unknown>[]}
          keyField="id"
        />
      )}
    </div>
  )
}

/* ── Carjam Cost Tab ── */

function CarjamCostTab() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<CarjamCostData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{
        total_lookups: number
        total_cost_nzd: number
        total_revenue_nzd: number
        net_nzd: number
        per_lookup_cost_nzd: number
      }>('/admin/reports/carjam-cost', {
        params: { from: range.from, to: range.to },
      })
      const raw = res.data
      setData({
        total_cost: raw.total_cost_nzd ?? 0,
        total_revenue: raw.total_revenue_nzd ?? 0,
        net: raw.net_nzd ?? 0,
        monthly_breakdown: [],
      })
    } catch {
      setError('Failed to load Carjam cost report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">Carjam API cost vs revenue recovered from organisations.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6">
        <DateRangeFilter value={range} onChange={setRange} />
        <ExportButtons endpoint="/admin/reports/carjam-cost" params={{ from: range.from, to: range.to }} />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading Carjam cost report" /></div>}

      {!loading && data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total Cost</p>
              <p className="text-2xl font-semibold text-red-600">{fmt(data.total_cost)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total Revenue</p>
              <p className="text-2xl font-semibold text-green-600">{fmt(data.total_revenue)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Net</p>
              <p className={`text-2xl font-semibold ${data.net >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {fmt(data.net)}
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Monthly Cost vs Revenue</h3>
            <SimpleBarChart
              title="Monthly Carjam cost vs revenue"
              items={data.monthly_breakdown.flatMap((m) => [
                { label: `${m.month} Cost`, value: m.cost, colour: 'bg-red-400' },
                { label: `${m.month} Rev`, value: m.revenue, colour: 'bg-green-400' },
              ])}
              formatValue={fmt}
            />
          </div>
        </>
      )}
    </div>
  )
}

/* ── Vehicle DB Tab ── */

function VehicleDbTab() {
  const [data, setData] = useState<VehicleDbStatsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get<{
          total_records: number
          total_lookups_all_orgs: number
          cache_hit_rate: number
        }>('/admin/vehicle-db/stats')
        setData({
          total_records: res.data.total_records,
          cache_hit_rate: Math.round((res.data.cache_hit_rate ?? 0) * 100),
          total_lookups: res.data.total_lookups_all_orgs ?? 0,
        })
      } catch {
        setError('Failed to load Vehicle DB stats.')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">Global Vehicle Database statistics.</p>

      <div className="flex justify-end mb-6">
        <ExportButtons endpoint="/admin/reports/vehicle-db" />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading Vehicle DB stats" /></div>}

      {!loading && data && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Total Records</p>
            <p className="text-2xl font-semibold text-gray-900">{(data.total_records ?? 0).toLocaleString()}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Cache Hit Rate</p>
            <p className="text-2xl font-semibold text-gray-900">{data.cache_hit_rate}%</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Total Lookups</p>
            <p className="text-2xl font-semibold text-gray-900">{(data.total_lookups ?? 0).toLocaleString()}</p>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Churn Tab ── */

function ChurnTab() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<ChurnRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{
        churned_organisations: Array<Record<string, any>>
        total: number
      }>('/admin/reports/churn', {
        params: { from: range.from, to: range.to },
      })
      setData((res.data.churned_organisations ?? []).map((c) => ({
        id: c.organisation_id,
        name: c.organisation_name,
        plan: c.plan_name,
        status: c.status,
        cancelled_at: c.churned_at,
        subscription_duration_days: c.subscription_duration_days,
      })))
    } catch {
      setError('Failed to load churn report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  const columns: Column<Record<string, unknown>>[] = [
    { key: 'name', header: 'Organisation', sortable: true },
    { key: 'plan', header: 'Plan', sortable: true },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      render: (r) => {
        const v = r.status as string
        return <Badge variant={v === 'cancelled' ? 'error' : 'warning'}>{v}</Badge>
      },
    },
    { key: 'cancelled_at', header: 'Date', sortable: true, render: (r) => formatDate(r.cancelled_at as string) },
    {
      key: 'subscription_duration_days',
      header: 'Duration',
      sortable: true,
      render: (r) => {
        const days = r.subscription_duration_days as number
        if (days < 30) return `${days}d`
        const months = Math.round(days / 30)
        return months === 1 ? '1 month' : `${months} months`
      },
    },
  ]

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">Organisations that cancelled or were suspended.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6">
        <DateRangeFilter value={range} onChange={setRange} />
        <ExportButtons endpoint="/admin/reports/churn" params={{ from: range.from, to: range.to }} />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading churn report" /></div>}

      {!loading && (
        <DataTable
          caption="Churn report"
          columns={columns}
          data={data as unknown as Record<string, unknown>[]}
          keyField="id"
        />
      )}
    </div>
  )
}

/* ── Main Reports Page ── */

/**
 * Admin reports page with tabbed navigation for platform-wide analytics.
 * Tabs: MRR, Organisations, Carjam Cost, Vehicle DB, Churn
 *
 * Requirements: 46.1-46.5
 */
export function Reports() {
  const tabs = [
    { id: 'mrr', label: 'MRR', content: <MrrTab /> },
    { id: 'organisations', label: 'Organisations', content: <OrganisationsTab /> },
    { id: 'carjam-cost', label: 'Carjam Cost', content: <CarjamCostTab /> },
    { id: 'vehicle-db', label: 'Vehicle DB', content: <VehicleDbTab /> },
    { id: 'churn', label: 'Churn', content: <ChurnTab /> },
  ]

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Admin Reports</h1>
      <Tabs tabs={tabs} defaultTab="mrr" urlPersist />
    </div>
  )
}

export default Reports
