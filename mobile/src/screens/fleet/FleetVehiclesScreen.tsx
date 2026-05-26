/**
 * Mobile Fleet Portal — Vehicle list screen.
 * Shows fleet vehicles with expiry badges and navigation to detail.
 *
 * Implements: B2B Fleet Portal Req 24.8 — Mobile fleet vehicles.
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
} from 'konsta/react'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

interface FleetVehicle {
  customer_vehicle_id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  wof_badge: string | null
  cof_badge: string | null
  service_badge: string | null
  odometer_last_recorded: number | null
}

export default function FleetVehiclesScreen() {
  const navigate = useNavigate()
  const [vehicles, setVehicles] = useState<FleetVehicle[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (signal: AbortSignal, refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)
    try {
      const res = await apiClient.get<{ items: FleetVehicle[]; total: number }>('/api/v2/fleet-portal/vehicles', { signal, params: { limit: 100 } })
      setVehicles(res.data?.items ?? [])
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

  if (isLoading && vehicles.length === 0) {
    return (
      <Page>
        <KonstaNavbar title="Fleet Vehicles" backLink />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page>
      <KonstaNavbar title="Fleet Vehicles" backLink />
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {vehicles.length === 0 ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400">No vehicles in your fleet.</p>
            </Block>
          ) : (
            <List strongIos outlineIos>
              {vehicles.map(v => (
                <ListItem
                  key={v.customer_vehicle_id}
                  link
                  onClick={() => navigate(`/fleet/vehicles/${v.customer_vehicle_id}`)}
                  title={<span className="font-medium">{v.rego}</span>}
                  subtitle={<span className="text-xs text-gray-500">{[v.make, v.model, v.year].filter(Boolean).join(' ')}</span>}
                  after={
                    <div className="flex gap-1">
                      {v.wof_badge && <Badge color={v.wof_badge} label="W" />}
                      {v.cof_badge && <Badge color={v.cof_badge} label="C" />}
                      {v.service_badge && <Badge color={v.service_badge} label="S" />}
                    </div>
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

function Badge({ color, label }: { color: string; label: string }) {
  const cls = color === 'red' ? 'bg-red-500' : color === 'amber' ? 'bg-amber-500' : 'bg-green-500'
  return (
    <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold text-white ${cls}`}>
      {label}
    </span>
  )
}
