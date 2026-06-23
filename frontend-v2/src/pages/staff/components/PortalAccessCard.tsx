// ---------------------------------------------------------------------------
// PortalAccessCard — staff-detail "Employee Portal" access lifecycle card.
//
// Mirrors OnboardingLinkCard: on mount fetches GET /staff/{id}/portal-access
// and renders the state (none / invited / active) with Send invite / Resend /
// Revoke actions. The Employee Portal gives the staff member an org-branded
// login at /e/{slug} where they can view their profile and roster.
//
// Endpoints (api/v2/staff):
//   GET    /{id}/portal-access      → { state, email, invite_sent_at, ... }
//   POST   /{id}/portal-access      → issue access + email a set-password link
//   DELETE /{id}/portal-access      → revoke access (tears down sessions)
//
// "Resend" reuses revoke + issue (there's no dedicated resend endpoint): the
// existing invite is single-use and issuing again would 409 while one is
// active, so we revoke then re-issue to mint a fresh link.
// ---------------------------------------------------------------------------
import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'

interface PortalAccessStatus {
  state: 'none' | 'invited' | 'active'
  email: string | null
  invite_sent_at: string | null
  invite_accepted_at: string | null
  last_login_at: string | null
}

const NONE_STATUS: PortalAccessStatus = {
  state: 'none',
  email: null,
  invite_sent_at: null,
  invite_accepted_at: null,
  last_login_at: null,
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-NZ', { day: '2-digit', month: 'short', year: 'numeric' })
}

function apiMsg(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: string }).message)
  }
  return fallback
}

export default function PortalAccessCard({ staffId }: { staffId: string }) {
  const [status, setStatus] = useState<PortalAccessStatus>(NONE_STATUS)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<null | 'send' | 'resend' | 'revoke'>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionNote, setActionNote] = useState<string | null>(null)

  const cardCls = 'rounded-card border border-border bg-card shadow-card mb-4'

  const fetchStatus = useCallback(async (signal?: AbortSignal): Promise<void> => {
    try {
      const res = await apiClient.get<PortalAccessStatus>(
        `/api/v2/staff/${staffId}/portal-access`,
        signal ? { signal } : undefined,
      )
      if (signal?.aborted) return
      setStatus(res.data ?? NONE_STATUS)
    } catch (err) {
      if (signal?.aborted) return
      // A 404 (module disabled) or any failure → treat as no access so the
      // tab never crashes (safe-api-consumption).
      setStatus(NONE_STATUS)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [staffId])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setActionError(null)
    setActionNote(null)
    void fetchStatus(controller.signal)
    return () => controller.abort()
  }, [fetchStatus])

  const issue = useCallback(async () => {
    const res = await apiClient.post<{ invite_sent: boolean; invite_error: string | null }>(
      `/api/v2/staff/${staffId}/portal-access`,
    )
    return res.data
  }, [staffId])

  const handleSend = useCallback(async (kind: 'send' | 'resend') => {
    setBusy(kind)
    setActionError(null)
    setActionNote(null)
    try {
      if (kind === 'resend') {
        // Revoke the existing (single-use) invite first, then mint a fresh one.
        await apiClient.delete(`/api/v2/staff/${staffId}/portal-access`)
      }
      const res = await issue()
      if (res && res.invite_sent === false) {
        setActionError('Portal access was created, but the invite email could not be sent. Check the staff email address.')
      } else {
        setActionNote('Invite email sent.')
      }
      await fetchStatus()
    } catch (err) {
      setActionError(apiMsg(err, 'Could not send the portal invite. Please try again.'))
    } finally {
      setBusy(null)
    }
  }, [staffId, issue, fetchStatus])

  const handleRevoke = useCallback(async () => {
    if (!confirm('Revoke this staff member\'s portal access? Their portal sessions will end immediately.')) return
    setBusy('revoke')
    setActionError(null)
    setActionNote(null)
    try {
      await apiClient.delete(`/api/v2/staff/${staffId}/portal-access`)
      await fetchStatus()
    } catch (err) {
      setActionError(apiMsg(err, 'Could not revoke portal access. Please try again.'))
    } finally {
      setBusy(null)
    }
  }, [staffId, fetchStatus])

  const btnSecondaryCls =
    'inline-flex min-h-[44px] items-center justify-center rounded-ctl border border-border px-3 text-[13px] font-medium text-text hover:bg-canvas disabled:opacity-50'
  const btnPrimaryCls =
    'inline-flex min-h-[44px] items-center justify-center rounded-ctl bg-accent px-3 text-[13px] font-semibold text-white hover:brightness-95 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card'

  let headline = 'No portal access'
  let detail: string | null = null
  if (status.state === 'invited') {
    headline = 'Invite sent — not accepted yet'
    detail = `Sent ${fmtDate(status.invite_sent_at)}`
  } else if (status.state === 'active') {
    headline = 'Portal access active'
    detail = status.last_login_at ? `Last login ${fmtDate(status.last_login_at)}` : `Accepted ${fmtDate(status.invite_accepted_at)}`
  }

  return (
    <section className={cardCls} aria-label="Employee Portal access" data-testid="portal-access-card">
      <div className="p-5">
        <div className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-muted-2">
          Employee Portal
        </div>

        {loading ? (
          <div className="h-10 animate-pulse rounded bg-muted/10" />
        ) : (
          <>
            <p className="text-[13px] font-medium text-text">{headline}</p>
            {detail && <p className="mt-1 text-[12px] text-muted">{detail}</p>}
            {status.email && (
              <p className="mt-0.5 text-[12px] text-muted-2">{status.email}</p>
            )}

            <p className="mt-2 text-[12px] leading-relaxed text-muted">
              Lets this staff member sign in at the org portal to view their profile and roster.
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              {status.state === 'none' ? (
                <button type="button" className={btnPrimaryCls} disabled={busy !== null} onClick={() => handleSend('send')}>
                  {busy === 'send' ? 'Sending…' : 'Send portal invite'}
                </button>
              ) : (
                <>
                  <button type="button" className={btnSecondaryCls} disabled={busy !== null} onClick={() => handleSend('resend')}>
                    {busy === 'resend' ? 'Resending…' : 'Resend invite'}
                  </button>
                  <button type="button" className={btnSecondaryCls} disabled={busy !== null} onClick={handleRevoke}>
                    {busy === 'revoke' ? 'Revoking…' : 'Revoke access'}
                  </button>
                </>
              )}
            </div>

            {actionNote && <p className="mt-2 text-[12px] text-success">{actionNote}</p>}
            {actionError && <p className="mt-2 text-[12px] text-danger">{actionError}</p>}
          </>
        )}
      </div>
    </section>
  )
}
