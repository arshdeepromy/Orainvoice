/**
 * FleetAccounts — Task 24 port of frontend/src/pages/customers/FleetAccounts.tsx.
 *
 * ALL logic is copied VERBATIM from the original: the fleet-account CRUD
 * (GET/POST/PUT/DELETE /customers/fleet-accounts), the create/edit modal
 * (name required, optional contact/email/phone/billing/notes trimmed before
 * send), the customer-count column, the total footer, and the delete
 * confirmation. The original already consumes the list safely
 * (`res.data?.fleet_accounts ?? []`); `setTotal` is hardened to `?? 0` here per
 * the safe-API rule.
 *
 * Design reference: OraInvoice_Handoff/app/FleetAccounts.html (the B2B fleet
 * prototype). That prototype is a different, fleet-portal-oriented screen
 * (Fleet / Status / Vehicles / Portal accounts / Last activity columns); FR-1
 * wins, so this page keeps production's column set and CRUD and styles it in the
 * prototype's language (FR-2b): `page page-wide` head with an eyebrow, a
 * card-wrapped token table with uppercase `.mono` heads + hover rows, and the
 * shared Modal/Button/Input primitives. `.mono` is applied to the numeric
 * customer-count cell (FR-2).
 */

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Spinner, Modal } from '@/components/ui'

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
      setTotal(res.data?.total ?? 0)
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

  const TH = 'mono border-b border-border px-5 py-[11px] text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">People · B2B</div>
          <h1>Fleet Accounts</h1>
          <p className="sub">Manage commercial fleet accounts with consolidated billing</p>
        </div>
        <div className="head-actions">
          <Button
            leftIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
              </svg>
            }
            onClick={openCreate}
          >
            New Fleet Account
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && !accounts.length && (
        <div className="py-16"><Spinner label="Loading fleet accounts" /></div>
      )}

      {!loading && (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse" role="grid">
              <caption className="sr-only">Fleet accounts</caption>
              <thead>
                <tr>
                  <th scope="col" className={`${TH} text-left`}>Name</th>
                  <th scope="col" className={`${TH} text-left`}>Contact</th>
                  <th scope="col" className={`${TH} text-left`}>Email</th>
                  <th scope="col" className={`${TH} text-right`}>Customers</th>
                  <th scope="col" className={`${TH} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {accounts.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-12 text-center text-[13px] text-muted">
                      No fleet accounts yet. Create one to manage commercial customers.
                    </td>
                  </tr>
                ) : (
                  accounts.map((acct) => (
                    <tr key={acct.id} className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas">
                      <td className="whitespace-nowrap px-5 py-3 text-[13.5px] font-medium text-text">{acct.name}</td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-muted">{acct.primary_contact_name || '—'}</td>
                      <td className="whitespace-nowrap px-5 py-3 text-[13.5px] text-text">{acct.primary_contact_email || '—'}</td>
                      <td className="mono whitespace-nowrap px-5 py-3 text-right text-[13.5px] text-text">{acct.customer_count}</td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-[13.5px]">
                        <div className="flex justify-end gap-2">
                          <Button size="sm" variant="ghost" onClick={() => openEdit(acct)}>Edit</Button>
                          <Button size="sm" variant="danger" onClick={() => setDeleteId(acct.id)}>Delete</Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {total > 0 && (
        <p className="mt-3 text-[13px] text-muted">
          <span className="mono">{total}</span> fleet account{total !== 1 ? 's' : ''}
        </p>
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
          <div className="flex flex-col gap-[7px]">
            <label htmlFor="fleet-notes" className="text-[12.5px] font-medium text-text">Notes</label>
            <textarea
              id="fleet-notes"
              value={form.notes}
              onChange={(e) => updateField('notes', e.target.value)}
              rows={2}
              className="w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text transition-[border-color,box-shadow] duration-150 placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>
        </div>
        {formError && <p className="mt-2 text-[12.5px] text-danger" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create'}</Button>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Fleet Account">
        <p className="mb-4 text-[13.5px] text-muted">
          Are you sure you want to delete this fleet account? This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
