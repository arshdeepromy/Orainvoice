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
import type { Quote, QuoteLineItem } from '@shared/types/quote'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import HapticButton from '@/components/konsta/HapticButton'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { buildPortalUrl, canSharePortalLink } from '@/utils/portalLink'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface QuoteData extends Quote {
  attachment_count?: number
  attachments?: Array<{
    id?: string
    filename?: string
    url?: string
    thumbnail_url?: string
    mime_type?: string
    size_bytes?: number
    created_at?: string
  }> | null
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

export function pickFileFromInput(): Promise<File> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/jpeg,image/png,image/webp,image/gif,application/pdf'
    input.setAttribute('capture', 'environment')
    input.onchange = () => {
      const file = input.files?.[0]
      if (file) resolve(file)
      else reject(new Error('No file selected'))
    }
    input.onerror = () => reject(new Error('Input error'))
    input.click()
  })
}

export function isCameraCancelled(err: unknown): boolean {
  const msg = String((err as { message?: string })?.message ?? err ?? '')
  return msg.includes('cancelled') || msg.includes('canceled') || msg.includes('User cancelled')
}

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

/* ------------------------------------------------------------------ */
/* Exported helpers for testing                                       */
/* ------------------------------------------------------------------ */

export async function sendQuote(quoteId: string): Promise<boolean> {
  try {
    await apiClient.post(`/api/v1/quotes/${quoteId}/send`)
    return true
  } catch {
    return false
  }
}

/**
 * Convert a quote to an invoice by POSTing to the backend.
 * Returns the new invoice ID on success, or null on failure.
 */
