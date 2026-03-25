import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal, Input, Select } from '@/components/ui'

interface Expense {
  id: string
  job_id: string | null
  project_id: string | null
  invoice_id: string | null
  date: string
  description: string
  amount: string
  tax_amount: string
  category: string | null
  receipt_file_key: string | null
  is_pass_through: boolean
  is_invoiced: boolean
  created_at: string
}

interface Summary {
  total_amount: string
  total_tax: string
  total_count: number
  by_category: { category: string | null; total_amount: string; count: number }[]
}

const CATEGORIES = [
  { value: '', label: 'All Categories' },
  { value: 'materials', label: 'Materials' },
  { value: 'travel', label: 'Travel' },
  { value: 'subcontractor', label: 'Subcontractor' },
  { value: 'equipment', label: 'Equipment' },
  { value: 'fuel', label: 'Fuel' },
  { value: 'accommodation', label: 'Accommodation' },
  { value: 'meals', label: 'Meals' },
  { value: 'office', label: 'Office' },
  { value: 'other', label: 'Other' },
]

const EMPTY_FORM = {
  date: new Date().toISOString().split('T')[0],
  description: '',
  amount: '',
  tax_amount: '',
  category: '',
  is_pass_through: false,
  receipt_file_key: '',
}

function formatNZD(amount: string | number) {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(Number(amount))
}

function categoryLabel(cat: string | null) {
  return CATEGORIES.find(c => c.value === cat)?.label || cat || '—'
}

