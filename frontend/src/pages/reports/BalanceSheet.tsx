import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Spinner, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'
import { useBranch } from '@/contexts/BranchContext'

interface LineItem {
  account_id: string
  account_code: string
  account_name: string
  sub_type: string | null
  balance: number
}

interface BalanceSheetData {
  currency: string
  as_at_date: string
  assets: { current: LineItem[]; non_current: LineItem[]; total: number }
  liabilities: { current: LineItem[]; non_current: LineItem[]; total: number }
  equity: { items: LineItem[]; total: number }
  total_assets: number
  total_liabilities: number
  total_equity: number
  balanced: boolean
}

const fmt = (n: number) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function BalanceSheet() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const { branches, selectedBranchId } = useBranch()

  const [asAtDate, setAsAtDate] = useState(new Date().toISOString().slice(0, 10))
  const [branchId, setBranchId] = useState<string>(selectedBranchId ?? '')
  const [data, setData] = useState<BalanceSheetData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchReport = useCallback(async (signal?: AbortSignal) => {
    if (!asAtDate) return
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { as_at_date: asAtDate }
      if (branchId) params.branch_id = branchId
      const res = await apiClient.get<BalanceSheetData>('/reports/balance-sheet', { params, signal })
      setData(res.data ?? null)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'Failed to load report')
        setData(null)
      }
    } finally {
      setLoading(false)
    }
  }, [asAtDate, branchId])

  useEffect(() => {
    const controller = new AbortController()
    fetchReport(controller.signal)
    return () => controller.abort()
  }, [fetchReport])

  const renderItems = (items: LineItem[]) => (
    (items ?? []).length > 0 ? (
      <table className="w-full text-sm mb-2">
        <tbody>
          {(items ?? []).map(item => (
            <tr key={item.account_id} className="border-b border-gray-100">
              <td className="py-1.5 font-mono text-gray-500 w-20">{item.account_code}</td>
              <td className="py-1.5 text-gray-900">{item.account_name}</td>
              <td className="py-1.5 text-right text-gray-900">{fmt(item.balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    ) : (
      <p className="text-sm text-gray-400 italic mb-2">No items</p>
    )
  )

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Balance Sheet</h1>
        <p className="text-sm text-gray-500 mt-1">Financial position as at a specific date</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">As At Date</label>
          <input
            type="date"
            value={asAtDate}
            onChange={e => setAsAtDate(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        {(branches ?? []).length > 1 && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Branch</label>
            <select
              value={branchId}
              onChange={e => setBranchId(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All Branches</option>
              {(branches ?? []).map(b => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading report" /></div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{error}</div>
      ) : !data ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          Select a date to generate the report.
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="flex items-center justify-between mb-6 text-xs text-gray-500">
            <span>As at {data?.as_at_date}</span>
            <div className="flex items-center gap-2">
              <span>{data?.currency ?? 'NZD'}</span>
              <Badge variant={data?.balanced ? 'success' : 'error'}>
                {data?.balanced ? 'Balanced' : 'Unbalanced'}
              </Badge>
            </div>
          </div>

          {/* Assets */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">Assets</h3>
            <div className="ml-2 mb-3">
              <h4 className="text-xs font-medium text-gray-500 mb-1">Current Assets</h4>
              {renderItems(data?.assets?.current ?? [])}
            </div>
            <div className="ml-2 mb-3">
              <h4 className="text-xs font-medium text-gray-500 mb-1">Non-Current Assets</h4>
              {renderItems(data?.assets?.non_current ?? [])}
            </div>
            <div className="border-t-2 border-gray-300 py-2 flex justify-between font-semibold text-gray-900">
              <span>Total Assets</span>
              <span>{fmt(data?.total_assets ?? 0)}</span>
            </div>
          </div>

          {/* Liabilities */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">Liabilities</h3>
            <div className="ml-2 mb-3">
              <h4 className="text-xs font-medium text-gray-500 mb-1">Current Liabilities</h4>
              {renderItems(data?.liabilities?.current ?? [])}
            </div>
            <div className="ml-2 mb-3">
              <h4 className="text-xs font-medium text-gray-500 mb-1">Non-Current Liabilities</h4>
              {renderItems(data?.liabilities?.non_current ?? [])}
            </div>
            <div className="border-t-2 border-gray-300 py-2 flex justify-between font-semibold text-gray-900">
              <span>Total Liabilities</span>
              <span>{fmt(data?.total_liabilities ?? 0)}</span>
            </div>
          </div>

          {/* Equity */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">Equity</h3>
            {renderItems(data?.equity?.items ?? [])}
            <div className="border-t-2 border-gray-300 py-2 flex justify-between font-semibold text-gray-900">
              <span>Total Equity</span>
              <span>{fmt(data?.total_equity ?? 0)}</span>
            </div>
          </div>

          {/* Summary */}
          <div className="border-t-2 border-gray-800 py-3 flex justify-between font-bold text-gray-900">
            <span>Liabilities + Equity</span>
            <span>{fmt((data?.total_liabilities ?? 0) + (data?.total_equity ?? 0))}</span>
          </div>
        </div>
      )}
    </div>
  )
}
