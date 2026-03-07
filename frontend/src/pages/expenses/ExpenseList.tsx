/**
 * Expense list page with paginated table, receipt upload, category filter,
 * date range filter, and links to job/project.
 *
 * Validates: Requirement — Expense Module
 */

import React, { useEffect, useState, useCallback } from 'react'
import apiClient from '@/api/client'

interface Expense {
  id: string
  org_id: string
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

const CATEGORY_OPTIONS = [
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

export default function ExpenseList() {
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [categoryFilter, setCategoryFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [receiptUploading, setReceiptUploading] = useState(false)
  const pageSize = 20

  // Create form state
  const [newExpense, setNewExpense] = useState({
    date: new Date().toISOString().split('T')[0],
    description: '',
    amount: '',
    tax_amount: '0',
    category: '',
    is_pass_through: false,
    receipt_file_key: '',
  })

  const fetchExpenses = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      })
      if (categoryFilter) params.set('category', categoryFilter)
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)

      const res = await apiClient.get(`/api/v2/expenses?${params}`)
      setExpenses(res.data.expenses)
      setTotal(res.data.total)
    } catch {
      setExpenses([])
    } finally {
      setLoading(false)
    }
  }, [page, categoryFilter, dateFrom, dateTo])

  useEffect(() => { fetchExpenses() }, [fetchExpenses])

  const handleReceiptUpload = async (file: File) => {
    setReceiptUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await apiClient.post('/api/v2/uploads/receipts', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setNewExpense(prev => ({ ...prev, receipt_file_key: res.data.file_key }))
    } catch {
      // Upload failed — user can retry
    } finally {
      setReceiptUploading(false)
    }
  }

  const handleCreateExpense = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await apiClient.post('/api/v2/expenses', {
        date: newExpense.date,
        description: newExpense.description,
        amount: parseFloat(newExpense.amount),
        tax_amount: parseFloat(newExpense.tax_amount || '0'),
        category: newExpense.category || null,
        is_pass_through: newExpense.is_pass_through,
        receipt_file_key: newExpense.receipt_file_key || null,
      })
      setShowCreateForm(false)
      setNewExpense({
        date: new Date().toISOString().split('T')[0],
        description: '', amount: '', tax_amount: '0',
        category: '', is_pass_through: false, receipt_file_key: '',
      })
      fetchExpenses()
    } catch {
      // Creation failed
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return <div role="status" aria-label="Loading expenses">Loading expenses…</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Expenses</h1>
        <button onClick={() => setShowCreateForm(true)} aria-label="Add expense">
          + Add Expense
        </button>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <label htmlFor="category-filter">Category</label>
          <select
            id="category-filter"
            value={categoryFilter}
            onChange={e => { setCategoryFilter(e.target.value); setPage(1) }}
          >
            {CATEGORY_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="date-from">From</label>
          <input
            id="date-from"
            type="date"
            value={dateFrom}
            onChange={e => { setDateFrom(e.target.value); setPage(1) }}
          />
        </div>
        <div>
          <label htmlFor="date-to">To</label>
          <input
            id="date-to"
            type="date"
            value={dateTo}
            onChange={e => { setDateTo(e.target.value); setPage(1) }}
          />
        </div>
      </div>

      {/* Create form */}
      {showCreateForm && (
        <form onSubmit={handleCreateExpense} aria-label="Create expense">
          <div style={{ display: 'grid', gap: '0.5rem', marginBottom: '1rem', padding: '1rem', border: '1px solid #ccc' }}>
            <div>
              <label htmlFor="expense-date">Date</label>
              <input id="expense-date" type="date" required value={newExpense.date}
                onChange={e => setNewExpense(p => ({ ...p, date: e.target.value }))} />
            </div>
            <div>
              <label htmlFor="expense-description">Description</label>
              <input id="expense-description" type="text" required value={newExpense.description}
                onChange={e => setNewExpense(p => ({ ...p, description: e.target.value }))} />
            </div>
            <div>
              <label htmlFor="expense-amount">Amount</label>
              <input id="expense-amount" type="number" step="0.01" required value={newExpense.amount}
                onChange={e => setNewExpense(p => ({ ...p, amount: e.target.value }))} />
            </div>
            <div>
              <label htmlFor="expense-category">Category</label>
              <select id="expense-category" value={newExpense.category}
                onChange={e => setNewExpense(p => ({ ...p, category: e.target.value }))}>
                {CATEGORY_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="expense-pass-through">
                <input id="expense-pass-through" type="checkbox" checked={newExpense.is_pass_through}
                  onChange={e => setNewExpense(p => ({ ...p, is_pass_through: e.target.checked }))} />
                Pass-through to invoice
              </label>
            </div>
            <div>
              <label htmlFor="receipt-upload">Receipt</label>
              <input id="receipt-upload" type="file" accept="image/*,.pdf"
                onChange={e => { if (e.target.files?.[0]) handleReceiptUpload(e.target.files[0]) }} />
              {receiptUploading && <span role="status" aria-label="Uploading receipt">Uploading…</span>}
              {newExpense.receipt_file_key && <span>✓ Receipt attached</span>}
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button type="submit">Save Expense</button>
              <button type="button" onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        </form>
      )}

      {/* Expense table */}
      {expenses.length === 0 ? (
        <p>No expenses found. Add your first expense to get started.</p>
      ) : (
        <>
          <table role="grid" aria-label="Expenses list">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th>Category</th>
                <th>Amount</th>
                <th>Pass-through</th>
                <th>Invoiced</th>
                <th>Receipt</th>
                <th>Job</th>
                <th>Project</th>
              </tr>
            </thead>
            <tbody>
              {expenses.map(expense => (
                <tr key={expense.id} role="row">
                  <td>{new Date(expense.date).toLocaleDateString()}</td>
                  <td>{expense.description}</td>
                  <td>{expense.category || '—'}</td>
                  <td>${Number(expense.amount).toFixed(2)}</td>
                  <td>{expense.is_pass_through ? 'Yes' : 'No'}</td>
                  <td>{expense.is_invoiced ? 'Yes' : 'No'}</td>
                  <td>{expense.receipt_file_key ? <a href={`/api/v2/files/${expense.receipt_file_key}`}>View</a> : '—'}</td>
                  <td>{expense.job_id ? <a href={`/jobs/${expense.job_id}`}>View Job</a> : '—'}</td>
                  <td>{expense.project_id ? <a href={`/projects/${expense.project_id}`}>View Project</a> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <nav aria-label="Pagination">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
              <span>Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
