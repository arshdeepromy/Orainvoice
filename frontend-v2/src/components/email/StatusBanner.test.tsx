import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StatusBanner } from './StatusBanner'

/**
 * StatusBanner unit tests (task 12.6, R21.4).
 *
 * The FailureKind→tone/message mapping is the PARENT's responsibility (the modal
 * picks tone + message + which actions to pass); these tests cover the banner
 * itself: it announces via role="alert", maps tone to design-system classes,
 * always renders Dismiss, and renders Retry / Copy details ONLY when their
 * handlers are provided — each wired to call the matching handler.
 */

describe('StatusBanner', () => {
  it('renders role="alert" with the message so screen readers announce it', () => {
    render(<StatusBanner tone="red" message="Recipient address rejected." onDismiss={vi.fn()} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Recipient address rejected.')
  })

  it('maps tone="red" to the danger tokens', () => {
    render(<StatusBanner tone="red" message="boom" onDismiss={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveClass('bg-danger-soft', 'text-danger')
  })

  it('maps tone="amber" to the warn tokens', () => {
    render(<StatusBanner tone="amber" message="transient" onDismiss={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveClass('bg-warn-soft', 'text-warn')
  })

  it('always renders a Dismiss (×) action and calls onDismiss', async () => {
    const onDismiss = vi.fn()
    render(<StatusBanner tone="red" message="boom" onDismiss={onDismiss} />)
    const dismiss = screen.getByRole('button', { name: 'Dismiss' })
    await userEvent.click(dismiss)
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('does NOT render Retry or Copy details when their handlers are absent', () => {
    render(<StatusBanner tone="red" message="boom" onDismiss={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Copy details' })).toBeNull()
  })

  it('renders Retry only when onRetry is provided and calls it', async () => {
    const onRetry = vi.fn()
    render(<StatusBanner tone="amber" message="try again" onDismiss={vi.fn()} onRetry={onRetry} />)
    const retry = screen.getByRole('button', { name: 'Retry' })
    await userEvent.click(retry)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('renders Copy details only when onCopyDetails is provided and calls it', async () => {
    const onCopyDetails = vi.fn()
    render(
      <StatusBanner
        tone="red"
        message="auth failed"
        onDismiss={vi.fn()}
        onCopyDetails={onCopyDetails}
      />,
    )
    const copy = screen.getByRole('button', { name: 'Copy details' })
    await userEvent.click(copy)
    expect(onCopyDetails).toHaveBeenCalledTimes(1)
  })
})
