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
  is_gst_exempt?: boolean
  gst_inclusive?: boolean
  purchase_price: string | null
  packaging_type: string | null
  qty_per_pack: number | null
  total_packs: number | null
  cost_per_unit: string | null
  sell_price_per_unit: string | null
  margin: string | null
  margin_pct: string | null
  gst_mode: string | null
  min_stock_threshold?: number
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
  supplier_ids: string[]
  default_price: string
  gst_mode: 'inclusive' | 'exclusive' | 'exempt' | ''
  purchase_price: string
  packaging_type: string
  qty_per_pack: string
  total_packs: string
  sell_price_per_unit: string
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
  category_id: '', category_name: '', brand: '', supplier_id: '', supplier_ids: [],
  default_price: '', gst_mode: '',
  purchase_price: '', packaging_type: 'single', qty_per_pack: '1', total_packs: '1', sell_price_per_unit: '',
  min_stock_threshold: '0', reorder_quantity: '0', is_active: true,
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
  const [showAddSupplier, setShowAddSupplier] = useState(false)
  const [newSupplier, setNewSupplier] = useState({ name: '', contact_name: '', email: '', phone: '', address: '' })
  const [addSupplierSaving, setAddSupplierSaving] = useState(false)
  const [addSupplierError, setAddSupplierError] = useState('')
  const [supplierSearch, setSupplierSearch] = useState('')
  const [supplierDropOpen, setSupplierDropOpen] = useState(false)
  const supplierDropRef = useRef<HTMLDivElement>(null)
  // Real-time pricing calculations
  const totalUnits = (parseInt(form.qty_per_pack) || 0) * (parseInt(form.total_packs) || 0)
  const costPerUnit = totalUnits > 0 && parseFloat(form.purchase_price) > 0
    ? parseFloat(form.purchase_price) / totalUnits : null
  const sellPerUnit = parseFloat(form.sell_price_per_unit) || null
  const margin = costPerUnit !== null && sellPerUnit !== null ? sellPerUnit - costPerUnit : null
  const marginPct = margin !== null && sellPerUnit !== null && sellPerUnit > 0
    ? (margin / sellPerUnit) * 100 : (sellPerUnit === 0 ? 0 : null)

  const fmtNZD = (v: number) => '$' + v.toFixed(2)

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
      if (supplierDropRef.current && !supplierDropRef.current.contains(e.target as Node)) setSupplierDropOpen(false)
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
      supplier_ids: part.supplier_id ? [part.supplier_id] : [],
      default_price: part.default_price,
      gst_mode: (part.gst_mode as PartForm['gst_mode']) || (part.is_gst_exempt ? 'exempt' : part.gst_inclusive ? 'inclusive' : 'exclusive'),
      purchase_price: part.purchase_price ?? '',
      packaging_type: part.packaging_type ?? 'single',
      qty_per_pack: String(part.qty_per_pack ?? 1),
      total_packs: String(part.total_packs ?? 1),
      sell_price_per_unit: part.sell_price_per_unit ?? '',
      min_stock_threshold: String(part.min_stock_threshold ?? 0),
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
    if (!form.gst_mode) { setFormError('Please select a GST mode in the Pricing section.'); return }
    // Use sell_price_per_unit as the canonical price; fall back to default_price for legacy compat
    const effectivePrice = form.sell_price_per_unit.trim() || form.default_price.trim()
    if (!effectivePrice || isNaN(Number(effectivePrice))) {
      setFormError('Valid sell price per unit is required.'); return
    }
    setSaving(true); setFormError('')
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        default_price: effectivePrice,
        is_gst_exempt: form.gst_mode === 'exempt',
        gst_inclusive: form.gst_mode === 'inclusive',
        is_active: form.is_active,
        part_type: form.part_type,
        purchase_price: form.purchase_price.trim() || null,
        packaging_type: form.packaging_type || null,
        qty_per_pack: parseInt(form.qty_per_pack) || null,
        total_packs: parseInt(form.total_packs) || null,
        sell_price_per_unit: form.sell_price_per_unit.trim() || null,
        gst_mode: form.gst_mode || null,
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
      await apiClient.put(`/catalogue/parts/${part.id}`, { is_active: !part.is_active })
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
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to delete part.'
      setError(msg)
      setDeleteId(null)
    } finally { setDeleting(false) }
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

  const handleAddSupplier = async () => {
    if (!newSupplier.name.trim()) { setAddSupplierError('Supplier name is required.'); return }
    setAddSupplierSaving(true)
    setAddSupplierError('')
    try {
      const body: Record<string, string> = { name: newSupplier.name.trim() }
      if (newSupplier.contact_name.trim()) body.contact_name = newSupplier.contact_name.trim()
      if (newSupplier.email.trim()) body.email = newSupplier.email.trim()
      if (newSupplier.phone.trim()) body.phone = newSupplier.phone.trim()
      if (newSupplier.address.trim()) body.address = newSupplier.address.trim()
      const res = await apiClient.post('/inventory/suppliers', body)
      const created: Supplier = res.data.supplier || res.data
      setSuppliers(prev => [...prev, created])
      // Auto-add to selected suppliers
      setForm(f => ({ ...f, supplier_ids: [...f.supplier_ids, created.id], supplier_id: f.supplier_id || created.id }))
      setShowAddSupplier(false)
      setNewSupplier({ name: '', contact_name: '', email: '', phone: '', address: '' })
    } catch (err: any) {
      setAddSupplierError(err?.response?.data?.detail || 'Failed to create supplier.')
    } finally { setAddSupplierSaving(false) }
  }

  const toggleSupplier = (supplierId: string) => {
    setForm(f => {
      const ids = f.supplier_ids.includes(supplierId)
        ? f.supplier_ids.filter(id => id !== supplierId)
        : [...f.supplier_ids, supplierId]
      return { ...f, supplier_ids: ids, supplier_id: ids[0] || '' }
    })
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
                  <td className="px-4 py-3 text-sm text-gray-900 text-right tabular-nums font-medium">${part.sell_price_per_unit || part.default_price}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{part.supplier_name || '—'}</td>
                  <td className="px-4 py-3 text-sm text-center">
                    <Badge variant={part.is_active ? 'success' : 'neutral'}>{part.is_active ? 'Active' : 'Inactive'}</Badge>
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="secondary" onClick={() => openEdit(part)}>Edit</Button>
                      <Button size="sm" variant="secondary" onClick={() => handleToggleActive(part)}>
                        {part.is_active !== false ? 'Deactivate' : 'Activate'}
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

          <Input label="Part No/Code" value={form.part_number} onChange={e => updateField('part_number', e.target.value)} placeholder="e.g. BRK-PAD-001" />

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

          {/* Supplier searchable dropdown + add */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">Suppliers</label>
              <button type="button" onClick={() => { setNewSupplier({ name: '', contact_name: '', email: '', phone: '', address: '' }); setAddSupplierError(''); setShowAddSupplier(true) }}
                className="text-xs text-blue-600 hover:underline font-medium">+ Add Supplier</button>
            </div>
            {/* Selected chips */}
            {form.supplier_ids.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {form.supplier_ids.map(sid => {
                  const s = suppliers.find(x => x.id === sid)
                  return s ? (
                    <span key={sid} className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 px-2.5 py-0.5 text-xs font-medium">
                      {s.name}
                      <button type="button" onClick={() => toggleSupplier(sid)} className="text-blue-600 hover:text-blue-800">✕</button>
                    </span>
                  ) : null
                })}
              </div>
            )}
            {/* Searchable dropdown */}
            <div ref={supplierDropRef} className="relative">
              <input
                type="text"
                value={supplierSearch}
                onChange={e => { setSupplierSearch(e.target.value); setSupplierDropOpen(true) }}
                onFocus={() => setSupplierDropOpen(true)}
                placeholder="Search suppliers…"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoComplete="off"
              />
              {supplierDropOpen && (
                <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
                  {suppliers
                    .filter(s => !supplierSearch.trim() || s.name.toLowerCase().includes(supplierSearch.toLowerCase()))
                    .slice(0, 15)
                    .map(s => (
                      <button key={s.id} type="button" onClick={() => { toggleSupplier(s.id); setSupplierSearch(''); setSupplierDropOpen(false) }}
                        className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 flex items-center justify-between">
                        <span className="text-gray-900">{s.name}</span>
                        {form.supplier_ids.includes(s.id) && <span className="text-blue-600 text-xs">✓ selected</span>}
                      </button>
                    ))}
                  {suppliers.filter(s => !supplierSearch.trim() || s.name.toLowerCase().includes(supplierSearch.toLowerCase())).length === 0 && (
                    <div className="px-3 py-2 text-sm text-gray-500">No suppliers match</div>
                  )}
                  <button type="button" onClick={() => { setNewSupplier({ name: supplierSearch.trim(), contact_name: '', email: '', phone: '', address: '' }); setAddSupplierError(''); setShowAddSupplier(true); setSupplierDropOpen(false) }}
                    className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm font-medium text-blue-600 hover:bg-blue-50">
                    + Add New Supplier{supplierSearch.trim() ? ` "${supplierSearch.trim()}"` : ''}
                  </button>
                </div>
              )}
            </div>
          </div>

          <Input label="Brand" value={form.brand} onChange={e => updateField('brand', e.target.value)} placeholder="e.g. Bosch, Continental" />

          {/* ── Pricing & Packaging Section ── */}
          <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-3">
            <p className="text-sm font-medium text-gray-900">Pricing &amp; Packaging</p>

            {/* Packaging Type */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Packaging Type</label>
              <select
                value={form.packaging_type}
                onChange={e => {
                  const val = e.target.value
                  if (val === 'single') {
                    setForm(prev => ({ ...prev, packaging_type: val, qty_per_pack: '1', total_packs: '1' }))
                  } else {
                    updateField('packaging_type', val)
                  }
                }}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="single">Single</option>
                <option value="box">Box</option>
                <option value="carton">Carton</option>
                <option value="pack">Pack</option>
                <option value="bag">Bag</option>
                <option value="pallet">Pallet</option>
              </select>
            </div>

            {/* Qty Per Pack & Total Packs */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Qty Per Pack</label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={form.qty_per_pack}
                  onChange={e => updateField('qty_per_pack', e.target.value)}
                  disabled={form.packaging_type === 'single'}
                  className={`w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${form.packaging_type === 'single' ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''}`}
                  placeholder="e.g. 10"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Total Packs</label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={form.total_packs}
                  onChange={e => updateField('total_packs', e.target.value)}
                  disabled={form.packaging_type === 'single'}
                  className={`w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${form.packaging_type === 'single' ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''}`}
                  placeholder="e.g. 2"
                />
              </div>
            </div>

            {/* Purchase Price & Sell Price Per Unit */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Purchase Price</label>
                <div className="flex">
                  <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.purchase_price}
                    onChange={e => updateField('purchase_price', e.target.value)}
                    className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0.00"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Sell Price Per Unit</label>
                <div className="flex">
                  <span className="rounded-l-md border border-r-0 border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.sell_price_per_unit}
                    onChange={e => updateField('sell_price_per_unit', e.target.value)}
                    className="flex-1 rounded-r-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0.00"
                  />
                </div>
              </div>
            </div>

            {/* GST Mode */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">GST Mode</label>
              <div className="inline-flex rounded-md border border-gray-300 overflow-hidden w-full">
                {([
                  { value: 'inclusive', label: 'GST Inc.' },
                  { value: 'exclusive', label: 'GST Excl.' },
                  { value: 'exempt', label: 'Exempt' },
                ] as const).map((opt, i) => (
                  <button key={opt.value} type="button" onClick={() => updateField('gst_mode', opt.value)}
                    className={`flex-1 py-2 text-sm font-medium transition-colors ${i > 0 ? 'border-l border-gray-300' : ''} ${
                      form.gst_mode === opt.value ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
                    }`}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Read-only calculated displays */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-md bg-white border border-gray-200 px-3 py-2 text-center">
                <span className="block text-xs text-gray-500">Cost/Unit</span>
                <span className="block text-sm font-semibold text-gray-900">{costPerUnit !== null ? fmtNZD(costPerUnit) : '—'}</span>
              </div>
              <div className="rounded-md bg-white border border-gray-200 px-3 py-2 text-center">
                <span className="block text-xs text-gray-500">Margin $</span>
                <span className="block text-sm font-semibold text-gray-900">{margin !== null ? fmtNZD(margin) : '—'}</span>
              </div>
              <div className="rounded-md bg-white border border-gray-200 px-3 py-2 text-center">
                <span className="block text-xs text-gray-500">Margin %</span>
                <span className="block text-sm font-semibold text-gray-900">{marginPct !== null ? marginPct.toFixed(2) + '%' : '—'}</span>
              </div>
            </div>
          </div>

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

      {/* Add Supplier Modal */}
      <Modal open={showAddSupplier} onClose={() => setShowAddSupplier(false)} title="New Supplier">
        <div className="space-y-3">
          <Input label="Supplier name *" value={newSupplier.name}
            onChange={e => setNewSupplier(prev => ({ ...prev, name: e.target.value }))} />
          <Input label="Contact person" value={newSupplier.contact_name}
            onChange={e => setNewSupplier(prev => ({ ...prev, contact_name: e.target.value }))} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Email" type="email" value={newSupplier.email}
              onChange={e => setNewSupplier(prev => ({ ...prev, email: e.target.value }))} />
            <Input label="Phone" value={newSupplier.phone}
              onChange={e => setNewSupplier(prev => ({ ...prev, phone: e.target.value }))} />
          </div>
          <Input label="Address" value={newSupplier.address}
            onChange={e => setNewSupplier(prev => ({ ...prev, address: e.target.value }))} />
          {addSupplierError && <p className="text-sm text-red-600">{addSupplierError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowAddSupplier(false)}>Cancel</Button>
            <Button onClick={handleAddSupplier} loading={addSupplierSaving}>Create Supplier</Button>
          </div>
        </div>
      </Modal>

      <Modal open={!!deleteId} onClose={() => setDeleteId(null)} title="Delete Part">
        <p className="text-sm text-gray-600 mb-4">This will permanently delete the part. This cannot be undone.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button size="sm" variant="danger" onClick={handleDelete} loading={deleting}>Delete</Button>
        </div>
      </Modal>
    </div>
  )
}
