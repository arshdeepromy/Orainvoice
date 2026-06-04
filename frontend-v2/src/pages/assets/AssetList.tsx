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
          <h1 className="text-2xl font-semibold text-text">{label}s</h1>
          <p className="text-sm text-muted mt-1">
            {(assets ?? []).length.toLocaleString()} {label.toLowerCase()}{(assets ?? []).length !== 1 ? 's' : ''}
          </p>
        </div>
        <Button onClick={openCreate}>+ Add {label}</Button>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl bg-danger-soft border border-danger/40 p-3 text-sm text-danger flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-danger hover:brightness-90 ml-3" aria-label="Dismiss error">×</button>
        </div>
      )}

      {loading ? (
        <div className="py-8 text-center"><Spinner label={`Loading ${label.toLowerCase()}s`} /></div>
      ) : (assets ?? []).length === 0 ? (
        <div className="rounded-card border border-border bg-card p-8 text-center text-muted shadow-card">
          No {label.toLowerCase()}s found. Click &quot;+ Add {label}&quot; to get started.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full">
            <thead>
              <tr>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Identifier</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Make</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Model</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Year</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Type</th>
                <th className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                <th className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(assets ?? []).map(a => (
                <tr key={a.id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm font-medium text-text">{a.identifier || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{a.make || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{a.model || '—'}</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-sm text-muted">{a.year ?? '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <Badge variant="info">{a.asset_type}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {a.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="neutral">Inactive</Badge>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                    <button onClick={() => handleDelete(a)} className="text-danger hover:underline text-xs">Delete</button>
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
          {error && <div className="rounded-ctl bg-danger-soft p-3 text-sm text-danger">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-text mb-1">Type</label>
            <select
              value={form.asset_type}
              onChange={e => setForm({ ...form, asset_type: e.target.value })}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {ASSET_TYPES.map(t => (
                <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-text mb-1">Identifier</label>
            <input
              type="text"
              value={form.identifier}
              onChange={e => setForm({ ...form, identifier: e.target.value })}
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="e.g. ABC123"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-text mb-1">Make</label>
              <input
                type="text"
                value={form.make}
                onChange={e => setForm({ ...form, make: e.target.value })}
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="e.g. Toyota"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text mb-1">Model</label>
              <input
                type="text"
                value={form.model}
                onChange={e => setForm({ ...form, model: e.target.value })}
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="e.g. Hilux"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-text mb-1">Year</label>
              <input
                type="number"
                value={form.year}
                onChange={e => setForm({ ...form, year: e.target.value })}
                className="mono w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="e.g. 2024"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text mb-1">Serial Number</label>
              <input
                type="text"
                value={form.serial_number}
                onChange={e => setForm({ ...form, serial_number: e.target.value })}
                className="mono w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="Optional"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving}>
              {saving ? 'Creating…' : `Create ${label}`}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
