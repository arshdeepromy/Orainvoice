/**
 * F5 — Reminder Consent section on the Customer Profile.
 *
 * Feature: customer-reminder-consent
 * Covers presence (headline + entries + revocations + version) and absence
 * (empty state) of a consent record.
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ReminderConsentSection } from '../ReminderConsentSection'
import type {
  RemindersConsentRecord,
  RemindersRevocationRecord,
} from '@/api/customers'

const consent: RemindersConsentRecord = {
  given_at: '2026-06-08T03:00:00Z',
  source: 'manually_recorded_by_staff:phone',
  recorded_by_user_email: 'staff@example.com',
  consent_text_version: '2026-06-08-v1',
  entries: [
    { vehicle_id: 'veh-1', category: 'wof_expiry', channel: 'sms' },
    { vehicle_id: null, category: 'service_due', channel: 'both' },
  ],
}

const revocations: RemindersRevocationRecord[] = [
  {
    revoked_at: '2026-06-09T01:00:00Z',
    source: 'manually_recorded_by_staff:phone',
    recorded_by_user_id: 'u1',
    recorded_by_user_email: 'staff@example.com',
    channel: 'sms',
    categories_affected: ['wof_expiry'],
    reason_note: 'Customer asked to stop',
  },
]

describe('ReminderConsentSection', () => {
  it('renders the headline, entries, version, and revocation history', () => {
    render(
      <ReminderConsentSection
        consent={consent}
        revocations={revocations}
        enabledByCategory={{ wof_expiry: true, service_due: true }}
        vehicleRegoById={{ 'veh-1': 'ABC123' }}
      />,
    )
    expect(screen.getByTestId('consent-section')).toBeInTheDocument()
    expect(screen.getByText(/Manually recorded \(phone\)/)).toBeInTheDocument()
    expect(screen.getByText('2026-06-08-v1')).toBeInTheDocument()
    expect(screen.getByTestId('consent-entry-wof_expiry-sms')).toBeInTheDocument()
    expect(screen.getByTestId('consent-entry-service_due-both')).toBeInTheDocument()
    expect(screen.getByText('ABC123')).toBeInTheDocument()
    expect(screen.getByText('Customer-wide')).toBeInTheDocument()
    // Revocation history table present.
    expect(screen.getByTestId('revocations-table')).toBeInTheDocument()
    expect(screen.getByText('Customer asked to stop')).toBeInTheDocument()
  })

  it('renders the empty state when there is no consent record', () => {
    render(<ReminderConsentSection consent={null} revocations={[]} />)
    expect(screen.getByTestId('consent-empty')).toBeInTheDocument()
    expect(screen.getByText(/No consent on record/i)).toBeInTheDocument()
  })

  it('shows a Revoke control only for active entries when onRevoke is provided', () => {
    render(
      <ReminderConsentSection
        consent={consent}
        revocations={[]}
        enabledByCategory={{ wof_expiry: true, service_due: false }}
        onRevoke={() => {}}
      />,
    )
    expect(screen.getByTestId('revoke-wof_expiry-sms')).toBeInTheDocument()
    // service_due is disabled → no revoke control.
    expect(screen.queryByTestId('revoke-service_due-both')).not.toBeInTheDocument()
  })
})
