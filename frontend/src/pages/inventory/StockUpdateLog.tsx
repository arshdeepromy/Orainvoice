import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '../../api/client'
import { Badge, Spinner } from '../../components/ui'

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
  purchase: { label: 'Purchase', color: 'bg-green-100 text-green-800' },
  sale: { label: 'Sale', color: 'bg-blue-100 text-blue-800' },
  adjustment: { label: 'Adjustment', color: 'bg-amber-100 text-amber-800' },
  reservation: { label: 'Reserved', color: 'bg-orange-100 text-orange-800' },
  reservation_release: { label: 'Released', color: 'bg-gray-100 text-gray-700' },
}

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
    const info = TYPE_LABELS[type] || { label: type, color: 'bg-gray-100 text-gray-700' }
    return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${info.color}`}>{info.label}</span>
  }

  function catBadge(type: string) {
    switch (type) {
      case 'part': return <Badge variant="info">Part</Badge>
      case 'tyre': return <Badge variant="neutral">Tyre</Badge>
      case 'fluid': return <Badge variant="neutral" className="bg-purple-100 text-purple-800 border-purple-300">Fluid/Oil</Badge>
      default: return null
    }
  }

  if (loading) return <div className="py-16"><Spinner label="Loading stock update log" /></div>
  if (error) return <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>

  return (
    <div>
      {/* Filters row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search item, part no, barcode, supplier, notes..."
            className="w-64 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="all">All types</option>
            {movementTypes.map(t => <option key={t} value={t}>{(TYPE_LABELS[t]?.label || t)}</option>)}
          </select>
          <input type="date" value={dateFilter} onChange={e => setDateFilter(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          {(search || typeFilter !== 'all' || dateFilter) && (
            <button onClick={() => { setSearch(''); setTypeFilter('all'); setDateFilter('') }}
              className="text-xs text-blue-600 hover:underline">Clear filters</button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">{filtered.length} records</span>
          <label className="text-sm text-gray-500">Show</label>
          <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))}
            className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {PAGE_SIZES.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-6 py-12 text-center text-sm text-gray-500">
          {search || typeFilter !== 'all' || dateFilter ? 'No records match your filters.' : 'No stock movements recorded yet.'}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Action</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Item</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part No</th>
                  <th className="px-3 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Change</th>
                  <th className="px-3 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Result</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Supplier</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reason / Notes</th>
                  <th className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {paginated.map(r => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-gray-500">{formatDate(r.date)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm">{typeBadge(r.movement_type)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm">{catBadge(r.catalogue_type)}</td>
                    <td className="px-3 py-2.5 text-sm">
                      <span className="font-medium text-gray-900">{r.item_name || '—'}</span>
                      {r.subtitle && <span className="block text-xs text-gray-500">{r.subtitle}</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-gray-600">{r.part_number || '—'}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm text-right tabular-nums font-semibold">
                      <span className={r.direction === 'in' ? 'text-green-700' : r.direction === 'out' ? 'text-red-600' : 'text-gray-500'}>
                        {r.direction === 'in' ? '+' : ''}{r.quantity_change}{r.catalogue_type === 'fluid' ? ' L' : ''}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm text-right tabular-nums text-gray-700">
                      {r.resulting_quantity}{r.catalogue_type === 'fluid' ? ' L' : ''}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-gray-600">{r.supplier_name || '—'}</td>
                    <td className="px-3 py-2.5 text-xs text-gray-600 max-w-[200px] truncate" title={r.notes || ''}>
                      {r.notes || '—'}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-gray-500">{r.performed_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, filtered.length)} of {filtered.length}</p>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(1)} disabled={page === 1} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40">««</button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40">‹</button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let p: number
                  if (totalPages <= 5) p = i + 1
                  else if (page <= 3) p = i + 1
                  else if (page >= totalPages - 2) p = totalPages - 4 + i
                  else p = page - 2 + i
                  return <button key={p} onClick={() => setPage(p)} className={`rounded px-3 py-1 text-sm font-medium ${page === p ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>{p}</button>
                })}
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40">›</button>
                <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40">»»</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
