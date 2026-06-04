/**
 * Claims Reports page — tab navigation for different report types.
 *
 * Requirements: 10.1-10.6
 */

import { useState, useMemo } from 'react'
import { Tabs, Spinner, Badge } from '@/components/ui'
import { useBranch } from '@/contexts/BranchContext'
import {
  useClaimsByPeriodReport,
  useCostOverheadReport,
  useSupplierQualityReport,
  useServiceQualityReport,
} from '@/hooks/useClaimsReports'
import type { ReportFilters } from '@/hooks/useClaimsReports'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(amount: number | string | null | undefined): string {
  const num = typeof amount === 'string' ? parseFloat(amount) : (amount ?? 0)
  if (isNaN(num)) return '$0.00'
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(num)
}

function formatPeriod(period: string | null): string {
  if (!period) return '—'
  try {
    const d = new Date(period)
    return new Intl.DateTimeFormat('en-NZ', { month: 'short', year: 'numeric' }).format(d)
  } catch {
    return period
  }
}

const headerCellClass =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const headerCellRightClass =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/* ------------------------------------------------------------------ */
/*  Sub-components for each report tab                                 */
/* ------------------------------------------------------------------ */

function ClaimsByPeriodView({ filters }: { filters: ReportFilters }) {
  const { data, loading, error } = useClaimsByPeriodReport(filters)

  if (loading) return <Spinner size="sm" />
  if (error) return <p className="text-sm text-danger">{error}</p>

  const periods = data?.periods ?? []

  if (periods.length === 0) {
    return <p className="text-sm text-muted">No claims data for the selected period.</p>
  }

  return (
    <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Claims by period</caption>
        <thead>
          <tr>
            <th scope="col" className={headerCellClass}>Period</th>
            <th scope="col" className={headerCellRightClass}>Claims</th>
            <th scope="col" className={headerCellRightClass}>Total Cost</th>
            <th scope="col" className={headerCellRightClass}>Avg Resolution (hrs)</th>
          </tr>
        </thead>
        <tbody>
          {periods.map((row, i) => (
            <tr key={row.period ?? i} className="border-b border-border last:border-b-0 hover:bg-canvas">
              <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{formatPeriod(row.period)}</td>
              <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm text-text">{(row.claim_count ?? 0).toLocaleString()}</td>
              <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm text-text">{formatNZD(row.total_cost)}</td>
              <td className="mono whitespace-nowrap px-4 py-3 text-right text-sm text-text">{(row.average_resolution_hours ?? 0).toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


function CostOverheadView({ filters }: { filters: ReportFilters }) {
  const { data, loading, error } = useCostOverheadReport(filters)

  if (loading) return <Spinner size="sm" />
  if (error) return <p className="text-sm text-danger">{error}</p>
  if (!data) return <p className="text-sm text-muted">No cost data available.</p>

  const cards = [
    { label: 'Total Refunds', value: data.total_refunds, color: 'text-danger' },
    { label: 'Total Credit Notes', value: data.total_credit_notes, color: 'text-warn' },
    { label: 'Total Write-offs', value: data.total_write_offs, color: 'text-warn' },
    { label: 'Total Labour Cost', value: data.total_labour_cost, color: 'text-accent' },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <div key={card.label} className="rounded-card border border-border bg-card p-4 shadow-card">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">{card.label}</p>
          <p className={`mono mt-1 text-xl font-semibold ${card.color}`}>
            {formatNZD(card.value)}
          </p>
        </div>
      ))}
    </div>
  )
}

function SupplierQualityView({ filters }: { filters: ReportFilters }) {
  const { data, loading, error } = useSupplierQualityReport(filters)

  if (loading) return <Spinner size="sm" />
  if (error) return <p className="text-sm text-danger">{error}</p>

  const items = data?.items ?? []

  if (items.length === 0) {
    return <p className="text-sm text-muted">No supplier quality data for the selected period.</p>
  }

  return (
    <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Supplier quality — parts with highest return rates</caption>
        <thead>
          <tr>
            <th scope="col" className={headerCellClass}>Part Name</th>
            <th scope="col" className={headerCellClass}>SKU</th>
            <th scope="col" className={headerCellRightClass}>Return Count</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.product_id} className="border-b border-border last:border-b-0 hover:bg-canvas">
              <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{item.product_name}</td>
              <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">{item.sku || '—'}</td>
              <td className="whitespace-nowrap px-4 py-3 text-right text-sm text-text">
                <Badge variant="danger">{(item.return_count ?? 0).toLocaleString()}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ServiceQualityView({ filters }: { filters: ReportFilters }) {
  const { data, loading, error } = useServiceQualityReport(filters)

  if (loading) return <Spinner size="sm" />
  if (error) return <p className="text-sm text-danger">{error}</p>

  const items = data?.items ?? []

  if (items.length === 0) {
    return <p className="text-sm text-muted">No service quality data for the selected period.</p>
  }

  return (
    <div className="overflow-x-auto overflow-hidden rounded-card border border-border bg-card shadow-card">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Service quality — technicians with most redo claims</caption>
        <thead>
          <tr>
            <th scope="col" className={headerCellClass}>Technician</th>
            <th scope="col" className={headerCellRightClass}>Redo Count</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.staff_id} className="border-b border-border last:border-b-0 hover:bg-canvas">
              <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{item.staff_name}</td>
              <td className="whitespace-nowrap px-4 py-3 text-right text-sm text-text">
                <Badge variant="warn">{(item.redo_count ?? 0).toLocaleString()}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function ClaimsReports() {
  const { branches, selectedBranchId } = useBranch()
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [branchId, setBranchId] = useState(selectedBranchId ?? '')

  const filters = useMemo<ReportFilters>(() => ({
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    branch_id: branchId || undefined,
  }), [dateFrom, dateTo, branchId])

  return (
    <div className="space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="text-2xl font-bold text-text">Claims Reports</h1>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="report-date-from" className="mb-1 block text-sm font-medium text-text">From</label>
          <input
            id="report-date-from"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          />
        </div>
        <div>
          <label htmlFor="report-date-to" className="mb-1 block text-sm font-medium text-text">To</label>
          <input
            id="report-date-to"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          />
        </div>
        {(branches ?? []).length > 0 && (
          <div>
            <label htmlFor="report-branch" className="mb-1 block text-sm font-medium text-text">Branch</label>
            <select
              id="report-branch"
              value={branchId}
              onChange={(e) => setBranchId(e.target.value)}
              className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            >
              <option value="">All Branches</option>
              {(branches ?? []).map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Report tabs */}
      <Tabs
        tabs={[
          { id: 'by-period', label: 'Claims by Period', content: <ClaimsByPeriodView filters={filters} /> },
          { id: 'cost-overhead', label: 'Cost Overhead', content: <CostOverheadView filters={filters} /> },
          { id: 'supplier-quality', label: 'Supplier Quality', content: <SupplierQualityView filters={filters} /> },
          { id: 'service-quality', label: 'Service Quality', content: <ServiceQualityView filters={filters} /> },
        ]}
        defaultTab="by-period"
        urlPersist
      />
    </div>
  )
}
