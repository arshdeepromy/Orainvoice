/**
 * Global admin branch overview — paginated table of all branches across all orgs.
 * Filter by org name, branch status, and module status.
 *
 * Validates: Requirements 13.1, 13.2, 21.1, 21.2, 21.3, 21.4
 */
import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import Badge from '@/components/ui/Badge'
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
  branch_module_enabled: boolean
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
  const [moduleStatusFilter, setModuleStatusFilter] = useState<string>('')
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
        if (moduleStatusFilter) params.module_status = moduleStatusFilter
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
  }, [page, orgFilter, statusFilter, moduleStatusFilter])

  useEffect(() => { setPage(1) }, [orgFilter, statusFilter, moduleStatusFilter])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-text">Branch Overview</h1>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <p className="text-sm text-muted">Active Branches</p>
            <p className="text-2xl font-semibold text-text mono">{summary.total_active ?? 0}</p>
          </div>
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <p className="text-sm text-muted">Inactive Branches</p>
            <p className="text-2xl font-semibold text-text mono">{summary.total_inactive ?? 0}</p>
          </div>
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <p className="text-sm text-muted">Avg Branches / Org</p>
            <p className="text-2xl font-semibold text-text mono">{(summary.avg_per_org ?? 0).toFixed(1)}</p>
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
          <label className="block text-[12.5px] font-medium text-text mb-1">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            aria-label="Filter by status"
          >
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <div className="w-44">
          <label className="block text-[12.5px] font-medium text-text mb-1">Module Status</label>
          <select
            value={moduleStatusFilter}
            onChange={(e) => setModuleStatusFilter(e.target.value)}
            className="h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            aria-label="Filter by module status"
          >
            <option value="">All</option>
            <option value="enabled">Enabled</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
      </div>

      {loading && branches.length === 0 && (
        <div className="py-16"><Spinner label="Loading branches" /></div>
      )}

      {!loading && (
        <>
          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">All branches across organisations</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Organisation</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Branch</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Module Status</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Created</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Timezone</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Users</th>
                </tr>
              </thead>
              <tbody>
                {branches.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-12 text-center text-sm text-muted">No branches found.</td></tr>
                ) : (
                  branches.map((b) => (
                    <tr
                      key={b.id}
                      className="border-b border-border last:border-b-0 hover:bg-canvas cursor-pointer"
                      onClick={() => setSelectedBranch(selectedBranch?.id === b.id ? null : b)}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">{b.org_name ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text">
                        {b.branch_name ?? '—'}
                        {b.is_hq && <Badge variant="info" className="ml-1">HQ</Badge>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <Badge variant={b.is_active ? 'success' : 'neutral'}>
                          {b.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <Badge variant={b.branch_module_enabled ? 'success' : 'neutral'}>
                          {b.branch_module_enabled ? 'Enabled' : 'Disabled'}
                        </Badge>
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">
                        {b.created_at ? new Date(b.created_at).toLocaleDateString('en-NZ') : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{b.timezone ?? '—'}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-right text-muted">{b.user_count ?? 0}</td>
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
        <div className="rounded-card border border-accent/30 bg-accent-soft p-4">
          <h3 className="text-sm font-semibold text-accent mb-2">{selectedBranch.branch_name} — Details</h3>
          <div className="grid grid-cols-2 gap-2 text-sm text-accent">
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
