/**
 * SigningOrderControls — unit tests (task 19.1, Requirement 15).
 *
 * Verifies the signing-order block + its pure helpers:
 *   • the mode toggle defaults are reported correctly and switching reports the
 *     chosen mode (R15.1, R15.2);
 *   • while sequential, every signer is shown with a distinct 1-based position
 *     and reorder controls that report the new order (R15.3);
 *   • viewers are excluded from positions but still listed (R15.6);
 *   • the advisory note is shown for sequential;
 *   • `reconcileSignerOrder` / `signingPositionByKey` are pure and correct.
 *
 * _Requirements: 15.1, 15.2, 15.3, 15.6_
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import SigningOrderControls, {
  reconcileSignerOrder,
  signingPositionByKey,
  type SigningOrderRecipient,
} from './SigningOrderControls'

const SIGNERS_AND_VIEWER: SigningOrderRecipient[] = [
  { key: 1, name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' },
  { key: 2, name: 'Sam Lee', email: 'sam@example.com', signing_role: 'signer' },
  { key: 3, name: 'Viewer Vee', email: 'vee@example.com', signing_role: 'viewer' },
]

describe('SigningOrderControls — pure helpers', () => {
  it('reconcileSignerOrder keeps only signer keys, preserves order, appends new (R15.3, R15.6)', () => {
    // Fresh list with no prior order → signers in recipient order, viewer dropped.
    expect(reconcileSignerOrder(SIGNERS_AND_VIEWER, [])).toEqual([1, 2])

    // Prior order preserved; a removed key is dropped; a new signer appended.
    const recipients: SigningOrderRecipient[] = [
      { key: 2, signing_role: 'signer' },
      { key: 4, signing_role: 'signer' },
    ]
    expect(reconcileSignerOrder(recipients, [2, 1])).toEqual([2, 4])

    // Flipping a signer to viewer drops it from the order (R15.6).
    const flipped: SigningOrderRecipient[] = [
      { key: 1, signing_role: 'viewer' },
      { key: 2, signing_role: 'signer' },
    ]
    expect(reconcileSignerOrder(flipped, [1, 2])).toEqual([2])
  })

  it('signingPositionByKey yields distinct, contiguous 1-based positions (R15.3)', () => {
    const positions = signingPositionByKey([5, 9, 7])
    expect(positions.get(5)).toBe(1)
    expect(positions.get(9)).toBe(2)
    expect(positions.get(7)).toBe(3)
    expect([...positions.values()].sort()).toEqual([1, 2, 3])
  })
})

describe('SigningOrderControls — UI', () => {
  it('defaults to parallel and reports a mode switch (R15.1, R15.2)', () => {
    const onModeChange = vi.fn()
    render(
      <SigningOrderControls
        recipients={SIGNERS_AND_VIEWER}
        mode="parallel"
        onModeChange={onModeChange}
        signerOrder={[1, 2]}
        onReorder={() => {}}
      />,
    )

    // Parallel selected; no reorder list shown.
    expect(screen.getByTestId('signing-order-mode-parallel')).toHaveAttribute(
      'aria-checked',
      'true',
    )
    expect(screen.queryByTestId('signing-order-list')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('signing-order-mode-sequential'))
    expect(onModeChange).toHaveBeenCalledWith('sequential')
  })

  it('shows signers with 1-based positions, an advisory note, and excludes viewers (R15.3, R15.6)', () => {
    render(
      <SigningOrderControls
        recipients={SIGNERS_AND_VIEWER}
        mode="sequential"
        onModeChange={() => {}}
        signerOrder={[1, 2]}
        onReorder={() => {}}
      />,
    )

    const list = screen.getByTestId('signing-order-list')
    expect(list).toBeInTheDocument()
    expect(screen.getByTestId('signing-order-item-1')).toHaveAttribute('data-position', '1')
    expect(screen.getByTestId('signing-order-item-2')).toHaveAttribute('data-position', '2')

    // Advisory note about engine-dependent enforcement.
    expect(screen.getByText(/order enforcement depends on the signing engine/i)).toBeInTheDocument()

    // Viewer listed separately, with no position (R15.6).
    expect(screen.getByTestId('signing-order-viewer-3')).toBeInTheDocument()
    expect(screen.queryByTestId('signing-order-item-3')).not.toBeInTheDocument()
  })

  it('reorders signers via the move controls (R15.3)', () => {
    const onReorder = vi.fn()
    render(
      <SigningOrderControls
        recipients={SIGNERS_AND_VIEWER}
        mode="sequential"
        onModeChange={() => {}}
        signerOrder={[1, 2]}
        onReorder={onReorder}
      />,
    )

    // Move the second signer up → [2, 1].
    fireEvent.click(screen.getByTestId('signing-order-up-2'))
    expect(onReorder).toHaveBeenCalledWith([2, 1])

    // Move the first signer down → [2, 1].
    onReorder.mockClear()
    fireEvent.click(screen.getByTestId('signing-order-down-1'))
    expect(onReorder).toHaveBeenCalledWith([2, 1])
  })

  it('disables move controls at the boundaries (first cannot go up, last cannot go down)', () => {
    render(
      <SigningOrderControls
        recipients={SIGNERS_AND_VIEWER}
        mode="sequential"
        onModeChange={() => {}}
        signerOrder={[1, 2]}
        onReorder={() => {}}
      />,
    )
    expect(screen.getByTestId('signing-order-up-1')).toBeDisabled()
    expect(screen.getByTestId('signing-order-down-2')).toBeDisabled()
  })
})
