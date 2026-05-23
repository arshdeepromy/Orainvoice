/**
 * Checklist submission flow — item-by-item pass/fail/na with photo upload.
 *
 * Implements: B2B Fleet Portal — Requirements 9.1–9.12.
 */
import { useEffect, useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'

import { fleetClient } from '../api/client'
import type { ChecklistSubmission, ChecklistSubmissionItem } from '../api/types'

type Result = 'pass' | 'fail' | 'na'

export default function ChecklistSubmit() {
  const { submissionId } = useParams<{ submissionId: string }>()
  const navigate = useNavigate()
  const [submission, setSubmission] = useState<ChecklistSubmission | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [completing, setCompleting] = useState(false)
  const [currentIdx, setCurrentIdx] = useState(0)

  const fetchSubmission = async () => {
    if (!submissionId) return
    try {
      const res = await fleetClient.get<ChecklistSubmission>(`/checklists/submissions/${submissionId}`)
      setSubmission(res.data ?? null)
    } catch { setError('Failed to load checklist.') }
    finally { setLoading(false) }
  }

  useEffect(() => { fetchSubmission() }, [submissionId])

  const updateItem = async (itemId: string, result: Result, notes?: string) => {
    try {
      await fleetClient.patch(`/checklists/${submissionId}/items/${itemId}`, { result, notes: notes || null })
      await fetchSubmission()
      // Auto-advance to next item
      if (currentIdx < (submission?.items ?? []).length - 1) {
        setCurrentIdx(prev => prev + 1)
      }
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to update item.')
    }
  }

  const uploadPhoto = async (itemId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      await fleetClient.post(`/checklists/${submissionId}/items/${itemId}/photo`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      await fetchSubmission()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to upload photo.')
    }
  }

  const completeChecklist = async () => {
    setCompleting(true); setError(null)
    try {
      await fleetClient.post(`/checklists/${submissionId}/complete`)
      navigate('/fleet/checklists', { replace: true })
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Cannot complete — ensure all failed items with photo requirements have photos uploaded.')
    } finally { setCompleting(false) }
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading checklist…</div>
  if (error && !submission) return <div className="p-4 text-sm text-red-600">{error}</div>
  if (!submission) return <div className="p-4 text-sm text-gray-500">Submission not found.</div>

  if (submission.status === 'completed') {
    return (
      <div className="space-y-4">
        <Link to="/fleet/checklists" className="text-sm text-indigo-600 hover:underline">← Back to checklists</Link>
        <div className="rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950/20">
          <h1 className="text-lg font-semibold text-green-800 dark:text-green-200">✓ Checklist Completed</h1>
          <p className="text-sm text-green-700 dark:text-green-300 mt-1">
            Pass: {submission.passed_item_count} · Fail: {submission.failed_item_count} · N/A: {submission.na_item_count}
          </p>
        </div>
        <SubmissionItemList items={submission.items ?? []} readOnly />
      </div>
    )
  }

  const items = submission.items ?? []
  const allAnswered = items.every(i => i.result !== null)
  const currentItem = items[currentIdx]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Link to="/fleet/checklists" className="text-sm text-indigo-600 hover:underline">← Back</Link>
        <span className="text-xs text-gray-500">{currentIdx + 1} / {items.length}</span>
      </div>

      {error && <p className="text-xs text-red-600 rounded border border-red-200 bg-red-50 p-2">{error}</p>}

      {/* Progress bar */}
      <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-800">
        <div className="h-2 rounded-full bg-indigo-600 transition-all" style={{ width: `${((items.filter(i => i.result !== null).length) / Math.max(items.length, 1)) * 100}%` }} />
      </div>

      {/* Current item */}
      {currentItem && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
          <p className="text-xs font-medium text-indigo-600 uppercase mb-1">{currentItem.category}</p>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-2">{currentItem.label}</h2>
          {currentItem.requires_photo_on_fail && (
            <p className="text-xs text-amber-600 mb-3">📷 Photo required if failed</p>
          )}

          {/* Pass / Fail / N/A buttons — large touch targets */}
          <div className="grid grid-cols-3 gap-2 mb-4">
            <button onClick={() => updateItem(currentItem.id, 'pass')}
              className={`rounded-lg py-4 text-sm font-bold min-h-[56px] transition-colors ${currentItem.result === 'pass' ? 'bg-green-600 text-white ring-2 ring-green-400' : 'bg-green-100 text-green-800 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-300'}`}>
              ✓ PASS
            </button>
            <button onClick={() => updateItem(currentItem.id, 'fail')}
              className={`rounded-lg py-4 text-sm font-bold min-h-[56px] transition-colors ${currentItem.result === 'fail' ? 'bg-red-600 text-white ring-2 ring-red-400' : 'bg-red-100 text-red-800 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-300'}`}>
              ✗ FAIL
            </button>
            <button onClick={() => updateItem(currentItem.id, 'na')}
              className={`rounded-lg py-4 text-sm font-bold min-h-[56px] transition-colors ${currentItem.result === 'na' ? 'bg-gray-600 text-white ring-2 ring-gray-400' : 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300'}`}>
              N/A
            </button>
          </div>

          {/* Photo upload for failed items */}
          {currentItem.result === 'fail' && currentItem.requires_photo_on_fail && (
            <div className="border-t border-gray-200 pt-3 dark:border-gray-700">
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">Upload photo evidence:</p>
              {(currentItem.photo_urls ?? []).length > 0 && (
                <p className="text-xs text-green-600 mb-2">✓ {(currentItem.photo_urls ?? []).length} photo(s) uploaded</p>
              )}
              <input
                type="file"
                accept="image/*"
                capture="environment"
                onChange={e => { const f = e.target.files?.[0]; if (f) uploadPhoto(currentItem.id, f) }}
                className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 min-h-[44px]"
              />
            </div>
          )}
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between">
        <button onClick={() => setCurrentIdx(Math.max(0, currentIdx - 1))} disabled={currentIdx === 0}
          className="rounded-md border border-gray-300 px-4 py-2 text-sm min-h-[44px] disabled:opacity-30 dark:border-gray-700">
          ← Previous
        </button>
        {currentIdx < items.length - 1 ? (
          <button onClick={() => setCurrentIdx(currentIdx + 1)}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700">
            Next →
          </button>
        ) : (
          <button onClick={completeChecklist} disabled={!allAnswered || completing}
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-green-700">
            {completing ? 'Completing…' : '✓ Complete Checklist'}
          </button>
        )}
      </div>

      {/* Item overview */}
      <details className="mt-4">
        <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">View all items ({items.filter(i => i.result).length}/{items.length} answered)</summary>
        <SubmissionItemList items={items} readOnly={false} onSelect={setCurrentIdx} currentIdx={currentIdx} />
      </details>
    </div>
  )
}

function SubmissionItemList({ items, readOnly, onSelect, currentIdx }: {
  items: ChecklistSubmissionItem[]
  readOnly: boolean
  onSelect?: (idx: number) => void
  currentIdx?: number
}) {
  return (
    <div className="mt-2 space-y-1">
      {(items ?? []).map((item, idx) => (
        <div key={item.id}
          onClick={() => !readOnly && onSelect?.(idx)}
          className={`flex items-center justify-between rounded px-3 py-2 text-sm ${idx === currentIdx ? 'bg-indigo-50 border border-indigo-200 dark:bg-indigo-950/20 dark:border-indigo-800' : 'hover:bg-gray-50 dark:hover:bg-gray-900'} ${!readOnly ? 'cursor-pointer' : ''}`}>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-5">{idx + 1}.</span>
            <span className={item.result ? 'text-gray-900 dark:text-white' : 'text-gray-500'}>{item.label}</span>
          </div>
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${item.result === 'pass' ? 'bg-green-100 text-green-800' : item.result === 'fail' ? 'bg-red-100 text-red-800' : item.result === 'na' ? 'bg-gray-100 text-gray-600' : 'text-gray-400'}`}>
            {item.result?.toUpperCase() ?? '—'}
          </span>
        </div>
      ))}
    </div>
  )
}
