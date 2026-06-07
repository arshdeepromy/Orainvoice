import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '@/contexts/AuthContext'
import { makeToken } from '@/test/providers'
import type { EmailPreviewResponse } from './types'

/**
 * SendEmailModal unit tests (task 12.1, R21.4).
 *
 * Covers the modal's full lifecycle against a mocked `@/api/client`:
 *   - loading-state: the 300 ms skeleton timer + preview resolving into fields
 *   - default-render: fields seeded from the preview response
 *   - edited-render: editing the subject sets the edited flag and includes
 *     `subject` in the POST while the unedited `body_html` is OMITTED (R3.6)
 *   - send-success: POST resolves → onSent called + modal closes + success toast
 *   - send-failure: 503 → amber StatusBanner with Retry (fields preserved);
 *     400 → red banner
 *
 * The modal is wrapped in the REAL AuthProvider (so `useAuth().isOrgAdmin`
 * resolves) with a seeded org_admin session. `apiClient.get` returns a full
 * EmailPreviewResponse; `apiClient.request` performs the override-send.
 */

/* ------------------------------------------------------------------ *
 * Mock @/api/client — get() serves auth/me + the email preview; request()
 * is the override-send; token helpers reproduce the real session restore.
 * ------------------------------------------------------------------ */

const h = vi.hoisted(() => ({
  preview: null as EmailPreviewResponse | null,
  getImpl: null as ((url: string, config?: unknown) => Promise<{ data: unknown }>) | null,
  requestImpl: null as ((config: unknown) => Promise<{ data: unknown }>) | null,
}))

vi.mock('@/api/client', () => {
  let token: string | null = null
  const isValid = () => {
    if (!token) return false
    try {
      const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
      return payload.exp * 1000 > Date.now() + 60_000
    } catch {
      return false
    }
  }

  const get = vi.fn(async (url: string, config?: unknown) => {
    if (url === '/auth/me') {
      return { data: { first_name: 'Ada', last_name: 'Admin', branch_ids: [] } }
    }
    if (url === '/api/v2/email-preview') {
      if (h.getImpl) return h.getImpl(url, config)
      return { data: h.preview }
    }
    return { data: {} }
  })

  const request = vi.fn(async (config: unknown) => {
    if (h.requestImpl) return h.requestImpl(config)
    return { data: {} }
  })

  return {
    default: {
      get,
      post: vi.fn(async () => ({ data: {} })),
      request,
      interceptors: {
        request: { use: vi.fn(() => 0), eject: vi.fn() },
        response: { use: vi.fn(() => 0), eject: vi.fn() },
      },
    },
    setAccessToken: (t: string | null) => {
      token = t
    },
    getAccessToken: () => token,
    isAccessTokenValid: isValid,
    doTokenRefresh: () => Promise.resolve(token),
  }
})

/* Stub the lazy TipTap BodyEditor with a light textarea so the modal's body
 * editing + sender footer are exercised without TipTap's editor in jsdom. */
vi.mock('./BodyEditor', () => ({
  default: function MockBodyEditor(props: {
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
      </div>
    )
  },
}))

import apiClient, { setAccessToken } from '@/api/client'
import { SendEmailModal } from './SendEmailModal'
import type { SendEmailModalProps } from './types'

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

function renderModal(overrides: Partial<SendEmailModalProps> = {}) {
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
  render(
    <AuthProvider>
      <SendEmailModal {...props} />
    </AuthProvider>,
  )
  return props
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  h.preview = fullPreview()
  h.getImpl = null
  h.requestImpl = null
  setAccessToken(makeToken({ role: 'org_admin' }))
})

describe('SendEmailModal — default render', () => {
  it('fetches the preview and seeds the fields from the response', async () => {
    renderModal()

    // To field pre-populated with the default recipient chip.
    expect(await screen.findByText('customer@example.com')).toBeInTheDocument()
    // Subject seeded.
    expect(screen.getByLabelText('Subject')).toHaveValue('Your invoice INV-001')
    // Attachment row + sender footer.
    expect(screen.getByText('Invoice PDF')).toBeInTheDocument()
    expect(
      await screen.findByText('Sender: Kerikeri Motors <billing@kerikerimotors.test>'),
    ).toBeInTheDocument()

    // Preview called with the identifying query params.
    expect(apiClient.get).toHaveBeenCalledWith(
      '/api/v2/email-preview',
      expect.objectContaining({
        params: {
          template_type: 'invoice_issued',
          entity_type: 'invoice',
          entity_id: 'inv-1',
        },
      }),
    )
  })

  it('enables Send once a recipient and subject are present', async () => {
    renderModal()
    await screen.findByText('customer@example.com')
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
  })
})

