import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Badge, Spinner, Modal } from '../../components/ui'

interface Part {
  id: string
  name: string
  part_number: string | null
  description: string | null
  part_type: string
  category_id: string | null
  category_name: string | null
  brand: string | null
  supplier_id: string | null
  supplier_name: string | null
  default_price: string
  is_active: boolean
  tyre_width: string | null
  tyre_profile: string | null
  tyre_rim_dia: string | null
  tyre_load_index: string | null
  tyre_speed_index: string | null
  created_at: string
  updated_at: string
}

interface PartForm {
  name: string
  part_number: string
  description: string
  part_type: 'part' | 'tyre'
  category_id: string
  category_name: string
  brand: string
  supplier_id: string
  default_price: string
  gst_mode: 'inclusive' | 'exclusive' | 'exempt' | ''
  min_stock_threshold: string
  reorder_quantity: string
  is_active: boolean
  tyre_width: string
  tyre_profile: string
  tyre_rim_dia: string
  tyre_load_index: string
  tyre_speed_index: string
}

interface Category { id: string; name: string }
interface Supplier { id: string; name: string }

const EMPTY_FORM: PartForm = {
  name: '', part_number: '', description: '', part_type: 'part',
  category_id: '', category_name: '', brand: '', supplier_id: '',
  default_price: '', gst_mode: '', min_stock_threshold: '0', reorder_quantity: '0', is_active: true,
  tyre_width: '', tyre_profile: '', tyre_rim_dia: '',
  tyre_load_index: '', tyre_speed_index: '',
}

