import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Modal, Spinner, Badge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
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

const typeColors: Record<string, BadgeVariant> = {
  asset: 'info',
  liability: 'warn',
  equity: 'neutral',
  revenue: 'success',
  expense: 'danger',
  cogs: 'danger',
}

const TH =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_RIGHT =
  'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

const INPUT =
  'h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const SELECT =
  'rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
const LABEL = 'mb-1 block text-[12.5px] font-medium text-text'

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
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">Chart of Accounts</h1>
          <p className="mt-1 text-sm text-muted">{(total ?? 0).toLocaleString()} account{total !== 1 ? 's' : ''}</p>
        </div>
        <Button onClick={openCreate}>+ New Account</Button>
      </div>

      {/* Filters */}
      <div className="mb-4 flex gap-3">
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          className={`h-[42px] ${SELECT}`}
        >
          <option value="">All Types</option>
          {ACCOUNT_TYPES.map(t => (
            <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
          ))}
        </select>
        <select
          value={filterActive}
          onChange={e => setFilterActive(e.target.value)}
          className={`h-[42px] ${SELECT}`}
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
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted">
          No accounts found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className={TH}>Code</th>
                <th className={TH}>Name</th>
                <th className={TH}>Type</th>
                <th className={TH}>Tax Code</th>
                <th className={TH}>Status</th>
                <th className={TH}>System</th>
                <th className={TH_RIGHT}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(accounts ?? []).map(acct => (
                <tr key={acct.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text">{acct.code}</td>
                  <td className="px-4 py-3 text-sm text-text">{acct.name}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant={typeColors[acct.account_type] ?? 'neutral'}>
                      {acct.account_type}
                    </Badge>
                  </td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">{acct.tax_code ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {acct.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="neutral">Inactive</Badge>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{acct.is_system ? 'Yes' : '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                    {!acct.is_system && (
                      <div className="flex justify-end gap-2">
                        <button onClick={() => openEdit(acct)} className="text-xs text-accent hover:underline">Edit</button>
                        <button onClick={() => handleDelete(acct)} className="text-xs text-danger hover:underline">Delete</button>
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
          {error && <div className="rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}
          {!editAccount && (
            <>
              <div>
                <label className={LABEL}>Code</label>
                <input
                  type="text"
                  value={formCode}
                  onChange={e => setFormCode(e.target.value)}
                  className={INPUT}
                  placeholder="e.g. 6100"
                />
              </div>
              <div>
                <label className={LABEL}>Account Type</label>
                <select
                  value={formType}
                  onChange={e => setFormType(e.target.value)}
                  className={`${SELECT} w-full`}
                >
                  {ACCOUNT_TYPES.map(t => (
                    <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                  ))}
                </select>
              </div>
            </>
          )}
          <div>
            <label className={LABEL}>Name</label>
            <input
              type="text"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              className={INPUT}
              placeholder="Account name"
            />
          </div>
          <div>
            <label className={LABEL}>Sub Type</label>
            <input
              type="text"
              value={formSubType}
              onChange={e => setFormSubType(e.target.value)}
              className={INPUT}
              placeholder="e.g. current_asset"
            />
          </div>
          <div>
            <label className={LABEL}>Description</label>
            <textarea
              value={formDescription}
              onChange={e => setFormDescription(e.target.value)}
              className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              rows={2}
            />
          </div>
          <div>
            <label className={LABEL}>Tax Code</label>
            <input
              type="text"
              value={formTaxCode}
              onChange={e => setFormTaxCode(e.target.value)}
              className={INPUT}
              placeholder="e.g. GST, EXEMPT, NONE"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !formName}>
              {saving ? 'Saving…' : editAccount ? 'Update' : 'Create'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
