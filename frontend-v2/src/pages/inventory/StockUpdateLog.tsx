import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { Badge, Spinner } from '@/components/ui'

/**
 * StockUpdateLog — Task 35 port of frontend/src/pages/inventory/StockUpdateLog.tsx.
 *
 * Movement-log table with type/date/search filters, page-size selection, and a
 * custom pagination footer. ALL logic — fetch from
 * GET /inventory/stock-items/movement-log, filtering, derived movement types —
 * copied VERBATIM; presentation remapped onto the design tokens (FR-2b).
 */

interface MovementRecord {
  id: string
  item_name: string
  subtitle: string | null
  part_number: string | null
  barcode: string | null
  catalogue_type: string
  supplier_name: string | null
  movement_type: string
  quantity_change: number
  resulting_quantity: number
  direction: 'in' | 'out' | 'neutral'
  reference_type: string | null
  reference_id: string | null
  notes: string | null
  performed_by: string
  date: string
}

const PAGE_SIZES = [15, 20, 30, 50, 100]
const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  purchase: { label: 'Purchase', color: 'bg-ok-soft text-ok' },
  sale: { label: 'Sale', color: 'bg-accent-soft text-accent' },
  adjustment: { label: 'Adjustment', color: 'bg-warn-soft text-warn' },
  reservation: { label: 'Reserved', color: 'bg-warn-soft text-warn' },
  reservation_release: { label: 'Released', color: 'bg-[#EEF0F4] text-muted' },
}

const TH = 'mono border-b border-border px-3 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-3 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

