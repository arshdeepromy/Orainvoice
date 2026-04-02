/**
 * Claims Reports page — tab navigation for different report types.
 *
 * Requirements: 10.1-10.6
 */

import { useState, useMemo } from 'react'
import { Tabs, Spinner, Badge } from '../../components/ui'
import { useBranch } from '../../contexts/BranchContext'
import {
  useClaimsByPeriodReport,
  useCostOverheadReport,
  useSupplierQualityReport,
  useServiceQualityReport,
} from '../../hooks/useClaimsReports'
import type { ReportFilters } from '../../hooks/useClaimsReports'

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

/* ------------------------------------------------------------------ */
/*  Sub-components for each report tab                                 */
/* ------------------------------------------------------------------ */

function ClaimsByPeriodView({ filters }: { filters: ReportFilters }) {
  const { data, loading, error } = useClaimsByPeriodReport(filters)

  if (loading) return <Spinner size="sm" />
  if (error) return <p className="text-sm text-red-600">{error}</p>

  const periods = data?.periods ?? []

  if (periods.length === 0) {
    return <p className="text-sm text-gray-500">No claims data for the selected period.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200">
        <caption className="sr-only">Claims by period</caption>
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Period</th>
            <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Claims</th>
            <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total Cost</th>
            <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Avg Resolution (hrs)</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {periods.map((row, i) => (
            <tr key={row.period ?? i}>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{formatPeriod(row.period)}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{(row.claim_count ?? 0).toLocaleString()}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{formatNZD(row.total_cost)}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{(row.average_resolution_hours ?? 0).toFixed(1)}</td>
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
  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!data) return <p className="text-sm text-gray-500">No cost data available.</p>

  const cards = [
    { label: 'Total Refunds', value: data.total_refunds, color: 'text-red-600' },
    { label: 'Total Credit Notes', value: data.total_credit_notes, color: 'text-orange-600' },
    { label: 'Total Write-offs', value: data.total_write_offs, color: 'text-amber-600' },
    { label: 'Total Labour Cost', value: data.total_labour_cost, color: 'text-blue-600' },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <div key={card.label} className="rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">{card.label}</p>
          <p className={`mt-1 text-xl font-semibold tabular-nums ${card.color}`}>
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
  if (error) return <p className="text-sm text-red-600">{error}</p>

  const items = data?.items ?? []

  if (items.length === 0) {
    return <p className="text-sm text-gray-500">No supplier quality data for the selected period.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200">
        <caption className="sr-only">Supplier quality — parts with highest return rates</caption>
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Name</th>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">SKU</th>
            <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Return Count</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {items.map((item) => (
            <tr key={item.product_id}>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{item.product_name}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500 font-mono">{item.sku || '—'}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">
                <Badge variant="error">{(item.return_count ?? 0).toLocaleString()}</Badge>
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
  if (error) return <p className="text-sm text-red-600">{error}</p>

  const items = data?.items ?? []

  if (items.length === 0) {
    return <p className="text-sm text-gray-500">No service quality data for the selected period.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200">
        <caption className="sr-only">Service quality — technicians with most redo claims</caption>
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Technician</th>
            <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Redo Count</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {items.map((item) => (
            <tr key={item.staff_id}>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{item.staff_name}</td>
              <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">
                <Badge variant="warning">{(item.redo_count ?? 0).toLocaleString()}</Badge>
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
    <div className="px-4 py-6 sm:px-6 lg:px-8 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Claims Reports</h1>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="report-date-from" className="block text-sm font-medium text-gray-700 mb-1">From</label>
          <input
            id="report-date-from"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          />
        </div>
        <div>
          <label htmlFor="report-date-to" className="block text-sm font-medium text-gray-700 mb-1">To</label>
          <input
            id="report-date-to"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
          />
        </div>
        {(branches ?? []).length > 0 && (
          <div>
            <label htmlFor="report-branch" className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
            <select
              id="report-branch"
              value={branchId}
              onChange={(e) => setBranchId(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none"
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