describe('SendEmailModal — loading state', () => {
  it('shows the skeleton spinner after 300 ms while the preview is pending', async () => {
    let resolvePreview: ((v: { data: EmailPreviewResponse }) => void) | undefined
    h.getImpl = (url) => {
      if (url === '/api/v2/email-preview') {
        return new Promise((resolve) => {
          resolvePreview = resolve as never
        })
      }
      return Promise.resolve({ data: {} })
    }

    renderModal()

    // The 300 ms skeleton timer fires → spinner appears while pending.
    expect(await screen.findByText('Loading email preview')).toBeInTheDocument()

    // Resolve the preview — the skeleton clears and fields render.
    resolvePreview?.({ data: fullPreview() })
    expect(await screen.findByLabelText('Subject')).toHaveValue('Your invoice INV-001')
  })
})

describe('SendEmailModal — edited render', () => {
  it('includes an edited subject in the POST and OMITS the unedited body_html', async () => {
    h.requestImpl = vi.fn(async () => ({ data: { ok: true } }))
    renderModal()
    await screen.findByText('customer@example.com')

    const subject = screen.getByLabelText('Subject')
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

  it('includes body_html when the body is edited', async () => {
    h.requestImpl = vi.fn(async () => ({ data: { ok: true } }))
    renderModal()
    await screen.findByText('customer@example.com')

    const body = await screen.findByLabelText('Body editor')
    await userEvent.clear(body)
    await userEvent.type(body, 'Custom body')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(h.requestImpl).toHaveBeenCalled())
    const config = (h.requestImpl as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      data: Record<string, unknown>
    }
    expect(config.data.body_was_edited).toBe(true)
    expect(config.data.body_html).toContain('Custom body')
  })
})

describe('SendEmailModal — send success', () => {
  it('on 200 closes the modal, fires onSent, and shows the success toast', async () => {
    h.requestImpl = vi.fn(async () => ({ data: { ok: true } }))
    const props = renderModal()
    await screen.findByText('customer@example.com')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(props.onSent).toHaveBeenCalledTimes(1))
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Email sent to customer@example.com')).toBeInTheDocument()
  })
})

describe('SendEmailModal — send failure', () => {
  it('503 shows an amber banner with Retry and preserves edited fields', async () => {
    h.requestImpl = vi.fn(async () => {
      throw { response: { status: 503, data: { detail: 'Delivery temporarily failed.' } } }
    })
    const props = renderModal()
    await screen.findByText('customer@example.com')

    const subject = screen.getByLabelText('Subject')
    await userEvent.clear(subject)
    await userEvent.type(subject, 'Edited subject')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('Delivery temporarily failed.')
    expect(banner).toHaveClass('bg-warn-soft')
    expect(within(banner).getByRole('button', { name: 'Retry' })).toBeInTheDocument()

    // Modal stays open, edited subject preserved, onSent not called.
    expect(props.onClose).not.toHaveBeenCalled()
    expect(props.onSent).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Subject')).toHaveValue('Edited subject')
  })

  it('400 shows a red banner without a Retry action', async () => {
    h.requestImpl = vi.fn(async () => {
      throw { response: { status: 400, data: { detail: 'Recipient address rejected.' } } }
    })
    renderModal()
    await screen.findByText('customer@example.com')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('Recipient address rejected.')
    expect(banner).toHaveClass('bg-danger-soft')
    expect(within(banner).queryByRole('button', { name: 'Retry' })).toBeNull()
  })
})

describe('SendEmailModal — load errors', () => {
  it('403 shows a red banner and disables Send', async () => {
    h.getImpl = (url) => {
      if (url === '/api/v2/email-preview') {
        return Promise.reject({ response: { status: 403, data: { detail: 'Forbidden entity.' } } })
      }
      return Promise.resolve({ data: {} })
    }
    renderModal()

    expect(await screen.findByText('Forbidden entity.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})
