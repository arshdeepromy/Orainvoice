/**
 * JobCardDetail — Task 27 port of frontend/src/pages/job-cards/JobCardDetail.tsx.
 *
 * ALL logic copied VERBATIM: the fetch + response normalisation (items/
 * line_items, time_entries, active_timer), the live elapsed timer hook, status
 * transitions (open→in_progress→completed, auto-stopping the timer on complete),
 * timer start/stop, convert-to-invoice modal (→ /invoices/:id/edit), the
 * attachments section (upload hidden when locked, AttachmentList with lightbox),
 * the image lightbox, customer/vehicle/service-type/line-items/time-tracking/
 * notes/meta sections, and phone formatting with the org dial code. Presentation
 * remapped onto the design tokens (FR-2b); Badge `warning`→`warn`,
 * `error`→`danger`; `secondary`→`ghost`.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { useTenant } from '@/contexts/TenantContext'
import { getDialCodeForCountry, getCountryCodeFromName } from '@/components/ui/PhoneInput'
import AttachmentUploader from '@/components/attachments/AttachmentUploader'
import type { Attachment } from '@/components/attachments/AttachmentUploader'
import AttachmentList from '@/components/attachments/AttachmentList'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type JobCardStatus = 'open' | 'in_progress' | 'completed' | 'invoiced'

interface Customer {
  id: string
  first_name: string
  last_name: string
  email: string
  phone: string
  address?: string
}

interface JobCardItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  line_total: number
  item_type: string
  catalogue_item_id: string | null
}

interface TimeEntry {
  id: string
  started_at: string
  stopped_at: string | null
  duration_minutes: number | null
  user_name: string
}

interface JobCardDetailData {
  id: string
  job_card_number: string | null
  status: JobCardStatus
  customer: Customer | null
  vehicle_rego: string | null
  description: string
  notes: string
  assigned_to: string | null
  assigned_to_name: string | null
  items: JobCardItem[]
  time_entries: TimeEntry[]
  total_time_seconds: number
  active_timer: TimeEntry | null
  is_timer_active: boolean
  invoice_id: string | null
  service_type_id: string | null
  service_type_name: string | null
  service_type_values: ServiceTypeFieldValue[] | null
  created_at: string
  updated_at: string
}

interface ServiceTypeFieldValue {
  field_id: string
  label: string
  field_type: string
  value_text: string | null
  value_array: string[] | null
}

/** Attachment with uploader name from the list endpoint. */
interface AttachmentWithMeta extends Attachment {
  uploaded_by_name?: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(dateStr))
}

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return new Intl.DateTimeFormat('en-NZ', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(dateStr))
}

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const parts: string[] = []
  if (hours > 0) parts.push(`${hours}h`)
  if (minutes > 0 || hours > 0) parts.push(`${String(minutes).padStart(2, '0')}m`)
  parts.push(`${String(seconds).padStart(2, '0')}s`)
  return parts.join(' ')
}

const STATUS_CONFIG: Record<JobCardStatus, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Open', variant: 'info' },
  in_progress: { label: 'In Progress', variant: 'warn' },
  completed: { label: 'Completed', variant: 'success' },
  invoiced: { label: 'Invoiced', variant: 'neutral' },
}

function formatCurrency(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })
}

/**
 * Format a phone number with the org's country dial code.
 * If the phone already starts with '+', return as-is.
 */
function formatPhoneWithDialCode(phone: string, addressCountry: string | null): string {
  if (!phone) return ''
  // Already has a country code prefix
  if (phone.startsWith('+')) return phone
  const countryCode = addressCountry
    ? (addressCountry.length === 2 ? addressCountry.toUpperCase() : getCountryCodeFromName(addressCountry))
    : 'NZ'
  const dialCode = getDialCodeForCountry(countryCode)
  // Strip leading 0 (local format) before prepending dial code
  const cleaned = phone.startsWith('0') ? phone.slice(1) : phone
  return `${dialCode} ${cleaned}`
}

