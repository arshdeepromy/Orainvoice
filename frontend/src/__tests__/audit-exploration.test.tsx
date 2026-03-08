/**
 * Bug condition exploration tests for frontend contract mismatches.
 *
 * These tests encode the EXPECTED (correct) behavior. They are designed to
 * FAIL on the current unfixed code, proving the bugs exist. After fixes are
 * applied, these same tests should PASS.
 *
 * **Validates: Requirements 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19**
 *
 * Property 1: Fault Condition — Frontend-Backend Contract Mismatches
 */

import { describe, it, expect } from 'vitest'
import * as fs from 'fs'
import * as path from 'path'
import * as fc from 'fast-check'

// Helper to read source files for static analysis
function readSource(relativePath: string): string {
  const fullPath = path.resolve(__dirname, '..', '..', '..', relativePath)
  return fs.readFileSync(fullPath, 'utf-8')
}

// ===================================================================
// SMTP CONFIGURATION PANEL (Req 1.8)
// ===================================================================

describe('Integrations SMTP Panel — Contract Exploration', () => {
  /**
   * Req 1.8: SMTP panel renders only 4 fields but backend SmtpConfigRequest
   * expects 10 fields. Assert all 10 fields are present.
   *
   * **Validates: Requirements 1.8**
   */
  it('should define all 10 SmtpConfigRequest fields in SMTP integration', () => {
    const source = readSource('frontend/src/pages/admin/Integrations.tsx')

    // The backend SmtpConfigRequest expects these 10 fields:
    const requiredFields = [
      'provider',
      'from_email',
      'host',
      'port',
      'username',
      'password',
      'api_key',
      'domain',
      'from_name',
      'reply_to',
    ]

    // Extract the smtp field definitions section
    const smtpSectionMatch = source.match(/smtp:\s*\[([\s\S]*?)\]/m)
    expect(smtpSectionMatch).toBeTruthy()
    const smtpSection = smtpSectionMatch![1]

    const missingFields: string[] = []
    for (const field of requiredFields) {
      // Check if the field key appears in the smtp section
      if (!smtpSection.includes(`'${field}'`) && !smtpSection.includes(`"${field}"`)) {
        missingFields.push(field)
      }
    }

    expect(missingFields).toEqual([])
  })
})

// ===================================================================
// OVERDUE RULES (Req 1.9, 1.10)
// ===================================================================

describe('OverdueRules — Contract Exploration', () => {
  const source = readSource('frontend/src/pages/notifications/OverdueRules.tsx')

  /**
   * Req 1.9: OverdueRules sends bulk PUT. Assert individual CRUD endpoints
   * are used instead.
   *
   * **Validates: Requirements 1.9**
   */
  it('should use individual CRUD endpoints, not bulk PUT', () => {
    // The buggy code sends a bulk PUT to /notifications/overdue-rules
    // The fixed code should use individual POST, PUT/{id}, DELETE/{id}
    const hasBulkPut = source.includes(
      "apiClient.put('/notifications/overdue-rules'",
    ) || source.includes(
      'apiClient.put("/notifications/overdue-rules"',
    )

    // Check for the toggle endpoint
    const hasToggleEndpoint = source.includes('overdue-rules-toggle')

    expect(hasBulkPut).toBe(false)
    expect(hasToggleEndpoint).toBe(true)
  })

  /**
   * Req 1.10: OverdueRules uses `channel` field but backend uses
   * `send_email`/`send_sms` booleans. Assert mapping exists.
   *
   * **Validates: Requirements 1.10**
   */
  it('should map between channel and send_email/send_sms booleans', () => {
    // The fixed code should reference send_email and send_sms
    const hasSendEmail = source.includes('send_email')
    const hasSendSms = source.includes('send_sms')

    expect(hasSendEmail).toBe(true)
    expect(hasSendSms).toBe(true)
  })
})

// ===================================================================
// NOTIFICATION PREFERENCES (Req 1.11, 1.12)
// ===================================================================

describe('NotificationPreferences — Contract Exploration', () => {
  const source = readSource(
    'frontend/src/pages/notifications/NotificationPreferences.tsx',
  )

  /**
   * Req 1.11: NotificationPreferences expects flat response. Assert grouped
   * { categories } response is consumed.
   *
   * **Validates: Requirements 1.11**
   */
  it('should consume grouped { categories } response shape', () => {
    // The fixed code should reference 'categories' in the response type
    const hasCategories = source.includes('categories')
      && (source.includes('notification_type') || source.includes('is_enabled'))

    // The buggy code uses a flat { preferences: [...] } shape
    const hasFlatPreferences =
      /interface\s+PreferencesResponse\s*\{[^}]*preferences\s*:/m.test(source)
      && !source.includes('categories:')

    expect(hasFlatPreferences).toBe(false)
    expect(hasCategories).toBe(true)
  })

  /**
   * Req 1.12: NotificationPreferences matches on snake_case category keys.
   * Assert backend display-name category strings are used.
   *
   * **Validates: Requirements 1.12**
   */
  it('should not use snake_case category keys for matching', () => {
    // The buggy code has CATEGORIES with snake_case keys like 'invoicing', 'payments', 'vehicle_reminders'
    const hasSnakeCaseCategories =
      source.includes("key: 'vehicle_reminders'") ||
      source.includes('key: "vehicle_reminders"')

    expect(hasSnakeCaseCategories).toBe(false)
  })
})

