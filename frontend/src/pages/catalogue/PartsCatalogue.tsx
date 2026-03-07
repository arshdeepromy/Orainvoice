import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Badge, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Part {
  id: string
  name: string
  part_number: string | null
  default_price: string
  supplier: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

interface PartForm {
  name: string
  part_number: string
  default_price: string
  supplier: string
  is_active: boolean
}

const EMPTY_FORM: PartForm = {
  name: '',
  part_number: '',
  default_price: '',
  supplier: '',
  is_active: true,
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function PartsCatalogue() {
  const [parts, setParts] = useState<Part[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create / Edit modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<PartForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const fetchParts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ parts: Part[]; total: number }>('/catalogue/parts')
      setParts(res.data.parts)
    } catch {
      setError('Failed to load parts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchParts() }, [fetchParts])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (part: Part) => {
    setEditingId(part.id)
    setForm({
      name: part.name,
      part_number: part.part_number || '',
      default_price: part.default_price,
      supplier: part.supplier || '',
      is_active: part.is_active,
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Part name is required.'); return }
    if (!form.default_price.trim() || isNaN(Number(form.default_price))) {
      setFormError('Valid default price is required.'); return
    }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        default_price: form.default_price.trim(),
        is_active: form.is_active,
      }
      if (form.part_number.trim()) body.part_number = form.part_number.trim()
      if (form.supplier.trim()) body.supplier = form.supplier.trim()

      if (editingId) {
        await apiClient.put(`/catalogue/parts/${editingId}`, body)
      } else {
        await apiClient.post('/catalogue/parts', body)
      }
      setModalOpen(false)
      fetchParts()
    } catch {
      setFormError(editingId ? 'Failed to update part.' : 'Failed to create part.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async (part: Part) => {
    try {
      await apiClient.put(`/catalogue/parts/${part.id}`, { is_active: !part.is_active })
      fetchParts()
    } catch {
      setError('Failed to update part status.')
    }
  }

  const updateField = <K extends keyof PartForm>(field: K, value: PartForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Pre-load common parts for quick selection during invoicing. Parts can also be added ad-hoc per invoice.
        </p>
        <Button onClick={openCreate}>+ New Part</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !parts.length && (
        <div className="py-16"><Spinner label="Loading parts" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Parts catalogue</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Number</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Default Price</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Supplier</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {parts.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                    No parts yet. Add common parts to speed up invoicing.
                  </td>
                </tr>
              ) : (
                parts.map((part) => (
                  <tr key={part.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{part.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{part.part_number || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">
                      ${part.default_price}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{part.supplier || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <button
                        onClick={() => handleToggleActive(part)}
                        className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                        aria-label={`Toggle ${part.name} ${part.is_active ? 'off' : 'on'}`}
                      >
                        <Badge variant={part.is_active ? 'success' : 'neutral'}>
                          {part.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <Button size="sm" variant="secondary" onClick={() => openEdit(part)}>Edit</Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Part' : 'New Part'}>
        <div className="space-y-3">
          <Input label="Part name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Part number"
              value={form.part_number}
              onChange={(e) => updateField('part_number', e.target.value)}
              placeholder="e.g. BRK-PAD-001"
            />
            <Input
              label="Default price *"
              type="number"
              value={form.default_price}
              onChange={(e) => updateField('default_price', e.target.value)}
              placeholder="e.g. 29.95"
            />
          </div>
          <Input
            label="Supplier"
            value={form.supplier}
            onChange={(e) => updateField('supplier', e.target.value)}
            placeholder="Optional supplier name"
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
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Part'}</Button>
        </div>
      </Modal>
    </div>
  )
}
