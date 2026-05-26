/**
 * Mobile Fleet Portal — Checklist screen.
 * Start pre-trip checklists and view submission history.
 *
 * Implements: B2B Fleet Portal Req 24.8 — Mobile fleet checklists.
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  List,
  ListItem,
  Preloader,
  Chip,
} from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import HapticButton from '@/components/konsta/HapticButton'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface FleetVehicle {
  customer_vehicle_id: string
  rego: string
}

interface ChecklistSubmission {
  id: string
  status: string
  started_at: string
  completed_at: string | null
  passed_item_count: number
  failed_item_count: number
  na_item_count: number
}

export default function FleetChecklistScreen() {
  const navigate = useNavigate()
  const [vehicles, setVehicles] = useState<FleetVehicle[]>([])
  const [submissions, setSubmissions] = useState<ChecklistSubmission[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [starting, setStarting] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (signal: AbortSignal, refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)
    try {
      const [vRes, sRes] = await Promise.all([
        apiClient.get<{ items: FleetVehicle[] }>('/api/v2/fleet-portal/vehicles', { signal, params: { limit: 100 } }),
        apiClient.get<{ items: ChecklistSubmission[] }>('/api/v2/fleet-portal/checklists/submissions', { signal, params: { limit: 20 } }),
      ])
      setVehicles(vRes.data?.items ?? [])
      setSubmissions(sRes.data?.items ?? [])
    } catch {} finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchData(controller.signal, true)
  }, [fetchData])

  const startChecklist = async (vehicleId: string) => {
    setStarting(vehicleId)
    try {
      await apiClient.post('/api/v2/fleet-portal/checklists/start', { customer_vehicle_id: vehicleId })
      const controller = new AbortController()
      abortRef.current = controller
      await fetchData(controller.signal, true)
    } catch {} finally { setStarting(null) }
  }

  if (isLoading && submissions.length === 0) {
    return (
      <Page>
        <KonstaNavbar title="Checklists" backLink />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page>
      <KonstaNavbar title="Checklists" backLink />
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <BlockTitle>Start Pre-Trip Checklist</BlockTitle>
          <Block>
            <div className="flex flex-wrap gap-2">
              {(vehicles ?? []).map(v => (
                <HapticButton
                  key={v.customer_vehicle_id}
                  hapticStyle="light"
                  small
                  onClick={() => startChecklist(v.customer_vehicle_id)}
                  disabled={starting === v.customer_vehicle_id}
                >
                  {starting === v.customer_vehicle_id ? '…' : v.rego}
                </HapticButton>
              ))}
            </div>
          </Block>

          <BlockTitle>Recent Submissions</BlockTitle>
          {(submissions ?? []).length === 0 ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400">No submissions yet.</p>
            </Block>
          ) : (
            <List strongIos outlineIos>
              {(submissions ?? []).map(s => (
                <ListItem
                  key={s.id}
                  title={
                    <span className="font-medium">
                      {s.status === 'completed' ? '✓' : '⏳'} {new Date(s.started_at).toLocaleDateString()}
                    </span>
                  }
                  subtitle={
                    s.status === 'completed'
                      ? <span className="text-xs">Pass: {s.passed_item_count ?? 0} · Fail: {s.failed_item_count ?? 0}</span>
                      : <span className="text-xs text-blue-600">In progress</span>
                  }
                  after={
                    <Chip className={(s.failed_item_count ?? 0) > 0 ? 'bg-red-100 text-red-800' : s.status === 'completed' ? 'bg-green-100 text-green-800' : 'bg-blue-100 text-blue-800'}>
                      {s.status}
                    </Chip>
                  }
                />
              ))}
            </List>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}