export async function convertQuoteToInvoice(quoteId: string): Promise<string | null> {
  try {
    const res = await apiClient.post<{ id?: string }>(`/api/v1/quotes/${quoteId}/convert`)
    return res.data?.id ?? null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Quote detail screen — hero card with customer, total, status,
 * line items list, bottom action sheet.
 *
 * Requirements: 24.3, 24.4, 24.5
 */
export default function QuoteDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [quote, setQuote] = useState<QuoteData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [showActions, setShowActions] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [isConverting, setIsConverting] = useState(false)
  const [toast, setToast] = useState<{ message: string; variant: 'success' | 'error' } | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const fetchQuote = useCallback(
    async (signal: AbortSignal, refresh = false) => {
      if (refresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const res = await apiClient.get<QuoteData>(`/api/v1/quotes/${id}`, { signal })
        setQuote(res.data ?? null)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load quote')
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
    fetchQuote(controller.signal)
    return () => controller.abort()
  }, [fetchQuote])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchQuote(controller.signal, true)
  }, [fetchQuote])

  const handleSend = useCallback(async () => {
    if (!id) return
    setIsSending(true)
    const ok = await sendQuote(id)
    setIsSending(false)
    if (ok) {
      setToast({ message: 'Quote sent', variant: 'success' })
      await handleRefresh()
    } else {
      setToast({ message: 'Failed to send quote', variant: 'error' })
    }
    setShowActions(false)
  }, [id, handleRefresh])

  const handleConvertToInvoice = useCallback(async () => {
    if (!id) return
    setIsConverting(true)
    const invoiceId = await convertQuoteToInvoice(id)
    setIsConverting(false)
    if (invoiceId) {
      navigate(`/invoices/${invoiceId}`, { replace: true })
    } else {
      setToast({ message: 'Failed to convert quote to invoice', variant: 'error' })
    }
    setShowActions(false)
  }, [id, navigate])

  const handlePreviewPDF = useCallback(() => {
    navigate(`/quotes/${id}/pdf`)
    setShowActions(false)
  }, [id, navigate])

  const handlePrint = useCallback(() => {
    window.print()
    setShowActions(false)
  }, [])

  const handleTakePhoto = useCallback(async () => {
    const isNative = !!(window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } })
      .Capacitor?.isNativePlatform?.()

    try {
      let file: Blob
      let filename = 'photo.jpg'

      if (isNative) {
        const { Camera, CameraResultType } = await import('@capacitor/camera')
        const photo = await Camera.getPhoto({
          resultType: CameraResultType.Uri,
          quality: 80,
        })
        if (!photo.webPath) return
        file = await fetch(photo.webPath).then((r) => r.blob())
      } else {
        const picked = await pickFileFromInput()
        file = picked
        filename = picked.name || 'photo.jpg'
      }

      // Client-side validation
      if (file.size > 20 * 1024 * 1024) {
        setToast({ message: 'File exceeds 20 MB', variant: 'error' })
        return
      }
      const ALLOWED_MIMES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf']
      const mimeType = (file as File).type || 'image/jpeg'
      if (!ALLOWED_MIMES.includes(mimeType)) {
        setToast({ message: 'Only JPEG, PNG, WebP, GIF, and PDF files are allowed', variant: 'error' })
        return
      }
      if ((quote?.attachment_count ?? 0) >= 5) {
        setToast({ message: 'This quote already has the maximum 5 attachments', variant: 'error' })
        return
      }

      const formData = new FormData()
      formData.append('file', file, filename)
      await apiClient.post(`/api/v1/quotes/${id}/attachments`, formData)
      await handleRefresh()
      setToast({ message: 'Attachment uploaded', variant: 'success' })
    } catch (err: unknown) {
      if (isCameraCancelled(err)) return
      const status = (err as { response?: { status?: number } }).response?.status
      if (status === 413) setToast({ message: 'File exceeds 20 MB', variant: 'error' })
      else if (status === 400) setToast({ message: 'File rejected — please try another', variant: 'error' })
      else if (status === 507) setToast({ message: 'Storage quota exceeded for this organisation', variant: 'error' })
      else setToast({ message: 'Upload failed — please retry', variant: 'error' })
    }
  }, [id, quote?.attachment_count, handleRefresh])

  const handleDeleteAttachment = useCallback(
    async (attachmentId: string) => {
      if (!quote || quote.status !== 'draft') return
      try {
        await apiClient.delete(`/api/v1/quotes/${id}/attachments/${attachmentId}`)
        await handleRefresh()
        setToast({ message: 'Attachment removed', variant: 'success' })
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } }).response?.status
        if (status === 403) {
          setToast({ message: 'Attachments can only be removed while the quote is a draft', variant: 'error' })
        } else {
          setToast({ message: 'Delete failed — please retry', variant: 'error' })
        }
      }
    },
    [id, quote, handleRefresh],
  )

  // Loading state
  if (isLoading) {
    return (
      <ModuleGate moduleSlug="quotes">
        <Page data-testid="quote-detail-page">
          <KonstaNavbar title="Quote" showBack />
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  // Error state
  if (error || !quote) {
    return (
      <ModuleGate moduleSlug="quotes">
        <Page data-testid="quote-detail-page">
          <KonstaNavbar title="Quote" showBack />
          <Block>
            <div
              className="rounded-lg bg-red-50 p-3 text-center text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              role="alert"
            >
              {error ?? 'Quote not found'}
              <button
                type="button"
                onClick={() => handleRefresh()}
                className="ml-2 font-medium underline"
              >
                Retry
              </button>
            </div>
          </Block>
        </Page>
      </ModuleGate>
    )
  }

  const status = quote.status ?? 'draft'
  const lineItems: QuoteLineItem[] = quote.line_items ?? []

  return (
    <ModuleGate moduleSlug="quotes">
      <Page data-testid="quote-detail-page">
        <KonstaNavbar
          title={quote.quote_number ?? 'Quote'}
          showBack
          rightActions={
            <Button
              onClick={() => setShowActions(!showActions)}
              clear
              small
              className="text-gray-500"
            >
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
                  <button
                    type="button"
                    className="ml-2 text-xs underline"
                    onClick={() => setToast(null)}
                  >
                    Dismiss
                  </button>
                </div>
              </Block>
            )}

            {/* ── Hero Card ─────────────────────────────────────────── */}
            <Card className="mx-4 mt-2" data-testid="quote-hero-card">
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
                    {quote.customer_name ?? 'Unknown Customer'}
                  </p>
                  <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
                    {quote.quote_number}
                  </p>
                </div>
                <StatusBadge status={status} size="md" />
              </div>
              <div className="mt-3 flex items-end justify-between border-t border-gray-100 pt-3 dark:border-gray-700">
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Total</p>
                  <p className="text-2xl font-bold tabular-nums text-gray-900 dark:text-gray-100">
                    {formatNZD(quote.total)}
                  </p>
                </div>
                <div className="text-right text-xs text-gray-500 dark:text-gray-400">
                  <p>Created {formatDate(quote.created_at)}</p>
                  {quote.valid_until && <p>Valid until {formatDate(quote.valid_until)}</p>}
                </div>
              </div>
              <HapticButton
                large
                outline
                data-testid="preview-pdf-button"
                onClick={handlePreviewPDF}
                className="mt-3 min-h-[44px] w-full"
              >
                Preview PDF
              </HapticButton>
            </Card>

            {/* ── Line Items ────────────────────────────────────────── */}
            <BlockTitle>Line Items</BlockTitle>
            {lineItems.length === 0 ? (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">No line items</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="quote-line-items">
                {lineItems.map((item) => {
                  const qty = item.quantity ?? 0
                  const price = item.unit_price ?? 0
                  const amount = item.amount ?? qty * price

                  return (
                    <ListItem
                      key={item.id}
                      title={
                        <span className="font-medium text-gray-900 dark:text-gray-100">
                          {item.description || 'Unnamed item'}
                        </span>
                      }
                      subtitle={
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {qty} × {formatNZD(price)}
                          {item.tax_rate > 0 && ` · ${Number(item.tax_rate * 100).toFixed(0)}% tax`}
                        </span>
                      }
                      after={
                        <span className="text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                          {formatNZD(amount)}
                        </span>
                      }
                    />
                  )
                })}
              </List>
            )}

            {/* ── Totals ────────────────────────────────────────────── */}
            <Card className="mx-4">
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Subtotal</span>
                  <span className="text-gray-900 dark:text-gray-100">
                    {formatNZD(quote.subtotal)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Tax</span>
                  <span className="text-gray-900 dark:text-gray-100">
                    {formatNZD(quote.tax_amount)}
                  </span>
                </div>
                {(quote.discount_amount ?? 0) > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Discount</span>
                    <span className="text-red-600 dark:text-red-400">
                      -{formatNZD(quote.discount_amount)}
                    </span>
                  </div>
                )}
                <div className="flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
                  <span className="font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(quote.total)}
                  </span>
                </div>
              </div>
            </Card>

            {/* ── Attachments ─────────────────────────────────────── */}
            <BlockTitle>Attachments</BlockTitle>
            {(quote.attachment_count ?? 0) > 0 ? (
              <div className="flex gap-2 overflow-x-auto px-4">
                {(quote.attachments ?? []).map((att, idx) => {
                  const canDelete = quote.status === 'draft'
                  return (
                    <div key={att.id ?? idx} className="relative shrink-0">
                      <a
                        href={`/api/v1/quotes/${id}/attachments/${att.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block h-24 w-24 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700"
                      >
                        {att.mime_type?.startsWith('image/') ? (
                          <img
                            src={att.thumbnail_url ?? att.url ?? ''}
                            alt={att.filename ?? 'Attachment'}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center bg-gray-50 dark:bg-gray-800">
                            <svg className="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                            </svg>
                          </div>
                        )}
                      </a>
                      {canDelete && (
                        <button
                          type="button"
                          aria-label={`Delete ${att.filename ?? 'attachment'}`}
                          onClick={() => {
                            if (window.confirm(`Delete ${att.filename ?? 'this attachment'}?`)) {
                              handleDeleteAttachment(att.id!)
                            }
                          }}
                          className="absolute -right-1 -top-1 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-red-600 text-white shadow sm:min-h-[24px] sm:min-w-[24px]"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">No attachments</p>
              </Block>
            )}
            <Block>
              <HapticButton
                large
                outline
                onClick={handleTakePhoto}
                data-testid="take-photo-button"
                className="min-h-[44px] w-full"
              >
                Take Photo
              </HapticButton>
            </Block>

            {/* ── Action Buttons ─────────────────────────────────────── */}
            {showActions && (
              <Block data-testid="action-sheet">
                <div className="flex flex-col gap-2">
                  {canSharePortalLink(quote.customer_portal_token, quote.customer_enable_portal) && (
                    <Button
                      outline
                      large
                      onClick={async () => {
                        const portalUrl = buildPortalUrl(window.location.origin, quote.customer_portal_token)
                        if (!portalUrl) return
                        try {
                          const { Share } = await import('@capacitor/share')
                          await Share.share({
                            title: `Quote ${quote.quote_number ?? ''}`,
                            text: `View quote ${quote.quote_number ?? ''} from ${quote.customer_name ?? 'us'}`,
                            url: portalUrl,
                          })
                        } catch {
                          try {
                            await navigator.clipboard.writeText(portalUrl)
                            setToast({ message: 'Link copied', variant: 'success' })
                          } catch {
                            // Ignore clipboard errors
                          }
                        }
                        setShowActions(false)
                      }}
                      className="w-full"
                    >
                      Share Portal Link
                    </Button>
                  )}
                  <Button
                    outline
                    large
                    data-testid="download-pdf-action"
                    onClick={handlePreviewPDF}
                    className="w-full"
                  >
                    Download PDF
                  </Button>
                  <Button
                    outline
                    large
                    data-testid="print-action"
                    onClick={handlePrint}
                    className="w-full"
                  >
                    Print
                  </Button>
                  <Button
                    outline
                    large
                    onClick={async () => {
                      try {
                        await apiClient.post(`/api/v1/quotes/${id}/duplicate`)
                        setToast({ message: 'Quote duplicated', variant: 'success' })
                        await handleRefresh()
                      } catch {
                        setToast({ message: 'Failed to duplicate', variant: 'error' })
                      }
                      setShowActions(false)
                    }}
                    className="w-full"
                  >
                    Duplicate
                  </Button>
                  {status === 'draft' && (
                    <HapticButton
                      large
                      onClick={handleSend}
                      disabled={isSending}
                      className="w-full"
                    >
                      {isSending ? 'Sending…' : 'Send Quote'}
                    </HapticButton>
                  )}
                  {(status === 'sent' || status === 'accepted') && (
                    <HapticButton
                      large
                      onClick={handleConvertToInvoice}
                      disabled={isConverting}
                      colors={{
                        fillBgIos: 'bg-green-600',
                        fillBgMaterial: 'bg-green-600',
                        fillTextIos: 'text-white',
                        fillTextMaterial: 'text-white',
                      }}
                      className="w-full"
                    >
                      {isConverting ? 'Converting…' : 'Convert to Invoice'}
                    </HapticButton>
                  )}
                  <Button
                    outline
                    large
                    onClick={() => navigate(`/quotes/${id}/edit`)}
                    className="w-full"
                  >
                    Edit
                  </Button>
                </div>
              </Block>
            )}
          </div>
        </PullRefresh>
      </Page>
    </ModuleGate>
  )
}
