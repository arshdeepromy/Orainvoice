/**
 * Global admin branch overview — paginated table of all branches across all orgs.
 * Filter by org name and branch status.
 *
 * Validates: Requirements 21.1, 21.2, 21.3, 21.4
 */
import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { Pagination } from '@/components/ui/Pagination'
import { Input } from '@/components/ui/Input'

interface BranchRow {
  id: string
  org_name: string
  branch_name: string
  is_active: boolean
  is_hq: boolean
  created_at: string
  timezone: string | null
  address: string | null
  phone: string | null
  email: string | null
  user_count: number
}

interface BranchSummary {
  total_active: number
  total_inactive: number
  avg_per_org: number
}

interface BranchListResponse {
  branches: BranchRow[]
  total: number
  summary: BranchSummary | null
}

export default function GlobalBranchOverview() {
  const [branches, setBranches] = useState<BranchRow[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<BranchSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [orgFilter, setOrgFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [selectedBranch, setSelectedBranch] = useState<BranchRow | null>(null)
  const pageSize = 20

  useEffect(() => {
    const controller = new AbortController()
    const fetchBranches = async () => {
      setLoading(true)
      try {
        const params: Record<string, string | number> = { page, page_size: pageSize }
        if (orgFilter.trim()) params.org_name = orgFilter.trim()
        if (statusFilter) params.status = statusFilter
        const res = await apiClient.get<BranchListResponse>('/admin/branches', {
          params,
          signal: controller.signal,
        })
        setBranches(res.data?.branches ?? [])
        setTotal(res.data?.total ?? 0)
        setSummary(res.data?.summary ?? null)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          // Silently fail
        }
      } finally {
        setLoading(false)
      }
    }
    fetchBranches()
    return () => controller.abort()
  }, [page, orgFilter, statusFilter])

  useEffect(() => { setPage(1) }, [orgFilter, statusFilter])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">Branch Overview</h1>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Active Branches</p>
            <p className="text-2xl font-semibold text-gray-900">{summary.total_active ?? 0}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Inactive Branches</p>
            <p className="text-2xl font-semibold text-gray-900">{summary.total_inactive ?? 0}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Avg Branches / Org</p>
            <p className="text-2xl font-semibold text-gray-900">{(summary.avg_per_org ?? 0).toFixed(1)}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1 max-w-sm">
          <Input
            label="Filter by org"
            placeholder="Organisation name…"
            value={orgFilter}
            onChange={(e) => setOrgFilter(e.target.value)}
            aria-label="Filter by organisation name"
          />
        </div>
        <div className="w-40">
          <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            aria-label="Filter by status"
          >
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </div>

      {loading && branches.length === 0 && (
        <div className="py-16"><Spinner label="Loading branches" /></div>
      )}

      {!loading && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">All branches across organisations</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Organisation</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Branch</th>
                  <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Created</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Timezone</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Users</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {branches.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">No branches found.</td></tr>
                ) : (
                  branches.map((b) => (
                    <tr
                      key={b.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => setSelectedBranch(selectedBranch?.id === b.id ? null : b)}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{b.org_name ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">
                        {b.branch_name ?? '—'}
                        {b.is_hq && <Badge variant="info" className="ml-1">HQ</Badge>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <Badge variant={b.is_active ? 'success' : 'neutral'}>
                          {b.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {b.created_at ? new Date(b.created_at).toLocaleDateString('en-NZ') : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{b.timezone ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{b.user_count ?? 0}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {total > pageSize && (
            <Pagination currentPage={page} totalPages={Math.ceil(total / pageSize)} onPageChange={setPage} />
          )}
        </>
      )}

      {/* Detail panel */}
      {selectedBranch && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <h3 className="text-sm font-semibold text-blue-900 mb-2">{selectedBranch.branch_name} — Details</h3>
          <div className="grid grid-cols-2 gap-2 text-sm text-blue-800">
            <div>Address: {selectedBranch.address ?? '—'}</div>
            <div>Phone: {selectedBranch.phone ?? '—'}</div>
            <div>Email: {selectedBranch.email ?? '—'}</div>
            <div>Users: {selectedBranch.user_count ?? 0}</div>
          </div>
        </div>
      )}
    </div>
  )
}
