/**
 * LeaveReferenceGuidePage — in-app NZ Holidays Act 2003 reference guide (R15).
 *
 * Consumes `GET /api/v2/leave/reference-guide` (module-gated). Renders the
 * statutory leave rules, the hours test, the service milestones, and the
 * parental-leave-out-of-scope note. Loading / error+retry / empty states per the
 * frontend-feature-completeness checklist; AbortController cleanup + safe
 * consumption.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  getLeaveReferenceGuide,
  type ReferenceGuideSection,
} from '@/api/leave'
import { Button, Card, Spinner } from '@/components/ui'

export default function LeaveReferenceGuidePage() {
  const navigate = useNavigate()
  const [sections, setSections] = useState<ReferenceGuideSection[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState<number>(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getLeaveReferenceGuide(controller.signal)
      .then((res) => setSections(res.sections ?? []))
      .catch((err: unknown) => {
        if ((err as { code?: string })?.code === 'ERR_CANCELED') return
        setError('Could not load the reference guide. Please try again.')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [reloadKey])

  return (
    <div className="p-6 space-y-4 max-w-3xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">People</p>
          <h1 className="text-2xl font-semibold">NZ Holidays Act 2003 — leave guide</h1>
        </div>
        <Button variant="quiet" onClick={() => navigate('/leave/balances')}>
          Back to balances
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-16" aria-label="Loading reference guide">
          <Spinner />
        </div>
      ) : error ? (
        <Card>
          <div className="p-6 text-center space-y-3">
            <p className="text-sm text-danger">{error}</p>
            <Button onClick={() => setReloadKey((k) => k + 1)}>Retry</Button>
          </div>
        </Card>
      ) : sections.length === 0 ? (
        <Card>
          <div className="p-10 text-center text-muted">
            The reference guide has no content yet.
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {sections.map((s) => (
            <Card key={s.key}>
              <div className="p-4 space-y-1">
                <h2 className="font-semibold">{s.title}</h2>
                <p className="text-sm text-muted leading-relaxed">{s.body}</p>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
