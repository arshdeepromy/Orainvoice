import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface FleetAccount {
  id: string
  name: string
  primary_contact_name: string | null
  primary_contact_email: string | null
  primary_contact_phone: string | null
  billing_address: string | null
  notes: string | null
  pricing_overrides: Record<string, unknown>
  customer_count: number
  created_at: string
  updated_at: string
}

interface FleetForm {
  name: string
  primary_contact_name: string
  primary_contact_email: string
  primary_contact_phone: string
  billing_address: string
  notes: string
}

const EMPTY_FORM: FleetForm = {
  name: '',
  primary_contact_name: '',
  primary_contact_email: '',
  primary_contact_phone: '',
  billing_address: '',
  notes: '',
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function FleetAccounts() {
  const [accounts, setAccounts] = useState<FleetAccount[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create / Edit modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FleetForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  /* Delete confirmation */
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchAccounts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ fleet_accounts: FleetAccount[]; total: number }>('/customers/fleet-accounts')
      setAccounts(res.data?.fleet_accounts ?? [])
      setTotal(res.data.total)
    } catch {
      setError('Failed to load fleet accounts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAccounts() }, [fetchAccounts])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (acct: FleetAccount) => {
    setEditingId(acct.id)
    setForm({
      name: acct.name,
      primary_contact_name: acct.primary_contact_name || '',
      primary_contact_email: acct.primary_contact_email || '',
      primary_contact_phone: acct.primary_contact_phone || '',
      billing_address: acct.billing_address || '',
      notes: acct.notes || '',
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Fleet name is required.')
      return
    }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, string> = { name: form.name.trim() }
      if (form.primary_contact_name.trim()) body.primary_contact_name = form.primary_contact_name.trim()
      if (form.primary_contact_email.trim()) body.primary_contact_email = form.primary_contact_email.trim()
      if (form.primary_contact_phone.trim()) body.primary_contact_phone = form.primary_contact_phone.trim()
      if (form.billing_address.trim()) body.billing_address = form.billing_address.trim()
      if (form.notes.trim()) body.notes = form.notes.trim()

      if (editingId) {
        await apiClient.put(`/customers/fleet-accounts/${editingId}`, body)
      } else {
        await apiClient.post('/customers/fleet-accounts', body)
      }
      setModalOpen(false)
      fetchAccounts()
    } catch {
      setFormError(editingId ? 'Failed to update fleet account.' : 'Failed to create fleet account.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      await apiClient.delete(`/customers/fleet-accounts/${deleteId}`)
      setDeleteId(null)
      fetchAccounts()
    } catch {
      setError('Failed to delete fleet account.')
    } finally {
      setDeleting(false)
    }
  }

  const updateField = (field: keyof FleetForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Fleet Accounts</h1>
          <p className="text-sm text-gray-500 mt-1">Manage commercial fleet accounts with consolidated billing</p>
        </div>
        <Button onClick={openCreate}>+ New Fleet Account</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !accounts.length && (
        <div className="py-16"><Spinner label="Loading fleet accounts" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Fleet accounts</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Contact</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Customers</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {accounts.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-500">
                    No fleet accounts yet. Create one to manage commercial customers.
                  </td>
                </tr>
              ) : (
                accounts.map((acct) => (
                  <tr key={acct.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{acct.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{acct.primary_contact_name || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{acct.primary_contact_email || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums">{acct.customer_count}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="secondary" onClick={() => openEdit(acct)}>Edit</Button>
                        <Button size="sm" variant="danger" onClick={() => setDeleteId(acct.id)}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {total > 0 && (
        <p className="mt-3 text-sm text-gray-500">{total} fleet account{total !== 1 ? 's' : ''}</p>
      )}

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Fleet Account' : 'New Fleet Account'}>
        <div className="space-y-3">
          <Input label="Fleet name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <Input label="Primary contact" value={form.primary_contact_name} onChange={(e) => updateField('primary_contact_name', e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Contact email" type="email" value={form.primary_contact_email} onChange={(e) => updateField('primary_contact_email', e.target.value)} />
            <Input label="Contact phone" value={form.primary_contact_phone} onChange={(e) => updateField('primary_contact_phone', e.target.value)} />
          </div>
          <Input label="Billing address" value={form.billing_address} onChange={(e) => updateField('billing_address', e.target.value)} />
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
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create'}</Button>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Fleet Account">
        <p className="text-sm text-gray-600 mb-4">
          Are you sure you want to delete this fleet account? This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
