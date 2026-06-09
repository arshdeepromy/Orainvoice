/**
 * F1 — computeMissingConsent mirrors the backend gate.
 *
 * Feature: customer-reminder-consent
 */

import { describe, it, expect } from 'vitest'
import {
  computeMissingConsent,
  type RemindersConsentRecord,
  type ReminderConfigEntry,
  type ReminderCategory,
} from '../customers'

function entry(channel: 'sms' | 'email' | 'both', enabled = true): ReminderConfigEntry {
  return { enabled, days_before: 30, channel }
}

function consent(
  ...pairs: Array<[ReminderCategory, 'sms' | 'email' | 'both']>
): RemindersConsentRecord {
  return {
    given_at: '2026-06-08T00:00:00Z',
    source: 'kiosk_self_checkin',
    consent_text_version: 'v1',
    entries: pairs.map(([category, channel]) => ({ vehicle_id: null, category, channel })),
  }
}

describe('computeMissingConsent', () => {
  it('flags an enabled pair with no existing consent', () => {
    const missing = computeMissingConsent(null, { wof_expiry: entry('sms') })
    expect(missing).toEqual([{ category: 'wof_expiry', channel: 'sms' }])
  })

  it('returns empty when the pair is already covered', () => {
    const missing = computeMissingConsent(consent(['wof_expiry', 'sms']), {
      wof_expiry: entry('sms'),
    })
    expect(missing).toEqual([])
  })

  it('treats "both" coverage as covering sms and email', () => {
    const missing = computeMissingConsent(consent(['service_due', 'both']), {
      service_due: entry('email'),
    })
    expect(missing).toEqual([])
  })

  it('expands an uncovered "both" requirement into two missing entries', () => {
    const missing = computeMissingConsent(null, { cof_expiry: entry('both') })
    expect(missing).toEqual([
      { category: 'cof_expiry', channel: 'sms' },
      { category: 'cof_expiry', channel: 'email' },
    ])
  })

  it('ignores disabled categories (no gate)', () => {
    const missing = computeMissingConsent(null, {
      registration_expiry: entry('sms', false),
    })
    expect(missing).toEqual([])
  })

  it('covers all four categories and only reports the uncovered ones', () => {
    const existing = consent(['service_due', 'email'], ['wof_expiry', 'sms'])
    const missing = computeMissingConsent(existing, {
      service_due: entry('email'), // covered
      wof_expiry: entry('sms'), // covered
      cof_expiry: entry('sms'), // missing
      registration_expiry: entry('both'), // missing x2
    })
    expect(missing).toEqual([
      { category: 'cof_expiry', channel: 'sms' },
      { category: 'registration_expiry', channel: 'sms' },
      { category: 'registration_expiry', channel: 'email' },
    ])
  })
})
