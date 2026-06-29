/**
 * EsignConnectionCard — Global-Admin per-org Documenso connection settings
 * (feature: esignature-integration, Task 18.4).
 *
 * The card (`components/admin/EsignConnectionCard.tsx`) is embedded in the
 * Global-Admin OrganisationDetail page. These tests drive it through its typed
 * admin API client (`@/api/esignAdmin`), which is mocked here so no network is
 * touched. The real `SECRET_MASK` constant and `extractEsignError` helper are
 * preserved via `importActual` so masking / error-shape behaviour is exercised
 * end-to-end against deterministic shapes.
 *
 * Coverage (R1.4 masked secrets, R1.6 / R19.2 connection test → is_verified):
 *   1. Stored secrets render MASKED (bullet placeholder + "Change"), never
 *      plaintext — neither the team-scoped service token nor the webhook
 *      signing secret leak into the DOM.
 *   2. The organisation's webhook URL and verification status are shown.
 *   3. Clicking "Test connection" calls
 *      POST /api/v2/admin/organisations/{org_id}/esign/connection/test
 *      (the mocked `testEsignConnection`) and the UI reflects the resulting
 *      `is_verified` state.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type {
  EsignConnection,
  EsignConnectionTestResult,
} from '@/api/esignAdmin'

// Mock only the network functions; keep SECRET_MASK + extractEsignError real so
// the component's masking/error handling runs against the genuine constants.
vi.mock('@/api/esignAdmin', async () => {
  const actual = await vi.importActual<typeof import('@/api/esignAdmin')>(
    '@/api/esignAdmin',
  )
  return {
    ...actual,
    getEsignConnection: vi.fn(),
    saveEsignConnection: vi.fn(),
    testEsignConnection: vi.fn(),
  }
})

import {
  getEsignConnection,
  testEsignConnection,
  SECRET_MASK,
} from '@/api/esignAdmin'
import { EsignConnectionCard } from './EsignConnectionCard'

const mockGet = getEsignConnection as ReturnType<typeof vi.fn>
const mockTest = testEsignConnection as ReturnType<typeof vi.fn>

const ORG_ID = 'org-123'
const WEBHOOK_URL =
  'https://app.example.com/api/v2/esign/webhook/route-abc-987'

/**
 * A configured-but-not-yet-verified connection whose secrets come back from the
 * backend already MASKED (the API never returns plaintext). `configured: true`
 * is what enables the "Test connection" button.
 */
function connection(overrides: Partial<EsignConnection> = {}): EsignConnection {
  return {
    configured: true,
    org_id: ORG_ID,
    base_url: 'https://documenso.example.com',
    documenso_team_id: '42',
    is_verified: false,
    service_token: SECRET_MASK,
    service_token_last4: '4242',
    webhook_signing_secret: SECRET_MASK,
    webhook_secret_last4: 'cdef',
    webhook_routing_id: 'route-abc-987',
    webhook_url: WEBHOOK_URL,
    webhook_subscription_status: 'pending_verification',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    ...overrides,
  }
}

function testResult(
  overrides: Partial<EsignConnectionTestResult> = {},
): EsignConnectionTestResult {
  return { is_verified: true, valid: true, ...overrides }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('EsignConnectionCard — masked secrets (R1.4)', () => {
  it('renders stored secrets masked and never exposes plaintext', async () => {
    mockGet.mockResolvedValue(connection())
    render(<EsignConnectionCard orgId={ORG_ID} />)

    // Wait for the load to resolve (heading + base url field render).
    expect(
      await screen.findByDisplayValue('https://documenso.example.com'),
    ).toBeInTheDocument()

    // Both secrets render with the bullet placeholder + a "Change" affordance,
    // i.e. masked — not as editable plaintext inputs.
    const masked = screen.getAllByText('••••••••')
    expect(masked).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Change' })).toHaveLength(2)

    // The masked echo the backend sends ('********') is never surfaced as
    // visible text, and no input carries a plaintext secret value.
    expect(screen.queryByText(SECRET_MASK)).toBeNull()
    expect(screen.queryByDisplayValue(SECRET_MASK)).toBeNull()
    expect(screen.queryByDisplayValue('4242')).toBeNull()
    expect(screen.queryByDisplayValue('cdef')).toBeNull()
  })
})

describe('EsignConnectionCard — webhook URL + verify status (R19.2)', () => {
  it("shows the organisation's webhook URL and verification status", async () => {
    mockGet.mockResolvedValue(connection())
    render(<EsignConnectionCard orgId={ORG_ID} />)

    // Webhook URL surfaced for the Global Admin to copy into Documenso.
    expect(await screen.findByText(WEBHOOK_URL)).toBeInTheDocument()

    // Verification status badge reflects the unverified connection.
    expect(screen.getByText('Not verified')).toBeInTheDocument()
    // Webhook subscription status badge.
    expect(screen.getByText('Pending verification')).toBeInTheDocument()
  })
})

describe('EsignConnectionCard — connection test (R1.6 / R19.2)', () => {
  it('triggers the test endpoint and reflects the resulting is_verified state', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue(connection())
    mockTest.mockResolvedValue(testResult({ is_verified: true, valid: true }))

    render(<EsignConnectionCard orgId={ORG_ID} />)

    // Starts unverified.
    expect(await screen.findByText('Not verified')).toBeInTheDocument()

    const testButton = screen.getByRole('button', { name: 'Test connection' })
    expect(testButton).toBeEnabled()

    await user.click(testButton)

    // POST .../esign/connection/test is invoked for this org.
    await waitFor(() => expect(mockTest).toHaveBeenCalledTimes(1))
    expect(mockTest).toHaveBeenCalledWith(ORG_ID)

    // The UI reflects the resulting verified state: success banner + the badge
    // flips to verified (and the unverified badge is gone).
    expect(
      await screen.findByText(
        'Connection verified — this organisation can now send for signature.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('Not verified')).toBeNull()
    expect(screen.getAllByText('Verified').length).toBeGreaterThanOrEqual(1)
  })

  it('reflects a failed test (is_verified stays false) with an error message', async () => {
    const user = userEvent.setup()
    mockGet.mockResolvedValue(connection())
    mockTest.mockResolvedValue(testResult({ is_verified: false, valid: false }))

    render(<EsignConnectionCard orgId={ORG_ID} />)

    await screen.findByText('Not verified')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    await waitFor(() => expect(mockTest).toHaveBeenCalledWith(ORG_ID))

    expect(
      await screen.findByText(
        'Connection test failed — check the base URL and service token.',
      ),
    ).toBeInTheDocument()
    // Remains unverified after a failed test.
    expect(screen.getByText('Not verified')).toBeInTheDocument()
  })
})
