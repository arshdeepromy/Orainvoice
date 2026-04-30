import { useState, useCallback, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  Card,
  List,
  ListItem,
  Chip,
  Button,
  Preloader,
} from 'konsta/react'
import type { Vehicle } from '@shared/types/vehicle'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface VehicleDetail extends Vehicle {
  wof_expiry?: string | null
  rego_expiry?: string | null
  odometer?: number | null
  service_due_date?: string | null
}

interface ServiceHistoryEntry {
  id: string
  date: string
  description: string
  status: string
  total: number | null
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function expiryPill(
  dateStr: string | null | undefined,
  label: string,
): { text: string; color: string; bg: string } | null {
  if (!dateStr) return null
  const expiry = new Date(dateStr)
  const now = new Date()
  const diffDays = Math.floor((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))

  if (diffDays < 0) {
    return { text: `${label} Expired`, color: 'text-red-700', bg: 'bg-red-100 dark:bg-red-900/30' }
  }
  if (diffDays < 30) {
    return { text: `${label} ${diffDays}d`, color: 'text-amber-700', bg: 'bg-amber-100 dark:bg-amber-900/30' }
  }
  return { text: `${label} OK`, color: 'text-green-700', bg: 'bg-green-100 dark:bg-green-900/30' }
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Vehicle profile screen — hero (large rego, make/model/year/colour).
 * Stats: WOF expiry, rego expiry, odometer, service due date.
 * Sections: Service History, Linked Customer.
 * "Edit" button.
 *
 * Requirements: 29.2, 29.3, 29.4
 */
export default function VehicleProfileScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [serviceHistory, setServiceHistory] = useState<ServiceHistoryEntry[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  const fetchVehicle = useCallback(
    async (signal: AbortSignal, refresh = false) => {
      if (refresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<VehicleDetail>(`/api/v1/vehicles/${id}`, { signal })
        setVehicle(res.data ?? null)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load vehicle')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [id],
  )

  const fetchHistory = useCallback(
    async (signal: AbortSignal) => {
      setIsLoadingHistory(true)
      try {
        const res = await apiClient.get<{ items?: ServiceHistoryEntry[] }>(
          `/api/v1/vehicles/${id}/service-history`,
          { signal },
        )
        setServiceHistory(res.data?.items ?? [])
      } catch {
        // Non-critical — silently fail
      } finally {
        setIsLoadingHistory(false)
      }
    },
    [id],
  )

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchVehicle(controller.signal)
    fetchHistory(controller.signal)
    return () => controller.abort()
  }, [fetchVehicle, fetchHistory])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await Promise.all([
      fetchVehicle(controller.signal, true),
      fetchHistory(controller.signal),
    ])
  }, [fetchVehicle, fetchHistory])