export default function PartsCatalogue() {
  const [parts, setParts] = useState<Part[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<PartForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Category search
  const [categories, setCategories] = useState<Category[]>([])
  const [catSearch, setCatSearch] = useState('')
  const [catDropOpen, setCatDropOpen] = useState(false)
  const [catCreating, setCatCreating] = useState(false)
  const catRef = useRef<HTMLDivElement>(null)

  // Suppliers
  const [suppliers, setSuppliers] = useState<Supplier[]>([])

  const fetchParts = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await apiClient.get<{ parts: Part[]; total: number }>('/catalogue/parts')
      setParts(res.data.parts)
    } catch { setError('Failed to load parts.') }
    finally { setLoading(false) }
  }, [])

  const fetchSuppliers = useCallback(async () => {
    try {
      const res = await apiClient.get('/inventory/suppliers')
      const data = res.data as any
      setSuppliers(Array.isArray(data?.suppliers) ? data.suppliers : [])
    } catch { /* non-blocking */ }
  }, [])

  const searchCategories = useCallback(async (q: string) => {
    try {
      const res = await apiClient.get('/catalogue/part-categories', { params: { search: q } })
      setCategories((res.data as any).categories || [])
    } catch { /* non-blocking */ }
  }, [])

  useEffect(() => { fetchParts(); fetchSuppliers() }, [fetchParts, fetchSuppliers])

  // Close category dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (catRef.current && !catRef.current.contains(e.target as Node)) setCatDropOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const openCreate = () => {
    setEditingId(null); setForm(EMPTY_FORM); setFormError(''); setCatSearch('')
    setModalOpen(true)
  }

  const openEdit = (part: Part) => {
    setEditingId(part.id)
    setForm({
      name: part.name,
      part_number: part.part_number || '',
      description: part.description || '',
      part_type: (part.part_type as 'part' | 'tyre') || 'part',
      category_id: part.category_id || '',
      category_name: part.category_name || '',
      brand: part.brand || '',
      supplier_id: part.supplier_id || '',
      default_price: part.default_price,
      gst_mode: (part as any).is_gst_exempt ? 'exempt' : (part as any).gst_inclusive ? 'inclusive' : 'exclusive',
      min_stock_threshold: String((part as any).min_stock_threshold ?? 0),
      reorder_quantity: String((part as any).reorder_quantity ?? 0),
      is_active: part.is_active,
      tyre_width: part.tyre_width || '',
      tyre_profile: part.tyre_profile || '',
      tyre_rim_dia: part.tyre_rim_dia || '',
      tyre_load_index: part.tyre_load_index || '',
      tyre_speed_index: part.tyre_speed_index || '',
    })
    setCatSearch(part.category_name || '')
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Part name is required.'); return }
    if (!form.gst_mode) { setFormError('Please select a GST option before entering the price.'); return }
    if (!form.default_price.trim() || isNaN(Number(form.default_price))) {
      setFormError('Valid price is required.'); return
    }
    setSaving(true); setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        default_price: form.default_price.trim(),
        is_gst_exempt: form.gst_mode === 'exempt',
        gst_inclusive: form.gst_mode === 'inclusive',
        is_active: form.is_active,
        part_type: form.part_type,
      }
      if (form.part_number.trim()) body.part_number = form.part_number.trim()
      if (form.description.trim()) body.description = form.description.trim()
      if (form.category_id) body.category_id = form.category_id
      if (form.brand.trim()) body.brand = form.brand.trim()
      if (form.min_stock_threshold) body.min_stock_threshold = parseInt(form.min_stock_threshold) || 0
      if (form.reorder_quantity) body.reorder_quantity = parseInt(form.reorder_quantity) || 0
      if (form.supplier_id) body.supplier_id = form.supplier_id
      if (form.part_type === 'tyre') {
        if (form.tyre_width.trim()) body.tyre_width = form.tyre_width.trim()
        if (form.tyre_profile.trim()) body.tyre_profile = form.tyre_profile.trim()
        if (form.tyre_rim_dia.trim()) body.tyre_rim_dia = form.tyre_rim_dia.trim()
        if (form.tyre_load_index.trim()) body.tyre_load_index = form.tyre_load_index.trim()
        if (form.tyre_speed_index.trim()) body.tyre_speed_index = form.tyre_speed_index.trim()
      }
      if (editingId) {
        await apiClient.put(`/catalogue/parts/${editingId}`, body)
      } else {
        await apiClient.post('/catalogue/parts', body)
      }
      setModalOpen(false); fetchParts()
    } catch { setFormError(editingId ? 'Failed to update part.' : 'Failed to create part.') }
    finally { setSaving(false) }
  }

  const handleToggleActive = async (part: Part) => {
    try {
      await apiClient.put(`/catalogue/parts/${part.id}`, { is_active: !(part as any).is_active })
      fetchParts()
    } catch { setError('Failed to update part status.') }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      await apiClient.delete(`/catalogue/parts/${deleteId}`)
      setDeleteId(null)
      fetchParts()
    } catch { setError('Failed to delete part.') }
    finally { setDeleting(false) }
  }

  const handleCreateCategory = async () => {
    if (!catSearch.trim()) return
    setCatCreating(true)
    try {
      const res = await apiClient.post('/catalogue/part-categories', { name: catSearch.trim() })
      const data = res.data as any
      setForm(f => ({ ...f, category_id: data.id, category_name: data.name }))
      setCatSearch(data.name)
      setCatDropOpen(false)
    } catch { /* non-blocking */ }
    finally { setCatCreating(false) }
  }

  const selectCategory = (cat: Category) => {
    setForm(f => ({ ...f, category_id: cat.id, category_name: cat.name }))
    setCatSearch(cat.name)
    setCatDropOpen(false)
  }

  const updateField = <K extends keyof PartForm>(field: K, value: PartForm[K]) => {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Pre-load common parts and tyres for quick selection during invoicing.
        </p>
        <Button onClick={openCreate}>+ New Part</Button>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {loading && !parts.length && <div className="py-16"><Spinner label="Loading parts" /></div>}

      {!loading && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part No</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Category</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Price</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Supplier</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {parts.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-500">No parts yet.</td></tr>
              ) : parts.map(part => (
                <tr key={part.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{part.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{part.part_number || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700 capitalize">{part.part_type}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{part.category_name || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">${part.default_price}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{part.supplier_name || '—'}</td>
                  <td className="px-4 py-3 text-sm text-center">
                    <Badge variant={part.is_active ? 'success' : 'neutral'}>{part.is_active ? 'Active' : 'Inactive'}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="secondary" onClick={() => openEdit(part)}>Edit</Button>
                      <Button size="sm" variant="secondary" onClick={() => handleToggleActive(part)}>
                        {(part as any).is_active !== false ? 'Deactivate' : 'Activate'}
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => setDeleteId(part.id)}>Delete</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Part' : 'New Part'}>
        <div className="space-y-3">
          {/* Part / Tyre toggle */}
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" checked={form.part_type === 'part'} onChange={() => updateField('part_type', 'part')} className="h-4 w-4 text-blue-600" />
              Part
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" checked={form.part_type === 'tyre'} onChange={() => updateField('part_type', 'tyre')} className="h-4 w-4 text-blue-600" />
              Tyre
            </label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Input label="Part No/Code" value={form.part_number} onChange={e => updateField('part_number', e.target.value)} placeholder="e.g. BRK-PAD-001" />
            <Input
              label={`Price (${form.gst_mode === 'inclusive' ? 'inc-GST' : form.gst_mode === 'exempt' ? 'no GST' : 'ex-GST'}) *`}
              type="number" value={form.default_price}
              onChange={e => updateField('default_price', e.target.value)}
              placeholder="e.g. 29.95"
              disabled={!form.gst_mode}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">GST *</label>
            <div className="inline-flex rounded-md border border-gray-300 overflow-hidden w-full">
              {(['inclusive', 'exclusive', 'exempt'] as const).map((mode, i) => (
                <button key={mode} type="button" onClick={() => updateField('gst_mode', mode)}
                  className={`flex-1 py-2 text-sm font-medium transition-colors ${i > 0 ? 'border-l border-gray-300' : ''} ${
                    form.gst_mode === mode ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                  }`}>
                  {mode === 'inclusive' ? 'GST Inclusive' : mode === 'exclusive' ? 'GST Exclusive' : 'GST Exempt'}
                </button>
              ))}
            </div>
          </div>

          <Input label="Part name *" value={form.name} onChange={e => updateField('name', e.target.value)} />

          {form.part_type === 'part' && (
            <Input label="Description" value={form.description} onChange={e => updateField('description', e.target.value)} />
          )}

          {form.part_type === 'tyre' && (
            <div className="grid grid-cols-5 gap-2">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Width</label>
                <input value={form.tyre_width} onChange={e => updateField('tyre_width', e.target.value)} className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" placeholder="205" />
              </div>
              <div className="flex items-end pb-1 justify-center text-gray-400 font-bold">/</div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Profile</label>
                <input value={form.tyre_profile} onChange={e => updateField('tyre_profile', e.target.value)} className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" placeholder="55" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Rim Dia</label>
                <div className="flex items-center gap-1">
                  <span className="text-gray-400 font-bold text-sm">R</span>
                  <input value={form.tyre_rim_dia} onChange={e => updateField('tyre_rim_dia', e.target.value)} className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" placeholder="16" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Load/Speed</label>
                <div className="flex gap-1">
                  <input value={form.tyre_load_index} onChange={e => updateField('tyre_load_index', e.target.value)} className="w-full rounded-md border border-gray-300 px-1 py-1.5 text-sm" placeholder="91" />
                  <input value={form.tyre_speed_index} onChange={e => updateField('tyre_speed_index', e.target.value)} className="w-full rounded-md border border-gray-300 px-1 py-1.5 text-sm" placeholder="V" />
                </div>
              </div>
            </div>
          )}

          {/* Category with live search + create */}
          <div ref={catRef} className="relative">
            <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
            <input
              value={catSearch}
              onChange={e => { setCatSearch(e.target.value); searchCategories(e.target.value); setCatDropOpen(true) }}
              onFocus={() => { searchCategories(catSearch); setCatDropOpen(true) }}
              placeholder="Search or type to create..."
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
            {catDropOpen && (
              <div className="absolute z-10 mt-1 w-full rounded-md border border-gray-200 bg-white shadow-lg max-h-48 overflow-y-auto">
                {categories.map(cat => (
                  <button key={cat.id} onClick={() => selectCategory(cat)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 text-gray-900">
                    {cat.name}
                  </button>
                ))}
                {catSearch.trim() && !categories.some(c => c.name.toLowerCase() === catSearch.trim().toLowerCase()) && (
                  <button onClick={handleCreateCategory} disabled={catCreating}
                    className="w-full text-left px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 border-t border-gray-100">
                    {catCreating ? 'Creating...' : `+ Create "${catSearch.trim()}"`}
                  </button>
                )}
                {categories.length === 0 && !catSearch.trim() && (
                  <div className="px-3 py-2 text-sm text-gray-400">No categories yet</div>
                )}
              </div>
            )}
          </div>

          {/* Supplier dropdown */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Supplier</label>
            <select value={form.supplier_id} onChange={e => updateField('supplier_id', e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
              <option value="">— None —</option>
              {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          <Input label="Brand" value={form.brand} onChange={e => updateField('brand', e.target.value)} placeholder="e.g. Bosch, Continental" />

          <div className="grid grid-cols-2 gap-3">
            <Input label="Min stock threshold" type="number" value={form.min_stock_threshold} onChange={e => updateField('min_stock_threshold', e.target.value)} placeholder="0" />
            <Input label="Reorder quantity" type="number" value={form.reorder_quantity} onChange={e => updateField('reorder_quantity', e.target.value)} placeholder="0" />
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.is_active} onChange={e => updateField('is_active', e.target.checked)} className="h-4 w-4 rounded border-gray-300 text-blue-600" />
            Active
          </label>
        </div>
        {formError && <p className="mt-2 text-sm text-red-600">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save Changes' : 'Create Part'}</Button>
        </div>
      </Modal>

      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Part">
        <p className="text-sm text-gray-600 mb-4">This will deactivate the part and hide it from invoice creation. Historical data is preserved.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button size="sm" variant="danger" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