// ===================================================================
// TEMPLATE EDITOR (Req 1.13, 1.14, 1.15)
// ===================================================================

describe('TemplateEditor — Contract Exploration', () => {
  const source = readSource(
    'frontend/src/pages/notifications/TemplateEditor.tsx',
  )

  /**
   * Req 1.13: TemplateEditor PUT uses UUID. Assert template_type string
   * is used in PUT path.
   *
   * **Validates: Requirements 1.13**
   */
  it('should use template_type in PUT path, not UUID', () => {
    // The buggy code uses selected.id in the PUT path
    const usesIdInPut =
      source.includes('`/notifications/templates/${selected.id}`') ||
      source.includes("'/notifications/templates/' + selected.id")

    // The fixed code should use template_type
    const usesTemplateTypeInPut =
      source.includes('template_type') &&
      (source.includes('selected.template_type') || source.includes('.template_type'))

    expect(usesIdInPut).toBe(false)
    expect(usesTemplateTypeInPut).toBe(true)
  })

  /**
   * Req 1.14: TemplateEditor only fetches email templates. Assert both
   * email and SMS templates are fetched.
   *
   * **Validates: Requirements 1.14**
   */
  it('should fetch both email and SMS templates', () => {
    // The fixed code should fetch from both endpoints
    const fetchesEmailTemplates = source.includes('/notifications/templates')
    const fetchesSmsTemplates = source.includes('/notifications/sms-templates')

    expect(fetchesEmailTemplates).toBe(true)
    expect(fetchesSmsTemplates).toBe(true)
  })

  /**
   * Req 1.15: TemplateEditor uses `name` field. Assert `template_type`
   * field is used.
   *
   * **Validates: Requirements 1.15**
   */
  it('should use template_type field instead of name field', () => {
    // The NotificationTemplate interface should have template_type
    const interfaceMatch = source.match(
      /interface\s+NotificationTemplate\s*\{([\s\S]*?)\}/m,
    )
    expect(interfaceMatch).toBeTruthy()
    const interfaceBody = interfaceMatch![1]

    const hasTemplateType = interfaceBody.includes('template_type')
    expect(hasTemplateType).toBe(true)
  })
})

// ===================================================================
// WOF/REGO REMINDERS (Req 1.16)
// ===================================================================

describe('WofRegoReminders — Contract Exploration', () => {
  const source = readSource(
    'frontend/src/pages/notifications/WofRegoReminders.tsx',
  )

  /**
   * Req 1.16: WofRegoReminders expects separate fields. Assert combined
   * { enabled, days_in_advance, channel } is consumed.
   *
   * **Validates: Requirements 1.16**
   */
  it('should use combined { enabled, days_in_advance, channel } setting', () => {
    // The buggy code has separate wof_enabled, wof_days_in_advance,
    // rego_enabled, rego_days_in_advance fields
    const hasSeparateWofFields =
      source.includes('wof_enabled') || source.includes('wof_days_in_advance')
    const hasSeparateRegoFields =
      source.includes('rego_enabled') || source.includes('rego_days_in_advance')

    expect(hasSeparateWofFields).toBe(false)
    expect(hasSeparateRegoFields).toBe(false)
  })
})

// ===================================================================
// NOTIFICATION LOG (Req 1.17, 1.18)
// ===================================================================

describe('NotificationLog — Contract Exploration', () => {
  const source = readSource(
    'frontend/src/pages/notifications/NotificationLog.tsx',
  )

  /**
   * Req 1.17: NotificationLog reads `template_name`. Assert `template_type`
   * is read instead.
   *
   * **Validates: Requirements 1.17**
   */
  it('should read template_type instead of template_name', () => {
    // The buggy code uses template_name in the LogEntry interface
    const hasTemplateName = source.includes('template_name')
    const hasTemplateType = source.includes('template_type')

    expect(hasTemplateName).toBe(false)
    expect(hasTemplateType).toBe(true)
  })

  /**
   * Req 1.18: NotificationLog has non-functional search parameter.
   * Assert search input is removed or made client-side.
   *
   * **Validates: Requirements 1.18**
   */
  it('should not send search parameter to backend', () => {
    // The buggy code sends params.search to the backend which ignores it
    const sendsSearchParam =
      source.includes("params.search = search") ||
      source.includes('params.search =') ||
      /if\s*\(search\.trim\(\)\)\s*params\.search\s*=/.test(source)

    expect(sendsSearchParam).toBe(false)
  })
})

// ===================================================================
// SETTINGS NAVIGATION (Req 1.19)
// ===================================================================

describe('Settings Page — Contract Exploration', () => {
  const source = readSource('frontend/src/pages/settings/Settings.tsx')

  /**
   * Req 1.19: Settings page has no Notifications link. Assert Notifications
   * navigation entry exists.
   *
   * **Validates: Requirements 1.19**
   */
  it('should include Notifications in navigation items', () => {
    // The fixed code should have a 'notifications' entry in NAV_ITEMS
    const hasNotificationsNav =
      source.includes("'notifications'") || source.includes('"notifications"')
    const hasNotificationsLabel =
      source.includes("'Notifications'") || source.includes('"Notifications"')

    expect(hasNotificationsNav).toBe(true)
    expect(hasNotificationsLabel).toBe(true)
  })
})
