import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

export interface PortalAsset {
  id: string
  asset_type: string
  identifier: string | null
  make: string | null
  model: string | null
  year: number | null
  description: string | null
  serial_number: string | null
  service_history: {
    reference_type: string
    reference_id: string
    reference_number: string | null
    description: string | null
    date: string | null
    status: string | null
  }[]
}

interface AssetHistoryProps {
  token: string
}

export function AssetHistory({ token }: AssetHistoryProps) {
  const [assets, setAssets] = useState<PortalAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchAssets = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/portal/${token}/assets`)
      setAssets(res.data.assets ?? res.data)
    } catch {
      setError('Failed to load assets.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { fetchAssets() }, [fetchAssets])

  if (loading) return <div className="py-8"><Spinner label="Loading assets" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (assets.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No assets found.</p>

  return (
    <div className="space-y-4">
      {assets.map((asset) => (
        <div key={asset.id} className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-medium text-gray-900">
              {asset.identifier || asset.serial_number || 'Unnamed Asset'}
            </span>
            <Badge variant="neutral">{asset.asset_type}</Badge>
          </div>
          {(asset.make || asset.model) && (
            <p className="text-sm text-gray-500">
              {[asset.make, asset.model, asset.year].filter(Boolean).join(' ')}
            </p>
          )}
          {asset.description && (
            <p className="text-sm text-gray-400 mt-1">{asset.description}</p>
          )}

          {asset.service_history.length > 0 && (
            <div className="mt-3 border-t pt-3">
              <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">Service History</h4>
              <div className="space-y-2">
                {asset.service_history.map((entry) => (
                  <div key={entry.reference_id} className="flex items-center justify-between text-sm">
                    <div>
                      <span className="text-gray-700">
                        {entry.reference_number || entry.reference_type}
                      </span>
                      {entry.description && (
                        <span className="text-gray-400 ml-2 truncate">{entry.description}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {entry.status && <Badge variant="neutral">{entry.status}</Badge>}
                      {entry.date && (
                        <span className="text-xs text-gray-400">{formatDate(entry.date)}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-NZ', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}
