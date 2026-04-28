import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Modal } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface FieldDefinition {
  /** Client-side key for React list rendering */
  _key: string
  label: string
  field_type: 'text' | 'select' | 'multi_select' | 'number'
  display_order: number
  is_required: boolean
  options: string[]
}

interface ServiceTypeFormData {
  name: string
  description: string
  fields: FieldDefinition[]
}

export interface ServiceTypeForEdit {
  id: string
  name: string
  description: string | null
  is_active: boolean
  fields: {
    id: string
    label: string
    field_type: string
    display_order: number
    is_required: boolean
    options: string[] | null
  }[]
}

interface ServiceTypeModalProps {
  open: boolean
  onClose: () => void
  onSaved: () => void
  editData?: ServiceTypeForEdit | null
}

const FIELD_TYPE_OPTIONS = [
  { value: 'text', label: 'Text' },
  { value: 'select', label: 'Select' },
  { value: 'multi_select', label: 'Multi Select' },
  { value: 'number', label: 'Number' },
]

let nextKey = 0
function genKey(): string {
  return `field_${++nextKey}_${Date.now()}`
}

function makeEmptyField(order: number): FieldDefinition {
  return {
    _key: genKey(),
    label: '',
    field_type: 'text',
    display_order: order,
    is_required: false,
    options: [],
  }
}

