import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Badge, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface LabourRate {
  id: string
  name: string
  hourly_rate: string
  is_active: boolean
  created_at: string
  updated_at: string
}

interface LabourRateForm {
  name: string
  hourly_rate: string
  is_active: boolean
}

const EMPTY_FORM: LabourRateForm = {
  name: '',
  hourly_rate: '',
  is_active: true,
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function LabourRates() {
  const [rates, setRates] = useState<LabourRate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create / Edit modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<LabourRateForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const fetchRates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ labour_rates: LabourRate[]; total: number }>('/catalogue/labour-rates')
      setRates(res.data.labour_rates)
    } catch {
      setError('Failed to load labour rates.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchRates() }, [fetchRates])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (rate: LabourRate) => {
    setEditingId(rate.id)
    setForm({
      name: rate.name,
      hourly_rate: rate.hourly_rate,
      is_active: rate.is_active,
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Rate name is required.'); return }
    if (!form.hourly_rate.trim() || isNaN(Number(form.hourly_rate))) {
      setFormError('Valid hourly rate is required.'); return
    }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        hourly_rate: form.hourly_rate.trim(),
        is_active: form.is_active,
      }

      if (editingId) {
        await apiClient.put(`/catalogue/labour-rates/${editingId}`, body)
      } else {
        await apiClient.post('/catalogue/labour-rates', body)
      }
      setModalOpen(false)
      fetchRates()
    } catch {
      setFormError(editingId ? 'Failed to update labour rate.' : 'Failed to create labour rate.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async (rate: LabourRate) => {
    try {
      await apiClient.put(`/catalogue/labour-rates/${rate.id}`, { is_active: !rate.is_active })
      fetchRates()
    } catch {
      setError('Failed to update rate status.')
    }
  }

  const handleDelete = async (rate: LabourRate) => {
    if (!window.confirm(`Permanently delete "${rate.name}"? This cannot be undone.`)) return
    try {
      await apiClient.delete(`/catalogue/labour-rates/${rate.id}`)
      fetchRates()
    } catch {
      setError('Failed to delete labour rate.')
    }
  }

  const updateField = <K extends keyof LabourRateForm>(field: K, value: LabourRateForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Configure named labour rates selectable when adding labour line items to invoices.
        </p>
        <Button onClick={openCreate}>+ New Rate</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !rates.length && (
        <div className="py-16"><Spinner label="Loading labour rates" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Labour rates</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Hourly Rate</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {rates.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-500">
                    No labour rates yet. Add rates like "Standard" or "Specialist" to use during invoicing.
                  </td>
                </tr>
              ) : (
                rates.map((rate) => (
                  <tr key={rate.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{rate.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">
                      ${rate.hourly_rate}/hr
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <button
                        onClick={() => handleToggleActive(rate)}
                        className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                        aria-label={`Toggle ${rate.name} ${rate.is_active ? 'off' : 'on'}`}
                      >
                        <Badge variant={rate.is_active ? 'success' : 'neutral'}>
                          {rate.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button size="sm" variant="secondary" onClick={() => openEdit(rate)}>Edit</Button>
                        <Button size="sm" variant="danger" onClick={() => handleDelete(rate)}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Labour Rate' : 'New Labour Rate'}>
        <div className="space-y-3">
          <Input label="Rate name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} placeholder="e.g. Standard Rate" />
          <Input
            label="Hourly rate ($) *"
            type="number"
            value={form.hourly_rate}
            onChange={(e) => updateField('hourly_rate', e.target.value)}
            placeholder="e.g. 95.00"
          />
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => updateField('is_active', e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Active
          </label>
        </div>
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Rate'}</Button>
        </div>
      </Modal>
    </div>
  )
}
