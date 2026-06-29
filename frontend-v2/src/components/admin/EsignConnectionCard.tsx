/**
 * Global-Admin per-organisation Documenso connection settings (Task 18.3).
 *
 * Embedded in `pages/admin/OrganisationDetail.tsx`, this section lets a Global
 * Admin manage one organisation's Documenso connection:
 *
 *   - view the masked connection (base URL, team id, masked service token /
 *     webhook secret, webhook URL + subscription status, is_verified),
 *   - edit + save it (masked round-trip retains stored secrets, R1.5),
 *   - run "Test connection" (sets is_verified, R1.6 / R19.2),
 *   - copy the org's webhook URL into Documenso with manual-registration
 *     guidance (R18.1 / R19.1).
 *
 * Secrets are shown masked (`********`), never plaintext (R1.4 / R15.3).
 *
 * Backed by `api/esignAdmin.ts`:
 *   - GET  /api/v2/admin/organisations/{org_id}/esign/connection
 *   - PUT  /api/v2/admin/organisations/{org_id}/esign/connection
 *   - POST /api/v2/admin/organisations/{org_id}/esign/connection/test
 *
 * Follows the frontend-feature-completeness checklist (loading / error-with-
 * retry / empty states, disabled+spinner action buttons) and safe-api-
 * consumption rules (`?.`, `?? ''`, typed generics, AbortController cleanup).
 *
 * _Requirements: 1.1, 1.4, 1.5, 1.6, 18.1, 19.1, 19.2_
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Button,
  Badge,
  Input,
  Spinner,
  AlertBanner,
  type BadgeVariant,
} from '@/components/ui'
import {
  getEsignConnection,
  saveEsignConnection,
  testEsignConnection,
  extractEsignError,
  SECRET_MASK,
  type EsignConnection,
  type EsignConnectionSave,
  type WebhookSubscriptionStatus,
} from '@/api/esignAdmin'

/* ── Secret field state (mirrors XeroCredentialsSettings) ── */

interface FieldState {
  /** Current input value (or the masked echo when `isMasked`). */
  value: string
  /** True when the field holds a stored-but-masked secret (untouched). */
  isMasked: boolean
}

const MASKED_PLACEHOLDER = '••••••••'

/* ── Webhook subscription status presentation ── */

const SUBSCRIPTION_LABELS: Record<WebhookSubscriptionStatus, string> = {
  not_configured: 'Not configured',
  pending_verification: 'Pending verification',
  verified: 'Verified',
  active: 'Active (webhook received)',
}

const SUBSCRIPTION_VARIANTS: Record<WebhookSubscriptionStatus, BadgeVariant> = {
  not_configured: 'neutral',
  pending_verification: 'warn',
  verified: 'info',
  active: 'success',
}

/* ── Copy-to-clipboard button (matches XeroSetupGuide CopyButton) ── */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      },
      () => {
        /* clipboard unavailable — silently ignore, the URL stays selectable */
      },
    )
  }
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="ml-2 inline-flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-xs text-muted hover:bg-canvas"
      title="Copy to clipboard"
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  )
}

/* ── Component ── */