export default function ExpenseList() {
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [categoryFilter, setCategoryFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const pageSize = 20

  const [summary, setSummary] = useState<Summary | null>(null)

  // Create/Edit modal
  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [receiptUploading, setReceiptUploading] = useState(false)

  // Delete confirm
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchExpenses = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), page_size: String(pageSize) }
      if (categoryFilter) params.category = categoryFilter
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const res = await apiClient.get('/api/v2/expenses', { params })
      setExpenses(res.data.expenses || [])
      setTotal(res.data.total || 0)
    } catch { setExpenses([]) }
    finally { setLoading(false) }
  }, [page, categoryFilter, dateFrom, dateTo])

  const fetchSummary = useCallback(async () => {
    try {
      const params: Record<string, string> = {}
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const res = await apiClient.get('/api/v2/expenses/summary', { params })
      setSummary(res.data)
    } catch { /* non-blocking */ }
  }, [dateFrom, dateTo])

  useEffect(() => { fetchExpenses() }, [fetchExpenses])
  useEffect(() => { fetchSummary() }, [fetchSummary])

  const totalPages = Math.ceil(total / pageSize)

  const openCreate = () => {
    setEditId(null)
    setForm({ ...EMPTY_FORM })
    setFormError('')
    setShowModal(true)
  }

  const openEdit = (e: Expense) => {
    setEditId(e.id)
    setForm({
      date: e.date,
      description: e.description,
      amount: String(Number(e.amount)),
      tax_amount: String(Number(e.tax_amount)),
      category: e.category || '',
      is_pass_through: e.is_pass_through,
      receipt_file_key: e.receipt_file_key || '',
    })
    setFormError('')
    setShowModal(true)
  }

  const handleReceiptUpload = async (file: File) => {
    setReceiptUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await apiClient.post('/api/v2/uploads/receipts', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setForm(prev => ({ ...prev, receipt_file_key: res.data.file_key }))
    } catch { /* silent */ }
    finally { setReceiptUploading(false) }
  }

  const handleSave = async () => {
    if (!form.description.trim()) { setFormError('Description is required.'); return }
    if (!form.amount || isNaN(Number(form.amount)) || Number(form.amount) <= 0) { setFormError('Enter a valid amount.'); return }
    setSaving(true)
    setFormError('')
    try {
      const payload = {
        date: form.date,
        description: form.description.trim(),
        amount: Number(form.amount),
        tax_amount: Number(form.tax_amount) || 0,
        category: form.category || null,
        is_pass_through: form.is_pass_through,
        receipt_file_key: form.receipt_file_key || null,
      }
      if (editId) {
        await apiClient.put(`/api/v2/expenses/${editId}`, payload)
      } else {
        await apiClient.post('/api/v2/expenses', payload)
      }
      setShowModal(false)
      fetchExpenses()
      fetchSummary()
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || 'Failed to save expense.')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      await apiClient.delete(`/api/v2/expenses/${deleteId}`)
      setDeleteId(null)
      fetchExpenses()
      fetchSummary()
    } catch { /* silent */ }
    finally { setDeleting(false) }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Expenses</h1>
        <Button onClick={openCreate}>+ Add Expense</Button>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs font-medium uppercase text-gray-500">Total Expenses</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">{formatNZD(summary.total_amount)}</p>
            <p className="text-xs text-gray-400">{summary.total_count} record{summary.total_count !== 1 ? 's' : ''}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs font-medium uppercase text-gray-500">Total Tax</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">{formatNZD(summary.total_tax)}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-xs font-medium uppercase text-gray-500">Top Category</p>
            {summary.by_category.length > 0 ? (
              <>
                <p className="mt-1 text-lg font-semibold text-gray-900">{categoryLabel(summary.by_category[0].category)}</p>
                <p className="text-xs text-gray-400">{formatNZD(summary.by_category[0].total_amount)}</p>
              </>
            ) : <p className="mt-1 text-sm text-gray-400">—</p>}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <div className="w-44">
          <Select label="Category" options={CATEGORIES} value={categoryFilter}
            onChange={e => { setCategoryFilter(e.target.value); setPage(1) }} />
        </div>
        <div>
          <Input label="From" type="date" value={dateFrom}
            onChange={e => { setDateFrom(e.target.value); setPage(1) }} />
        </div>
        <div>
          <Input label="To" type="date" value={dateTo}
            onChange={e => { setDateTo(e.target.value); setPage(1) }} />
        </div>
        {(categoryFilter || dateFrom || dateTo) && (
          <div className="flex items-end">
            <Button size="sm" variant="secondary" onClick={() => { setCategoryFilter(''); setDateFrom(''); setDateTo(''); setPage(1) }}>
              Clear filters
            </Button>
          </div>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-16 text-center"><Spinner label="Loading expenses" /></div>
      ) : expenses.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
          <p className="text-gray-500">No expenses found.</p>
          <Button className="mt-4" onClick={openCreate}>Add your first expense</Button>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Amount</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Tax</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Receipt</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {expenses.map(exp => (
                  <tr key={exp.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {new Date(exp.date).toLocaleDateString('en-NZ')}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">{exp.description}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{categoryLabel(exp.category)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-medium tabular-nums text-gray-900">
                      {formatNZD(exp.amount)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-500">
                      {Number(exp.tax_amount) > 0 ? formatNZD(exp.tax_amount) : '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <div className="flex flex-wrap gap-1">
                        {exp.is_invoiced && <Badge variant="success">Invoiced</Badge>}
                        {exp.is_pass_through && <Badge variant="info">Pass-through</Badge>}
                        {!exp.is_invoiced && !exp.is_pass_through && <span className="text-gray-400 text-xs">—</span>}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {exp.receipt_file_key ? (
                        <a href={`/api/v2/files/${exp.receipt_file_key}`} target="_blank" rel="noopener noreferrer"
                          className="text-blue-600 hover:underline text-xs">View</a>
                      ) : <span className="text-gray-400 text-xs">—</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <div className="flex justify-end gap-2">
                        <button type="button" onClick={() => openEdit(exp)}
                          className="text-blue-600 hover:text-blue-800 text-xs font-medium">Edit</button>
                        {!exp.is_invoiced && (
                          <button type="button" onClick={() => setDeleteId(exp.id)}
                            className="text-red-500 hover:text-red-700 text-xs font-medium">Delete</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">{total} expense{total !== 1 ? 's' : ''}</p>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                <span className="flex items-center text-sm text-gray-600">Page {page} of {totalPages}</span>
                <Button size="sm" variant="secondary" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Create / Edit Modal */}
      <Modal open={showModal} onClose={() => setShowModal(false)} title={editId ? 'Edit Expense' : 'New Expense'}>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Input label="Date *" type="date" value={form.date}
              onChange={e => setForm(p => ({ ...p, date: e.target.value }))} />
            <Select label="Category" options={CATEGORIES} value={form.category}
              onChange={e => setForm(p => ({ ...p, category: e.target.value }))} />
          </div>
          <Input label="Description *" value={form.description} placeholder="What was this expense for?"
            onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Amount (ex-tax) *" type="number" min="0.01" step="0.01" value={form.amount}
              onChange={e => setForm(p => ({ ...p, amount: e.target.value }))} />
            <Input label="Tax amount" type="number" min="0" step="0.01" value={form.tax_amount}
              onChange={e => setForm(p => ({ ...p, tax_amount: e.target.value }))} />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
            <input type="checkbox" checked={form.is_pass_through}
              onChange={e => setForm(p => ({ ...p, is_pass_through: e.target.checked }))}
              className="rounded border-gray-300 text-blue-600" />
            Pass-through to invoice (charge to customer)
          </label>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Receipt</label>
            {form.receipt_file_key ? (
              <div className="flex items-center gap-2">
                <span className="text-sm text-green-600">✓ Receipt attached</span>
                <button type="button" onClick={() => setForm(p => ({ ...p, receipt_file_key: '' }))}
                  className="text-xs text-red-500 hover:underline">Remove</button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <input type="file" accept="image/*,.pdf"
                  onChange={e => { if (e.target.files?.[0]) handleReceiptUpload(e.target.files[0]) }}
                  className="text-sm text-gray-600" />
                {receiptUploading && <Spinner size="sm" label="Uploading…" />}
              </div>
            )}
          </div>
          {formError && <p className="text-sm text-red-600">{formError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowModal(false)}>Cancel</Button>
            <Button onClick={handleSave} loading={saving}>{editId ? 'Save Changes' : 'Add Expense'}</Button>
          </div>
        </div>
      </Modal>

      {/* Delete confirm */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Expense">
        <p className="text-sm text-gray-600 mb-4">Are you sure you want to delete this expense? This cannot be undone.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="danger" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