export default function StockUpdateLog() {
  const [records, setRecords] = useState<MovementRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [dateFilter, setDateFilter] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)

  const fetchData = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await apiClient.get('/inventory/stock-items/movement-log')
      setRecords(res.data?.movements ?? [])
    } catch { setError('Failed to load stock update log.') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const filtered = useMemo(() => {
    let result = records
    if (typeFilter !== 'all') result = result.filter(r => r.movement_type === typeFilter)
    if (dateFilter) result = result.filter(r => r.date.startsWith(dateFilter))
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(r =>
        (r.item_name && r.item_name.toLowerCase().includes(q)) ||
        (r.subtitle && r.subtitle.toLowerCase().includes(q)) ||
        (r.part_number && r.part_number.toLowerCase().includes(q)) ||
        (r.barcode && r.barcode.toLowerCase().includes(q)) ||
        (r.supplier_name && r.supplier_name.toLowerCase().includes(q)) ||
        (r.notes && r.notes.toLowerCase().includes(q)) ||
        (r.performed_by && r.performed_by.toLowerCase().includes(q)) ||
        (r.catalogue_type && r.catalogue_type.toLowerCase().includes(q))
      )
    }
    return result
  }, [records, typeFilter, dateFilter, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const paginated = useMemo(() => filtered.slice((page - 1) * pageSize, page * pageSize), [filtered, page, pageSize])
  useEffect(() => { setPage(1) }, [pageSize, search, typeFilter, dateFilter])

  const movementTypes = useMemo(() => {
    const types = new Set(records.map(r => r.movement_type))
    return Array.from(types).sort()
  }, [records])

  function formatDate(iso: string) {
    try { return new Date(iso).toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) }
    catch { return iso }
  }

  function typeBadge(type: string) {
    const info = TYPE_LABELS[type] || { label: type, color: 'bg-[#EEF0F4] text-muted' }
    return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${info.color}`}>{info.label}</span>
  }

  function catBadge(type: string) {
    switch (type) {
      case 'part': return <Badge variant="info">Part</Badge>
      case 'tyre': return <Badge variant="neutral">Tyre</Badge>
      case 'fluid': return <Badge variant="neutral" className="bg-purple-soft text-purple">Fluid/Oil</Badge>
      default: return null
    }
  }

  if (loading) return <div className="py-16"><Spinner label="Loading stock update log" /></div>
  if (error) return <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger">{error}</div>

  return (
    <div>
      {/* Filters row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search item, part no, barcode, supplier, notes..."
            className="w-64 rounded-ctl border border-border bg-card px-3 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
            className="rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
            <option value="all">All types</option>
            {movementTypes.map(t => <option key={t} value={t}>{(TYPE_LABELS[t]?.label || t)}</option>)}
          </select>
          <input type="date" value={dateFilter} onChange={e => setDateFilter(e.target.value)}
            className="rounded-ctl border border-border bg-card px-2 py-1.5 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]" />
          {(search || typeFilter !== 'all' || dateFilter) && (
            <button onClick={() => { setSearch(''); setTypeFilter('all'); setDateFilter('') }}
              className="text-xs text-accent hover:underline">Clear filters</button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[13px] text-muted">{filtered.length} records</span>
          <label className="text-[13px] text-muted">Show</label>
          <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))}
            className="rounded-ctl border border-border bg-card px-2 py-1 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]">
            {PAGE_SIZES.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-card border border-border bg-canvas px-6 py-12 text-center text-[13px] text-muted">
          {search || typeFilter !== 'all' || dateFilter ? 'No records match your filters.' : 'No stock movements recorded yet.'}
        </div>
      ) : (
        <>
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className={TH}>Date</th>
                  <th className={TH}>Action</th>
                  <th className={TH}>Type</th>
                  <th className={TH}>Item</th>
                  <th className={TH}>Part No</th>
                  <th className={TH_R}>Change</th>
                  <th className={TH_R}>Result</th>
                  <th className={TH}>Supplier</th>
                  <th className={TH}>Reason / Notes</th>
                  <th className={TH}>By</th>
                </tr>
              </thead>
              <tbody>
                {paginated.map(r => (
                  <tr key={r.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="mono whitespace-nowrap px-3 py-2.5 text-xs text-muted">{formatDate(r.date)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm">{typeBadge(r.movement_type)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm">{catBadge(r.catalogue_type)}</td>
                    <td className="px-3 py-2.5 text-sm">
                      <span className="font-medium text-text">{r.item_name || '—'}</span>
                      {r.subtitle && <span className="block text-xs text-muted">{r.subtitle}</span>}
                    </td>
                    <td className="mono whitespace-nowrap px-3 py-2.5 text-xs text-muted">{r.part_number || '—'}</td>
                    <td className="mono whitespace-nowrap px-3 py-2.5 text-sm text-right font-semibold">
                      <span className={r.direction === 'in' ? 'text-ok' : r.direction === 'out' ? 'text-danger' : 'text-muted'}>
                        {r.direction === 'in' ? '+' : ''}{r.quantity_change}{r.catalogue_type === 'fluid' ? ' L' : ''}
                      </span>
                    </td>
                    <td className="mono whitespace-nowrap px-3 py-2.5 text-sm text-right text-muted">
                      {r.resulting_quantity}{r.catalogue_type === 'fluid' ? ' L' : ''}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{r.supplier_name || '—'}</td>
                    <td className="px-3 py-2.5 text-xs text-muted max-w-[200px] truncate" title={r.notes || ''}>
                      {r.notes || '—'}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{r.performed_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </section>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-[12.5px] text-muted">Showing <span className="mono text-text">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, filtered.length)}</span> of <span className="mono text-text">{filtered.length}</span></p>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(1)} disabled={page === 1} className="mono rounded-ctl px-2 py-1 text-sm text-muted hover:bg-canvas disabled:opacity-40">««</button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="rounded-ctl px-2 py-1 text-sm text-muted hover:bg-canvas disabled:opacity-40">‹</button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let p: number
                  if (totalPages <= 5) p = i + 1
                  else if (page <= 3) p = i + 1
                  else if (page >= totalPages - 2) p = totalPages - 4 + i
                  else p = page - 2 + i
                  return <button key={p} onClick={() => setPage(p)} className={`mono rounded-ctl px-3 py-1 text-sm font-medium ${page === p ? 'bg-accent text-white' : 'text-muted hover:bg-canvas'}`}>{p}</button>
                })}
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="rounded-ctl px-2 py-1 text-sm text-muted hover:bg-canvas disabled:opacity-40">›</button>
                <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="mono rounded-ctl px-2 py-1 text-sm text-muted hover:bg-canvas disabled:opacity-40">»»</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
