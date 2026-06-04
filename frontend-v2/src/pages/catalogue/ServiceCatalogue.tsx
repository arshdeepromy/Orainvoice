import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Badge, Spinner, Modal } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ServiceCategory = 'warrant' | 'service' | 'repair' | 'diagnostic'

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

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_C = 'mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

function categoryBadgeVariant(cat: ServiceCategory): BadgeVariant {
  switch (cat) {
    case 'warrant': return 'warn'
    case 'service': return 'info'
    case 'repair': return 'danger'
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

  /* Delete confirm */
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchServices = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<{ services: Service[]; total: number }>('/catalogue/services')
      setServices(res.data?.services ?? [])
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
      gst_mode: svc.is_gst_exempt ? 'exempt' : (svc as any).gst_inclusive ? 'inclusive' : 'exclusive',
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
        gst_inclusive: form.gst_mode === 'inclusive',
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

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      await apiClient.delete(`/catalogue/services/${deleteId}`)
      setDeleteId(null)
      fetchServices()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to delete service.'
      setError(msg)
      setDeleteId(null)
    } finally { setDeleting(false) }
  }

  const updateField = <K extends keyof ServiceForm>(field: K, value: ServiceForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-muted">
          Configure services with default pricing. Inactive services are hidden from invoice creation but retained for history.
        </p>
        <Button onClick={openCreate}>+ New Service</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">{error}</div>
      )}

      {loading && !services.length && (
        <div className="py-16"><Spinner label="Loading services" /></div>
      )}

      {!loading && (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse" role="grid">
              <caption className="sr-only">Service catalogue</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Name</th>
                  <th scope="col" className={TH}>Category</th>
                  <th scope="col" className={TH_R}>Price (ex-GST)</th>
                  <th scope="col" className={TH_C}>GST</th>
                  <th scope="col" className={TH_C}>Status</th>
                  <th scope="col" className={TH_R}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {services.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-sm text-muted">
                      No services yet. Add your first service to get started.
                    </td>
                  </tr>
                ) : (
                  services.map((svc) => (
                    <tr key={svc.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 text-sm">
                        <div className="font-medium text-text">{svc.name}</div>
                        {svc.description && <div className="text-muted text-xs mt-0.5 truncate max-w-xs">{svc.description}</div>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Badge variant={categoryBadgeVariant(svc.category)}>{categoryLabel(svc.category)}</Badge>
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text text-right font-medium">
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
                          className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
                          aria-label={`Toggle ${svc.name} ${svc.is_active ? 'off' : 'on'}`}
                        >
                          <Badge variant={svc.is_active ? 'success' : 'neutral'}>
                            {svc.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => openEdit(svc)}>Edit</Button>
                          <Button size="sm" variant="ghost" onClick={() => handleToggleActive(svc)}>
                            {svc.is_active ? 'Deactivate' : 'Activate'}
                          </Button>
                          <Button size="sm" variant="danger" onClick={() => setDeleteId(svc.id)}>Delete</Button>
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

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Service' : 'New Service'}>
        <div className="space-y-3">
          <Input label="Service name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <div>
            <label className="block text-[12.5px] font-medium text-text mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
              rows={2}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text shadow-sm placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              placeholder="Optional service description"
            />
          </div>
          <div>
            <label className="block text-[12.5px] font-medium text-text mb-1">GST *</label>
            <div className="inline-flex rounded-ctl border border-border overflow-hidden w-full">
              {(['inclusive', 'exclusive', 'exempt'] as const).map((mode, i) => (
                <button key={mode} type="button" onClick={() => updateField('gst_mode', mode)}
                  className={`flex-1 py-2 text-sm font-medium transition-colors ${i > 0 ? 'border-l border-border' : ''} ${
                    form.gst_mode === mode ? 'bg-accent text-white' : 'bg-card text-text hover:bg-canvas'
                  }`}>
                  {mode === 'inclusive' ? 'GST Inclusive' : mode === 'exclusive' ? 'GST Exclusive' : 'GST Exempt'}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12.5px] font-medium text-text mb-1">
                {form.gst_mode
                  ? `Default price (${form.gst_mode === 'inclusive' ? 'inc-GST' : form.gst_mode === 'exempt' ? 'no GST' : 'ex-GST'}) *`
                  : 'Default price *'}
              </label>
              {!form.gst_mode ? (
                <div className="flex items-center gap-2 rounded-ctl border-2 border-dashed border-warn/40 bg-warn-soft px-3 py-2.5 text-sm text-warn">
                  <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                  Select a GST type above to unlock
                </div>
              ) : (
                <input
                  type="number" min="0" step="0.01"
                  value={form.default_price}
                  onChange={(e) => updateField('default_price', e.target.value)}
                  placeholder="e.g. 85.00"
                  className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-3 text-sm text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                />
              )}
            </div>
            <Select
              label="Category"
              options={CATEGORY_OPTIONS}
              value={form.category}
              onChange={(e) => updateField('category', e.target.value as ServiceCategory)}
            />
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-text">
              <input type="checkbox" checked={form.is_active}
                onChange={(e) => updateField('is_active', e.target.checked)}
                className="h-4 w-4 rounded border-border text-accent focus:ring-accent" />
              Active
            </label>
          </div>
        </div>
        {formError && <p className="mt-2 text-sm text-danger" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Service'}</Button>
        </div>
      </Modal>

      {/* Delete confirm */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Service">
        <p className="text-sm text-muted mb-4">This will permanently delete the service. This cannot be undone.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button size="sm" variant="danger" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
