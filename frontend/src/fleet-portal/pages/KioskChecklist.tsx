/**
 * Kiosk checklist view — full-screen, large touch targets (≥56px),
 * no sidebar, optimised for depot tablets.
 *
 * Implements: B2B Fleet Portal — Requirements 9.11, 19.3.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { listVehicles } from '../api/endpoints'
import type { ChecklistSubmission, ChecklistSubmissionItem, VehicleListItem } from '../api/types'
import { useFleetSession } from '../contexts/FleetSessionContext'

type Result = 'pass' | 'fail' | 'na'

export default function KioskChecklist() {
  const { user } = useFleetSession()
  const navigate = useNavigate()
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [submission, setSubmission] = useState<ChecklistSubmission | null>(null)
  const [currentIdx, setCurrentIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listVehicles(0, 50).then(r => setVehicles(r.items ?? [])).finally(() => setLoading(false))
  }, [])

  const startForVehicle = async (vehicleId: string) => {
    setError(null)
    try {
      const res = await fleetClient.post<ChecklistSubmission>('/checklists/start', { customer_vehicle_id: vehicleId })
      setSubmission(res.data ?? null)
      setCurrentIdx(0)
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to start checklist.')
    }
  }

  const updateItem = async (itemId: string, result: Result) => {
    if (!submission) return
    try {
      await fleetClient.patch(`/checklists/${submission.id}/items/${itemId}`, { result, notes: null })
      // Refresh
      const res = await fleetClient.get<ChecklistSubmission>(`/checklists/submissions/${submission.id}`)
      setSubmission(res.data ?? null)
      if (currentIdx < (submission.items ?? []).length - 1) setCurrentIdx(prev => prev + 1)
    } catch {}
  }

  const uploadPhoto = async (itemId: string, file: File) => {
    if (!submission) return
    const fd = new FormData(); fd.append('file', file)
    await fleetClient.post(`/checklists/${submission.id}/items/${itemId}/photo`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    const res = await fleetClient.get<ChecklistSubmission>(`/checklists/submissions/${submission.id}`)
    setSubmission(res.data ?? null)
  }

  const complete = async () => {
    if (!submission) return
    try {
      await fleetClient.post(`/checklists/${submission.id}/complete`)
      setSubmission(null)
      setError(null)
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Cannot complete — photos may be required for failed items.')
    }
  }

  if (loading) return <div className="flex min-h-screen items-center justify-center text-lg text-gray-500">Loading…</div>

  // Vehicle selection screen
  if (!submission) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-6 dark:bg-gray-900">
        <h1 className="text-2xl font-bold mb-2">Pre-Trip Checklist</h1>
        <p className="text-base text-gray-500 mb-6">Select a vehicle to begin</p>
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
        <div className="grid grid-cols-1 gap-3 w-full max-w-md">
          {(vehicles ?? []).map(v => (
            <button key={v.customer_vehicle_id} onClick={() => startForVehicle(v.customer_vehicle_id)}
              className="rounded-xl border-2 border-gray-200 bg-white px-6 py-5 text-left hover:border-indigo-400 hover:bg-indigo-50 min-h-[72px] dark:border-gray-700 dark:bg-gray-950 dark:hover:border-indigo-600">
              <p className="text-xl font-bold">{v.rego}</p>
              <p className="text-sm text-gray-500">{[v.make, v.model].filter(Boolean).join(' ')}</p>
            </button>
          ))}
        </div>
      </div>
    )
  }

  // Checklist flow
  const items = submission.items ?? []
  const item = items[currentIdx]
  const allDone = items.every(i => i.result !== null)
  const progress = items.filter(i => i.result !== null).length

  return (
    <div className="flex min-h-screen flex-col bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between bg-white px-6 py-4 border-b dark:bg-gray-950 dark:border-gray-800">
        <div>
          <p className="text-sm text-gray-500">Pre-Trip Checklist</p>
          <p className="text-xs text-gray-400">{progress}/{items.length} completed</p>
        </div>
        <div className="h-3 w-48 rounded-full bg-gray-200 dark:bg-gray-800">
          <div className="h-3 rounded-full bg-indigo-600 transition-all" style={{ width: `${(progress / Math.max(items.length, 1)) * 100}%` }} />
        </div>
      </div>

      {error && <p className="px-6 py-2 text-sm text-red-600 bg-red-50">{error}</p>}

      {/* Current item — large display */}
      {item && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8">
          <p className="text-sm font-medium text-indigo-600 uppercase mb-2">{item.category}</p>
          <h2 className="text-2xl font-bold text-center text-gray-900 dark:text-white mb-1" style={{ fontSize: '1.5rem' }}>{item.label}</h2>
          {item.requires_photo_on_fail && <p className="text-sm text-amber-600 mb-4">📷 Photo required if failed</p>}

          {/* Large buttons — 56px+ */}
          <div className="grid grid-cols-3 gap-4 w-full max-w-lg mt-6">
            <button onClick={() => updateItem(item.id, 'pass')}
              className={`rounded-2xl py-6 text-lg font-bold min-h-[72px] ${item.result === 'pass' ? 'bg-green-600 text-white ring-4 ring-green-300' : 'bg-green-100 text-green-800 hover:bg-green-200'}`}>
              ✓ PASS
            </button>
            <button onClick={() => updateItem(item.id, 'fail')}
              className={`rounded-2xl py-6 text-lg font-bold min-h-[72px] ${item.result === 'fail' ? 'bg-red-600 text-white ring-4 ring-red-300' : 'bg-red-100 text-red-800 hover:bg-red-200'}`}>
              ✗ FAIL
            </button>
            <button onClick={() => updateItem(item.id, 'na')}
              className={`rounded-2xl py-6 text-lg font-bold min-h-[72px] ${item.result === 'na' ? 'bg-gray-600 text-white ring-4 ring-gray-300' : 'bg-gray-200 text-gray-800 hover:bg-gray-300'}`}>
              N/A
            </button>
          </div>

          {/* Photo upload */}
          {item.result === 'fail' && item.requires_photo_on_fail && (
            <div className="mt-6 w-full max-w-lg">
              {(item.photo_urls ?? []).length > 0 && <p className="text-sm text-green-600 mb-2">✓ {(item.photo_urls ?? []).length} photo(s)</p>}
              <label className="block w-full rounded-xl border-2 border-dashed border-gray-300 py-6 text-center cursor-pointer hover:border-indigo-400 min-h-[72px]">
                <span className="text-base text-gray-600">📷 Tap to take photo</span>
                <input type="file" accept="image/*" capture="environment" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) uploadPhoto(item.id, f) }} />
              </label>
            </div>
          )}
        </div>
      )}

      {/* Bottom navigation */}
      <div className="flex items-center justify-between bg-white px-6 py-4 border-t dark:bg-gray-950 dark:border-gray-800">
        <button onClick={() => setCurrentIdx(Math.max(0, currentIdx - 1))} disabled={currentIdx === 0}
          className="rounded-xl px-6 py-4 text-base font-medium border border-gray-300 min-h-[56px] disabled:opacity-30 dark:border-gray-700">
          ← Prev
        </button>
        {currentIdx < items.length - 1 ? (
          <button onClick={() => setCurrentIdx(currentIdx + 1)}
            className="rounded-xl bg-indigo-600 px-6 py-4 text-base font-medium text-white min-h-[56px] hover:bg-indigo-700">
            Next →
          </button>
        ) : (
          <button onClick={complete} disabled={!allDone}
            className="rounded-xl bg-green-600 px-8 py-4 text-base font-bold text-white min-h-[56px] disabled:opacity-50 hover:bg-green-700">
            ✓ COMPLETE
          </button>
        )}
      </div>
    </div>
  )
}
