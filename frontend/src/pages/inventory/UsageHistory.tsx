import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '../../api/client'
import { Badge, Button, Spinner } from '../../components/ui'

interface UsageRecord {
  id: string
  item_name: string
  subtitle: string | null
  part_number: string | null
  barcode: string | null
  catalogue_type: string
  quantity_used: number
  unit: string
  supplier_name: string | null
  vehicle_rego: string | null
  invoice_id: string | null
  invoice_number: string | null
  notes: string | null
  date: string
}

const PAGE_SIZE_OPTIONS = [10, 15, 20, 50, 100]

export default function UsageHistory() {
  const [records, setRecords] = useState<UsageRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await apiClient.get('/inventory/stock-items/usage-history', { params: { limit: 1000 } })
      setRecords(res.data?.usage ?? [])
    } catch { setError('Failed to load usage history.') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  // Client-side search filter
  const filtered = useMemo(() => {
    if (!search.trim()) return records
    const q = search.toLowerCase()
    return records.filter(r =>
      (r.item_name && r.item_name.toLowerCase().includes(q)) ||
      (r.subtitle && r.subtitle.toLowerCase().includes(q)) ||
      (r.part_number && r.part_number.toLowerCase().includes(q)) ||
      (r.barcode && r.barcode.toLowerCase().includes(q)) ||
      (r.vehicle_rego && r.vehicle_rego.toLowerCase().includes(q)) ||
      (r.supplier_name && r.supplier_name.toLowerCase().includes(q)) ||
      (r.invoice_number && r.invoice_number.toLowerCase().includes(q)) ||
      (r.catalogue_type && r.catalogue_type.toLowerCase().includes(q))
    )
  }, [records, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const paginated = useMemo(() => {
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page, pageSize])

  useEffect(() => { setPage(1) }, [pageSize, search])

  function typeBadge(type: string) {
    switch (type) {
      case 'part': return <Badge variant="info">Part</Badge>
      case 'tyre': return <Badge variant="neutral">Tyre</Badge>
      case 'fluid': return <Badge variant="neutral" className="bg-purple-100 text-purple-800 border-purple-300">Fluid/Oil</Badge>
      default: return <Badge variant="neutral">{type}</Badge>
    }
  }

  function formatDate(iso: string) {
    try { return new Date(iso).toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) }
    catch { return iso }
  }

  // Export CSV
  const exportCSV = () => {
    const headers = ['Type', 'Item', 'Tyre Size', 'Part No', 'Barcode', 'Qty Used', 'Unit', 'Vehicle', 'Supplier', 'Invoice', 'Date']
    const rows = filtered.map(r => [
      r.catalogue_type, r.item_name, r.subtitle || '', r.part_number || '', r.barcode || '',
      r.quantity_used, r.unit, r.vehicle_rego || '', r.supplier_name || '',
      r.invoice_number || '', formatDate(r.date),
    ])
    const csv = [headers, ...rows].map(row => row.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `inventory-usage-${new Date().toISOString().slice(0, 10)}.csv`
    a.click(); URL.revokeObjectURL(url)
  }

  // Export PDF (simple print-friendly table)
  const exportPDF = () => {
    const rows = filtered.map(r =>
      `<tr><td>${r.catalogue_type}</td><td>${r.item_name}${r.subtitle ? `<br><small>${r.subtitle}</small>` : ''}</td><td>${r.part_number || '—'}</td><td>${r.barcode || '—'}</td><td style="text-align:right">${r.quantity_used} ${r.unit}</td><td>${r.vehicle_rego || '—'}</td><td>${r.supplier_name || '—'}</td><td>${r.invoice_number || '—'}</td><td>${formatDate(r.date)}</td></tr>`
    ).join('')
    const html = `<!DOCTYPE html><html><head><title>Inventory Usage Report</title><style>body{font-family:Arial,sans-serif;font-size:12px;margin:20px}h1{font-size:18px}table{width:100%;border-collapse:collapse;margin-top:10px}th,td{border:1px solid #ddd;padding:6px 8px;text-align:left}th{background:#f5f5f5;font-weight:600}small{color:#888}@media print{body{margin:0}}</style></head><body><h1>Inventory Usage Report</h1><p>Generated: ${new Date().toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' })} — ${filtered.length} records${search ? ` (filtered: "${search}")` : ''}</p><table><thead><tr><th>Type</th><th>Item</th><th>Part No</th><th>Barcode</th><th>Qty Used</th><th>Vehicle</th><th>Supplier</th><th>Invoice</th><th>Date</th></tr></thead><tbody>${rows}</tbody></table></body></html>`
    const w = window.open('', '_blank')
    if (w) { w.document.write(html); w.document.close(); w.print() }
  }

  if (loading) return <div className="py-16"><Spinner label="Loading usage history" /></div>
  if (error) return <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          {search ? `${filtered.length} of ${records.length} records` : `Total: ${records.length} records`}
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search vehicle, item, part no, barcode, supplier..."
            className="w-64 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <Button variant="secondary" size="sm" onClick={exportCSV}>Export CSV</Button>
          <Button variant="secondary" size="sm" onClick={exportPDF}>Export PDF</Button>
          <label htmlFor="usage-page-size" className="text-sm text-gray-500 ml-2">Show</label>
          <select id="usage-page-size" value={pageSize} onChange={e => setPageSize(Number(e.target.value))}
            className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {PAGE_SIZE_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-6 py-12 text-center text-sm text-gray-500">
          {search ? 'No records match your search.' : 'No inventory usage recorded yet.'}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Item</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part No</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Barcode</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Qty Used</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Vehicle</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Supplier</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Invoice</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {paginated.map(r => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm">{typeBadge(r.catalogue_type)}</td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {r.item_name || '—'}
                      {r.subtitle && <p className="text-xs font-normal text-gray-500">{r.subtitle}</p>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{r.part_number || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{r.barcode || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-gray-900">
                      {r.quantity_used} {r.unit}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {r.vehicle_rego ? (
                        <span className="inline-flex items-center gap-1">
                          <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10m10 0h4m-4 0H9m4 0a1 1 0 001-1v-4a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V15a1 1 0 01-1 1h-1" /></svg>
                          {r.vehicle_rego}
                        </span>
                      ) : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{r.supplier_name || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {r.invoice_id ? (
                        <a href={`/invoices/${r.invoice_id}`} className="text-blue-600 hover:underline font-medium">
                          {r.invoice_number || 'Draft'}
                        </a>
                      ) : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">{formatDate(r.date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, filtered.length)} of {filtered.length}
              </p>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(1)} disabled={page === 1} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed">««</button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed">‹ Prev</button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let p: number
                  if (totalPages <= 5) p = i + 1
                  else if (page <= 3) p = i + 1
                  else if (page >= totalPages - 2) p = totalPages - 4 + i
                  else p = page - 2 + i
                  return <button key={p} onClick={() => setPage(p)} className={`rounded px-3 py-1 text-sm font-medium ${page === p ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>{p}</button>
                })}
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed">Next ›</button>
                <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed">»»</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
