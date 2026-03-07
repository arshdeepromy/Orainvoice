import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Spinner, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CategoryNode {
  id: string
  name: string
  parent_id: string | null
  display_order: number
  children: CategoryNode[]
}

interface CategoryTreeResponse {
  tree: CategoryNode[]
  total: number
}

interface CategoryForm {
  name: string
  parent_id: string
}

const EMPTY_FORM: CategoryForm = { name: '', parent_id: '' }

/**
 * Category tree with drag-and-drop reordering and CRUD.
 *
 * Validates: Requirement 9.2
 */
export default function CategoryTree() {
  const [tree, setTree] = useState<CategoryNode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<CategoryForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const dragItem = useRef<string | null>(null)
  const dragOverItem = useRef<string | null>(null)

  const fetchTree = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<CategoryTreeResponse>('/v2/product-categories/tree')
      setTree(res.data.tree)
    } catch {
      setError('Failed to load categories.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTree() }, [fetchTree])

  const flattenTree = (nodes: CategoryNode[]): { id: string; name: string }[] => {
    const result: { id: string; name: string }[] = []
    const walk = (items: CategoryNode[], prefix: string) => {
      for (const item of items) {
        result.push({ id: item.id, name: prefix + item.name })
        walk(item.children, prefix + '  ')
      }
    }
    walk(nodes, '')
    return result
  }

  const openCreate = (parentId?: string) => {
    setEditingId(null)
    setForm({ name: '', parent_id: parentId || '' })
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (node: CategoryNode) => {
    setEditingId(node.id)
    setForm({ name: node.name, parent_id: node.parent_id || '' })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Category name is required.'); return }
    setSaving(true)
    setFormError('')
    try {
      const body: Record<string, unknown> = { name: form.name.trim() }
      if (form.parent_id) body.parent_id = form.parent_id

      if (editingId) {
        await apiClient.put(`/v2/product-categories/${editingId}`, body)
      } else {
        await apiClient.post('/v2/product-categories', body)
      }
      setModalOpen(false)
      fetchTree()
    } catch {
      setFormError('Failed to save category.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this category? Products in this category will become uncategorised.')) return
    try {
      await apiClient.delete(`/v2/product-categories/${id}`)
      fetchTree()
    } catch {
      setError('Failed to delete category.')
    }
  }

  const handleDragStart = (id: string) => {
    dragItem.current = id
  }

  const handleDragOver = (e: React.DragEvent, id: string) => {
    e.preventDefault()
    dragOverItem.current = id
  }

  const handleDrop = async () => {
    if (!dragItem.current || !dragOverItem.current || dragItem.current === dragOverItem.current) return
    try {
      await apiClient.put(`/v2/product-categories/${dragItem.current}`, {
        parent_id: dragOverItem.current,
      })
      fetchTree()
    } catch {
      setError('Failed to move category.')
    }
    dragItem.current = null
    dragOverItem.current = null
  }

  const renderNode = (node: CategoryNode, depth: number = 0): React.ReactNode => (
    <div
      key={node.id}
      className="border border-gray-200 rounded-md bg-white"
      style={{ marginLeft: depth * 24 }}
      draggable
      onDragStart={() => handleDragStart(node.id)}
      onDragOver={(e) => handleDragOver(e, node.id)}
      onDrop={handleDrop}
      role="treeitem"
      aria-label={node.name}
    >
      <div className="flex items-center justify-between px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="cursor-grab text-gray-400" aria-hidden="true">⠿</span>
          <span className="text-sm font-medium text-gray-900">{node.name}</span>
          {node.children.length > 0 && (
            <span className="text-xs text-gray-400">({node.children.length})</span>
          )}
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => openCreate(node.id)}
            className="text-xs text-blue-600 hover:text-blue-800 px-2 py-1"
            aria-label={`Add subcategory under ${node.name}`}
          >+ Sub</button>
          <button
            onClick={() => openEdit(node)}
            className="text-xs text-gray-600 hover:text-gray-800 px-2 py-1"
            aria-label={`Edit ${node.name}`}
          >Edit</button>
          <button
            onClick={() => handleDelete(node.id)}
            className="text-xs text-red-600 hover:text-red-800 px-2 py-1"
            aria-label={`Delete ${node.name}`}
          >Delete</button>
        </div>
      </div>
      {node.children.length > 0 && (
        <div className="pl-2 pb-2 space-y-1">
          {node.children.map((child) => renderNode(child, depth + 1))}
        </div>
      )}
    </div>
  )

  const allCategories = flattenTree(tree)

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">
          Organise products into categories. Drag and drop to rearrange the hierarchy.
        </p>
        <Button onClick={() => openCreate()}>+ New Category</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && (
        <div className="py-16"><Spinner label="Loading categories" /></div>
      )}

      {!loading && tree.length === 0 && (
        <p className="text-sm text-gray-500 py-8 text-center">No categories yet. Create your first category to organise products.</p>
      )}

      {!loading && tree.length > 0 && (
        <div className="space-y-2" role="tree" aria-label="Product categories">
          {tree.map((node) => renderNode(node))}
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? 'Edit Category' : 'New Category'}>
        <div className="space-y-3">
          <Input label="Category name *" value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} />
          <div>
            <label htmlFor="parent-category" className="text-sm font-medium text-gray-700">Parent category</label>
            <select
              id="parent-category"
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              value={form.parent_id}
              onChange={(e) => setForm((prev) => ({ ...prev, parent_id: e.target.value }))}
            >
              <option value="">None (top level)</option>
              {allCategories
                .filter((c) => c.id !== editingId)
                .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        </div>
        {formError && <p className="mt-2 text-sm text-red-600" role="alert">{formError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSave} loading={saving}>{editingId ? 'Save' : 'Create'}</Button>
        </div>
      </Modal>
    </div>
  )
}
