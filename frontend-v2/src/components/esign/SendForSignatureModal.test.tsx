import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SendForSignatureModal } from './SendForSignatureModal'
import type { SendForSignatureModalProps } from './SendForSignatureModal'
import { AGREEMENT_TYPES } from '@/api/esign'
import type { EnvelopeCreate, EnvelopeOut } from '@/api/esign'

/**
 * SendForSignatureModal unit tests — the **two-step flow** (feature:
 * esignature-field-placement, task 13.2; built on esignature-integration task
 * 17.3).
 *
 * Step 1 (Compose) is the surface-agnostic composer: PDF + agreement type +
 * recipients, gated behind a **Continue to field placement** action. Step 2
 * mounts the `FieldPlacementEditor`; the actual send happens at the end of
 * step 2, carrying the placed Field_Set.
 *
 * The editor imports `pdfjs-dist` (which needs a real canvas / DOMMatrix), and
 * its drag/render behaviour is exercised by its own test suite. Here we keep
 * the modal's tests focused on its own responsibilities — the step transition
 * and the payload it assembles for the send — by mocking the editor with a tiny
 * stub that surfaces an `onSend` / `onCancel` trigger using the recipient list
 * the modal handed it.
 *
 * Coverage:
 *   - renders the title + all step-1 fields when `open`, and nothing when closed
 *   - offers all five agreement types when `allowedAgreementTypes` lists them
 *   - the agreement-type options reflect the entity-derived subset (staff vs
 *     invoice) when no explicit allow-list is supplied
 *   - renders repeatable recipient rows (name / email / role) and can add one
 *   - inline validation blocks the step-1 → step-2 transition (createEnvelopeFn
 *     NOT called) when a recipient is empty / has an invalid email
 *   - the happy path advances to step 2 and, on the editor's send, calls the
 *     injected `createEnvelopeFn` with a typed payload bound to the originating
 *     entity AND carrying the placed Field_Set, then `onSent` then `onClose`
 *   - a rejected send leaves the modal open (onSent / onClose not called) so the
 *     editor can surface the error and retain the set for retry (R11.4)
 */

/** Captures the props the mocked editor last received (for trigger helpers). */
const editorProps: { current: MockEditorProps | null } = { current: null }

interface MockEditorRecipient {
  key: number
  name?: string
  email?: string
  signing_role: 'signer' | 'viewer'
}
interface MockPlacedField {
  clientId: string
  type: string
  page: number
  rect: { positionX: number; positionY: number; width: number; height: number }
  recipientKey: number
  required: boolean
}
interface MockEditorProps {
  file: File | null
  recipients: MockEditorRecipient[]
  onSend?: (fields: MockPlacedField[], signal: AbortSignal) => Promise<void>
  onCancel?: () => void
}

// Mock the heavy PDF editor: it pulls in `pdfjs-dist`, which can't render in
// jsdom. The stub records its props and exposes buttons that drive `onSend`
// (with a single signature field assigned to the first recipient) and `onCancel`.
vi.mock('./fieldplacement/FieldPlacementEditor', () => ({
  FieldPlacementEditor: (props: MockEditorProps) => {
    editorProps.current = props
    const firstKey = props.recipients?.[0]?.key ?? 0
    const placedFields: MockPlacedField[] = [
      {
        clientId: 'f1',
        type: 'signature',
        page: 1,
        rect: { positionX: 10, positionY: 20, width: 30, height: 10 },
        recipientKey: firstKey,
        required: true,
      },
    ]
    return (
      <div data-testid="mock-editor">
        <button
          type="button"
          onClick={() => {
            void props.onSend?.(placedFields, new AbortController().signal).catch(() => {})
          }}
        >
          Send for signature
        </button>
        <button type="button" onClick={() => props.onCancel?.()}>
          Editor cancel
        </button>
      </div>
    )
  },
}))

/** A non-empty fake PDF File the client-side picker accepts. */
function pdfFile(name = 'agreement.pdf'): File {
  return new File(['%PDF-1.4\n%mock pdf bytes'], name, { type: 'application/pdf' })
}

