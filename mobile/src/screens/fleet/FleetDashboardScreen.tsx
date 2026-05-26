/**
 * Mobile Fleet Portal — Dashboard screen.
 * Shows fleet summary cards, recent failures, and quick actions.
 *
 * Implements: B2B Fleet Portal Req 24.7 — Mobile fleet dashboard.
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  Card,
  List,
  ListItem,
  Preloader,
} from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import HapticButton from '@/components/konsta/HapticButton'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface FleetDashboard {
  total_vehicles: number
  valid_wof_cof: number
  expiring_within_28: number
  service_overdue: number
  checklists_completed_today: number
  pending_booking_requests: number
  pending_quote_requests: number
}

export default function FleetDashboardScreen() {
  const navigate = useNavigate()
  const [data, setData] = useState<FleetDashboard | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (signal: AbortSignal, refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)
    try {
      const res = await apiClient.get<FleetDashboard>('/api/v2/fleet-portal/dashboard', { signal })
      setData(res.data ?? null)
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

  if (isLoading && !data) {
    return (
      <Page>
        <KonstaNavbar title="Fleet Portal" />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page>
      <KonstaNavbar title="Fleet Portal" />
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          <BlockTitle>Fleet Overview</BlockTitle>
          <Block>
            <div className="grid grid-cols-2 gap-3">
              <StatCard label="Vehicles" value={data?.total_vehicles ?? 0} />
              <StatCard label="Valid WOF/COF" value={data?.valid_wof_cof ?? 0} color="green" />
              <StatCard label="Expiring Soon" value={data?.expiring_within_28 ?? 0} color="amber" />
              <StatCard label="Service Overdue" value={data?.service_overdue ?? 0} color="red" />
              <StatCard label="Checklists Today" value={data?.checklists_completed_today ?? 0} />
              <StatCard label="Pending Bookings" value={data?.pending_booking_requests ?? 0} />
            </div>
          </Block>

          <BlockTitle>Quick Actions</BlockTitle>
          <Block>
            <div className="grid grid-cols-2 gap-3">
              <HapticButton hapticStyle="light" onClick={() => navigate('/fleet/vehicles')} className="w-full">
                🚗 Vehicles
              </HapticButton>
              <HapticButton hapticStyle="light" onClick={() => navigate('/fleet/checklists')} className="w-full">
                📋 Checklists
              </HapticButton>
              <HapticButton hapticStyle="light" onClick={() => navigate('/fleet/bookings')} className="w-full">
                🔧 Bookings
              </HapticButton>
              <HapticButton hapticStyle="light" onClick={() => navigate('/fleet/reminders')} className="w-full">
                🔔 Reminders
              </HapticButton>
            </div>
          </Block>
        </div>
      </PullRefresh>
    </Page>
  )
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  const colorClass = color === 'green' ? 'text-green-600' : color === 'amber' ? 'text-amber-600' : color === 'red' ? 'text-red-600' : 'text-gray-900 dark:text-white'
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-900">
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className={`text-xl font-semibold ${colorClass}`}>{(value ?? 0).toLocaleString()}</p>
    </div>
  )
}
