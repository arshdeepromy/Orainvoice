/**
 * Organisations — per-row "Provision e-signature" action states (Task 18.6).
 *
 * Covers the four outcomes of the Global-Admin per-row provisioning action
 * (R19.6, R19.7, R20.1, R20.2, R20.3, R20.5):
 *
 *   1. progress     — clicking the action puts the row button in a
 *                     loading/disabled state while the request is in flight
 *                     (driven by a deferred promise).
 *   2. success      — a `provisioned` + `is_verified` result opens the result
 *                     modal showing the verified success banner and surfacing
 *                     the org's webhook URL (R20.2).
 *   3. failure      — a `partial` result shows the humanized `{ message, code }`
 *                     plus a "Configure manually" link into the org's connection
 *                     management view `/admin/organisations/{orgId}` (R20.3).
 *   4. unavailable  — an `unavailable` result (ESIGN_PROVISIONING_MODE=off)
 *                     indicates auto-provisioning is unavailable and points to
 *                     the manual config view (R20.5).
 *
 * `@/api/esignAdmin` is partially mocked — only `autoProvisionEsignConnection`
 * is replaced so the page's real `extractEsignError`/types run unchanged. The
 * `@/api/client` default export is mocked so the org/plan list loads against
 * deterministic shapes. Render is wrapped in MemoryRouter so the result modal's
 * react-router `<Link>` ("Configure manually") resolves. Typed generics
 * throughout — no `as any`.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

// Partial mock: keep the real types + `extractEsignError`, replace only the
// network call so we can drive each outcome deterministically.
vi.mock('@/api/esignAdmin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/esignAdmin')>()
  return { ...actual, autoProvisionEsignConnection: vi.fn() }
})

import apiClient from '@/api/client'
import {
  autoProvisionEsignConnection,
  type EsignAutoProvisionResult,
  type EsignAutoProvisionStatus,
  type EsignConnection,
} from '@/api/esignAdmin'
import { Organisations } from './Organisations'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>
const mockAutoProvision = vi.mocked(autoProvisionEsignConnection)

const ORG_ID = 'org-42'
const ORG_NAME = 'Acme Trades Ltd'
const WEBHOOK_URL = 'https://app.example.test/api/v2/esign/webhook/route-abc123'

/** A single active org so the per-row "Provision e-signature" button renders. */
function mockOrgList(): void {
  mockGet.mockImplementation((url: string) => {
    if (url === '/admin/organisations') {
      return Promise.resolve({
        data: {
          organisations: [
            {
              id: ORG_ID,
              name: ORG_NAME,
              plan_name: 'Pro',
              plan_id: 'plan-1',
              status: 'active',
              created_at: '2026-01-01T00:00:00Z',
              storage_used_bytes: 0,
              storage_quota_gb: 10,
              last_login_at: null,
              next_billing_date: null,
              billing_interval: 'monthly',
            },
          ],
          total: 1,
        },
      })
    }
    if (url === '/admin/plans') {
      return Promise.resolve({ data: { plans: [], total: 0 } })
    }
    return Promise.resolve({ data: {} })
  })
}

/** Build a fully-populated masked connection projection for a given verification state. */
function buildConnection(overrides: Partial<EsignConnection> = {}): EsignConnection {
  return {
    configured: true,
    org_id: ORG_ID,
    base_url: 'https://documenso.example.test',
    documenso_team_id: '7',
    is_verified: false,
    service_token: '********',
    service_token_last4: 'cdef',
    webhook_signing_secret: '********',
    webhook_secret_last4: '9876',
    webhook_routing_id: 'route-abc123',
    webhook_url: WEBHOOK_URL,
    webhook_subscription_status: 'pending_verification',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    ...overrides,
  }
}

function buildResult(
  status: EsignAutoProvisionStatus,
  overrides: Partial<Omit<EsignAutoProvisionResult, 'connection'>> & {
    connection?: Partial<EsignConnection>
  } = {},
): EsignAutoProvisionResult {
  return {
    status,
    connection: buildConnection(overrides.connection ?? {}),
    error: overrides.error ?? null,
    code: overrides.code ?? null,
  }
}

function renderOrganisations() {
  return render(
    <MemoryRouter initialEntries={['/admin/organisations']}>
      <Organisations />
    </MemoryRouter>,
  )
}