const EMPTY_FORM: ServiceTypeFormData = {
  name: '',
  description: '',
  fields: [],
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ServiceTypeModal({ open, onClose, onSaved, editData }: ServiceTypeModalProps) {
  const isEdit = !!editData
  const [form, setForm] = useState<ServiceTypeFormData>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  useEffect(() => {
    if (!open) return
    if (editData) {
      setForm({
        name: editData.name,
        description: editData.description ?? '',
        fields: (editData.fields ?? []).map((f) => ({
          _key: genKey(),
          label: f.label,
          field_type: f.field_type as FieldDefinition['field_type'],
          display_order: f.display_order,
          is_required: f.is_required,
          options: f.options ?? [],
        })),
      })
    } else {
      setForm(EMPTY_FORM)
    }
    setFormError('')
  }, [open, editData])

  /* ---- Field helpers ---- */

  const addField = () => {
    setForm((prev) => ({
      ...prev,
      fields: [...prev.fields, makeEmptyField(prev.fields.length)],
    }))
  }

  const removeField = (key: string) => {
    setForm((prev) => ({
      ...prev,
      fields: prev.fields
        .filter((f) => f._key !== key)
        .map((f, i) => ({ ...f, display_order: i })),
    }))
  }

  const updateFieldProp = <K extends keyof FieldDefinition>(key: string, prop: K, value: FieldDefinition[K]) => {
    setForm((prev) => ({
      ...prev,
      fields: prev.fields.map((f) => (f._key === key ? { ...f, [prop]: value } : f)),
    }))
  }

  const moveField = (key: string, direction: 'up' | 'down') => {
    setForm((prev) => {
      const idx = prev.fields.findIndex((f) => f._key === key)
      if (idx < 0) return prev
      const newIdx = direction === 'up' ? idx - 1 : idx + 1
      if (newIdx < 0 || newIdx >= prev.fields.length) return prev
      const newFields = [...prev.fields]
      ;[newFields[idx], newFields[newIdx]] = [newFields[newIdx], newFields[idx]]
      return {
        ...prev,
        fields: newFields.map((f, i) => ({ ...f, display_order: i })),
      }
    })
  }

  /* ---- Options helpers ---- */

  const addOption = (fieldKey: string) => {
    setForm((prev) => ({
      ...prev,
      fields: prev.fields.map((f) =>
        f._key === fieldKey ? { ...f, options: [...f.options, ''] } : f,
      ),
    }))
  }

  const updateOption = (fieldKey: string, optIdx: number, value: string) => {
    setForm((prev) => ({
      ...prev,
      fields: prev.fields.map((f) =>
        f._key === fieldKey
          ? { ...f, options: f.options.map((o, i) => (i === optIdx ? value : o)) }
          : f,
      ),
    }))
  }

  const removeOption = (fieldKey: string, optIdx: number) => {
    setForm((prev) => ({
      ...prev,
      fields: prev.fields.map((f) =>
        f._key === fieldKey
          ? { ...f, options: f.options.filter((_, i) => i !== optIdx) }
          : f,
      ),
    }))
  }

  /* ---- Validation & Save ---- */

  const validate = (): string | null => {
    if (!form.name.trim()) return 'Service type name is required.'
    for (const f of form.fields) {
      if (!f.label.trim()) return `All field labels are required. Found an empty label.`
      if (f.label.trim() !== f.label && f.label.trim().length === 0) {
        return 'Field labels must not be whitespace-only.'
      }
    }
    return null
  }

  const handleSave = async () => {
    const err = validate()
    if (err) { setFormError(err); return }

    setSaving(true)
    setFormError('')

    const fields = form.fields.map((f) => ({
      label: f.label.trim(),
      field_type: f.field_type,
      display_order: f.display_order,
      is_required: f.is_required,
      options: (f.field_type === 'select' || f.field_type === 'multi_select')
        ? f.options.filter((o) => o.trim() !== '')
        : null,
    }))

    const body: Record<string, unknown> = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      fields,
    }

    try {
      if (isEdit && editData) {
        await apiClient.put(`/service-types/${editData.id}`, body)
      } else {
        await apiClient.post('/service-types/', body)
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const msg = axiosErr?.response?.data?.detail
        || (isEdit ? 'Failed to update service type.' : 'Failed to create service type.')
      setFormError(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Edit Service Type' : 'New Service Type'}
      className="max-w-2xl"
    >
      <div className="space-y-4">
        {/* Name */}
        <Input
          label="Name *"
          value={form.name}
          onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
          placeholder="e.g. Fixture Replacement"
        />

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
            rows={2}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="Optional description of this service type"
          />
        </div>

        {/* Additional Info Fields */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-gray-700">Additional Info Fields</h3>
            <Button size="sm" variant="secondary" onClick={addField}>+ Add Field</Button>
          </div>

          {form.fields.length === 0 ? (
            <p className="text-sm text-gray-400 py-2">
              No additional info fields. Workers won't be prompted for extra information.
            </p>
          ) : (
            <div className="space-y-3">
              {form.fields.map((field, idx) => (
                <FieldRow
                  key={field._key}
                  field={field}
                  index={idx}
                  total={form.fields.length}
                  onUpdate={(prop, value) => updateFieldProp(field._key, prop, value)}
                  onRemove={() => removeField(field._key)}
                  onMove={(dir) => moveField(field._key, dir)}
                  onAddOption={() => addOption(field._key)}
                  onUpdateOption={(optIdx, val) => updateOption(field._key, optIdx, val)}
                  onRemoveOption={(optIdx) => removeOption(field._key, optIdx)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {formError && <p className="mt-3 text-sm text-red-600" role="alert">{formError}</p>}

      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" onClick={handleSave} loading={saving}>
          {isEdit ? 'Save Changes' : 'Create Service Type'}
        </Button>
      </div>
    </Modal>
  )
}


/* ------------------------------------------------------------------ */
/*  FieldRow sub-component                                             */
/* ------------------------------------------------------------------ */

interface FieldRowProps {
  field: FieldDefinition
  index: number
  total: number
  onUpdate: <K extends keyof FieldDefinition>(prop: K, value: FieldDefinition[K]) => void
  onRemove: () => void
  onMove: (direction: 'up' | 'down') => void
  onAddOption: () => void
  onUpdateOption: (optIdx: number, value: string) => void
  onRemoveOption: (optIdx: number) => void
}

function FieldRow({
  field,
  index,
  total,
  onUpdate,
  onRemove,
  onMove,
  onAddOption,
  onUpdateOption,
  onRemoveOption,
}: FieldRowProps) {
  const showOptions = field.field_type === 'select' || field.field_type === 'multi_select'

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-2">
      {/* Top row: label, type, controls */}
      <div className="flex items-start gap-2">
        {/* Reorder buttons */}
        <div className="flex flex-col gap-0.5 pt-6">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onMove('up')}
            className="rounded p-0.5 text-gray-400 hover:text-gray-600 disabled:opacity-30"
            aria-label={`Move field ${field.label || 'unnamed'} up`}
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
            </svg>
          </button>
          <button
            type="button"
            disabled={index === total - 1}
            onClick={() => onMove('down')}
            className="rounded p-0.5 text-gray-400 hover:text-gray-600 disabled:opacity-30"
            aria-label={`Move field ${field.label || 'unnamed'} down`}
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>

        {/* Label input */}
        <div className="flex-1">
          <Input
            label="Label *"
            value={field.label}
            onChange={(e) => onUpdate('label', e.target.value)}
            placeholder="e.g. Fixture Type"
          />
        </div>

        {/* Field type select */}
        <div className="w-40">
          <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
          <select
            value={field.field_type}
            onChange={(e) => onUpdate('field_type', e.target.value as FieldDefinition['field_type'])}
            className="h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            aria-label="Field type"
          >
            {FIELD_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {/* Required toggle */}
        <div className="pt-6">
          <label className="flex items-center gap-1.5 text-sm text-gray-700 whitespace-nowrap">
            <input
              type="checkbox"
              checked={field.is_required}
              onChange={(e) => onUpdate('is_required', e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Required
          </label>
        </div>

        {/* Remove button */}
        <div className="pt-6">
          <button
            type="button"
            onClick={onRemove}
            className="rounded p-1 text-red-400 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
            aria-label={`Remove field ${field.label || 'unnamed'}`}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Options editor for select / multi_select */}
      {showOptions && (
        <div className="ml-7 pl-2 border-l-2 border-blue-200">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Options</span>
            <button
              type="button"
              onClick={onAddOption}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium"
            >
              + Add Option
            </button>
          </div>
          {field.options.length === 0 ? (
            <p className="text-xs text-gray-400">No options defined. Add at least one option.</p>
          ) : (
            <div className="space-y-1">
              {field.options.map((opt, optIdx) => (
                <div key={optIdx} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={opt}
                    onChange={(e) => onUpdateOption(optIdx, e.target.value)}
                    placeholder={`Option ${optIdx + 1}`}
                    className="flex-1 rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    aria-label={`Option ${optIdx + 1} value`}
                  />
                  <button
                    type="button"
                    onClick={() => onRemoveOption(optIdx)}
                    className="rounded p-0.5 text-red-400 hover:text-red-600"
                    aria-label={`Remove option ${optIdx + 1}`}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
