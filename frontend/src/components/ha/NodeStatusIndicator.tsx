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
    <div
      className="inline-flex items-center rounded-md p-1.5"
      title={`${status.node_name} · ${isPrimary ? 'Primary' : 'Standby'}${peerUnreachable ? ' — Peer unreachable' : ''}`}
    >
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${
          peerUnreachable ? 'bg-red-500' : isPrimary ? 'bg-green-500' : 'bg-amber-500'
        }`}
        aria-label={`${isPrimary ? 'Primary' : 'Standby'} node${peerUnreachable ? ', peer unreachable' : ''}`}
      />
    </div>
  )
}
