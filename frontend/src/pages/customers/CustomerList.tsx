import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Pagination, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CustomerSearchResult {
  id: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
}

interface CustomerListResponse {
  customers: CustomerSearchResult[]
  total: number
  has_exact_match: boolean
}

interface CreateCustomerForm {
  first_name: string
  last_name: string
  email: string
  phone: string
  address: string
  notes: string
}

const EMPTY_FORM: CreateCustomerForm = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  address: '',
  notes: '',
}

const PAGE_SIZE = 20

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function CustomerList() {
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<CustomerListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create modal */
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<CreateCustomerForm>(EMPTY_FORM)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const abortRef = useRef<AbortController>()

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  /* --- Fetch customers --- */
  const fetchCustomers = useCallback(async (search: string, pg: number) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { page: pg, page_size: PAGE_SIZE }
      if (search.trim()) params.search = search.trim()

      const res = await apiClient.get<CustomerListResponse>('/customers', {
        params,
        signal: controller.signal,
      })
      setData(res.data)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError('Failed to load customers. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  /* --- Debounced search --- */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchCustomers(searchQuery, 1)
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchQuery, fetchCustomers])

  useEffect(() => {
    fetchCustomers(searchQuery, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  /* --- Create customer --- */
  const handleCreate = async () => {
    if (!form.first_name.trim() || !form.last_name.trim()) {
      setCreateError('First name and last name are required.')
      return
    }
    setCreating(true)
    setCreateError('')
    try {
      const body: Record<string, string> = {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
      }
      if (form.email.trim()) body.email = form.email.trim()
      if (form.phone.trim()) body.phone = form.phone.trim()
      if (form.address.trim()) body.address = form.address.trim()
      if (form.notes.trim()) body.notes = form.notes.trim()

      const res = await apiClient.post<{ customer: { id: string } }>('/customers', body)
      setCreateOpen(false)
      setForm(EMPTY_FORM)
      window.location.href = `/customers/${res.data.customer.id}`
    } catch {
      setCreateError('Failed to create customer.')
    } finally {
      setCreating(false)
    }
  }

  const updateField = (field: keyof CreateCustomerForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Customers</h1>
        <Button onClick={() => setCreateOpen(true)}>+ New Customer</Button>
      </div>

      {/* Search */}
      <div className="mb-4">
        <Input
          label="Search"
          placeholder="Search by name, phone, or email…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="Search customers"
        />
        {searchQuery && data && (
          <p className="mt-1 text-sm text-gray-500">
            {data.total} result{data.total !== 1 ? 's' : ''}
            {!data.has_exact_match && data.total === 0 && (
              <>
                {' — '}
                <button
                  onClick={() => setCreateOpen(true)}
                  className="text-blue-600 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                >
                  Create new customer
                </button>
              </>
            )}
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="py-16"><Spinner label="Loading customers" /></div>
      )}

      {/* Customer table */}
      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Customer list</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Phone</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.customers.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-sm text-gray-500">
                      {searchQuery ? 'No customers match your search.' : 'No customers yet. Create your first customer to get started.'}
                    </td>
                  </tr>
                ) : (
                  data.customers.map((c) => (
                    <tr
                      key={c.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => { window.location.href = `/customers/${c.id}` }}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">
                        {c.first_name} {c.last_name}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {c.email || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {c.phone || '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}
              </p>
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
            </div>
          )}
        </>
      )}

      {/* Create Customer Modal */}
      <Modal open={createOpen} onClose={() => { setCreateOpen(false); setCreateError('') }} title="New Customer">
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Input label="First name *" value={form.first_name} onChange={(e) => updateField('first_name', e.target.value)} />
            <Input label="Last name *" value={form.last_name} onChange={(e) => updateField('last_name', e.target.value)} />
          </div>
          <Input label="Email" type="email" value={form.email} onChange={(e) => updateField('email', e.target.value)} />
          <Input label="Phone" value={form.phone} onChange={(e) => updateField('phone', e.target.value)} />
          <Input label="Address" value={form.address} onChange={(e) => updateField('address', e.target.value)} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <textarea
              value={form.notes}
              onChange={(e) => updateField('notes', e.target.value)}
              rows={2}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>
        {createError && <p className="mt-2 text-sm text-red-600" role="alert">{createError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => { setCreateOpen(false); setCreateError('') }}>Cancel</Button>
          <Button size="sm" onClick={handleCreate} loading={creating}>Create Customer</Button>
        </div>
      </Modal>
    </div>
  )
}
