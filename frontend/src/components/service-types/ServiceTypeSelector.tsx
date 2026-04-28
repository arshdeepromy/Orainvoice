import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner } from '../ui'
import { useTerm } from '@/contexts/TerminologyContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ServiceTypeField {
  id: string
  label: string
  field_type: 'text' | 'number' | 'select' | 'multi_select'
  display_order: number
  is_required: boolean
  options: string[] | null
}

interface ServiceType {
  id: string
  name: string
  description: string | null
  is_active: boolean
  fields: ServiceTypeField[]
}

interface ServiceTypeListResponse {
  service_types: ServiceType[]
  total: number
}

interface FieldValue {
  field_id: string
  value_text?: string
  value_array?: string[]
}

interface ServiceTypeSelectorProps {
  /** Currently selected service type ID (controlled) */
  serviceTypeId: string | null
  /** Current field values (controlled) */
  serviceTypeValues: FieldValue[]
  /** Called when the selected service type changes */
  onServiceTypeChange: (serviceTypeId: string | null) => void
  /** Called when field values change */
  onValuesChange: (values: FieldValue[]) => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ServiceTypeSelector({
  serviceTypeId,
  serviceTypeValues,
  onServiceTypeChange,
  onValuesChange,
}: ServiceTypeSelectorProps) {
  const serviceTypesLabel = useTerm('service_types', 'Service Types')

  const [serviceTypes, setServiceTypes] = useState<ServiceType[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* ---- Fetch active service types ---- */
  const fetchServiceTypes = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<ServiceTypeListResponse>('/service-types/', {
        params: { active_only: true },
        signal,
      })
      setServiceTypes(res.data?.service_types ?? [])
    } catch (err: unknown) {
      const abortErr = err as { name?: string }
      if (abortErr?.name === 'CanceledError' || abortErr?.name === 'AbortError') return
      setError('Failed to load service types.')
      setServiceTypes([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchServiceTypes(controller.signal)
    return () => controller.abort()
  }, [fetchServiceTypes])

  /* ---- Derived state ---- */
  const selectedType = serviceTypeId
    ? serviceTypes.find((st) => st.id === serviceTypeId) ?? null
    : null
  const fields = (selectedType?.fields ?? []).sort(
    (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0),
  )

  /* ---- Handlers ---- */

  const handleServiceTypeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newId = e.target.value || null
    onServiceTypeChange(newId)
    // Reset field values when service type changes
    onValuesChange([])
  }

  const getFieldValue = (fieldId: string): FieldValue | undefined => {
    return serviceTypeValues.find((v) => v.field_id === fieldId)
  }

  const updateFieldValue = (fieldId: string, patch: Partial<FieldValue>) => {
    const existing = serviceTypeValues.find((v) => v.field_id === fieldId)
    if (existing) {
      onValuesChange(
        serviceTypeValues.map((v) =>
          v.field_id === fieldId ? { ...v, ...patch } : v,
        ),
      )
    } else {
      onValuesChange([...serviceTypeValues, { field_id: fieldId, ...patch }])
    }
  }

  const handleTextChange = (fieldId: string, value: string) => {
    updateFieldValue(fieldId, { value_text: value })
  }

  const handleNumberChange = (fieldId: string, value: string) => {
    updateFieldValue(fieldId, { value_text: value })
  }

  const handleSelectChange = (fieldId: string, value: string) => {
    updateFieldValue(fieldId, { value_text: value })
  }

  const handleMultiSelectToggle = (fieldId: string, option: string) => {
    const current = getFieldValue(fieldId)?.value_array ?? []
    const updated = current.includes(option)
      ? current.filter((o) => o !== option)
      : [...current, option]
    updateFieldValue(fieldId, { value_array: updated })
  }

  /* ---- Render ---- */

  if (loading && serviceTypes.length === 0) {
    return (
      <div className="py-4">
        <Spinner label={`Loading ${serviceTypesLabel.toLowerCase()}`} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
        {error}
      </div>
    )
  }

  if (serviceTypes.length === 0) {
    return null // No service types configured — hide the selector entirely
  }

  return (
    <div className="space-y-4">
      {/* Service Type Dropdown */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="service-type-select"
          className="text-sm font-medium text-gray-700"
        >
          Service Type (optional)
        </label>
        <select
          id="service-type-select"
          value={serviceTypeId ?? ''}
          onChange={handleServiceTypeChange}
          className="h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm transition-colors
            bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%236b7280%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')]
            bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500"
        >
          <option value="">— None —</option>
          {serviceTypes.map((st) => (
            <option key={st.id} value={st.id}>
              {st.name}
            </option>
          ))}
        </select>
      </div>

      {/* Dynamic Fields */}
      {selectedType && fields.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-4">
          <h3 className="text-sm font-medium text-gray-700">
            Additional Information
          </h3>
          {fields.map((field) => (
            <DynamicField
              key={field.id}
              field={field}
              value={getFieldValue(field.id)}
              onTextChange={handleTextChange}
              onNumberChange={handleNumberChange}
              onSelectChange={handleSelectChange}
              onMultiSelectToggle={handleMultiSelectToggle}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Dynamic Field Renderer                                             */
/* ------------------------------------------------------------------ */

function DynamicField({
  field,
  value,
  onTextChange,
  onNumberChange,
  onSelectChange,
  onMultiSelectToggle,
}: {
  field: ServiceTypeField
  value: FieldValue | undefined
  onTextChange: (fieldId: string, value: string) => void
  onNumberChange: (fieldId: string, value: string) => void
  onSelectChange: (fieldId: string, value: string) => void
  onMultiSelectToggle: (fieldId: string, option: string) => void
}) {
  const fieldId = `stf-${field.id}`
  const requiredMark = field.is_required ? (
    <span className="text-red-500 ml-0.5" aria-hidden="true">*</span>
  ) : null

  switch (field.field_type) {
    case 'text':
      return (
        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className="text-sm font-medium text-gray-700">
            {field.label}{requiredMark}
          </label>
          <input
            id={fieldId}
            type="text"
            value={value?.value_text ?? ''}
            onChange={(e) => onTextChange(field.id, e.target.value)}
            required={field.is_required}
            className="h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
              placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:border-blue-500"
            aria-required={field.is_required}
          />
        </div>
      )

    case 'number':
      return (
        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className="text-sm font-medium text-gray-700">
            {field.label}{requiredMark}
          </label>
          <input
            id={fieldId}
            type="number"
            value={value?.value_text ?? ''}
            onChange={(e) => onNumberChange(field.id, e.target.value)}
            required={field.is_required}
            className="h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm
              placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:border-blue-500"
            aria-required={field.is_required}
          />
        </div>
      )

    case 'select':
      return (
        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className="text-sm font-medium text-gray-700">
            {field.label}{requiredMark}
          </label>
          <select
            id={fieldId}
            value={value?.value_text ?? ''}
            onChange={(e) => onSelectChange(field.id, e.target.value)}
            required={field.is_required}
            className="h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm
              bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20fill%3D%22none%22%20viewBox%3D%220%200%2024%2024%22%20stroke%3D%22%236b7280%22%3E%3Cpath%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222%22%20d%3D%22M19%209l-7%207-7-7%22%2F%3E%3C%2Fsvg%3E')]
              bg-[length:20px_20px] bg-[right_8px_center] bg-no-repeat pr-10
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:border-blue-500"
            aria-required={field.is_required}
          >
            <option value="">— Select —</option>
            {(field.options ?? []).map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
      )

    case 'multi_select':
      return (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-gray-700">
            {field.label}{requiredMark}
          </legend>
          <div className="flex flex-wrap gap-3">
            {(field.options ?? []).map((opt) => {
              const checked = (value?.value_array ?? []).includes(opt)
              const checkboxId = `${fieldId}-${opt}`
              return (
                <label
                  key={opt}
                  htmlFor={checkboxId}
                  className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer min-h-[44px]"
                >
                  <input
                    id={checkboxId}
                    type="checkbox"
                    checked={checked}
                    onChange={() => onMultiSelectToggle(field.id, opt)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  {opt}
                </label>
              )
            })}
          </div>
          {(field.options ?? []).length === 0 && (
            <p className="text-sm text-gray-400">No options configured.</p>
          )}
        </fieldset>
      )

    default:
      return null
  }
}

export type { FieldValue, ServiceTypeSelectorProps }