/** Valid status transitions: Open → In Progress → Completed → Invoiced */
const NEXT_STATUS: Partial<Record<JobCardStatus, { status: JobCardStatus; label: string }>> = {
  open: { status: 'in_progress', label: 'Start Work' },
  in_progress: { status: 'completed', label: 'Mark Complete' },
}

/* ------------------------------------------------------------------ */
/*  Timer display hook                                                 */
/* ------------------------------------------------------------------ */

function useElapsedTimer(activeTimer: TimeEntry | null): number {
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined)

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)

    if (activeTimer && !activeTimer.stopped_at) {
      const startTime = new Date(activeTimer.started_at).getTime()
      const tick = () => {
        setElapsed(Math.floor((Date.now() - startTime) / 1000))
      }
      tick()
      intervalRef.current = setInterval(tick, 1000)
    } else {
      setElapsed(0)
    }

    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [activeTimer])

  return elapsed
}

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const SECTION_TITLE = 'mono mb-2 text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function JobCardDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { tradeFamily, settings } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const [jobCard, setJobCard] = useState<JobCardDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /* Action states */
  const [transitioning, setTransitioning] = useState(false)
  const [timerLoading, setTimerLoading] = useState(false)
  const [converting, setConverting] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  /* Convert modal */
  const [convertModalOpen, setConvertModalOpen] = useState(false)

  /* Attachment state */
  const [attachments, setAttachments] = useState<AttachmentWithMeta[]>([])
  const [attachmentError, setAttachmentError] = useState('')

  /* Lightbox state */
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null)
  const [lightboxAlt, setLightboxAlt] = useState('')

  const closeLightbox = useCallback(() => {
    if (lightboxUrl) URL.revokeObjectURL(lightboxUrl)
    setLightboxUrl(null)
    setLightboxAlt('')
  }, [lightboxUrl])

  /* Timer elapsed display */
  const timerElapsed = useElapsedTimer(jobCard?.active_timer ?? null)

  /* ---- Fetch job card ---- */
  const fetchJobCard = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/job-cards/${id}`)
      const data = res.data as Record<string, unknown>

      // Normalise: backend returns `line_items` but component expects `items`
      const items = (data.items ?? data.line_items ?? []) as JobCardItem[]
      const time_entries = (data.time_entries ?? []) as TimeEntry[]
      const active_timer = (data.active_timer ?? null) as TimeEntry | null
      const total_time_seconds = (data.total_time_seconds ?? 0) as number

      setJobCard({
        ...data,
        items,
        time_entries,
        active_timer,
        total_time_seconds,
        job_card_number: (data.job_card_number ?? null) as string | null,
        invoice_id: (data.invoice_id ?? null) as string | null,
        assigned_to: (data.assigned_to ?? null) as string | null,
        assigned_to_name: (data.assigned_to_name ?? null) as string | null,
        is_timer_active: (data.is_timer_active ?? false) as boolean,
        vehicle_rego: (data.vehicle_rego ?? null) as string | null,
        service_type_id: (data.service_type_id ?? null) as string | null,
        service_type_name: (data.service_type_name ?? null) as string | null,
        service_type_values: (data.service_type_values ?? null) as ServiceTypeFieldValue[] | null,
      } as JobCardDetailData)
    } catch {
      setError('Failed to load job card. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchJobCard() }, [fetchJobCard])

  /* ---- Fetch attachments ---- */
  useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    const fetchAttachments = async () => {
      try {
        const res = await apiClient.get<{ attachments: AttachmentWithMeta[]; total: number }>(
          `/job-cards/${id}/attachments`,
          { signal: controller.signal },
        )
        setAttachments(res.data?.attachments ?? [])
      } catch {
        if (!controller.signal.aborted) {
          setAttachments([])
        }
      }
    }
    fetchAttachments()
    return () => controller.abort()
  }, [id])

  /* ---- Attachment handlers ---- */
  const handleUploadComplete = useCallback((attachment: Attachment) => {
    setAttachments((prev) => [...prev, attachment as AttachmentWithMeta])
    setAttachmentError('')
  }, [])

  const handleUploadError = useCallback((error: string) => {
    setAttachmentError(error)
  }, [])

  const handleDeleteAttachment = useCallback(
    async (attachmentId: string) => {
      if (!id) return
      try {
        await apiClient.delete(`/job-cards/${id}/attachments/${attachmentId}`)
        setAttachments((prev) => prev.filter((a) => a.id !== attachmentId))
      } catch {
        setAttachmentError('Failed to delete attachment. Please try again.')
      }
    },
    [id],
  )

  const handleAttachmentClick = useCallback(async (attachment: AttachmentWithMeta) => {
    if (attachment.mime_type?.startsWith('image/')) {
      // Fetch image via apiClient (with auth) and create blob URL for lightbox
      try {
        const res = await apiClient.get(
          `/job-cards/${attachment.job_card_id}/attachments/${attachment.id}`,
          { responseType: 'blob' },
        )
        const url = URL.createObjectURL(res.data as Blob)
        setLightboxUrl(url)
        setLightboxAlt(attachment.file_name ?? 'Image attachment')
      } catch {
        // Fallback
        setLightboxUrl(null)
      }
    } else {
      // PDFs and other files: fetch as blob and open in new tab
      try {
        const res = await apiClient.get(
          `/job-cards/${attachment.job_card_id}/attachments/${attachment.id}`,
          { responseType: 'blob' },
        )
        const url = URL.createObjectURL(res.data as Blob)
        window.open(url, '_blank', 'noopener,noreferrer')
        setTimeout(() => URL.revokeObjectURL(url), 10_000)
      } catch {
        // Silent fail
      }
    }
  }, [])

  /* ---- Status transition ---- */
  const handleStatusTransition = async (newStatus: JobCardStatus) => {
    if (!jobCard) return
    setTransitioning(true)
    setActionMessage('')
    try {
      // Auto-stop timer when marking complete
      if (newStatus === 'completed' && (jobCard.is_timer_active || (jobCard.active_timer && !jobCard.active_timer.stopped_at))) {
        try {
          await apiClient.post(`/job-cards/${jobCard.id}/timer/stop`)
        } catch { /* timer may already be stopped */ }
      }
      await apiClient.put(`/job-cards/${jobCard.id}`, { status: newStatus })
      fetchJobCard()
      setActionMessage(`Status updated to ${STATUS_CONFIG[newStatus].label}.`)
    } catch {
      setActionMessage('Failed to update status.')
      fetchJobCard()
    } finally {
      setTransitioning(false)
    }
  }

  /* ---- Timer start/stop ---- */
  const handleTimerStart = async () => {
    if (!jobCard) return
    setTimerLoading(true)
    setActionMessage('')
    try {
      await apiClient.post(`/job-cards/${jobCard.id}/timer/start`)
      fetchJobCard()
      setActionMessage('Timer started.')
    } catch {
      setActionMessage('Failed to start timer.')
    } finally {
      setTimerLoading(false)
    }
  }

  const handleTimerStop = async () => {
    if (!jobCard) return
    setTimerLoading(true)
    setActionMessage('')
    try {
      await apiClient.post(`/job-cards/${jobCard.id}/timer/stop`)
      fetchJobCard()
      setActionMessage('Timer stopped.')
    } catch {
      setActionMessage('Failed to stop timer.')
    } finally {
      setTimerLoading(false)
    }
  }

  /* ---- Convert to invoice ---- */
  const handleConvertToInvoice = async () => {
    if (!jobCard) return
    setConverting(true)
    setActionMessage('')
    try {
      const res = await apiClient.post(`/job-cards/${jobCard.id}/convert`)
      const data = res.data as { invoice_id: string }
      setConvertModalOpen(false)
      navigate(`/invoices/${data.invoice_id}/edit`)
    } catch {
      setActionMessage('Failed to convert to invoice.')
      setConvertModalOpen(false)
    } finally {
      setConverting(false)
    }
  }

  /* ---- Loading / Error states ---- */
  if (loading) {
    return <div className="py-16"><Spinner label="Loading job card" /></div>
  }

  if (error || !jobCard) {
    return (
      <div className="page page-wide">
        <div className="rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">
          {error || 'Job card not found.'}
        </div>
        <Button variant="ghost" className="mt-4" onClick={() => { window.location.href = '/job-cards' }}>
          ← Back to Job Cards
        </Button>
      </div>
    )
  }

  const statusCfg = STATUS_CONFIG[jobCard.status] ?? STATUS_CONFIG.open
  const nextTransition = NEXT_STATUS[jobCard.status]
  const canConvert = jobCard.status === 'completed'
  const isTimerActive = jobCard.is_timer_active || (!!jobCard.active_timer && !jobCard.active_timer.stopped_at)
  const canTimer = jobCard.status === 'open' || jobCard.status === 'in_progress'
  /** Job card is locked from modifications when completed or invoiced. */
  const isLocked = jobCard.status === 'completed' || jobCard.status === 'invoiced'
  const totalTimeDisplay = (jobCard.total_time_seconds ?? 0) + (isTimerActive ? timerElapsed : 0)
  const items = jobCard.items ?? []
  const timeEntries = jobCard.time_entries ?? []

  return (
    <div className="page page-wide">
      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => { window.location.href = '/job-cards' }}
            className="rounded p-1 text-muted-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Back to job cards">←</button>
          <h1 className="text-[22px] font-semibold text-text">
            {jobCard.job_card_number || 'Job Card'}
          </h1>
          <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {nextTransition && (
            <Button size="sm" variant="primary" onClick={() => handleStatusTransition(nextTransition.status)} loading={transitioning}>
              {nextTransition.label}
            </Button>
          )}
          {canConvert && (
            <Button size="sm" variant="primary" onClick={() => setConvertModalOpen(true)}>
              Convert to Invoice
            </Button>
          )}
          {jobCard.invoice_id && (
            <Button size="sm" variant="ghost" onClick={() => { window.location.href = `/invoices/${jobCard.invoice_id}` }}>
              View Invoice
            </Button>
          )}
        </div>
      </div>

      {/* Action feedback */}
      {actionMessage && (
        <div className="mb-4 rounded-ctl border border-border bg-canvas px-4 py-2 text-[13px] text-muted" role="status">
          {actionMessage}
        </div>
      )}

      {/* Customer & Vehicle */}
      <div className="mb-6 grid grid-cols-1 gap-6 sm:grid-cols-2">
        <section className="rounded-card border border-border p-4">
          <h2 className={SECTION_TITLE}>Customer</h2>
          {jobCard.customer ? (
            <>
              <p className="font-medium text-text">
                {jobCard.customer.first_name} {jobCard.customer.last_name}
              </p>
              {jobCard.customer.email && <p className="text-[13px] text-muted">{jobCard.customer.email}</p>}
              {jobCard.customer.phone && (
                <p className="mono text-[13px] text-muted">
                  {formatPhoneWithDialCode(jobCard.customer.phone, settings?.addressCountry ?? null)}
                </p>
              )}
              {jobCard.customer.address && <p className="mt-1 text-[13px] text-muted">{jobCard.customer.address}</p>}
            </>
          ) : (
            <p className="text-[13px] text-muted">Customer details not available</p>
          )}
        </section>

        {isAutomotive && (
        <section className="rounded-card border border-border p-4">
          <h2 className={SECTION_TITLE}>Vehicle</h2>
          {jobCard.vehicle_rego ? (
            <p className="mono font-medium text-text">{jobCard.vehicle_rego}</p>
          ) : (
            <p className="text-[13px] text-muted">No vehicle linked</p>
          )}
        </section>
        )}
      </div>

      {/* Service Type (shown when present, regardless of trade family — historical data) */}
      {jobCard.service_type_name && (
        <section className="mb-6">
          <h2 className={SECTION_TITLE}>Service Type</h2>
          <div className="rounded-card border border-border p-4">
            <p className="font-medium text-text">{jobCard.service_type_name}</p>
            {(jobCard.service_type_values ?? []).length > 0 && (
              <dl className="mt-3 space-y-2">
                {(jobCard.service_type_values ?? []).map((fv) => (
                  <div key={fv.field_id} className="flex flex-col sm:flex-row sm:gap-2">
                    <dt className="shrink-0 text-[13px] font-medium text-muted sm:w-40">
                      {fv.label ?? 'Field'}
                    </dt>
                    <dd className="text-[13px] text-text">
                      {fv.field_type === 'multi_select' && fv.value_array
                        ? (fv.value_array ?? []).join(', ') || '—'
                        : fv.value_text ?? '—'}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </section>
      )}

      {/* Assigned To */}
      <section className="mb-6">
        <h2 className={SECTION_TITLE}>Assigned To</h2>
        <p className="text-[13.5px] text-text">{jobCard.assigned_to_name ?? 'Unassigned'}</p>
      </section>

      {/* Description */}
      {jobCard.description && (
        <section className="mb-6">
          <h2 className={SECTION_TITLE}>Description</h2>
          <div className="whitespace-pre-wrap rounded-card border border-border bg-canvas p-4 text-[13.5px] text-muted">
            {jobCard.description}
          </div>
        </section>
      )}

      {/* Line Items */}
      <section className="mb-6">
        <h2 className={SECTION_TITLE}>Line Items</h2>
        {items.length === 0 ? (
          <p className="text-[13px] text-muted">No line items listed.</p>
        ) : (
          <div className="overflow-hidden rounded-card border border-border">
            <table className="w-full border-collapse">
              <caption className="sr-only">Job card line items</caption>
              <thead>
                <tr>
                  <th scope="col" className={`${TH} w-10`}>#</th>
                  <th scope="col" className={TH}>Description</th>
                  <th scope="col" className={`${TH} w-20 text-right`}>Qty</th>
                  <th scope="col" className={`${TH} w-28 text-right`}>Unit Price</th>
                  <th scope="col" className={`${TH} w-28 text-right`}>Total</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => (
                  <tr key={item.id} className="border-b border-border last:border-b-0">
                    <td className="whitespace-nowrap px-4 py-3 text-[13px] text-muted">{index + 1}</td>
                    <td className="px-4 py-3 text-[13.5px] text-text">{item.description}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-text">{item.quantity ?? 0}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-text">${formatCurrency(item.unit_price)}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] text-text">${formatCurrency(item.line_total)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-canvas">
                  <td colSpan={3} />
                  <td className="whitespace-nowrap px-4 py-3 text-right text-[13.5px] font-semibold text-text">Subtotal</td>
                  <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13.5px] font-semibold text-text">
                    ${formatCurrency(items.reduce((sum, item) => sum + (item.line_total ?? 0), 0))}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      {/* Time Tracking */}
      <section className="mb-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className={`${SECTION_TITLE} mb-0`}>Time Tracking</h2>
          <div className="flex items-center gap-3">
            {/* Total time */}
            <span className="text-[13px] font-medium text-muted">
              Total: <span className="mono text-text">{formatDuration(totalTimeDisplay)}</span>
            </span>

            {/* Timer controls */}
            {canTimer && (
              isTimerActive ? (
                <div className="flex items-center gap-2">
                  <span className="mono inline-flex items-center gap-1.5 text-[13px] font-medium text-danger">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-danger" aria-hidden="true" />
                    {formatDuration(timerElapsed)}
                  </span>
                  <Button size="sm" variant="danger" onClick={handleTimerStop} loading={timerLoading}>
                    Stop Timer
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="primary" onClick={handleTimerStart} loading={timerLoading}>
                  Start Timer
                </Button>
              )
            )}
          </div>
        </div>

        {timeEntries.length === 0 && !isTimerActive ? (
          <p className="text-[13px] text-muted">No time entries recorded.</p>
        ) : (
          <div className="overflow-hidden rounded-card border border-border">
            <table className="w-full border-collapse">
              <caption className="sr-only">Time entries</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Started</th>
                  <th scope="col" className={TH}>Stopped</th>
                  <th scope="col" className={`${TH} text-right`}>Duration</th>
                  <th scope="col" className={TH}>User</th>
                </tr>
              </thead>
              <tbody>
                {timeEntries.map((entry) => (
                  <tr key={entry.id} className={`border-b border-border last:border-b-0 ${!entry.stopped_at ? 'bg-danger-soft' : ''}`}>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13px] text-text">{formatDateTime(entry.started_at)}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13px] text-text">
                      {entry.stopped_at ? formatDateTime(entry.stopped_at) : (
                        <span className="inline-flex items-center gap-1 font-medium text-danger">
                          <span className="h-2 w-2 animate-pulse rounded-full bg-danger" aria-hidden="true" />
                          Running
                        </span>
                      )}
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-right text-[13px] text-text">
                      {entry.duration_minutes != null ? formatDuration(entry.duration_minutes * 60) : formatDuration(timerElapsed)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{entry.user_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Notes */}
      {jobCard.notes && (
        <section className="mb-6">
          <h2 className={SECTION_TITLE}>Notes</h2>
          <div className="whitespace-pre-wrap rounded-card border border-border bg-canvas p-4 text-[13.5px] text-muted">
            {jobCard.notes}
          </div>
        </section>
      )}

      {/* Attachments */}
      <section className="mb-6" aria-labelledby="section-attachments">
        <h2 id="section-attachments" className={SECTION_TITLE}>Attachments</h2>

        {/* Upload new attachments — hidden when job card is locked */}
        {!isLocked && (
          <div className="mb-3">
            <AttachmentUploader
              jobCardId={jobCard.id}
              onUploadComplete={handleUploadComplete}
              onError={handleUploadError}
            />
          </div>
        )}

        {attachmentError && (
          <p className="mb-3 text-[13px] text-danger" role="alert">{attachmentError}</p>
        )}

        {/* Attachment list — read-only when locked (no delete buttons) */}
        <AttachmentList
          attachments={attachments}
          onDelete={isLocked ? undefined : handleDeleteAttachment}
          onImageClick={handleAttachmentClick}
          readOnly={isLocked}
        />
        {attachments.length === 0 && (
          <p className="text-[13px] text-muted">No attachments.</p>
        )}
      </section>

      {/* Meta */}
      <section className="mb-6">
        <h2 className={SECTION_TITLE}>Details</h2>
        <dl className="space-y-1 text-[13px]">
          <div className="flex gap-2">
            <dt className="w-24 text-muted">Created:</dt>
            <dd className="mono text-text">{formatDate(jobCard.created_at)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-24 text-muted">Updated:</dt>
            <dd className="mono text-text">{formatDate(jobCard.updated_at)}</dd>
          </div>
        </dl>
      </section>

      {/* Convert to Invoice Modal */}
      <Modal open={convertModalOpen} onClose={() => setConvertModalOpen(false)} title="Convert to Invoice">
        <p className="mb-4 text-[13.5px] text-muted">
          This will create a new Draft invoice pre-filled with the job card's work items.
          The job card status will be updated to Invoiced.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setConvertModalOpen(false)}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={handleConvertToInvoice} loading={converting}>
            Create Invoice
          </Button>
        </div>
      </Modal>

      {/* Image Lightbox Modal */}
      {lightboxUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/70 backdrop-blur-sm"
          role="dialog"
          aria-label="Image preview"
          onClick={closeLightbox}
          onKeyDown={(e) => { if (e.key === 'Escape') closeLightbox() }}
        >
          <button
            type="button"
            className="absolute right-4 top-4 z-10 rounded-full bg-ink/50 p-2 text-white transition-colors hover:bg-ink/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            onClick={(e) => { e.stopPropagation(); closeLightbox() }}
            aria-label="Close image preview"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
          <img
            src={lightboxUrl}
            alt={lightboxAlt}
            className="max-h-[85vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  )
}