export function EsignConnectionCard({ orgId }: { orgId: string }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<
    { variant: 'success' | 'error'; text: string } | null
  >(null)

  const [conn, setConn] = useState<EsignConnection | null>(null)

  // Editable fields.
  const [baseUrl, setBaseUrl] = useState('')
  const [teamId, setTeamId] = useState('')
  const [serviceToken, setServiceToken] = useState<FieldState>({ value: '', isMasked: false })
  const [webhookSecret, setWebhookSecret] = useState<FieldState>({ value: '', isMasked: false })

  /** Apply a freshly-fetched connection into local form state. */
  const applyConnection = useCallback((data: EsignConnection) => {
    setConn(data)
    setBaseUrl(data.base_url ?? '')
    setTeamId(data.documenso_team_id ?? '')
    // A stored secret comes back as the mask + a *_last4; treat it as masked.
    const tokenSet = !!data.service_token_last4
    const secretSet = !!data.webhook_secret_last4
    setServiceToken({ value: tokenSet ? SECRET_MASK : '', isMasked: tokenSet })
    setWebhookSecret({ value: secretSet ? SECRET_MASK : '', isMasked: secretSet })
  }, [])

  const fetchConnection = useCallback(
    (signal?: AbortSignal) => {
      setLoading(true)
      setError(null)
      const run = async () => {
        try {
          const data = await getEsignConnection(orgId, signal)
          applyConnection(data)
        } catch (err: unknown) {
          if (signal?.aborted) return
          setError('Failed to load the Documenso connection for this organisation.')
        } finally {
          if (!signal?.aborted) setLoading(false)
        }
      }
      run()
    },
    [orgId, applyConnection],
  )

  useEffect(() => {
    const controller = new AbortController()
    fetchConnection(controller.signal)
    return () => controller.abort()
  }, [fetchConnection])

  /* ── Save ── */

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    setActionMessage(null)

    const trimmedBase = baseUrl.trim()
    if (!trimmedBase) {
      setFormError('Documenso base URL is required.')
      return
    }

    // Build the payload. For secrets: when the field is still masked (untouched)
    // send the mask back so the backend retains the stored value (R1.5); when
    // edited send the new value; when cleared+empty send null to leave unset.
    const payload: EsignConnectionSave = {
      base_url: trimmedBase,
      documenso_team_id: teamId.trim() || null,
      service_token: serviceToken.isMasked
        ? SECRET_MASK
        : (serviceToken.value.trim() || null),
      webhook_signing_secret: webhookSecret.isMasked
        ? SECRET_MASK
        : (webhookSecret.value.trim() || null),
    }

    setSaving(true)
    try {
      const data = await saveEsignConnection(orgId, payload)
      applyConnection(data)
      setActionMessage({ variant: 'success', text: 'Connection saved.' })
    } catch (err: unknown) {
      const { message } = extractEsignError(err)
      setFormError(message)
    } finally {
      setSaving(false)
    }
  }

  /* ── Test ── */

  const handleTest = async () => {
    setFormError(null)
    setActionMessage(null)
    setTesting(true)
    try {
      const result = await testEsignConnection(orgId)
      setActionMessage({
        variant: result.valid ? 'success' : 'error',
        text: result.valid
          ? 'Connection verified — this organisation can now send for signature.'
          : 'Connection test failed — check the base URL and service token.',
      })
      // Reflect the new is_verified state without a full reload.
      setConn((prev) =>
        prev
          ? {
              ...prev,
              is_verified: result.is_verified,
              webhook_subscription_status: result.is_verified
                ? (prev.webhook_subscription_status === 'active'
                    ? 'active'
                    : 'verified')
                : 'pending_verification',
            }
          : prev,
      )
    } catch (err: unknown) {
      const { message } = extractEsignError(err)
      setActionMessage({ variant: 'error', text: message })
    } finally {
      setTesting(false)
    }
  }

  /* ── Secret field renderer (masked vs editable) ── */

  const renderSecretField = (
    label: string,
    helpWhenSet: string,
    state: FieldState,
    setter: React.Dispatch<React.SetStateAction<FieldState>>,
  ) => {
    if (state.isMasked) {
      return (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text">{label}</label>
          <div className="flex items-center gap-2">
            <span className="rounded-ctl border border-border bg-canvas px-3 py-2 text-muted flex-1 mono">
              {MASKED_PLACEHOLDER}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setter({ value: '', isMasked: false })}
            >
              Change
            </Button>
          </div>
          <p className="text-sm text-muted">{helpWhenSet}</p>
        </div>
      )
    }
    return (
      <Input
        label={label}
        type="password"
        value={state.value}
        onChange={(e) => setter({ value: e.target.value, isMasked: false })}
        placeholder={MASKED_PLACEHOLDER}
        autoComplete="off"
      />
    )
  }

  /* ── Loading state ── */
  if (loading) {
    return (
      <section className="bg-card rounded-card border border-border p-6 lg:col-span-2">
        <h2 className="text-lg font-semibold text-text mb-4">E-Signature (Documenso) Connection</h2>
        <div className="py-8 text-center">
          <Spinner label="Loading Documenso connection" />
        </div>
      </section>
    )
  }

  /* ── Error state ── */
  if (error) {
    return (
      <section className="bg-card rounded-card border border-border p-6 lg:col-span-2">
        <h2 className="text-lg font-semibold text-text mb-4">E-Signature (Documenso) Connection</h2>
        <AlertBanner variant="error" title="Failed to load">
          {error}
        </AlertBanner>
        <div className="mt-4">
          <Button variant="ghost" onClick={() => fetchConnection()}>
            Retry
          </Button>
        </div>
      </section>
    )
  }

  const isVerified = conn?.is_verified ?? false
  const subscriptionStatus = conn?.webhook_subscription_status ?? 'not_configured'
  const webhookUrl = conn?.webhook_url ?? null

  return (
    <section id="esign-connection" className="bg-card rounded-card border border-border p-6 lg:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-text">E-Signature (Documenso) Connection</h2>        <div className="flex items-center gap-2">
          <Badge variant={isVerified ? 'success' : 'warn'}>
            {isVerified ? 'Verified' : 'Not verified'}
          </Badge>
          <Badge variant={SUBSCRIPTION_VARIANTS[subscriptionStatus]}>
            {SUBSCRIPTION_LABELS[subscriptionStatus]}
          </Badge>
        </div>
      </div>

      <p className="text-sm text-muted mb-4">
        Configure this organisation&apos;s own Documenso Team connection. Secrets are
        stored encrypted and shown masked. Saving an unchanged masked field keeps the
        stored value. A connection must pass the test before this organisation can send
        agreements for signature.
      </p>

      <form onSubmit={handleSave} className="space-y-4 max-w-2xl">
        <Input
          label="Documenso base URL"
          type="url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://documenso.example.com"
          required
        />
        <Input
          label="Documenso Team ID"
          value={teamId}
          onChange={(e) => setTeamId(e.target.value)}
          placeholder="e.g. 42"
        />
        {renderSecretField(
          'Service token',
          'Token is set. Click Change to replace it.',
          serviceToken,
          setServiceToken,
        )}
        {renderSecretField(
          'Webhook signing secret',
          'Secret is set. Click Change to replace it.',
          webhookSecret,
          setWebhookSecret,
        )}

        {formError && (
          <p className="text-sm text-danger" role="alert">{formError}</p>
        )}

        {actionMessage && (
          <AlertBanner
            variant={actionMessage.variant === 'success' ? 'success' : 'error'}
            title={actionMessage.variant === 'success' ? 'Success' : 'Problem'}
          >
            {actionMessage.text}
          </AlertBanner>
        )}

        <div className="flex flex-wrap gap-3 pt-1">
          <Button type="submit" variant="primary" loading={saving} disabled={saving || testing}>
            Save connection
          </Button>
          <Button
            type="button"
            variant="ghost"
            loading={testing}
            disabled={saving || testing || !conn?.configured}
            onClick={handleTest}
          >
            Test connection
          </Button>
        </div>
      </form>

      {/* Webhook URL + manual registration guidance (R18.1 / R19.1) */}
      <div className="mt-6 border-t border-border pt-4">
        <h3 className="text-sm font-semibold text-text mb-2">Webhook registration</h3>
        {webhookUrl ? (
          <>
            <p className="text-sm text-muted mb-2">
              Copy this organisation&apos;s webhook URL into its Documenso Team
              (Settings → Webhooks → Create webhook). Use the same webhook signing
              secret entered above, and subscribe to the document lifecycle events
              (opened/viewed, recipient completed/rejected, document completed/cancelled).
            </p>
            <div className="flex items-center rounded-ctl border border-border bg-canvas px-3 py-2 mono text-xs">
              <span className="flex-1 select-all break-all">{webhookUrl}</span>
              <CopyButton text={webhookUrl} />
            </div>
            <p className="text-xs text-muted mt-2">
              After registering the webhook in Documenso, run <span className="font-medium">Test connection</span>{' '}
              above. The subscription becomes <span className="font-medium">Active</span> once the first
              Documenso webhook is received on this URL.
            </p>
          </>
        ) : (
          <p className="text-sm text-muted">
            Save the connection first to generate this organisation&apos;s webhook URL.
          </p>
        )}
      </div>
    </section>
  )
}

export default EsignConnectionCard
