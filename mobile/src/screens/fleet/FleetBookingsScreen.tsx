/**
 * Mobile Fleet Portal — Bookings screen.
 * View and create service booking requests.
 *
 * Implements: B2B Fleet Portal Req 24.8 — Mobile fleet bookings.
 */
import { useState, useCallback, useEffect, useRef } from 'react'
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
import { PullRefresh } from '@/components/gestures/PullRefresh'
import StatusBadge from '@/components/konsta/StatusBadge'
import apiClient from '@/api/client'

interface BookingRequest {
  id: string
  preferred_date: string
  preferred_slot: string
  service_description: string
  status: string
  rego: string | null
  created_at: string
}

export default function FleetBookingsScreen() {
  const [bookings, setBookings] = useState<BookingRequest[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (signal: AbortSignal, refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)
    try {
      const res = await apiClient.get<{ items: BookingRequest[] }>('/api/v2/fleet-portal/bookings', { signal, params: { limit: 50 } })
      setBookings(res.data?.items ?? [])
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

  if (isLoading && bookings.length === 0) {
    return (
      <Page>
        <KonstaNavbar title="Service Bookings" backLink />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page>
      <KonstaNavbar title="Service Bookings" backLink />
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {(bookings ?? []).length === 0 ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400">No booking requests yet.</p>
            </Block>
          ) : (
            <>
              <BlockTitle>Your Bookings</BlockTitle>
              <List strongIos outlineIos>
                {(bookings ?? []).map(b => (
                  <ListItem
                    key={b.id}
                    title={
                      <span className="font-medium">
                        {b.rego ?? 'Vehicle'} — {b.preferred_date}
                      </span>
                    }
                    subtitle={
                      <span className="text-xs text-gray-500 line-clamp-1">
                        {b.service_description}
                      </span>
                    }
                    after={<StatusBadge status={b.status} size="sm" />}
                  />
                ))}
              </List>
            </>
          )}
        </div>
      </PullRefresh>
    </Page>
  )
}
