import { useState, useCallback, useEffect, useRef } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Customer {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  mobile_phone?: string
  company_name?: string
  display_name?: string
  linked_vehicles?: { id: string; rego: string; make: string | null; model: string | null }[]
}

interface StatementLine {
  date: string | null
  description: string
  reference: string | null
  debit: number
  credit: number
  balance: number
}

interface StatementData {
  customer_id: string
  customer_name: string
  items: StatementLine[]
  opening_balance: number
  closing_balance: number
  period_start: string
  period_end: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 3, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) =>
  v != null
    ? new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(v)
    : '$0.00'

function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(d))
}

/* ------------------------------------------------------------------ */
/*  Customer Search (inline — same pattern as InvoiceCreate)           */
/* ------------------------------------------------------------------ */

function CustomerSearchInput({
  selected,
  onSelect,
}: {
  selected: Customer | null
  onSelect: (c: Customer | null) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setResults([]); return }
    setLoading(true)
    try {
      const res = await apiClient.get<{ customers: Customer[]; total: number } | Customer[]>(
        '/customers', { params: { q, include_vehicles: true } }
      )
      const customers = Array.isArray(res.data) ? res.data : (res.data?.customers || [])
      const term = q.toLowerCase()
      const seq = (h: string, n: string): boolean => {
        let ni = 0; const hl = h.toLowerCase()
        for (let i = 0; i < hl.length && ni < n.length; i++) { if (hl[i] === n[ni]) ni++ }
        return ni === n.length
      }
      setResults(customers.filter(c => {
        const fn = c.first_name || '', ln = c.last_name || '', dn = c.display_name || ''
        const ph = c.phone || '', co = c.company_name || ''
        const regoMatch = (c.linked_vehicles || []).some(v => seq(v.rego || '', term))
        return seq(fn, term) || seq(ln, term) || seq(dn, term) || seq(ph, term) || seq(co, term) || regoMatch
      }))
    } catch { setResults([]) }
    finally { setLoading(false) }
  }, [])

  const handleInput = (v: string) => {
    setQuery(v); setShowDropdown(true)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(v), 300)
  }

  if (selected) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2">
        <svg className="h-4 w-4 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
        <span className="flex-1 text-sm text-gray-900">
          {selected.display_name || `${selected.first_name} ${selected.last_name}`}
          {selected.company_name && <span className="ml-1 text-gray-500">({selected.company_name})</span>}
          {selected.phone && <span className="ml-2 text-gray-400">{selected.phone}</span>}
        </span>
        <button type="button" onClick={() => { onSelect(null); setQuery('') }} className="rounded p-1 text-gray-400 hover:text-gray-600" aria-label="Change customer">✕</button>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center gap-2 rounded-md border border-gray-300 px-3 shadow-sm focus-within:ring-2 focus-within:ring-blue-500">
        <svg className="h-4 w-4 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          placeholder="Search by name, phone, company, or vehicle rego…"
          value={query}
          onChange={e => handleInput(e.target.value)}
          onFocus={() => query.length >= 2 && setShowDropdown(true)}
          className="w-full py-2 text-sm text-gray-900 bg-transparent placeholder:text-gray-400 focus:outline-none"
          autoComplete="off"
        />
      </div>
      {showDropdown && (
        <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-64 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
          {loading && <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500"><Spinner size="sm" /> Searching…</div>}
          {!loading && results.map(c => (
            <button key={c.id} type="button" onClick={() => { onSelect(c); setQuery(c.display_name || `${c.first_name} ${c.last_name}`); setShowDropdown(false) }}
              className="w-full px-4 py-3 text-left hover:bg-gray-50 border-b border-gray-50 last:border-0">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-gray-900">{c.display_name || `${c.first_name} ${c.last_name}`}</span>
                  {c.company_name && <span className="ml-2 text-sm text-gray-500">({c.company_name})</span>}
                </div>
                <span className="text-xs text-gray-400">{c.phone || c.email}</span>
              </div>
              {c.linked_vehicles && c.linked_vehicles.length > 0 && (
                <div className="mt-1 text-xs text-gray-500">
                  Vehicles: {c.linked_vehicles.slice(0, 3).map(v => v.rego).join(', ')}
                  {c.linked_vehicles.length > 3 && ` +${c.linked_vehicles.length - 3} more`}
                </div>
              )}
            </button>
          ))}
          {!loading && query.length >= 2 && results.length === 0 && (
            <div className="px-4 py-3 text-sm text-gray-500">No customers found</div>
          )}
        </div>
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Customer statement — search for a customer, view invoices, payments,
 * and refunds in a date range with running balance. Printable.
 * Requirements: 45.7
 */
export default function CustomerStatement() {
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<StatementData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchStatement = useCallback(async () => {
    if (!customer) return
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { start_date: range.from, end_date: range.to }
      const branchId = localStorage.getItem('selected_branch_id')
      if (branchId && branchId !== 'all') params.branch_id = branchId
      const res = await apiClient.get<StatementData>(`/reports/customer-statement/${customer.id}`, {
        params,
      })
      setData(res.data)
    } catch {
      setError('Failed to load customer statement. Please check the customer and try again.')
    } finally {
      setLoading(false)
    }
  }, [customer, range])

  // Auto-fetch when customer or range changes
  useEffect(() => {
    if (customer) fetchStatement()
  }, [customer, range, fetchStatement])

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4 no-print">
        Search for a customer to generate a printable statement showing invoices, payments, and outstanding balance.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end flex-1">
          <div className="w-full sm:w-80">
            <label className="text-sm font-medium text-gray-700 mb-1 block">Customer</label>
            <CustomerSearchInput selected={customer} onSelect={setCustomer} />
          </div>
          <DateRangeFilter value={range} onChange={setRange} />
        </div>
        <div className="flex items-center gap-2">
          {customer && (
            <ExportButtons
              endpoint={`/reports/customer-statement/${customer.id}`}
              params={{ start_date: range.from, end_date: range.to }}
            />
          )}
          <PrintButton label="Print Statement" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading customer statement" /></div>}

      {!customer && !loading && (
        <div className="py-16 text-center text-sm text-gray-400">
          Search and select a customer above to generate their statement.
        </div>
      )}

      {!loading && data && customer && (
        <>
          {/* Statement header */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 mb-4">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">{data.customer_name}</h3>
                {customer.email && <p className="text-sm text-gray-500">{customer.email}</p>}
                {customer.phone && <p className="text-sm text-gray-500">{customer.phone}</p>}
                {customer.company_name && <p className="text-sm text-gray-500">{customer.company_name}</p>}
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-400 uppercase tracking-wider">Statement Period</p>
                <p className="text-sm text-gray-700">{formatDate(data.period_start)} — {formatDate(data.period_end)}</p>
              </div>
            </div>
          </div>

          {/* Balance summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Opening Balance</p>
              <p className="text-xl font-semibold text-gray-900">{fmt(data.opening_balance)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Closing Balance</p>
              <p className={`text-xl font-semibold ${data.closing_balance > 0 ? 'text-red-600' : 'text-green-600'}`}>
                {fmt(data.closing_balance)}
              </p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Transactions</p>
              <p className="text-xl font-semibold text-gray-900">{data.items?.length || 0}</p>
            </div>
          </div>

          {/* Statement table */}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Customer statement transactions</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reference</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Debit</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Credit</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {!data.items || data.items.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                      No transactions for this period.
                    </td>
                  </tr>
                ) : (
                  data.items.map((line, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{formatDate(line.date)}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{line.description}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{line.reference || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        {line.debit > 0 ? <span className="text-red-600">{fmt(line.debit)}</span> : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        {line.credit > 0 ? <span className="text-green-600">{fmt(line.credit)}</span> : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-right text-gray-900">{fmt(line.balance)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
