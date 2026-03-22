import { useState, useEffect } from 'react'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PublicStatusResponse {
  node_name: string
  role: string
  peer_status: string
  sync_status: string
}

/* ------------------------------------------------------------------ */
/*  NodeStatusIndicator                                                */
/*  Small, non-intrusive indicator for the login page.                 */
/*  Fetches GET /ha/status (public, no auth).                          */
/*  Renders nothing when HA is not configured or fetch fails.          */
/* ------------------------------------------------------------------ */

export function NodeStatusIndicator() {
  const [status, setStatus] = useState<PublicStatusResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    apiClient
      .get<PublicStatusResponse>('/ha/status')
      .then((res) => {
        if (!cancelled) setStatus(res.data)
      })
      .catch(() => {
        /* HA not configured or network error — render nothing */
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!status || status.role === 'standalone') return null

  const isPrimary = status.role === 'primary'
  const peerUnreachable = status.peer_status === 'unreachable'

  return (
    <div className="inline-flex items-center gap-2 rounded-md bg-gray-50 px-3 py-1.5 text-xs text-gray-600 border border-gray-200">
      {/* Colored dot */}
      <span
        className={`inline-block h-2 w-2 rounded-full ${isPrimary ? 'bg-green-500' : 'bg-amber-500'}`}
        aria-hidden="true"
      />

      <span className="font-medium">{status.node_name}</span>
      <span className="text-gray-400">·</span>
      <span>{isPrimary ? 'Primary' : 'Standby'}</span>

      {/* Standby notice */}
      {!isPrimary && (
        <span className="text-amber-600">— Running on backup node</span>
      )}

      {/* Peer unreachable warning */}
      {peerUnreachable && (
        <span className="text-red-600">— Peer unreachable</span>
      )}
    </div>
  )
}
