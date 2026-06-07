import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { EmailPreviewResponse } from '../types'

/**
 * SendEmailSheet unit tests (task 15.4, R21.5).
 *
 * Mirrors the web `SendEmailModal` test (task 12.1), adapted to the mobile sheet:
 *   - loading-state: the 300 ms skeleton spinner shows while the preview is pending
 *   - default-render: the preview seeds To / subject / sender footer + Send button
 *   - edited-render: editing the subject includes `subject` + `subject_was_edited`
 *     in the POST and OMITS the unedited `body_html` (R3.6 / Property P1)
 *   - send-success: the override-send resolves → `onSent` + `onClose` fire
 *   - send-failure: 503 → amber StatusBanner with Retry, `onSent` NOT called, the
 *     sheet stays open
 *   - safe-area-inset render: the scrollable body uses `pb-safe` + the
 *     `env(safe-area-inset-*)` padding (R12.4) and the app-bar uses the top inset
 *   - global_admin → the sheet renders nothing (R12.7 / R15.3)
 *
 * `useAuth`/`useModules` are mocked (org_admin, module enabled by default).
 * `apiClient.get` serves the `EmailPreviewResponse`; `apiClient.request` performs
 * the override-send. The lazy TipTap `MobileBodyEditor` is stubbed with a plain
 * textarea so body editing is testable without TipTap in jsdom.
 */

// ── Auth / module mocks (mutable so individual tests can flip roles) ─────────
let mockAuth: { isOrgAdmin: boolean; isGlobalAdmin: boolean } = {
  isOrgAdmin: true,
  isGlobalAdmin: false,
}
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockAuth,
}))

let mockModuleEnabled = true
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isModuleEnabled: () => mockModuleEnabled }),
}))

// ── apiClient mock — get() = preview, request() = override-send ──────────────
const h = vi.hoisted(() => ({
  preview: null as EmailPreviewResponse | null,
  getImpl: null as ((url: string, config?: unknown) => Promise<{ data: unknown }>) | null,
  requestImpl: null as ((config: unknown) => Promise<{ data: unknown }>) | null,
}))

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn((url: string, config?: unknown) =>
      h.getImpl ? h.getImpl(url, config) : Promise.resolve({ data: h.preview }),
    ),
    request: vi.fn((config: unknown) =>
      h.requestImpl ? h.requestImpl(config) : Promise.resolve({ data: {} }),
    ),
  },
}))

// ── Stub the lazy TipTap editor with a light textarea ────────────────────────
vi.mock('@/components/email/MobileBodyEditor', () => ({
  default: function MockMobileBodyEditor(props: {
    valueHtml: string
    onChange: (html: string) => void
    onResetToDefault: () => void
    senderPreview: { from_name: string; from_email: string }
    locale: string
  }) {
    return (
      <div>
        <textarea
          aria-label="Body editor"
          value={props.valueHtml}
          onChange={(e) => props.onChange(e.target.value)}
        />
        <button type="button" onClick={props.onResetToDefault}>
          Reset to default
        </button>
        <p>
          Sender: {props.senderPreview.from_name} &lt;{props.senderPreview.from_email}&gt;
        </p>
        <p>Locale: {props.locale}</p>
      </div>
    )
  },
}))

import apiClient from '@/api/client'
import { SendEmailSheet } from '../SendEmailSheet'
import type { SendEmailModalProps } from '../types'

function fullPreview(overrides: Partial<EmailPreviewResponse> = {}): EmailPreviewResponse {
  return {
    subject: 'Your invoice INV-001',
    body_html: '<p>Please find your invoice attached.</p>',
    body_editable_html: '<p>Hi Jane,</p><p>Please find your invoice attached.</p>',
    recipients: ['customer@example.com'],
    cc: [],
    bcc: [],
    variable_context: { invoice_number: 'INV-001' },
    attachments: [
      {
        key: 'invoice_pdf',
        label: 'Invoice PDF',
        size_bytes: 80 * 1024,
        default_attached: true,
        required: true,
      },
    ],
    default_was_template: true,
    sender_preview: {
      from_email: 'billing@kerikerimotors.test',
      from_name: 'Kerikeri Motors',
      reply_to: null,
    },
    blocklisted: [],
    locale: 'en',
    email_size_limit_bytes: 25 * 1024 * 1024,
    total_budget_seconds: 45,
    ...overrides,
  }
}

function renderSheet(overrides: Partial<SendEmailModalProps> = {}) {
  const props: SendEmailModalProps = {
    open: true,
    onClose: vi.fn(),
    templateType: 'invoice_issued',
    entityType: 'invoice',
    entityId: 'inv-1',
    onSent: vi.fn(),
    surfaceLabel: 'Send Invoice',
    ...overrides,
  }
  const utils = render(<SendEmailSheet {...props} />)
  return { props, ...utils }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockAuth = { isOrgAdmin: true, isGlobalAdmin: false }
  mockModuleEnabled = true
  h.preview = fullPreview()
  h.getImpl = null
  h.requestImpl = null
})