/** A fully-populated envelope the injected createEnvelopeFn resolves with. */
function sentEnvelope(overrides: Partial<EnvelopeOut> = {}): EnvelopeOut {
  return {
    id: 'env-1',
    agreement_type: 'nda',
    originating_entity_type: 'staff',
    originating_entity_id: 'staff-7',
    status: 'sent',
    recipients: [
      {
        id: 'rec-1',
        name: 'Jane Doe',
        email: 'jane@example.com',
        signing_role: 'SIGNER',
        recipient_status: 'pending',
      },
    ],
    signed_document_url: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderModal(overrides: Partial<SendForSignatureModalProps> = {}) {
  const props: SendForSignatureModalProps = {
    open: true,
    onClose: vi.fn(),
    originatingEntityType: 'staff',
    originatingEntityId: 'staff-7',
    onSent: vi.fn(),
    createEnvelopeFn: vi.fn(async () => sentEnvelope()),
    ...overrides,
  }
  const utils = render(<SendForSignatureModal {...props} />)
  return { props, ...utils }
}

/** Fill step 1 with a valid PDF + agreement type + one recipient. */
async function fillStep1(user: ReturnType<typeof userEvent.setup>, file: File) {
  await user.upload(
    screen.getByLabelText('Select a PDF document to send for signature'),
    file,
  )
  await user.selectOptions(screen.getByLabelText('Agreement type'), 'nda')
  await user.type(screen.getByLabelText('Name'), 'Jane Doe')
  await user.type(screen.getByLabelText('Email'), 'jane@example.com')
}

describe('SendForSignatureModal — rendering', () => {
  it('renders the title and all step-1 fields when open', () => {
    renderModal()

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Send for signature' })).toBeInTheDocument()
    // PDF picker, agreement-type select, recipient row, and the step-1 action.
    expect(screen.getByText('Document (PDF)')).toBeInTheDocument()
    expect(screen.getByLabelText('Agreement type')).toBeInTheDocument()
    expect(screen.getByText('Recipient 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Continue to field placement' }),
    ).toBeInTheDocument()
    // The field-placement editor only mounts in step 2.
    expect(screen.queryByTestId('mock-editor')).toBeNull()
  })

  it('renders nothing when closed', () => {
    renderModal({ open: false })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByText('Document (PDF)')).toBeNull()
  })
})

describe('SendForSignatureModal — agreement-type options', () => {
  it('offers all five agreement types when explicitly allowed', () => {
    renderModal({ allowedAgreementTypes: AGREEMENT_TYPES })

    const select = screen.getByLabelText('Agreement type')
    for (const label of [
      'Sales agreement',
      'Purchase agreement',
      'NDA',
      'Employment agreement',
      'Contractor agreement',
    ]) {
      expect(within(select).getByRole('option', { name: label })).toBeInTheDocument()
    }
  })

  it('reflects the staff entity-derived subset when no allow-list is given', () => {
    renderModal({ originatingEntityType: 'staff' })

    const select = screen.getByLabelText('Agreement type')
    expect(within(select).getByRole('option', { name: 'NDA' })).toBeInTheDocument()
    expect(within(select).getByRole('option', { name: 'Employment agreement' })).toBeInTheDocument()
    expect(
      within(select).getByRole('option', { name: 'Contractor agreement' }),
    ).toBeInTheDocument()
    // Sales/purchase are an invoice/quote concern — not offered for staff.
    expect(within(select).queryByRole('option', { name: 'Sales agreement' })).toBeNull()
    expect(within(select).queryByRole('option', { name: 'Purchase agreement' })).toBeNull()
  })

  it('reflects the invoice entity-derived subset when no allow-list is given', () => {
    renderModal({ originatingEntityType: 'invoice', originatingEntityId: 'inv-9' })

    const select = screen.getByLabelText('Agreement type')
    expect(within(select).getByRole('option', { name: 'Sales agreement' })).toBeInTheDocument()
    expect(within(select).getByRole('option', { name: 'Purchase agreement' })).toBeInTheDocument()
    expect(within(select).queryByRole('option', { name: 'NDA' })).toBeNull()
  })
})

