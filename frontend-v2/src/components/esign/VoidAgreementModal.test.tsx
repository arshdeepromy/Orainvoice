import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VoidAgreementModal } from './VoidAgreementModal'
import type { EnvelopeOut } from '@/api/esign'

/**
 * VoidAgreementModal unit tests (feature: esignature-integration, task 17.5).
 *
 * The modal is self-contained: it consumes the `@/ui` primitives and an
 * injectable `voidEnvelopeFn` (defaults to the real esign client). That
 * injection point lets every test drive the in-flight / happy / error paths
 * with zero network and without mocking `@/api/client`, so no context
 * providers are needed here.
 *
 * Coverage (R7.1 / R7.3 / R16.1):
 *   - while the void POST is in flight the Confirm button is disabled and shows
 *     a spinner, and Cancel is disabled too (the request is never orphaned)
 *   - on failure the modal surfaces the server `{ message, code }` body inline
 *     (e.g. the R7.3 already-terminal `not_voidable` message) and re-enables
 *     the buttons so the user can dismiss / retry
 *   - the happy path resolves, calls `onVoided` with the updated envelope, then
 *     `onClose`
 *
 * _Requirements: 7.1, 7.3_
 */

/** A deferred promise whose resolve/reject we control from the test body. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** A fully-populated, non-terminal envelope the modal is asked to void. */
function envelope(overrides: Partial<EnvelopeOut> = {}): EnvelopeOut {
  return {
    id: 'env-1',
    agreement_type: 'sales_agreement',
    originating_entity_type: 'invoice',
    originating_entity_id: 'inv-9',
    status: 'sent',
    recipients: [],
    signed_document_url: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('VoidAgreementModal — rendering', () => {
  it('renders the confirmation copy and actions when an envelope is supplied', () => {
    render(<VoidAgreementModal envelope={envelope()} onClose={vi.fn()} />)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/This cannot be undone/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Void agreement' })).toBeInTheDocument()
  })

  it('renders nothing when no envelope is supplied', () => {
    render(<VoidAgreementModal envelope={null} onClose={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('VoidAgreementModal — in-flight request', () => {
  it('disables Confirm + Cancel and shows a spinner while the void is in flight', async () => {
    const user = userEvent.setup()
    const d = deferred<EnvelopeOut>()
    const voidEnvelopeFn = vi.fn(() => d.promise)

    render(
      <VoidAgreementModal
        envelope={envelope()}
        onClose={vi.fn()}
        voidEnvelopeFn={voidEnvelopeFn}
      />,
    )

    const confirm = screen.getByRole('button', { name: 'Void agreement' })
    const cancel = screen.getByRole('button', { name: 'Cancel' })

    await user.click(confirm)

    // Request issued and still pending: Confirm is disabled + spinning, Cancel
    // is disabled so the in-flight request can't be orphaned.
    expect(voidEnvelopeFn).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(confirm).toBeDisabled())
    expect(cancel).toBeDisabled()
    expect(screen.getByTestId('button-spinner')).toBeInTheDocument()

    // Resolve the request to let the component settle.
    d.resolve(envelope({ status: 'voided' }))
    await waitFor(() => expect(voidEnvelopeFn).toHaveBeenCalledTimes(1))
  })
})

describe('VoidAgreementModal — server error', () => {
  it('surfaces the server { message, code } body on failure and re-enables the buttons', async () => {
    const user = userEvent.setup()
    // R7.3: a stale terminal envelope comes back as a humanized 409.
    const voidEnvelopeFn = vi.fn(async () => {
      throw {
        response: {
          data: {
            message: 'This agreement can no longer be voided.',
            code: 'not_voidable',
          },
        },
      }
    })
    const onVoided = vi.fn()
    const onClose = vi.fn()

    render(
      <VoidAgreementModal
        envelope={envelope()}
        onClose={onClose}
        onVoided={onVoided}
        voidEnvelopeFn={voidEnvelopeFn}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Void agreement' }))

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('This agreement can no longer be voided.')
    expect(banner).toHaveTextContent('not_voidable')

    // The modal stays open on error and the buttons are usable again.
    expect(onVoided).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Void agreement' })).not.toBeDisabled(),
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).not.toBeDisabled()
  })

  it('falls back to a generic message when the server body carries no message', async () => {
    const user = userEvent.setup()
    const voidEnvelopeFn = vi.fn(async () => {
      throw new Error('network down')
    })

    render(
      <VoidAgreementModal
        envelope={envelope()}
        onClose={vi.fn()}
        voidEnvelopeFn={voidEnvelopeFn}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Void agreement' }))

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('We could not void this agreement. Please try again.')
  })
})

describe('VoidAgreementModal — happy path', () => {
  it('calls onVoided with the updated envelope then onClose on success', async () => {
    const user = userEvent.setup()
    const voided = envelope({ status: 'voided' })
    const voidEnvelopeFn = vi.fn(async () => voided)
    const onVoided = vi.fn()
    const onClose = vi.fn()

    render(
      <VoidAgreementModal
        envelope={envelope()}
        onClose={onClose}
        onVoided={onVoided}
        voidEnvelopeFn={voidEnvelopeFn}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Void agreement' }))

    await waitFor(() => expect(onVoided).toHaveBeenCalledWith(voided))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