/** Resolve the org list, render, and return the row's provision-action button. */
async function renderAndGetProvisionButton(): Promise<HTMLElement> {
  renderOrganisations()
  // Wait for the table to render the org row (loading spinner clears).
  await screen.findByText(ORG_NAME)
  return screen.getByRole('button', { name: 'Provision e-signature' })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockOrgList()
})

describe('Organisations — provision action: progress state', () => {
  it('shows the row button loading/disabled while the request is in flight', async () => {
    // A deferred promise keeps the request "in flight" until we resolve it.
    let resolve!: (value: EsignAutoProvisionResult) => void
    const pending = new Promise<EsignAutoProvisionResult>((res) => {
      resolve = res
    })
    mockAutoProvision.mockReturnValue(pending)

    const button = await renderAndGetProvisionButton()
    expect(button).not.toBeDisabled()

    fireEvent.click(button)

    // While in flight the button is disabled + aria-busy with a spinner.
    await waitFor(() => expect(button).toBeDisabled())
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button.querySelector('[data-testid="button-spinner"]')).toBeInTheDocument()
    expect(mockAutoProvision).toHaveBeenCalledWith(ORG_ID, expect.any(AbortSignal))

    // Resolve to settle the promise and flush React state for a clean teardown.
    resolve(buildResult('provisioned', { connection: { is_verified: true } }))
    await waitFor(() => expect(button).not.toBeDisabled())
  })
})

describe('Organisations — provision action: success state', () => {
  it('shows the verified success banner and the org webhook URL', async () => {
    mockAutoProvision.mockResolvedValue(
      buildResult('provisioned', {
        connection: { is_verified: true, webhook_url: WEBHOOK_URL },
      }),
    )

    const button = await renderAndGetProvisionButton()
    fireEvent.click(button)

    // Verified success banner.
    expect(await screen.findByText('E-signature provisioned')).toBeInTheDocument()
    // The org's webhook URL is surfaced for the Global Admin to register (R20.2).
    expect(screen.getByText(WEBHOOK_URL)).toBeInTheDocument()
    // Verified success offers no "Configure manually" link (nothing left to fix).
    expect(screen.queryByRole('link', { name: 'Configure manually' })).not.toBeInTheDocument()
  })
})

describe('Organisations — provision action: failure (partial) state', () => {
  it('shows the humanized message + code and a manual-config link to the org view', async () => {
    const message = 'We could not reach Documenso to finish provisioning.'
    const code = 'provisioning_failed'
    mockAutoProvision.mockResolvedValue(
      buildResult('partial', {
        error: message,
        code,
        connection: { is_verified: false },
      }),
    )

    const button = await renderAndGetProvisionButton()
    fireEvent.click(button)

    // Humanized { message, code } surfaced to the Global Admin (R20.3). Scope to
    // the result modal — the message also appears in the transient error toast.
    await screen.findByText("Auto-provisioning didn't finish")
    const dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByText("Auto-provisioning didn't finish")).toBeInTheDocument()
    expect(dialog.getByText(message)).toBeInTheDocument()
    expect(dialog.getByText(code)).toBeInTheDocument()

    // "Configure manually" link points to the org's connection management view.
    const link = dialog.getByRole('link', { name: 'Configure manually' })
    expect(link).toHaveAttribute('href', `/admin/organisations/${ORG_ID}#esign-connection`)
  })
})

describe('Organisations — provision action: unavailable state', () => {
  it('indicates auto-provisioning is unavailable and points to manual config', async () => {
    mockAutoProvision.mockResolvedValue(
      buildResult('unavailable', {
        error: 'Automatic setup is turned off in this environment.',
        code: 'provisioning_disabled',
      }),
    )

    const button = await renderAndGetProvisionButton()
    fireEvent.click(button)

    // Unavailable banner (ESIGN_PROVISIONING_MODE=off) → R20.5.
    expect(await screen.findByText('Auto-provisioning unavailable')).toBeInTheDocument()
    expect(
      screen.getByText('Automatic setup is turned off in this environment.'),
    ).toBeInTheDocument()

    // Still steers the admin to the always-available manual path.
    const link = screen.getByRole('link', { name: 'Configure manually' })
    expect(link).toHaveAttribute('href', `/admin/organisations/${ORG_ID}#esign-connection`)
  })
})
