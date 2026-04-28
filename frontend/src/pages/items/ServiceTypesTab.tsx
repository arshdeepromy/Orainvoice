import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Badge, Spinner } from '../../components/ui'
import { useTerm } from '@/contexts/TerminologyContext'
import ServiceTypeModal from './ServiceTypeModal'
import type { ServiceTypeForEdit } from './ServiceTypeModal'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ServiceTypeField {
  id: string
  label: string
  field_type: string
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
  created_at: string
  updated_at: string
}

interface ServiceTypeListResponse {
  service_types: ServiceType[]
  total: number
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ServiceTypesTab() {
  const heading = useTerm('service_types', 'Service Types')

  const [serviceTypes, setServiceTypes] = useState<ServiceType[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Modal state */
  const [modalOpen, setModalOpen] = useState(false)
  const [editData, setEditData] = useState<ServiceTypeForEdit | null>(null)

  const fetchServiceTypes = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<ServiceTypeListResponse>('/service-types/', { signal })
      setServiceTypes(res.data?.service_types ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      const abortErr = err as { name?: string }
      if (abortErr?.name === 'CanceledError' || abortErr?.name === 'AbortError') return
      setError('Failed to load service types.')
      setServiceTypes([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchServiceTypes(controller.signal)
    return () => controller.abort()
  }, [fetchServiceTypes])

  /* ---- Actions ---- */

  const openCreate = () => {
    setEditData(null)
    setModalOpen(true)
  }

  const openEdit = (st: ServiceType) => {
    setEditData(st)
    setModalOpen(true)
  }

  const handleToggleActive = async (st: ServiceType) => {
    try {
      await apiClient.put(`/service-types/${st.id}`, { is_active: !st.is_active })
      fetchServiceTypes()
    } catch {
      setError('Failed to update service type status.')
    }
  }

  const handleSaved = () => {
    fetchServiceTypes()
  }

  const truncate = (text: string | null, maxLen: number): string => {
    if (!text) return '—'
    return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Manage {heading.toLowerCase()} — non-priced categories of work with configurable info fields.
        </p>
        <Button onClick={openCreate}>+ New Service Type</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && serviceTypes.length === 0 ? (
        <div className="py-16"><Spinner label={`Loading ${heading.toLowerCase()}`} /></div>
      ) : !loading && serviceTypes.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-gray-500">No {heading.toLowerCase()} yet.</p>
          <p className="text-sm text-gray-400 mt-1">Create your first service type to classify the work your business performs.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">{heading}</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Fields</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {serviceTypes.map((st) => (
                <tr key={st.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{st.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 max-w-xs truncate">{truncate(st.description, 80)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700 text-center">
                    {(st.fields ?? []).length}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                    <Badge variant={st.is_active ? 'success' : 'neutral'}>
                      {st.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button size="sm" variant="secondary" onClick={() => openEdit(st)}>Edit</Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => handleToggleActive(st)}
                      >
                        {st.is_active ? 'Deactivate' : 'Activate'}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Total count footer */}
          {total > 0 && (
            <div className="border-t border-gray-200 px-4 py-3 bg-gray-50">
              <span className="text-sm text-gray-600">
                {total} {total === 1 ? 'service type' : 'service types'}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Create / Edit Modal */}
      <ServiceTypeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={handleSaved}
        editData={editData}
      />
    </div>
  )
}
