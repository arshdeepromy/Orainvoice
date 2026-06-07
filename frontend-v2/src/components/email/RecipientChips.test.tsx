import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RecipientChips } from './RecipientChips'
import type { BlocklistEntry } from './types'

/**
 * RecipientChips unit tests (task 12.2, R21.4).
 *
 * Covers: email validation (valid → chip via onChange, invalid → inline "Invalid
 * email address"); soft/hard blocklist chip treatment (amber + warning icon /
 * red + error-octagon icon); override-once gating (only shown when
 * canOverrideHard, calls onOverrideHard); and chip removal flowing through
 * onChange.
 */

function softEntry(email: string): BlocklistEntry {
  return { email, kind: 'soft', reason: 'mailbox full', bounced_at: null }
}
function hardEntry(email: string): BlocklistEntry {
  return { email, kind: 'hard', reason: 'no such mailbox', bounced_at: null }
}

describe('RecipientChips — validation', () => {
  it('commits a valid email as a chip via onChange on Enter', async () => {
    const onChange = vi.fn()
    render(
      <RecipientChips
        label="To"
        values={[]}
        onChange={onChange}
        blocklist={[]}
        canOverrideHard={false}
      />,
    )
    const input = screen.getByLabelText(/^To/)
    await userEvent.type(input, 'jane@example.com{Enter}')
    expect(onChange).toHaveBeenCalledWith(['jane@example.com'])
  })

  it('shows an inline "Invalid email address" error for a malformed entry', async () => {
    const onChange = vi.fn()
    render(
      <RecipientChips
        label="To"
        values={[]}
        onChange={onChange}
        blocklist={[]}
        canOverrideHard={false}
      />,
    )
    const input = screen.getByLabelText(/^To/)
    await userEvent.type(input, 'not-an-email{Enter}')
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByText('Invalid email address')).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })

  it('renders the existing values as chips', () => {
    render(
      <RecipientChips
        label="Cc"
        values={['a@x.co', 'b@y.co']}
        onChange={vi.fn()}
        blocklist={[]}
        canOverrideHard={false}
      />,
    )
    expect(screen.getByText('a@x.co')).toBeInTheDocument()
    expect(screen.getByText('b@y.co')).toBeInTheDocument()
  })
})

describe('RecipientChips — blocklist styling', () => {
  it('styles a soft-bounced chip amber with a warning icon', () => {
    render(
      <RecipientChips
        label="To"
        values={['soft@x.co']}
        onChange={vi.fn()}
        blocklist={[softEntry('soft@x.co')]}
        canOverrideHard={false}
      />,
    )
    const chip = screen.getByText('soft@x.co').closest('span[title]')!
    expect(chip).toHaveClass('border-warn', 'bg-warn-soft', 'text-warn')
    // Icon accompanies the colour (colour is never the sole signal).
    expect(chip.querySelector('svg')).not.toBeNull()
  })

  it('styles a hard-bounced chip red with an error-octagon icon', () => {
    render(
      <RecipientChips
        label="To"
        values={['hard@x.co']}
        onChange={vi.fn()}
        blocklist={[hardEntry('hard@x.co')]}
        canOverrideHard={false}
      />,
    )
    const chip = screen.getByText('hard@x.co').closest('span[title]')!
    expect(chip).toHaveClass('border-danger', 'bg-danger-soft', 'text-danger')
    expect(chip.querySelector('svg')).not.toBeNull()
  })

  it('warns to remove a hard-bounced recipient when the user cannot override', () => {
    render(
      <RecipientChips
        label="To"
        values={['hard@x.co']}
        onChange={vi.fn()}
        blocklist={[hardEntry('hard@x.co')]}
        canOverrideHard={false}
      />,
    )
    expect(screen.getByText(/Remove it to enable sending/i)).toBeInTheDocument()
  })
})

describe('RecipientChips — override-once gating', () => {
  it('hides "Override once" for a hard-bounced chip when canOverrideHard is false', () => {
    render(
      <RecipientChips
        label="To"
        values={['hard@x.co']}
        onChange={vi.fn()}
        blocklist={[hardEntry('hard@x.co')]}
        canOverrideHard={false}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Override once' })).toBeNull()
  })

  it('shows "Override once" only when canOverrideHard, and calls onOverrideHard', async () => {
    const onOverrideHard = vi.fn()
    render(
      <RecipientChips
        label="To"
        values={['hard@x.co']}
        onChange={vi.fn()}
        blocklist={[hardEntry('hard@x.co')]}
        canOverrideHard
        onOverrideHard={onOverrideHard}
      />,
    )
    const override = screen.getByRole('button', { name: 'Override once' })
    await userEvent.click(override)
    expect(onOverrideHard).toHaveBeenCalledTimes(1)
  })

  it('does not render "Override once" for a soft-bounced chip even when canOverrideHard', () => {
    render(
      <RecipientChips
        label="To"
        values={['soft@x.co']}
        onChange={vi.fn()}
        blocklist={[softEntry('soft@x.co')]}
        canOverrideHard
        onOverrideHard={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Override once' })).toBeNull()
  })
})

describe('RecipientChips — removal', () => {
  it('removes a chip through onChange when its remove button is clicked', async () => {
    const onChange = vi.fn()
    render(
      <RecipientChips
        label="To"
        values={['a@x.co', 'b@y.co']}
        onChange={onChange}
        blocklist={[]}
        canOverrideHard={false}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Remove a@x.co' }))
    expect(onChange).toHaveBeenCalledWith(['b@y.co'])
  })
})
