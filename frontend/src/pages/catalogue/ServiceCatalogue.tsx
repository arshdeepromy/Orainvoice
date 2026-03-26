import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Badge, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ServiceCategory = 'warrant' | 'service' | 'repair' | 'diagnostic'
type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

interface Service {
  id: string
  name: string
  description: string | null
  default_price: string
  is_gst_exempt: boolean
  category: ServiceCategory
  is_active: boolean
  created_at: string
  updated_at: string
}

interface ServiceForm {
  name: string
  description: string
  default_price: string
  is_gst_exempt: boolean
  gst_mode: 'inclusive' | 'exclusive' | 'exempt' | ''
  category: ServiceCategory
  is_active: boolean
}

const EMPTY_FORM: ServiceForm = {
  name: '',
  description: '',
  default_price: '',
  is_gst_exempt: false,
  gst_mode: '',
  category: 'service',
  is_active: true,
}

const CATEGORY_OPTIONS = [
  { value: 'warrant', label: 'Warrant' },
  { value: 'service', label: 'Service' },
  { value: 'repair', label: 'Repair' },
  { value: 'diagnostic', label: 'Diagnostic' },
]

function categoryBadgeVariant(cat: ServiceCategory): BadgeVariant {
  switch (cat) {
    case 'warrant': return 'warning'
    case 'service': return 'info'
    case 'repair': return 'error'
    case 'diagnostic': return 'neutral'
    default: return 'neutral'
  }
}

function categoryLabel(cat: ServiceCategory): string {
  return cat.charAt(0).toUpperCase() + cat.slice(1)
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ServiceCatalogue() {
  const [services, setServices] = useState<Service[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Create / Edit modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<ServiceForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const fetchServices = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ services: Service[]; total: number }>('/catalogue/services')
      setServices(res.data.services)
    } catch {
      setError('Failed to load services.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchServices() }, [fetchServices])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (svc: Service) => {
    setEditingId(svc.id)
    setForm({
      name: svc.name,
      description: svc.description || '',
      default_price: svc.default_price,
      is_gst_exempt: svc.is_gst_exempt,
      gst_mode: svc.is_gst_exempt ? 'exempt' : 'exclusive',
      category: svc.category,
      is_active: svc.is_active,
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Service name is required.'); return }
    if (!form.gst_mode) { setFormError('Please select a GST option before entering the price.'); return }
    if (!form.default_price.trim() || isNaN(Number(form.default_price))) {
      setFormError('Valid default price is required.'); return
    }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        default_price: form.default_price.trim(),
        is_gst_exempt: form.gst_mode === 'exempt',
        category: form.category,
        is_active: form.is_active,
      }
      if (form.description.trim()) body.description = form.description.trim()

      if (editingId) {
        await apiClient.put(`/catalogue/services/${editingId}`, body)
      } else {
        await apiClient.post('/catalogue/services', body)
      }
      setModalOpen(false)
      fetchServices()
    } catch {
      setFormError(editingId ? 'Failed to update service.' : 'Failed to create service.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async (svc: Service) => {
    try {
      await apiClient.put(`/catalogue/services/${svc.id}`, { is_active: !svc.is_active })
      fetchServices()
    } catch {
      setError('Failed to update service status.')
    }
  }

  const updateField = <K extends keyof ServiceForm>(field: K, value: ServiceForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Configure services with default pricing. Inactive services are hidden from invoice creation but retained for history.
        </p>
        <Button onClick={openCreate}>+ New Service</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !services.length && (
        <div className="py-16"><Spinner label="Loading services" /></div>
      )}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Service catalogue</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price (ex-GST)</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">GST</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {services.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                    No services yet. Add your first service to get started.
                  </td>
                </tr>
              ) : (
                services.map((svc) => (
                  <tr key={svc.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm">
                      <div className="font-medium text-gray-900">{svc.name}</div>
                      {svc.description && <div className="text-gray-500 text-xs mt-0.5 truncate max-w-xs">{svc.description}</div>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <Badge variant={categoryBadgeVariant(svc.category)}>{categoryLabel(svc.category)}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">
                      ${svc.default_price}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      {svc.is_gst_exempt ? (
                        <Badge variant="neutral">Exempt</Badge>
                      ) : (
                        <Badge variant="success">Incl.</Badge>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <button
                        onClick={() => handleToggleActive(svc)}
                        className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                        aria-label={`Toggle ${svc.name} ${svc.is_active ? 'off' : 'on'}`}
                      >
                        <Badge variant={svc.is_active ? 'success' : 'neutral'}>
                          {svc.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                      <Button size="sm" variant="secondary" onClick={() => openEdit(svc)}>Edit</Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Service' : 'New Service'}>
        <div className="space-y-3">
          <Input label="Service name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
              rows={2}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Optional service description"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                GST *
              </label>
              <div className="flex gap-3 pt-1">
                {(['inclusive', 'exclusive', 'exempt'] as const).map(mode => (
                  <label key={mode} className="flex items-center gap-1.5 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="svc_gst_mode"
                      checked={form.gst_mode === mode}
                      onChange={() => updateField('gst_mode', mode)}
                      className="h-4 w-4 text-blue-600"
                    />
                    {mode === 'inclusive' ? 'GST Inc.' : mode === 'exclusive' ? 'GST Excl.' : 'GST Exempt'}
                  </label>
                ))}
              </div>
            </div>
            <Input
              label={`Default price (${form.gst_mode === 'inclusive' ? 'inc-GST' : form.gst_mode === 'exempt' ? 'no GST' : 'ex-GST'}) *`}
              type="number"
              value={form.default_price}
              onChange={(e) => updateField('default_price', e.target.value)}
              placeholder="e.g. 85.00"
              disabled={!form.gst_mode}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Category"
              options={CATEGORY_OPTIONS}
              value={form.category}
              onChange={(e) => updateField('category', e.target.value as ServiceCategory)}
            />
          </div>
          <div className="flex gap-6">
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
        </div>
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Service'}</Button>
        </div>
      </Modal>
    </div>
  )
}
