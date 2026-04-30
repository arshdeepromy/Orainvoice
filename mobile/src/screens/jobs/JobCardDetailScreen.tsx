import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  Card,
  List,
  ListItem,
  Button,
  Preloader,
} from 'konsta/react'
import type { JobCard, JobStatus } from '@shared/types/job'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import HapticButton from '@/components/konsta/HapticButton'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { useCamera } from '@/hooks/useCamera'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return ''
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

const statusLabels: Record<JobStatus, string> = {
  pending: 'Open',
  in_progress: 'In Progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

/* ------------------------------------------------------------------ */
/* Types for extended job card detail                                  */
/* ------------------------------------------------------------------ */

interface PartItem {
  id: string
  name: string
  quantity: number
  unit_price: number
}

interface LabourItem {
  id: string
  description: string
  hours: number
  rate: number
}

interface Attachment {
  id: string
  filename: string
  url: string
}

interface StatusHistoryEntry {
  id: string
  status: string
  changed_at: string
  changed_by: string
}

interface JobCardDetail extends JobCard {
  assigned_staff_id?: string | null
  assigned_staff_name?: string | null
  parts?: PartItem[]
  labour_entries?: LabourItem[]
  attachments?: Attachment[]
  status_history?: StatusHistoryEntry[]
  notes?: string | null
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Job card detail screen — hero section with customer, vehicle, status,
 * assigned staff. Sections: Parts, Labour, Notes, Attachments, Status History.
 * Bottom actions: Edit, Add Parts, Add Labour, Upload Attachment, Complete Job, Reassign.
 *
 * Requirements: 27.1, 27.2, 27.3, 27.4
 */
export default function JobCardDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { takePhoto } = useCamera()

  const [card, setCard] = useState<JobCardDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [showActions, setShowActions] = useState(false)
  const [isCompleting, setIsCompleting] = useState(false)
  const [toast, setToast] = useState<{ message: string; variant: 'success' | 'error' } | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchCard = useCallback(
    async (signal: AbortSignal, refresh = false) => {
      if (refresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<JobCardDetail>(`/api/v1/job-cards/${id}`, { signal })
        setCard(res.data ?? null)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load job card')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [id],
  )

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchCard(controller.signal)
    return () => controller.abort()
  }, [fetchCard])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchCard(controller.signal, true)
  }, [fetchCard])

  const handleComplete = useCallback(async () => {
    if (!id) return
    setIsCompleting(true)
    try {
      await apiClient.post(`/api/v1/job-cards/${id}/complete`)
      setToast({ message: 'Job completed — invoice created', variant: 'success' })
      await handleRefresh()
    } catch {
      setToast({ message: 'Failed to complete job', variant: 'error' })
    } finally {
      setIsCompleting(false)
      setShowActions(false)
    }
  }, [id, handleRefresh])

  const handleUploadAttachment = useCallback(async () => {
    if (!id) return
    const photo = await takePhoto()
    if (!photo) return

    try {
      const blob = await fetch(photo.dataUrl).then((r) => r.blob())
      const formData = new FormData()
      formData.append('file', blob, `photo-${Date.now()}.jpg`)
      await apiClient.post(`/api/v1/job-cards/${id}/attachments`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setToast({ message: 'Attachment uploaded', variant: 'success' })
      await handleRefresh()
    } catch {
      setToast({ message: 'Failed to upload attachment', variant: 'error' })
    }
  }, [id, takePhoto, handleRefresh])

  // Loading state
  if (isLoading) {
    return (
      <ModuleGate moduleSlug="jobs">
        <Page data-testid="job-card-detail-page">
          <KonstaNavbar title="Job Card" showBack />
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  // Error state
  if (error || !card) {
    return (
      <ModuleGate moduleSlug="jobs">
        <Page data-testid="job-card-detail-page">
          <KonstaNavbar title="Job Card" showBack />
          <Block>
            <div
              className="rounded-lg bg-red-50 p-3 text-center text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              role="alert"
            >
              {error ?? 'Job card not found'}
              <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">
                Retry
              </button>
            </div>
          </Block>
        </Page>
      </ModuleGate>
    )
  }

  const status = card.status ?? 'pending'
  const parts = card.parts ?? []
  const labourEntries = card.labour_entries ?? []
  const attachments = card.attachments ?? []
  const statusHistory = card.status_history ?? []

  return (
    <ModuleGate moduleSlug="jobs">
      <Page data-testid="job-card-detail-page">
        <KonstaNavbar
          title={card.job_card_number ?? 'Job Card'}
          showBack
          rightActions={
            <Button onClick={() => setShowActions(!showActions)} clear small className="text-gray-500">
              •••
            </Button>
          }
        />

        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col pb-24">
            {/* Toast */}
            {toast && (
              <Block>
                <div
                  className={`rounded-lg p-3 text-sm ${
                    toast.variant === 'success'
                      ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                      : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                  }`}
                  role="alert"
                >
                  {toast.message}
                  <button type="button" className="ml-2 text-xs underline" onClick={() => setToast(null)}>
                    Dismiss
                  </button>
                </div>
              </Block>
            )}

            {/* ── Hero Card ─────────────────────────────────────────── */}
            <Card className="mx-4 mt-2" data-testid="job-card-hero">
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
                    {card.customer_name ?? 'Unknown Customer'}
                  </p>
                  {card.vehicle_registration && (
                    <p className="mt-0.5 font-mono text-sm text-gray-500 dark:text-gray-400">
                      {card.vehicle_registration}
                    </p>
                  )}
                </div>
                <StatusBadge status={status} size="md" />
              </div>
              {card.assigned_staff_name && (
                <div className="mt-2 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                    {card.assigned_staff_name.charAt(0).toUpperCase()}
                  </span>
                  <span>{card.assigned_staff_name}</span>
                </div>
              )}
              <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
                Created {formatDate(card.created_at)}
              </p>
            </Card>

            {/* ── Description ───────────────────────────────────────── */}
            {card.description && (
              <>
                <BlockTitle>Description</BlockTitle>
                <Block>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{card.description}</p>
                </Block>
              </>
            )}

            {/* ── Parts ─────────────────────────────────────────────── */}
            <BlockTitle>Parts ({parts.length})</BlockTitle>
            {parts.length === 0 ? (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">No parts added</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos>
                {parts.map((part) => (
                  <ListItem
                    key={part.id}
                    title={part.name}
                    subtitle={`Qty: ${part.quantity}`}
                    after={
                      <span className="text-sm font-semibold tabular-nums">
                        {formatNZD(part.quantity * part.unit_price)}
                      </span>
                    }
                  />
                ))}
              </List>
            )}

            {/* ── Labour ────────────────────────────────────────────── */}
            <BlockTitle>Labour ({labourEntries.length})</BlockTitle>
            {labourEntries.length === 0 ? (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">No labour entries</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos>
                {labourEntries.map((entry) => (
                  <ListItem
                    key={entry.id}
                    title={entry.description}
                    subtitle={`${entry.hours}h @ ${formatNZD(entry.rate)}/hr`}
                    after={
                      <span className="text-sm font-semibold tabular-nums">
                        {formatNZD(entry.hours * entry.rate)}
                      </span>
                    }
                  />
                ))}
              </List>
            )}

            {/* ── Notes ─────────────────────────────────────────────── */}
            {card.notes && (
              <>
                <BlockTitle>Notes</BlockTitle>
                <Block>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{card.notes}</p>
                </Block>
              </>
            )}

            {/* ── Attachments ───────────────────────────────────────── */}
            <BlockTitle>Attachments ({attachments.length})</BlockTitle>
            {attachments.length === 0 ? (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">No attachments</p>
              </Block>
            ) : (
              <div className="flex gap-2 overflow-x-auto px-4 pb-2">
                {attachments.map((att) => (
                  <div
                    key={att.id}
                    className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-gray-100 dark:bg-gray-700"
                  >
                    <span className="text-[10px] text-gray-500">{att.filename?.split('.').pop()?.toUpperCase()}</span>
                  </div>
                ))}
              </div>
            )}

            {/* ── Status History ─────────────────────────────────────── */}
            {statusHistory.length > 0 && (
              <>
                <BlockTitle>Status History</BlockTitle>
                <List strongIos outlineIos dividersIos>
                  {statusHistory.map((entry) => (
                    <ListItem
                      key={entry.id}
                      title={statusLabels[entry.status as JobStatus] ?? entry.status}
                      subtitle={`${formatDate(entry.changed_at)} by ${entry.changed_by}`}
                    />
                  ))}
                </List>
              </>
            )}

            {/* ── Action Buttons ─────────────────────────────────────── */}
            {showActions && (
              <Block>
                <div className="flex flex-col gap-2">
                  <Button outline large onClick={() => navigate(`/job-cards/${id}/edit`)} className="w-full">
                    Edit
                  </Button>
                  <Button outline large onClick={handleUploadAttachment} className="w-full">
                    📷 Upload Attachment
                  </Button>
                  {status !== 'completed' && status !== 'cancelled' && (
                    <HapticButton
                      large
                      hapticStyle="medium"
                      onClick={handleComplete}
                      disabled={isCompleting}
                      colors={{
                        fillBgIos: 'bg-green-600',
                        fillBgMaterial: 'bg-green-600',
                        fillTextIos: 'text-white',
                        fillTextMaterial: 'text-white',
                      }}
                      className="w-full"
                    >
                      {isCompleting ? 'Completing…' : 'Complete Job'}
                    </HapticButton>
                  )}
                </div>
              </Block>
            )}
          </div>
        </PullRefresh>
      </Page>
    </ModuleGate>
  )
}
