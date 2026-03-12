import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Badge, Spinner, Modal, ToastContainer, useToast } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Item {
  id: string
  name: string
  description: string | null
  default_price: string
  is_gst_exempt: boolean
  category: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

interface ItemForm {
  name: string
  description: string
  default_price: string
  category: string
  is_gst_exempt: boolean
  is_active: boolean
}

const EMPTY_FORM: ItemForm = {
  name: '',
  description: '',
  default_price: '',
  category: '',
  is_gst_exempt: false,
  is_active: true,
}

const PAGE_SIZE = 20

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ItemsPage() {
  const [items, setItems] = useState<Item[]>([])
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

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = {
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }
      if (search.trim()) params.search = search.trim()

      const res = await apiClient.get<{ items: Item[]; total: number }>('/catalogue/items', { params })
      setItems(res.data.items)
      setTotal(res.data.total)
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

  const openEdit = (item: Item) => {
    setEditingId(item.id)
    setForm({
      name: item.name,
      description: item.description || '',
      default_price: item.default_price,
      category: item.category || '',
      is_gst_exempt: item.is_gst_exempt,
      is_active: item.is_active,
    })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Item name is required.'); return }
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
        is_gst_exempt: form.is_gst_exempt,
        is_active: form.is_active,
      }
      if (form.description.trim()) body.description = form.description.trim()
      if (form.category.trim()) body.category = form.category.trim()

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

  const handleToggleActive = async (item: Item) => {
    try {
      await apiClient.put(`/catalogue/items/${item.id}`, { is_active: !item.is_active })
      addToast('success', `Item ${item.is_active ? 'deactivated' : 'activated'}.`)
      fetchItems()
    } catch {
      addToast('error', 'Failed to update item status.')
    }
  }

  const updateField = <K extends keyof ItemForm>(field: K, value: ItemForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div className="h-full">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">Items</h1>
          <Button onClick={openCreate}>+ New Item</Button>
        </div>
      </div>

      <div className="px-6 py-4 space-y-4">
        {/* Search */}
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="Search items by name…"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="w-64 rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Search items"
          />
        </div>

        {/* Table */}
        {loading && items.length === 0 ? (
          <div className="py-16"><Spinner label="Loading items" /></div>
        ) : items.length === 0 && !loading ? (
          <div className="py-16 text-center">
            <p className="text-gray-500">No items found.</p>
            <p className="text-sm text-gray-400 mt-1">Add your first item to get started.</p>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200" role="grid">
                <caption className="sr-only">Items catalogue</caption>
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price (ex-GST)</th>
                    <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">GST Exempt</th>
                    <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => (
                    <tr key={item.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => openEdit(item)}>
                      <td className="px-4 py-3 text-sm">
                        <div className="font-medium text-gray-900">{item.name}</div>
                        {item.description && <div className="text-gray-500 text-xs mt-0.5 truncate max-w-xs">{item.description}</div>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {item.category || <span className="text-gray-400">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">
                        ${item.default_price}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        {item.is_gst_exempt ? (
                          <Badge variant="neutral">Exempt</Badge>
                        ) : (
                          <Badge variant="success">Incl.</Badge>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleToggleActive(item) }}
                          className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                          aria-label={`Toggle ${item.name} ${item.is_active ? 'inactive' : 'active'}`}
                        >
                          <Badge variant={item.is_active ? 'success' : 'neutral'}>
                            {item.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <Button size="sm" variant="secondary" onClick={(e) => { e.stopPropagation(); openEdit(item) }}>Edit</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 bg-gray-50">
                <span className="text-sm text-gray-600">
                  Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50 hover:bg-gray-100"
                  >
                    Previous
                  </button>
                  <span className="text-sm text-gray-600">Page {page} of {totalPages}</span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50 hover:bg-gray-100"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Create / Edit Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Item' : 'New Item'}>
        <div className="space-y-3">
          <Input label="Item name *" value={form.name} onChange={(e) => updateField('name', e.target.value)} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
              rows={2}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Optional item description"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Default price (ex-GST) *"
              type="number"
              min="0"
              step="0.01"
              value={form.default_price}
              onChange={(e) => updateField('default_price', e.target.value)}
              placeholder="e.g. 85.00"
            />
            <Input
              label="Category"
              value={form.category}
              onChange={(e) => updateField('category', e.target.value)}
              placeholder="e.g. Plumbing, Electrical"
            />
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={form.is_gst_exempt}
                onChange={(e) => updateField('is_gst_exempt', e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              GST exempt
            </label>
            {editingId && (
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => updateField('is_active', e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                Active
              </label>
            )}
          </div>
        </div>
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Item'}</Button>
        </div>
      </Modal>

      {/* Toast notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