describe('SendForSignatureModal — recipient rows', () => {
  it('starts with one recipient row and can add another', async () => {
    const user = userEvent.setup()
    renderModal()

    expect(screen.getByText('Recipient 1')).toBeInTheDocument()
    expect(screen.queryByText('Recipient 2')).toBeNull()

    await user.click(screen.getByRole('button', { name: '+ Add recipient' }))

    expect(screen.getByText('Recipient 2')).toBeInTheDocument()
    // Each row renders a name/email input (queried by placeholder since the
    // primitive reuses the same derived id across rows).
    expect(screen.getAllByPlaceholderText('Full name')).toHaveLength(2)
    expect(screen.getAllByPlaceholderText('name@example.com')).toHaveLength(2)
  })
})

describe('SendForSignatureModal — validation blocks the step transition', () => {
  it('stays on step 1 when the recipient fields are empty', async () => {
    const user = userEvent.setup()
    const createEnvelopeFn = vi.fn(async () => sentEnvelope())
    renderModal({ createEnvelopeFn })

    // Pick a PDF + agreement type so the Continue button is enabled, but leave
    // the recipient name/email blank so validation must block the transition.
    await user.upload(
      screen.getByLabelText('Select a PDF document to send for signature'),
      pdfFile(),
    )
    await user.selectOptions(screen.getByLabelText('Agreement type'), 'nda')

    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))

    expect(createEnvelopeFn).not.toHaveBeenCalled()
    expect(screen.queryByTestId('mock-editor')).toBeNull()
    expect(screen.getByText('Enter a name.')).toBeInTheDocument()
    expect(screen.getByText('Enter an email address.')).toBeInTheDocument()
  })

  it('stays on step 1 when the email is syntactically invalid', async () => {
    const user = userEvent.setup()
    const createEnvelopeFn = vi.fn(async () => sentEnvelope())
    renderModal({ createEnvelopeFn })

    await user.upload(
      screen.getByLabelText('Select a PDF document to send for signature'),
      pdfFile(),
    )
    await user.selectOptions(screen.getByLabelText('Agreement type'), 'nda')
    await user.type(screen.getByLabelText('Name'), 'Jane Doe')
    await user.type(screen.getByLabelText('Email'), 'not-an-email')

    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))

    expect(createEnvelopeFn).not.toHaveBeenCalled()
    expect(screen.queryByTestId('mock-editor')).toBeNull()
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument()
  })
})

