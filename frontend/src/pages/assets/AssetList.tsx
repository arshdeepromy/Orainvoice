/**
 * Asset list page with trade-specific terminology.
 *
 * Displays assets (vehicles, devices, properties, etc.) based on the
 * organisation's trade category. Uses the terminology context to show
 * trade-appropriate labels.
 *
 * **Validates: Extended Asset Tracking — Task 45.10**
 */
import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Modal, Spinner, Badge } from '@/components/ui'
import { useModules } from '@/contexts/ModuleContext'

/** Trade-family → asset label mapping */
const ASSET_LABELS: Record<string, string> = {
  'automotive-transport': 'Vehicle',
  'it-technology': 'Device',
  'building-construction': 'Property',
  'landscaping-outdoor': 'Property',
  'cleaning-facilities': 'Property',
  'electrical-mechanical': 'Equipment',
  'plumbing-gas': 'Equipment',
  'food-hospitality': 'Equipment',
  'retail': 'Equipment',
  'health-wellness': 'Device',
}

export function getAssetLabel(tradeFamily?: string): string {
  if (!tradeFamily) return 'Asset'
  return ASSET_LABELS[tradeFamily] || 'Asset'
}

interface AssetData {
  id: string
  org_id: string
  customer_id: string | null
  asset_type: string
  identifier: string | null
  make: string | null
  model: string | null
  year: number | null
  serial_number: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

interface AssetForm {
  asset_type: string
  identifier: string
  make: string
  model: string
  year: string
  serial_number: string
}

const EMPTY_FORM: AssetForm = {
  asset_type: 'vehicle',
  identifier: '',
  make: '',
  model: '',
  year: '',
  serial_number: '',
}

const ASSET_TYPES = ['vehicle', 'device', 'property', 'equipment', 'other'] as const

interface AssetListProps {
  tradeFamily?: string
}

export default function AssetList({ tradeFamily }: AssetListProps = {}) {
  const { isEnabled } = useModules()
  if (!isEnabled('assets')) return <Navigate to="/dashboard" replace />

  const [assets, setAssets] = useState<AssetData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<AssetForm>({ ...EMPTY_FORM })

  const label = getAssetLabel(tradeFamily)

  const fetchAssets = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      // Backend returns list[AssetResponse] — bare array, not wrapped
      const res = await apiClient.get<AssetData[]>('/api/v2/assets', { signal })
      setAssets(res.data ?? [])
    } catch (err: unknown) {
      if (!(err instanceof Error && err.name === 'CanceledError')) {
        setError(`Failed to load ${label.toLowerCase()}s`)
        setAssets([])
      }
    } finally {
      setLoading(false)
    }
  }, [label])

  useEffect(() => {
    const controller = new AbortController()
    fetchAssets(controller.signal)
    return () => controller.abort()
  }, [fetchAssets])

  const openCreate = () => {
    setForm({ ...EMPTY_FORM })
    setError('')
    setModalOpen(true)
  }

  const handleCreate = async () => {
    setSaving(true)
    setError('')
    try {
      await apiClient.post('/api/v2/assets', {
        asset_type: form.asset_type,
        identifier: form.identifier || null,
        make: form.make || null,
        model: form.model || null,
        year: form.year ? parseInt(form.year, 10) : null,
        serial_number: form.serial_number || null,
      })
      setModalOpen(false)
      setForm({ ...EMPTY_FORM })
      fetchAssets()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? `Failed to create ${label.toLowerCase()}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (asset: AssetData) => {
    if (!confirm(`Delete ${label.toLowerCase()} "${asset.identifier ?? asset.make ?? asset.id}"?`)) return
    try {
      await apiClient.delete(`/api/v2/assets/${asset.id}`)
      fetchAssets()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(msg ?? `Failed to delete ${label.toLowerCase()}`)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">{label}s</h1>
          <p className="text-sm text-gray-500 mt-1">
            {(assets ?? []).length.toLocaleString()} {label.toLowerCase()}{(assets ?? []).length !== 1 ? 's' : ''}
          </p>
        </div>
        <Button onClick={openCreate}>+ Add {label}</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-500 hover:text-red-700 ml-3" aria-label="Dismiss error">×</button>
        </div>
      )}

      {loading ? (
        <div className="py-8 text-center"><Spinner label={`Loading ${label.toLowerCase()}s`} /></div>
      ) : (assets ?? []).length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No {label.toLowerCase()}s found. Click &quot;+ Add {label}&quot; to get started.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Identifier</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Make</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Model</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Year</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(assets ?? []).map(a => (
                <tr key={a.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{a.identifier || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{a.make || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{a.model || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{a.year ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant="info">{a.asset_type}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {a.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="neutral">Inactive</Badge>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                    <button onClick={() => handleDelete(a)} className="text-red-600 hover:underline text-xs">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={`New ${label}`}>
        <div className="space-y-4">
          {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
            <select
              value={form.asset_type}
              onChange={e => setForm({ ...form, asset_type: e.target.value })}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ASSET_TYPES.map(t => (
                <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Identifier</label>
            <input
              type="text"
              value={form.identifier}
              onChange={e => setForm({ ...form, identifier: e.target.value })}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. ABC123"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Make</label>
              <input
                type="text"
                value={form.make}
                onChange={e => setForm({ ...form, make: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="e.g. Toyota"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
              <input
                type="text"
                value={form.model}
                onChange={e => setForm({ ...form, model: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="e.g. Hilux"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Year</label>
              <input
                type="number"
                value={form.year}
                onChange={e => setForm({ ...form, year: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="e.g. 2024"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Serial Number</label>
              <input
                type="text"
                value={form.serial_number}
                onChange={e => setForm({ ...form, serial_number: e.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Optional"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving}>
              {saving ? 'Creating…' : `Create ${label}`}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