  // Loading state
  if (isLoading) {
    return (
      <ModuleGate moduleSlug="vehicles" tradeFamily="automotive-transport">
        <Page data-testid="vehicle-profile-page">
          <KonstaNavbar title="Vehicle" showBack />
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  // Error state
  if (error || !vehicle) {
    return (
      <ModuleGate moduleSlug="vehicles" tradeFamily="automotive-transport">
        <Page data-testid="vehicle-profile-page">
          <KonstaNavbar title="Vehicle" showBack />
          <Block>
            <div
              className="rounded-lg bg-red-50 p-3 text-center text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              role="alert"
            >
              {error ?? 'Vehicle not found'}
              <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">
                Retry
              </button>
            </div>
          </Block>
        </Page>
      </ModuleGate>
    )
  }

  const makeModel = [vehicle.make, vehicle.model].filter(Boolean).join(' ')
  const yearColour = [vehicle.year ? String(vehicle.year) : null, vehicle.colour]
    .filter(Boolean)
    .join(' · ')

  const wofPill = expiryPill(vehicle.wof_expiry, 'WOF')
  const regoPill = expiryPill(vehicle.rego_expiry, 'Rego')

  return (
    <ModuleGate moduleSlug="vehicles" tradeFamily="automotive-transport">
      <Page data-testid="vehicle-profile-page">
        <KonstaNavbar
          title="Vehicle"
          showBack
          rightActions={
            <Button
              onClick={() => navigate(`/vehicles/${id}/edit`)}
              clear
              small
              className="text-primary"
            >
              Edit
            </Button>
          }
        />

        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col pb-24">
            {/* ── Hero Card ─────────────────────────────────────────── */}
            <Card className="mx-4 mt-2" data-testid="vehicle-hero">
              <p className="font-mono text-3xl font-bold text-gray-900 dark:text-gray-100">
                {vehicle.registration ?? 'No Rego'}
              </p>
              {makeModel && (
                <p className="mt-1 text-base text-gray-700 dark:text-gray-300">{makeModel}</p>
              )}
              {yearColour && (
                <p className="text-sm text-gray-500 dark:text-gray-400">{yearColour}</p>
              )}
            </Card>

            {/* ── Stats ─────────────────────────────────────────────── */}
            <div className="grid grid-cols-2 gap-3 px-4 pt-3">
              {/* WOF Expiry */}
              <Card className="text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">WOF Expiry</p>
                <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {formatDate(vehicle.wof_expiry)}
                </p>
                {wofPill && (
                  <Chip
                    className={`mt-1 ${wofPill.color} ${wofPill.bg} text-xs`}
                    colors={{
                      fillBgIos: wofPill.bg,
                      fillBgMaterial: wofPill.bg,
                      fillTextIos: wofPill.color,
                      fillTextMaterial: wofPill.color,
                    }}
                  >
                    {wofPill.text}
                  </Chip>
                )}
              </Card>

              {/* Rego Expiry */}
              <Card className="text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">Rego Expiry</p>
                <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {formatDate(vehicle.rego_expiry)}
                </p>
                {regoPill && (
                  <Chip
                    className={`mt-1 ${regoPill.color} ${regoPill.bg} text-xs`}
                    colors={{
                      fillBgIos: regoPill.bg,
                      fillBgMaterial: regoPill.bg,
                      fillTextIos: regoPill.color,
                      fillTextMaterial: regoPill.color,
                    }}
                  >
                    {regoPill.text}
                  </Chip>
                )}
              </Card>

              {/* Odometer */}
              <Card className="text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">Odometer</p>
                <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {vehicle.odometer != null
                    ? `${Number(vehicle.odometer).toLocaleString()} km`
                    : '—'}
                </p>
              </Card>

              {/* Service Due */}
              <Card className="text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">Service Due</p>
                <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {formatDate(vehicle.service_due_date)}
                </p>
              </Card>
            </div>

            {/* ── Service History ────────────────────────────────────── */}
            <BlockTitle>Service History</BlockTitle>
            {isLoadingHistory ? (
              <div className="flex justify-center py-4">
                <Preloader />
              </div>
            ) : serviceHistory.length === 0 ? (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">No service history</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos>
                {serviceHistory.map((entry) => (
                  <ListItem
                    key={entry.id}
                    title={entry.description ?? 'Service'}
                    subtitle={formatDate(entry.date)}
                    after={
                      entry.total != null ? (
                        <span className="text-sm font-semibold tabular-nums">
                          {formatNZD(entry.total)}
                        </span>
                      ) : undefined
                    }
                  />
                ))}
              </List>
            )}

            {/* ── Linked Customer ───────────────────────────────────── */}
            <BlockTitle>Linked Customer</BlockTitle>
            <List strongIos outlineIos>
              <ListItem
                link
                title={vehicle.owner_name ?? 'Unknown'}
                onClick={() => {
                  if (vehicle.owner_id) navigate(`/customers/${vehicle.owner_id}`)
                }}
              />
            </List>
          </div>
        </PullRefresh>
      </Page>
    </ModuleGate>
  )
}