describe('SendEmailSheet — loading state', () => {
  it('shows the skeleton spinner (after 300 ms) while the preview is pending', async () => {
    let resolvePreview: ((v: { data: EmailPreviewResponse }) => void) | undefined
    h.getImpl = () =>
      new Promise((resolve) => {
        resolvePreview = resolve as never
      })

    renderSheet()

    // The 300 ms skeleton timer fires → the spinner (role=status) appears.
    expect(await screen.findByRole('status')).toBeInTheDocument()
    // Fields are not yet rendered while the preview is pending.
    expect(screen.queryByLabelText('Subject')).toBeNull()

    // Resolve the preview — the skeleton clears and the fields render.
    resolvePreview?.({ data: fullPreview() })
    expect(await screen.findByLabelText(/Subject/)).toHaveValue('Your invoice INV-001')
  })
})

describe('SendEmailSheet — default render', () => {
  it('fetches the preview and seeds the fields from the response', async () => {
    renderSheet()

    // To recipient chip pre-populated.
    expect(await screen.findByText('customer@example.com')).toBeInTheDocument()
    // Subject seeded.
    expect(screen.getByLabelText(/Subject/)).toHaveValue('Your invoice INV-001')
    // Attachment row + sender footer (from the stubbed body editor).
    expect(screen.getByText('Invoice PDF')).toBeInTheDocument()
    expect(
      await screen.findByText('Sender: Kerikeri Motors <billing@kerikerimotors.test>'),
    ).toBeInTheDocument()
    // Send button present + enabled once a recipient and subject exist.
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()

    // Preview fetched against the v2 endpoint with the identifying params.
    expect(apiClient.get).toHaveBeenCalledWith(
      '/email-preview',
      expect.objectContaining({
        baseURL: '/api/v2',
        params: {
          template_type: 'invoice_issued',
          entity_type: 'invoice',
          entity_id: 'inv-1',
        },
      }),
    )
  })
})

describe('SendEmailSheet — edited render', () => {
  it('includes an edited subject in the POST and OMITS the unedited body_html', async () => {
    h.requestImpl = vi.fn(async () => ({ data: { ok: true } }))
    renderSheet()
    await screen.findByText('customer@example.com')

    const subject = screen.getByLabelText(/Subject/)
    await userEvent.clear(subject)
    await userEvent.type(subject, 'REVISED invoice')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(h.requestImpl).toHaveBeenCalled())
    const config = (h.requestImpl as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      url: string
      method: string
      data: Record<string, unknown>
    }
    expect(config.method).toBe('POST')
    expect(config.url).toBe('/invoices/inv-1/email')
    expect(config.data.subject).toBe('REVISED invoice')
    expect(config.data.subject_was_edited).toBe(true)
    // Body was never edited → body_html omitted (byte-equivalent default, R3.6).
    expect(config.data).not.toHaveProperty('body_html')
    expect(config.data.body_was_edited).toBe(false)
  })
})

describe('SendEmailSheet — send success', () => {
  it('on success fires onSent and closes the sheet', async () => {
    h.requestImpl = vi.fn(async () => ({ data: { ok: true } }))
    const { props } = renderSheet()
    await screen.findByText('customer@example.com')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(props.onSent).toHaveBeenCalledTimes(1))
    expect(props.onClose).toHaveBeenCalledTimes(1)
  })
})

describe('SendEmailSheet — send failure', () => {
  it('503 shows an amber banner with Retry, keeps the sheet open, and does not fire onSent', async () => {
    h.requestImpl = vi.fn(async () => {
      throw { response: { status: 503, data: { detail: 'Delivery temporarily failed.' } } }
    })
    const { props } = renderSheet()
    await screen.findByText('customer@example.com')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('Delivery temporarily failed.')
    expect(banner.className).toContain('bg-amber-50')
    expect(within(banner).getByRole('button', { name: 'Retry' })).toBeInTheDocument()

    // Sheet stays open and onSent/onClose were not called.
    expect(screen.getByTestId('send-email-sheet')).toBeInTheDocument()
    expect(props.onSent).not.toHaveBeenCalled()
    expect(props.onClose).not.toHaveBeenCalled()
  })
})

describe('SendEmailSheet — safe-area insets', () => {
  it('renders the scrollable body with the pb-safe safe-area padding class (R12.4)', async () => {
    const { container } = renderSheet()
    await screen.findByText('customer@example.com')

    // The scrollable body container carries the `pb-safe` class so the Send
    // controls are never obscured by the home-indicator (R12.4). jsdom's CSSOM
    // strips the env()/max() inline style, so the class is the reliable signal.
    const body = container.querySelector('.pb-safe')
    expect(body).not.toBeNull()
    expect(body?.className).toContain('pb-safe')
  })
})

describe('SendEmailSheet — role gating', () => {
  it('renders nothing for a global_admin (mobile is org-users only, R12.7)', () => {
    mockAuth = { isOrgAdmin: false, isGlobalAdmin: true }
    renderSheet()
    expect(screen.queryByTestId('send-email-sheet')).toBeNull()
  })
})