describe('SendForSignatureModal — happy path (two-step)', () => {
  it('advances to step 2 then sends a typed payload with the placed Field_Set, then onSent + onClose', async () => {
    const user = userEvent.setup()
    const envelope = sentEnvelope()
    const createEnvelopeFn = vi.fn<
      (file: Blob | File, payload: EnvelopeCreate, signal?: AbortSignal) => Promise<EnvelopeOut>
    >(async () => envelope)
    const onSent = vi.fn()
    const onClose = vi.fn()
    const file = pdfFile()

    renderModal({
      originatingEntityType: 'staff',
      originatingEntityId: 'staff-7',
      createEnvelopeFn,
      onSent,
      onClose,
    })

    await fillStep1(user, file)
    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))

    // Step 2: the (mocked) editor is mounted with the file + recipients.
    expect(screen.getByTestId('mock-editor')).toBeInTheDocument()
    expect(editorProps.current?.file).toBe(file)
    expect(editorProps.current?.recipients).toHaveLength(1)

    // Trigger the editor's send (one signature field on the first recipient).
    await user.click(screen.getByRole('button', { name: 'Send for signature' }))

    await waitFor(() => expect(createEnvelopeFn).toHaveBeenCalledTimes(1))

    const [sentFile, payload] = createEnvelopeFn.mock.calls[0]
    expect(sentFile).toBe(file)
    expect(payload).toEqual({
      agreement_type: 'nda',
      originating_entity_type: 'staff',
      originating_entity_id: 'staff-7',
      recipients: [{ name: 'Jane Doe', email: 'jane@example.com', signing_role: 'signer' }],
      signing_order_mode: 'parallel',
      fields: [
        {
          type: 'signature',
          page: 1,
          recipient_index: 0,
          position_x: 10,
          position_y: 20,
          width: 30,
          height: 10,
          required: true,
          client_id: 'f1',
        },
      ],
    })

    await waitFor(() => expect(onSent).toHaveBeenCalledWith(envelope))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('attaches signing_order_mode + per-recipient order for a sequential send (R15.3, R15.4, R15.6)', async () => {
    const user = userEvent.setup()
    const envelope = sentEnvelope()
    const createEnvelopeFn = vi.fn<
      (file: Blob | File, payload: EnvelopeCreate, signal?: AbortSignal) => Promise<EnvelopeOut>
    >(async () => envelope)
    const file = pdfFile()

    renderModal({ originatingEntityType: 'staff', originatingEntityId: 'staff-7', createEnvelopeFn })

    // Two signers + one viewer.
    await user.upload(
      screen.getByLabelText('Select a PDF document to send for signature'),
      file,
    )
    await user.selectOptions(screen.getByLabelText('Agreement type'), 'nda')

    const names = () => screen.getAllByPlaceholderText('Full name')
    const emails = () => screen.getAllByPlaceholderText('name@example.com')

    await user.type(names()[0], 'Jane Doe')
    await user.type(emails()[0], 'jane@example.com')

    await user.click(screen.getByRole('button', { name: '+ Add recipient' }))
    await user.type(names()[1], 'Bob Roe')
    await user.type(emails()[1], 'bob@example.com')

    await user.click(screen.getByRole('button', { name: '+ Add recipient' }))
    await user.type(names()[2], 'Vee Lee')
    await user.type(emails()[2], 'vee@example.com')
    // Third recipient is a viewer. Role selects share a derived id with their
    // label (like the name/email inputs), so target the combobox directly.
    const roleCombos = screen
      .getAllByRole('combobox')
      .filter((c) => within(c).queryByRole('option', { name: 'Viewer' }) != null)
    await user.selectOptions(roleCombos[2], 'viewer')

    // Switch to sequential and put Bob first.
    await user.click(screen.getByTestId('signing-order-mode-sequential'))
    await user.click(
      screen.getByRole('button', { name: 'Move Bob Roe earlier in the signing order' }),
    )

    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))
    await user.click(screen.getByRole('button', { name: 'Send for signature' }))

    await waitFor(() => expect(createEnvelopeFn).toHaveBeenCalledTimes(1))
    const [, payload] = createEnvelopeFn.mock.calls[0]
    expect(payload.signing_order_mode).toBe('sequential')

    const byEmail = Object.fromEntries(payload.recipients.map((r) => [r.email, r]))
    // Bob was moved to position 1; Jane is position 2 (R15.3).
    expect(byEmail['bob@example.com'].order).toBe(1)
    expect(byEmail['jane@example.com'].order).toBe(2)
    // The viewer carries no position but stays on the document (R15.6).
    expect(byEmail['vee@example.com'].order).toBeUndefined()
    expect(byEmail['vee@example.com'].signing_role).toBe('viewer')
  })
})

describe('SendForSignatureModal — send failure', () => {
  it('keeps the modal open (no onSent / onClose) when the send is rejected, so the set can be retried', async () => {
    const user = userEvent.setup()
    const createEnvelopeFn = vi.fn(async () => {
      throw {
        response: {
          data: {
            message: 'The e-signature integration is not configured.',
            code: 'integration_not_configured',
          },
        },
      }
    })
    const onSent = vi.fn()
    const onClose = vi.fn()
    const file = pdfFile()

    renderModal({ createEnvelopeFn, onSent, onClose })

    await fillStep1(user, file)
    await user.click(screen.getByRole('button', { name: 'Continue to field placement' }))
    await user.click(screen.getByRole('button', { name: 'Send for signature' }))

    await waitFor(() => expect(createEnvelopeFn).toHaveBeenCalledTimes(1))

    // The editor (real component) surfaces the humanized error and retains the
    // Field_Set; the modal itself must not advance / close on a failed send.
    expect(onSent).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByTestId('mock-editor')).toBeInTheDocument()
  })
})
