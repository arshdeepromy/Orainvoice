/**
 * Fleet Portal checklists page — templates + start submission + history.
 *
 * Implements: B2B Fleet Portal — Requirements 8.3–8.8, 9.1–9.10.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { listVehicles } from '../api/endpoints'
import type { ChecklistTemplate, ChecklistSubmission, VehicleListItem, PaginatedResponse, ChecklistTemplateItem } from '../api/types'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function ChecklistsPage() {
  const { user } = useFleetSession()
  const navigate = useNavigate()
  const isAdmin = user?.portal_user_role === 'fleet_admin'
  const [tab, setTab] = useState<'submissions' | 'templates'>('submissions')
  const [templates, setTemplates] = useState<ChecklistTemplate[]>([])
  const [submissions, setSubmissions] = useState<ChecklistSubmission[]>([])
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [startingFor, setStartingFor] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)
  const [editingTemplate, setEditingTemplate] = useState<ChecklistTemplate | null>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)

  const fetchData = async () => {
    try {
      const [t, s, v] = await Promise.all([
        isAdmin ? fleetClient.get<PaginatedResponse<ChecklistTemplate>>('/checklists/templates', { params: { limit: 50 } }).then(r => r.data?.items ?? []) : Promise.resolve([]),
        fleetClient.get<PaginatedResponse<ChecklistSubmission>>('/checklists/submissions', { params: { limit: 50 } }).then(r => r.data?.items ?? []).catch(() => []),
        listVehicles(0, 100).then(r => r.items ?? []),
      ])
      setTemplates(t)
      setSubmissions(s)
      setVehicles(v)
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [])

  const startChecklist = async (vehicleId: string) => {
    setStartingFor(vehicleId)
    setMsg(null)
    try {
      const res = await fleetClient.post<{ id: string }>('/checklists/start', { customer_vehicle_id: vehicleId })
      const newId = res.data?.id
      if (newId) {
        // Navigate straight to the submission so the user can fill it in
        navigate(`/fleet/checklists/${newId}`)
      } else {
        setMsg({ type: 'ok', text: 'Checklist started.' })
        await fetchData()
      }
    } catch (err: unknown) {
      setMsg({ type: 'err', text: (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to start checklist.' })
    } finally { setStartingFor(null) }
  }

  const cloneTemplate = async (templateId: string) => {
    try {
      await fleetClient.post(`/checklists/templates/${templateId}/clone`)
      setMsg({ type: 'ok', text: 'Template cloned successfully.' })
      await fetchData()
    } catch (err: unknown) {
      setMsg({ type: 'err', text: (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to clone template.' })
    }
  }

  const setDefault = async (templateId: string) => {
    try {
      await fleetClient.post(`/checklists/templates/${templateId}/set-default`)
      await fetchData()
    } catch {}
  }

  const openEditor = async (templateId: string) => {
    try {
      const res = await fleetClient.get<ChecklistTemplate>(`/checklists/templates/${templateId}`)
      setEditingTemplate(res.data ?? null)
    } catch {
      setMsg({ type: 'err', text: 'Failed to load template details.' })
    }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>

  // Template editor view
  if (editingTemplate) {
    return (
      <TemplateEditor
        template={editingTemplate}
        onClose={() => { setEditingTemplate(null); fetchData() }}
      />
    )
  }

  // Create template form
  if (showCreateForm) {
    return (
      <CreateTemplateForm
        onClose={() => { setShowCreateForm(false); fetchData() }}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Checklists</h1>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-gray-200 dark:border-gray-800">
        <button onClick={() => setTab('submissions')} className={`px-4 py-2 text-sm font-medium min-h-[44px] border-b-2 ${tab === 'submissions' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
          Submissions
        </button>
        {isAdmin && (
          <button onClick={() => setTab('templates')} className={`px-4 py-2 text-sm font-medium min-h-[44px] border-b-2 ${tab === 'templates' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            Templates
          </button>
        )}
      </div>

      {msg && <p className={`text-xs ${msg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>{msg.text}</p>}

      {tab === 'submissions' && (
        <div className="space-y-4">
          {/* Start checklist for a vehicle */}
          <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
            <h2 className="text-sm font-medium mb-2">Start Pre-Trip Checklist</h2>
            <p className="text-xs text-gray-500 mb-3">Select a vehicle to begin a new checklist submission.</p>
            <div className="flex flex-wrap gap-2">
              {(vehicles ?? []).map(v => (
                <button key={v.customer_vehicle_id} onClick={() => startChecklist(v.customer_vehicle_id)}
                  disabled={startingFor === v.customer_vehicle_id}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] hover:bg-indigo-50 hover:border-indigo-300 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-indigo-950/20">
                  {startingFor === v.customer_vehicle_id ? '…' : v.rego}
                </button>
              ))}
            </div>
          </div>

          {/* Submission history */}
          {(submissions ?? []).length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center dark:border-gray-700">
              <p className="text-sm text-gray-500">No checklist submissions yet. Start one above.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {(submissions ?? []).map(s => (
                <Link key={s.id} to={`/fleet/checklists/${s.id}`} className="block rounded-lg border border-gray-200 bg-white p-3 hover:border-indigo-300 dark:border-gray-800 dark:bg-gray-950 dark:hover:border-indigo-700">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">
                        {s.status === 'completed' ? '✓' : s.status === 'in_progress' ? '⏳' : '✗'}{' '}
                        Submission — {new Date(s.started_at).toLocaleDateString()}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {s.status === 'completed' && `Pass: ${s.passed_item_count ?? 0} · Fail: ${s.failed_item_count ?? 0} · N/A: ${s.na_item_count ?? 0}`}
                        {s.status === 'in_progress' && 'In progress — tap to continue'}
                      </p>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${s.status === 'completed' ? ((s.failed_item_count ?? 0) > 0 ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800') : 'bg-blue-100 text-blue-800'}`}>
                      {s.status}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'templates' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <button
              onClick={() => setShowCreateForm(true)}
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700"
            >
              + New Template
            </button>
          </div>
          {(templates ?? []).length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center dark:border-gray-700">
              <p className="text-sm text-gray-500">No templates yet. The NZTA default will be seeded on first checklist start.</p>
            </div>
          ) : (
            (templates ?? []).map(t => (
              <div key={t.id} className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">{t.name}</p>
                    {t.description && <p className="text-xs text-gray-500 mt-0.5">{t.description}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    {t.is_default && <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded dark:bg-blue-900/40 dark:text-blue-200">Default</span>}
                    {t.is_system_seeded && <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded dark:bg-gray-800 dark:text-gray-400">NZTA</span>}
                    <button onClick={() => cloneTemplate(t.id)} className="text-xs text-indigo-600 hover:underline min-h-[44px]">Clone</button>
                    {!t.is_system_seeded && (
                      <button onClick={() => openEditor(t.id)} className="text-xs text-indigo-600 hover:underline min-h-[44px]">Edit</button>
                    )}
                    {!t.is_default && !t.is_system_seeded && (
                      <button onClick={() => setDefault(t.id)} className="text-xs text-green-600 hover:underline min-h-[44px]">Set Default</button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/* --- Template Editor --- */
function TemplateEditor({ template, onClose }: { template: ChecklistTemplate; onClose: () => void }) {
  const [items, setItems] = useState<Array<{ category: string; label: string; requires_photo_on_fail: boolean; display_order: number }>>(
    (template.items ?? []).map((i, idx) => ({ category: i.category, label: i.label, requires_photo_on_fail: i.requires_photo_on_fail, display_order: i.display_order ?? idx }))
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addItem = () => {
    setItems([...items, { category: '', label: '', requires_photo_on_fail: false, display_order: items.length }])
  }

  const removeItem = (idx: number) => {
    setItems(items.filter((_, i) => i !== idx).map((item, i) => ({ ...item, display_order: i })))
  }

  const updateItem = (idx: number, field: string, value: string | boolean) => {
    setItems(items.map((item, i) => i === idx ? { ...item, [field]: value } : item))
  }

  const moveItem = (idx: number, direction: 'up' | 'down') => {
    const newItems = [...items]
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1
    if (swapIdx < 0 || swapIdx >= newItems.length) return
    ;[newItems[idx], newItems[swapIdx]] = [newItems[swapIdx], newItems[idx]]
    setItems(newItems.map((item, i) => ({ ...item, display_order: i })))
  }

  const save = async () => {
    const invalid = items.find(i => !i.category.trim() || !i.label.trim())
    if (invalid) { setError('All items must have a category and label.'); return }
    setSaving(true)
    setError(null)
    try {
      await fleetClient.put(`/checklists/templates/${template.id}/items`, items)
      onClose()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to save.')
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Edit: {template.name}</h1>
        <button onClick={onClose} className="text-sm text-gray-500 hover:underline min-h-[44px]">← Back</button>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="space-y-2">
        {items.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2 rounded border border-gray-200 bg-white p-2 dark:border-gray-700 dark:bg-gray-950">
            <span className="text-xs text-gray-400 w-6">{idx + 1}</span>
            <input value={item.category} onChange={e => updateItem(idx, 'category', e.target.value)} placeholder="Category"
              className="w-28 rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            <input value={item.label} onChange={e => updateItem(idx, 'label', e.target.value)} placeholder="Item label"
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            <label className="flex items-center gap-1 text-xs text-gray-500">
              <input type="checkbox" checked={item.requires_photo_on_fail} onChange={e => updateItem(idx, 'requires_photo_on_fail', e.target.checked)} />
              Photo
            </label>
            <button onClick={() => moveItem(idx, 'up')} disabled={idx === 0} className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30 min-h-[32px]">↑</button>
            <button onClick={() => moveItem(idx, 'down')} disabled={idx === items.length - 1} className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30 min-h-[32px]">↓</button>
            <button onClick={() => removeItem(idx)} className="text-xs text-red-500 hover:text-red-700 min-h-[32px]">✕</button>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <button onClick={addItem} className="rounded border border-dashed border-gray-300 px-3 py-2 text-xs text-gray-500 hover:border-indigo-300 hover:text-indigo-600 min-h-[44px] dark:border-gray-700">
          + Add Item
        </button>
        <button onClick={save} disabled={saving} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save Items'}
        </button>
      </div>
    </div>
  )
}

/* --- Create Template Form --- */
function CreateTemplateForm({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError('Name is required.'); return }
    setSaving(true)
    setError(null)
    try {
      await fleetClient.post('/checklists/templates', { name: name.trim(), description: description.trim() || null, items: [] })
      onClose()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create template.')
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">New Template</h1>
        <button onClick={onClose} className="text-sm text-gray-500 hover:underline min-h-[44px]">← Back</button>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}

      <form onSubmit={handleSubmit} className="space-y-3 max-w-md">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Template Name</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Heavy Vehicle Inspection"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description (optional)</label>
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        </div>
        <button type="submit" disabled={saving} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700 disabled:opacity-50">
          {saving ? 'Creating…' : 'Create Template'}
        </button>
      </form>
      <p className="text-xs text-gray-500">After creating, you can add items by editing the template.</p>
    </div>
  )
}
