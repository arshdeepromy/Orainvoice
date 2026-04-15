import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Modal, Spinner, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

interface Account {
  id: string
  org_id: string
  code: string
  name: string
  account_type: string
  sub_type: string | null
  description: string | null
  is_system: boolean
  is_active: boolean
  parent_id: string | null
  tax_code: string | null
  xero_account_code: string | null
  created_at: string
  updated_at: string
}

const ACCOUNT_TYPES = ['asset', 'liability', 'equity', 'revenue', 'expense', 'cogs'] as const

const typeColors: Record<string, 'info' | 'warning' | 'neutral' | 'success' | 'error'> = {
  asset: 'info',
  liability: 'warning',
  equity: 'neutral',
  revenue: 'success',
  expense: 'error',
  cogs: 'error',
}

export default function ChartOfAccounts() {
  const { isEnabled } = useModules()
  if (!isEnabled('accounting')) return <Navigate to="/dashboard" replace />

  const [accounts, setAccounts] = useState<Account[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState('')
  const [filterActive, setFilterActive] = useState<string>('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editAccount, setEditAccount] = useState<Account | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Form state
  const [formCode, setFormCode] = useState('')
  const [formName, setFormName] = useState('')
  const [formType, setFormType] = useState('expense')
  const [formSubType, setFormSubType] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formTaxCode, setFormTaxCode] = useState('')

  const fetchAccounts = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (filterType) params.account_type = filterType
      if (filterActive === 'true' || filterActive === 'false') params.is_active = filterActive
      const res = await apiClient.get<{ items: Account[]; total: number }>('/ledger/accounts', { params, signal })
      setAccounts(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setAccounts([])
        setTotal(0)
      }
    } finally {
      setLoading(false)
    }
  }, [filterType, filterActive])

  useEffect(() => {
    const controller = new AbortController()
    fetchAccounts(controller.signal)
    return () => controller.abort()
  }, [fetchAccounts])

  const openCreate = () => {
    setEditAccount(null)
    setFormCode('')
    setFormName('')
    setFormType('expense')
    setFormSubType('')
    setFormDescription('')
    setFormTaxCode('')
    setError('')
    setModalOpen(true)
  }

  const openEdit = (acct: Account) => {
    setEditAccount(acct)
    setFormCode(acct.code)
    setFormName(acct.name)
    setFormType(acct.account_type)
    setFormSubType(acct.sub_type ?? '')
    setFormDescription(acct.description ?? '')
    setFormTaxCode(acct.tax_code ?? '')
    setError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      if (editAccount) {
        await apiClient.put(`/ledger/accounts/${editAccount.id}`, {
          name: formName || undefined,
          sub_type: formSubType || undefined,
          description: formDescription || undefined,
          tax_code: formTaxCode || undefined,
        })
      } else {
        await apiClient.post('/ledger/accounts', {
          code: formCode,
          name: formName,
          account_type: formType,
          sub_type: formSubType || undefined,
          description: formDescription || undefined,
          tax_code: formTaxCode || undefined,
        })
      }
      setModalOpen(false)
      fetchAccounts()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to save account')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (acct: Account) => {
    if (!confirm(`Delete account ${acct.code} — ${acct.name}?`)) return
    try {
      await apiClient.delete(`/ledger/accounts/${acct.id}`)
      fetchAccounts()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(msg ?? 'Failed to delete account')
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Chart of Accounts</h1>
          <p className="text-sm text-gray-500 mt-1">{(total ?? 0).toLocaleString()} account{total !== 1 ? 's' : ''}</p>
        </div>
        <Button onClick={openCreate}>+ New Account</Button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Types</option>
          {ACCOUNT_TYPES.map(t => (
            <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
          ))}
        </select>
        <select
          value={filterActive}
          onChange={e => setFilterActive(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Status</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-8 text-center"><Spinner label="Loading accounts" /></div>
      ) : (accounts ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No accounts found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Code</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Tax Code</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">System</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(accounts ?? []).map(acct => (
                <tr key={acct.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-900">{acct.code}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{acct.name}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant={typeColors[acct.account_type] ?? 'neutral'}>
                      {acct.account_type}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">{acct.tax_code ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {acct.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="neutral">Inactive</Badge>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">{acct.is_system ? 'Yes' : '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                    {!acct.is_system && (
                      <div className="flex justify-end gap-2">
                        <button onClick={() => openEdit(acct)} className="text-blue-600 hover:underline text-xs">Edit</button>
                        <button onClick={() => handleDelete(acct)} className="text-red-600 hover:underline text-xs">Delete</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create/Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editAccount ? 'Edit Account' : 'New Account'}>
        <div className="space-y-4">
          {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>}
          {!editAccount && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Code</label>
                <input
                  type="text"
                  value={formCode}
                  onChange={e => setFormCode(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. 6100"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Account Type</label>
                <select
                  value={formType}
                  onChange={e => setFormType(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {ACCOUNT_TYPES.map(t => (
                    <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                  ))}
                </select>
              </div>
            </>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Account name"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Sub Type</label>
            <input
              type="text"
              value={formSubType}
              onChange={e => setFormSubType(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. current_asset"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={formDescription}
              onChange={e => setFormDescription(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={2}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Tax Code</label>
            <input
              type="text"
              value={formTaxCode}
              onChange={e => setFormTaxCode(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. GST, EXEMPT, NONE"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !formName}>
              {saving ? 'Saving…' : editAccount ? 'Update' : 'Create'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
