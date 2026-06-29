/**
 * RecipientLegend — unit tests (task 6.1).
 *
 * Verifies the legend in isolation:
 *   • renders a per-recipient colour swatch using the index-based palette (R4.4);
 *   • selecting a recipient reports it to the parent as the active one (R4.2);
 *   • reflects the active recipient via aria-checked (R4.2);
 *   • each recipient control meets the 44×44 px minimum target (R10.1).
 *
 * _Requirements: 4.2, 4.4, 10.1_
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import RecipientLegend, { type LegendRecipient } from './RecipientLegend'
import { recipientColor } from './lib/fieldColors'

const RECIPIENTS: LegendRecipient[] = [
  { key: 10, name: 'Alex Tran', email: 'alex@example.com', signing_role: 'signer' },
  { key: 20, name: 'Sam Lee', email: 'sam@example.com', signing_role: 'viewer' },
]

describe('RecipientLegend', () => {
  it('renders a colour swatch per recipient using the index-based palette (R4.4)', () => {
    render(
      <RecipientLegend
        recipients={RECIPIENTS}
        activeRecipientKey={null}
        onSelectRecipient={() => {}}
      />,
    )

    const swatch0 = screen.getByTestId('recipient-swatch-10')
    const swatch1 = screen.getByTestId('recipient-swatch-20')
    expect(swatch0).toHaveStyle({ backgroundColor: recipientColor(0).solid })
    expect(swatch1).toHaveStyle({ backgroundColor: recipientColor(1).solid })
    // Distinct colours within palette capacity (R4.4).
    expect(recipientColor(0).solid).not.toBe(recipientColor(1).solid)
  })

  it('reports the selected recipient as active (R4.2)', () => {
    const onSelect = vi.fn()
    render(
      <RecipientLegend
        recipients={RECIPIENTS}
        activeRecipientKey={null}
        onSelectRecipient={onSelect}
      />,
    )

    fireEvent.click(screen.getByTestId('recipient-20'))
    expect(onSelect).toHaveBeenCalledWith(20)
  })

  it('reflects the active recipient via aria-checked (R4.2)', () => {
    render(
      <RecipientLegend
        recipients={RECIPIENTS}
        activeRecipientKey={10}
        onSelectRecipient={() => {}}
      />,
    )

    expect(screen.getByTestId('recipient-10')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('recipient-20')).toHaveAttribute('aria-checked', 'false')
  })

  it('renders each recipient control with a ≥44 px target (R10.1)', () => {
    render(
      <RecipientLegend
        recipients={RECIPIENTS}
        activeRecipientKey={null}
        onSelectRecipient={() => {}}
      />,
    )
    for (const r of RECIPIENTS) {
      expect(screen.getByTestId(`recipient-${r.key}`).className).toContain('min-h-[44px]')
    }
  })

  it('conveys recipient and role through the accessible name (R10.4 support)', () => {
    render(
      <RecipientLegend
        recipients={RECIPIENTS}
        activeRecipientKey={null}
        onSelectRecipient={() => {}}
      />,
    )
    expect(
      screen.getByRole('radio', { name: /Place fields for Alex Tran \(Signer\)/i }),
    ).toBeInTheDocument()
  })

  it('falls back to a generic name when no name/email is supplied', () => {
    render(
      <RecipientLegend
        recipients={[{ key: 5, signing_role: 'signer' }]}
        activeRecipientKey={null}
        onSelectRecipient={() => {}}
      />,
    )
    expect(screen.getByText('Recipient 1')).toBeInTheDocument()
  })
})
