import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import {
  Button,
  Input,
  Badge,
  Spinner,
  Modal,
  ConfirmDialog,
  ToastContainer,
  useToast,
} from '@/components/ui'
import type { CatalogueItem, PackageComponent } from './types'
import PackageBuilder from './components/PackageBuilder'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ItemForm {
  name: string
  description: string
  default_price: string
  category: string
  is_gst_exempt: boolean
  gst_mode: 'inclusive' | 'exclusive' | 'exempt' | ''
  is_active: boolean
  is_package: boolean
  package_components: PackageComponent[]
}

const EMPTY_FORM: ItemForm = {
  name: '',
  description: '',
  default_price: '',
  category: '',
  is_gst_exempt: false,
  gst_mode: '',
  is_active: true,
  is_package: false,
  package_components: [],
}

const PAGE_SIZE = 20

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_C = 'mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ItemsCatalogue() {
  const { user } = useAuth()
  const userRole = user?.role ?? 'salesperson'
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'

  const [items, setItems] = useState<CatalogueItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')

  /* Toast notifications */
  const { toasts, addToast, dismissToast } = useToast()

  /* Create / Edit modal */
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<ItemForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  /* Duplicate modal */
  const [duplicateItem, setDuplicateItem] = useState<CatalogueItem | null>(null)
  const [duplicating, setDuplicating] = useState(false)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = {
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }
      if (search.trim()) params.search = search.trim()

      const res = await apiClient.get<{ items: CatalogueItem[]; total: number }>('/catalogue/items', { params })
      setItems(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      addToast('error', 'Failed to load items.')
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [page, search, addToast])

  useEffect(() => { fetchItems() }, [fetchItems])

  const handleSearchChange = (value: string) => {
    setSearch(value)
    setPage(1)
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  /* ---- Modal helpers ---- */

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (item: CatalogueItem) => {
    setEditingId(item.id)
    setForm({
      name: item.name,
      description: item.description || '',
      default_price: item.default_price,
      category: item.category || '',
      is_gst_exempt: item.is_gst_exempt,
      gst_mode: item.is_gst_exempt ? 'exempt' : item.gst_inclusive ? 'inclusive' : 'exclusive',
      is_active: item.is_active,
      is_package: item.is_package ?? false,
      package_components: item.package_components ?? [],
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Item name is required.'); return }
    if (!form.gst_mode) { setFormError('Please select a GST option before entering the price.'); return }
    if (!form.default_price.trim() || isNaN(Number(form.default_price))) {
      setFormError('Valid default price is required.'); return
    }
    if (Number(form.default_price) < 0) {
      setFormError('Price cannot be negative.'); return
    }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        default_price: form.default_price.trim(),
        is_gst_exempt: form.gst_mode === 'exempt',
        gst_inclusive: form.gst_mode === 'inclusive',
        is_active: form.is_active,
      }
      if (form.description.trim()) body.description = form.description.trim()
      if (form.category.trim()) body.category = form.category.trim()

      // Include package data
      const hasComponents = (form.package_components ?? []).length > 0
      body.is_package = hasComponents
      if (hasComponents) {
        body.package_components = form.package_components
      } else {
        body.package_components = null
      }

      if (editingId) {
        await apiClient.put(`/catalogue/items/${editingId}`, body)
        addToast('success', 'Item updated successfully.')
      } else {
        await apiClient.post('/catalogue/items', body)
        addToast('success', 'Item created successfully.')
      }
      setModalOpen(false)
      fetchItems()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || (editingId ? 'Failed to update item.' : 'Failed to create item.')
      setFormError(msg)
      addToast('error', msg)
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async (item: CatalogueItem) => {
    try {
      await apiClient.put(`/catalogue/items/${item.id}`, { is_active: !item.is_active })
      addToast('success', `Item ${item.is_active ? 'deactivated' : 'activated'}.`)
      fetchItems()
    } catch {
      addToast('error', 'Failed to update item status.')
    }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      await apiClient.delete(`/catalogue/items/${deleteId}`)
      setDeleteId(null)
      addToast('success', 'Item deleted.')
      fetchItems()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to delete item.'
      addToast('error', msg)
      setDeleteId(null)
    } finally { setDeleting(false) }
  }

  const handleDuplicate = async () => {
    if (!duplicateItem) return
    setDuplicating(true)
    try {
      await apiClient.post(`/catalogue/items/${duplicateItem.id}/duplicate`)
      addToast('success', 'Package duplicated.')
      setDuplicateItem(null)
      fetchItems()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to duplicate package.'
      addToast('error', msg)
      setDuplicateItem(null)
    } finally { setDuplicating(false) }
  }

  const handlePackageComponentsChange = (components: PackageComponent[]) => {
    setForm((prev) => ({
      ...prev,
      package_components: components,
      is_package: components.length > 0,
    }))
  }

  const updateField = <K extends keyof ItemForm>(field: K, value: ItemForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div />
        <Button onClick={openCreate}>+ New Item</Button>
      </div>

      <div className="space-y-4">
        {/* Search */}
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="Search items by name…"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="h-[42px] w-64 rounded-ctl border border-border bg-card px-3 text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            aria-label="Search items"
          />
        </div>

        {/* Table */}
        {loading && items.length === 0 ? (
          <div className="py-16"><Spinner label="Loading items" /></div>
        ) : items.length === 0 && !loading ? (
          <div className="py-16 text-center">
            <p className="text-muted">No items found.</p>
            <p className="text-sm text-muted-2 mt-1">Add your first item to get started.</p>
          </div>
        ) : (
          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse" role="grid">
                <caption className="sr-only">Items catalogue</caption>
                <thead>
                  <tr>
                    <th scope="col" className={TH}>Name</th>
                    <th scope="col" className={TH}>Category</th>
                    <th scope="col" className={TH_R}>Price (ex-GST)</th>
                    {isAdmin && (
                      <>
                        <th scope="col" className={TH_R}>Cost</th>
                        <th scope="col" className={TH_R}>Profit</th>
                      </>
                    )}
                    <th scope="col" className={TH_C}>GST Exempt</th>
                    <th scope="col" className={TH_C}>Status</th>
                    <th scope="col" className={TH_R}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b border-border last:border-b-0 hover:bg-canvas cursor-pointer" onClick={() => openEdit(item)}>
                      <td className="px-4 py-3 text-sm">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-text">{item.name}</span>
                          {(item.is_package ?? false) && (
                            <Badge variant="info" className="text-[10px]">Package</Badge>
                          )}
                          {(item.has_unavailable_components ?? false) && (
                            <span className="text-warn" title="Has unavailable components" aria-label="Warning: has unavailable components">⚠️</span>
                          )}
                        </div>
                        {item.description && <div className="text-muted text-xs mt-0.5 truncate max-w-xs">{item.description}</div>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">
                        {item.category || <span className="text-muted-2">—</span>}
                      </td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-sm text-text text-right font-medium">
                        ${item.default_price}
                      </td>
                      {isAdmin && (
                        <>
                          <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted text-right">
                            {(item.is_package ?? false) && item.package_cost != null
                              ? `${(item.package_cost ?? 0).toFixed(2)}`
                              : <span className="text-muted-2">—</span>}
                          </td>
                          <td className="mono whitespace-nowrap px-4 py-3 text-sm text-right">
                            {(item.is_package ?? false) && item.package_profit != null
                              ? (
                                <span className={(item.package_profit ?? 0) < 0 ? 'text-danger font-medium' : 'text-ok'}>
                                  ${(item.package_profit ?? 0).toFixed(2)}
                                </span>
                              )
                              : <span className="text-muted-2">—</span>}
                          </td>
                        </>
                      )}
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        {item.is_gst_exempt ? (
                          <Badge variant="neutral">Exempt</Badge>
                        ) : item.gst_inclusive ? (
                          <Badge variant="success">Incl.</Badge>
                        ) : (
                          <Badge variant="info">Excl.</Badge>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleToggleActive(item) }}
                          className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
                          aria-label={`Toggle ${item.name} ${item.is_active ? 'inactive' : 'active'}`}
                        >
                          <Badge variant={item.is_active ? 'success' : 'neutral'}>
                            {item.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); openEdit(item) }}>Edit</Button>
                          {(item.is_package ?? false) && (
                            <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setDuplicateItem(item) }}>Duplicate</Button>
                          )}
                          <Button size="sm" variant="danger" onClick={(e) => { e.stopPropagation(); setDeleteId(item.id) }}>Delete</Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-border px-4 py-3 bg-canvas">
                <span className="text-sm text-muted">
                  Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="rounded-ctl border border-border px-3 py-1.5 text-sm text-text disabled:opacity-50 hover:bg-card"
                  >
                    Previous
                  </button>
                  <span className="text-sm text-muted">Page {page} of {totalPages}</span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="rounded-ctl border border-border px-3 py-1.5 text-sm text-text disabled:opacity-50 hover:bg-card"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </div>

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Item' : 'New Item'}>
        <div className="space-y-3">
          <Input label="Item name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <div>
            <label className="block text-[12.5px] font-medium text-text mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
              rows={2}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              placeholder="Optional item description"
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
            <Input label="Category" value={form.category}
              onChange={(e) => updateField('category', e.target.value)}
              placeholder="e.g. Plumbing, Electrical" />
          </div>
          <div className="flex gap-6">
            {editingId && (
              <label className="flex items-center gap-2 text-sm text-text">
                <input type="checkbox" checked={form.is_active}
                  onChange={(e) => updateField('is_active', e.target.checked)}
                  className="h-4 w-4 rounded border-border text-accent focus:ring-accent" />
                Active
              </label>
            )}
          </div>

          {/* Unavailable component warning banner (edit mode) */}
          {editingId && (form.is_package ?? false) && (form.package_components ?? []).length > 0 && (() => {
            const unavailable = (form.package_components ?? []).filter(
              (c) => (c as PackageComponent & { is_available?: boolean }).is_available === false
            )
            if (unavailable.length === 0) return null
            return (
              <div className="rounded-ctl border border-warn/40 bg-warn-soft p-3 text-sm text-warn">
                <span className="font-medium">⚠ {unavailable.length} component{unavailable.length > 1 ? 's are' : ' is'} no longer available in inventory.</span>
              </div>
            )
          })()}

          {/* PackageBuilder integration */}
          <PackageBuilder
            components={form.package_components ?? []}
            onChange={handlePackageComponentsChange}
            sellPrice={Number(form.default_price) || 0}
            userRole={userRole}
            itemId={editingId}
          />
        </div>
        {formError && <p className="mt-2 text-sm text-danger" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Item'}</Button>
        </div>
      </Modal>

      {/* Delete confirm */}
      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Item">
        <p className="text-sm text-muted mb-4">This will permanently delete the item. This cannot be undone.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button size="sm" variant="danger" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>

      {/* Duplicate confirm */}
      <ConfirmDialog
        open={!!duplicateItem}
        title="Duplicate Package"
        message={`Create a copy of '${duplicateItem?.name ?? ''}'?`}
        confirmLabel="Duplicate"
        cancelLabel="Cancel"
        variant="primary"
        loading={duplicating}
        onConfirm={handleDuplicate}
        onCancel={() => setDuplicateItem(null)}
      />

      {/* Toast notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
