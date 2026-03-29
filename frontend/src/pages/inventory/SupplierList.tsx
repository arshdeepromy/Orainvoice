import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Supplier {
  id: string
  name: string
  contact_name: string | null
  email: string | null
  phone: string | null
  address: string | null
  account_number: string | null
  created_at: string
}

interface SupplierListResponse {
  suppliers: Supplier[]
  total: number
}

interface SupplierForm {
  name: string
  contact_name: string
  email: string
  phone: string
  address: string
  account_number: string
}

const EMPTY_FORM: SupplierForm = {
  name: '',
  contact_name: '',
  email: '',
  phone: '',
  address: '',
  account_number: '',
}

/**
 * Supplier list and create form.
 *
 * Requirements: 63.1
 */
export default function SupplierList() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState<SupplierForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const fetchSuppliers = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<SupplierListResponse>('/inventory/suppliers')
      setSuppliers(res.data?.suppliers ?? [])
    } catch {
      setError('Failed to load suppliers.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSuppliers() }, [fetchSuppliers])

  const handleCreate = async () => {
    if (!form.name.trim()) { setFormError('Supplier name is required.'); return }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, string> = { name: form.name.trim() }
      if (form.contact_name.trim()) body.contact_name = form.contact_name.trim()
      if (form.email.trim()) body.email = form.email.trim()
      if (form.phone.trim()) body.phone = form.phone.trim()
      if (form.address.trim()) body.address = form.address.trim()
      if (form.account_number.trim()) body.account_number = form.account_number.trim()

      await apiClient.post('/inventory/suppliers', body)
      setModalOpen(false)
      setForm(EMPTY_FORM)
      fetchSuppliers()
    } catch {
      setFormError('Failed to create supplier.')
    } finally {
      setSaving(false)
    }
  }

  const updateField = (field: keyof SupplierForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Manage supplier records linked to parts for tracking and reordering.
        </p>
        <Button onClick={() => { setForm(EMPTY_FORM); setFormError(''); setModalOpen(true) }}>+ New Supplier</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !suppliers.length && (
        <div className="py-16"><Spinner label="Loading suppliers" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Suppliers</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Contact</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Phone</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Account #</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {suppliers.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-500">
                    No suppliers yet. Add suppliers to link them to parts and generate purchase orders.
                  </td>
                </tr>
              ) : (
                suppliers.map((s) => (
                  <tr key={s.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{s.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.contact_name || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.email || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.phone || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.account_number || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Supplier Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="New Supplier">
        <div className="space-y-3">
          <Input label="Supplier name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <Input label="Contact person" value={form.contact_name} onChange={(e) => updateField('contact_name', e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Email" type="email" value={form.email} onChange={(e) => updateField('email', e.target.value)} />
            <Input label="Phone" value={form.phone} onChange={(e) => updateField('phone', e.target.value)} />
          </div>
          <Input label="Address" value={form.address} onChange={(e) => updateField('address', e.target.value)} />
          <Input label="Account number" value={form.account_number} onChange={(e) => updateField('account_number', e.target.value)} placeholder="Your account # with this supplier" />
        </div>
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleCreate} loading={saving}>Create Supplier</Button>
        </div>
      </Modal>
    </div>
  )
}
