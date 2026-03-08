# SMTP & Notifications System — Gap Audit

**Date**: 2026-03-08
**Scope**: Email/SMTP configuration, notification preferences, overdue reminders, template editor, delivery log, WOF/rego reminders

---

## Summary

The backend is largely complete — SMTP (Brevo/SendGrid/custom), Twilio, notification templates, delivery log, overdue rules, preferences endpoints all exist and are registered in `main.py`. The primary issues are **frontend-backend contract mismatches** where the frontend sends/expects different field names or API shapes than what the backend provides.

---

## Issues Found

### ISSUE-001: SMTP Integrations UI — Missing Fields for Provider Selection
**Severity**: HIGH
**Files**: `frontend/src/pages/admin/Integrations.tsx`
**Problem**: The SMTP panel in the admin Integrations page only has 4 fields (`api_key`, `domain`, `from_name`, `reply_to`). The backend `SmtpConfigRequest` schema expects 10 fields including `provider` (brevo/sendgrid/smtp), `from_email`, `host`, `port`, `username`, `password`.
**Impact**: Cannot configure Brevo, SendGrid, or custom SMTP relay — the save will fail because `domain` and `from_email` are required fields and `provider` defaults to "smtp" but there's no way to select Brevo/SendGrid.
**Backend**: `PUT /api/v1/admin/integrations/smtp` — `SmtpConfigRequest` in `app/modules/admin/schemas.py` (line 77)
**Frontend**: `INTEGRATION_FIELDS.smtp` in `frontend/src/pages/admin/Integrations.tsx` (line 49)
**Fix**: Add provider dropdown (Brevo/SendGrid/Custom SMTP), `from_email` field, and conditionally show `host`/`port`/`username`/`password` when provider is "smtp".

---

### ISSUE-002: Twilio `auth_token` Not in Masked Fields
**Severity**: MEDIUM
**Files**: `app/modules/admin/service.py`
**Problem**: `_MASKED_FIELDS["twilio"]` only contains `["account_sid"]` — missing `"auth_token"`. The frontend expects `auth_token_last4` to be returned from `GET /admin/integrations/twilio` to show the masked credential indicator.
**Impact**: After saving Twilio config, the auth token field will appear empty instead of showing `••••••••` (masked).
**Fix**: Add `"auth_token"` to `_MASKED_FIELDS["twilio"]` list.
**Status**: ✅ FIXED

---

### ISSUE-003: OverdueRules Frontend — API Contract Mismatch
**Severity**: HIGH
**Files**: `frontend/src/pages/notifications/OverdueRules.tsx`, `app/modules/notifications/router.py`
**Problem**: The frontend expects a bulk-update API pattern:
- `GET /notifications/overdue-rules` → expects `{ enabled: bool, rules: [...] }`
- `PUT /notifications/overdue-rules` → sends `{ enabled: bool, rules: [...] }`

But the backend provides individual CRUD endpoints:
- `GET /notifications/overdue-rules` → returns `{ rules: [...], total: N, reminders_enabled: bool }`
- `POST /notifications/overdue-rules` → create single rule
- `PUT /notifications/overdue-rules/{rule_id}` → update single rule
- `DELETE /notifications/overdue-rules/{rule_id}` → delete single rule
- `PUT /notifications/overdue-rules-toggle?enabled=true` → toggle feature

Field name mismatch: backend returns `reminders_enabled`, frontend expects `enabled`.
Rule shape mismatch: backend rules have `send_email`/`send_sms` booleans, frontend expects `channel: 'email' | 'sms' | 'both'`.

**Impact**: OverdueRules page will fail to load (wrong response shape) and save (wrong endpoint).
**Fix**: Rewrite `OverdueRules.tsx` to use individual CRUD endpoints and the toggle endpoint, and map `send_email`/`send_sms` to/from the `channel` UI concept.

---

### ISSUE-004: NotificationPreferences Frontend — Field Name Mismatches
**Severity**: HIGH
**Files**: `frontend/src/pages/notifications/NotificationPreferences.tsx`, `app/modules/notifications/router.py`
**Problem**: 
- Frontend `GET` expects `{ preferences: [...] }` with items having `{ type, label, category, enabled, channels: { email, sms }, supports_sms }`
- Backend `GET /notifications/settings` returns `{ categories: [{ category, preferences: [{ notification_type, is_enabled, channel }] }] }`
- Frontend `PUT` sends `{ type, enabled, channels: { email, sms } }`
- Backend `PUT /notifications/settings` expects `{ notification_type, is_enabled, channel }` (channel is a string "email"/"sms"/"both", not an object)

**Impact**: NotificationPreferences page will fail to render — completely different response structure.
**Fix**: Rewrite `NotificationPreferences.tsx` to match the backend's grouped-by-category response shape and use `notification_type`/`is_enabled`/`channel` field names.

---

### ISSUE-005: TemplateEditor — Uses UUID Instead of template_type in URL
**Severity**: HIGH
**Files**: `frontend/src/pages/notifications/TemplateEditor.tsx`
**Problem**: The save call uses `apiClient.put(\`/notifications/templates/${selected.id}\`, body)` where `selected.id` is a UUID. But the backend route is `PUT /notifications/templates/{template_type}` where `template_type` is a string like "invoice_issued".
**Impact**: Template saves will 400 because the UUID won't match any valid template type.
**Fix**: Change to use `selected.template_type` instead of `selected.id`. Also need to update the `NotificationTemplate` interface to include `template_type` field (backend returns it but frontend interface doesn't declare it).

---

### ISSUE-006: TemplateEditor — SMS Templates Not Fetched
**Severity**: MEDIUM
**Files**: `frontend/src/pages/notifications/TemplateEditor.tsx`
**Problem**: The TemplateEditor has a channel filter for "email"/"sms"/"all" but only fetches from `GET /notifications/templates` which returns email templates only. SMS templates are served from a separate endpoint `GET /notifications/sms-templates`.
**Impact**: SMS templates never appear in the template editor despite the UI having an SMS filter tab.
**Fix**: Fetch both email and SMS templates, merge them into the templates list. For SMS saves, use `PUT /notifications/sms-templates/{template_type}` instead of the email endpoint.

---

### ISSUE-007: TemplateEditor — Interface Missing `template_type` Field
**Severity**: MEDIUM
**Files**: `frontend/src/pages/notifications/TemplateEditor.tsx`
**Problem**: The `NotificationTemplate` interface has `name: string` but the backend returns `template_type: string` (no `name` field). The interface also lacks `template_type`.
**Impact**: Template type won't be accessible for display or API calls.
**Fix**: Add `template_type: string` to the interface and use it for display and API paths.

---

### ISSUE-008: WofRegoReminders Frontend — Response Shape Mismatch
**Severity**: HIGH
**Files**: `frontend/src/pages/notifications/WofRegoReminders.tsx`, `app/modules/notifications/router.py`
**Problem**: The frontend expects separate WOF and rego settings:
- `{ wof_enabled, wof_days_in_advance, rego_enabled, rego_days_in_advance, channel }`

But the backend `GET /notifications/wof-rego-settings` returns a single combined setting:
- `{ enabled, days_in_advance, channel }`

The backend stores WOF/rego as a single `NotificationPreference` row with one `is_enabled` and one `days_in_advance` in the config JSONB. The frontend treats WOF and rego as independently toggleable with separate day thresholds.
**Impact**: WofRegoReminders page will fail to render — `wof_enabled` and `rego_enabled` will be `undefined`, toggles won't work, and saves will send fields the backend doesn't accept.
**Fix**: Either:
- (A) Rewrite the frontend to use the combined `enabled`/`days_in_advance` model, or
- (B) Extend the backend to store separate WOF and rego preferences (two `NotificationPreference` rows) and update the schema to return/accept separate fields.
Option (B) is better UX since customers may want WOF reminders but not rego reminders.

---

### ISSUE-009: NotificationLog Frontend — Field Name Mismatch (`template_name` vs `template_type`)
**Severity**: MEDIUM
**Files**: `frontend/src/pages/notifications/NotificationLog.tsx`, `app/modules/notifications/schemas.py`
**Problem**: The frontend `LogEntry` interface expects `template_name: string`, but the backend `NotificationLogEntry` schema returns `template_type: string`. There is no `template_name` field in the backend response.
**Impact**: The "Template" column in the notification log table will show `undefined` for every row.
**Fix**: Change the frontend interface to use `template_type` instead of `template_name`, and update the table cell to display `entry.template_type`.

---

### ISSUE-010: NotificationLog Frontend — `search` Query Param Not Supported by Backend
**Severity**: LOW
**Files**: `frontend/src/pages/notifications/NotificationLog.tsx`, `app/modules/notifications/router.py`
**Problem**: The frontend sends a `search` query parameter when filtering the notification log. The backend `GET /notifications/log` endpoint only accepts `status`, `channel`, `page`, and `page_size` query params — there is no `search` parameter.
**Impact**: The search box in the notification log UI will appear to work (no error) but will have no effect on results — the backend silently ignores unknown query params.
**Fix**: Either add a `search` query param to the backend endpoint (searching recipient, subject, template_type) or remove the search box from the frontend.

---

### ISSUE-011: Settings.tsx — No Link to Notifications Page
**Severity**: LOW
**Files**: `frontend/src/pages/settings/Settings.tsx`
**Problem**: The Settings page sidebar has tabs for organisation, branches, users, billing, accounting, currency, language, printer, webhooks — but no "Notifications" or "Email" tab. The notifications page exists at `/notifications` route but isn't discoverable from settings.
**Impact**: Users may not find the notification configuration pages. However, the `/notifications` route IS accessible from the main nav if it's in the sidebar/menu.
**Fix**: Either add a "Notifications" tab to Settings.tsx that links to `/notifications`, or ensure the main navigation has a clear "Notifications" link. This is a UX issue, not a functional break.

---

### ISSUE-012: NotificationPreferences — Category Key Mismatch
**Severity**: MEDIUM
**Files**: `frontend/src/pages/notifications/NotificationPreferences.tsx`
**Problem**: Frontend defines categories with keys `invoicing`, `payments`, `vehicle_reminders`, `system`. Backend returns category names `Invoicing`, `Payments`, `Vehicle Reminders`, `System Alerts`. The frontend tries to match by `p.category === cat.key` which will never match because the backend uses display names, not snake_case keys.
**Impact**: Even if the response structure issue (ISSUE-004) is fixed, categories won't group correctly.
**Fix**: Match on the backend's category names or normalize both sides.

---

### ISSUE-013: OverdueRules — Rule Shape Mismatch (send_email/send_sms vs channel)
**Severity**: HIGH (part of ISSUE-003)
**Files**: `frontend/src/pages/notifications/OverdueRules.tsx`
**Problem**: Frontend rule interface has `channel: 'email' | 'sms' | 'both'`. Backend rule has separate `send_email: bool` and `send_sms: bool` fields. No `channel` field exists on the backend.
**Impact**: Rules won't display or save correctly.
**Fix**: Map between the two representations in the frontend:
- `send_email=true, send_sms=false` → `channel='email'`
- `send_email=false, send_sms=true` → `channel='sms'`
- `send_email=true, send_sms=true` → `channel='both'`

---

### ISSUE-014: Bounce Webhook Receiver Missing
**Severity**: MEDIUM
**Files**: `app/modules/notifications/router.py`
**Problem**: The service layer has `flag_bounced_email_on_customer()` implemented and tested, but there is no webhook receiver endpoint for Brevo or SendGrid to call when an email bounces. The bounce flagging function exists but has no HTTP entry point.
**Impact**: Bounced emails are never automatically flagged on customer records. The `email_bounced` field on customers will always remain `False` unless manually updated.
**Fix**: Add webhook receiver endpoints:
- `POST /api/v1/notifications/webhooks/brevo-bounce` — parse Brevo webhook payload, extract bounced email, call `flag_bounced_email_on_customer()`
- `POST /api/v1/notifications/webhooks/sendgrid-bounce` — same for SendGrid event webhook
Both should verify webhook signatures for security.

---

### ISSUE-015: Multi-Language Email Template Rendering Not Implemented
**Severity**: LOW
**Files**: `app/modules/notifications/service.py`
**Problem**: Email templates are always rendered in English. There is no locale-aware template selection or rendering. The notification service has no references to `locale`, `language`, or `i18n`. The `notification_templates` table stores `body_blocks` as a single JSONB column with no locale key.
**Impact**: Organisations configured for non-English languages (French, Spanish, German, Hindi, Māori — all supported by the i18n module) will still receive English email notifications.
**Spec**: Requirement 50.8
**Fix**: Either:
- (A) Store locale-specific template overrides in a separate column or table, or
- (B) Add a `locale` column to `notification_templates` and seed templates per supported language, or
- (C) Use the i18n translation system to translate template content at render time

---

## Non-Issues (Verified Working)

| Component | Status | Notes |
|-----------|--------|-------|
| Backend SMTP endpoints | ✅ OK | `PUT /admin/integrations/smtp`, `POST /admin/integrations/smtp/test` exist |
| Backend Twilio endpoints | ✅ OK | `PUT /admin/integrations/twilio`, `POST /admin/integrations/twilio/test` exist |
| Backend notification templates | ✅ OK | Full CRUD at `/notifications/templates` |
| Backend SMS templates | ✅ OK | Full CRUD at `/notifications/sms-templates` |
| Backend delivery log | ✅ OK | `GET /notifications/log` with pagination and filters |
| Backend overdue rules | ✅ OK | Full CRUD + toggle endpoint |
| Backend notification preferences | ✅ OK | GET/PUT at `/notifications/settings` |
| Backend WOF/rego settings | ✅ OK | GET/PUT at `/notifications/wof-rego-settings` |
| Backend email sending (Brevo) | ✅ OK | `app/integrations/brevo.py` — full Brevo/SendGrid/SMTP client |
| Backend Celery tasks | ✅ OK | Email/SMS dispatch with retry + exponential backoff |
| Router registration in main.py | ✅ OK | All routers mounted at correct prefixes |
| Encrypted config storage | ✅ OK | `integration_configs` table with envelope encryption |
| WofRegoReminders frontend | ❌ BROKEN | ISSUE-008: Backend returns combined `enabled`/`days_in_advance`, frontend expects separate `wof_enabled`/`rego_enabled` |
| NotificationLog frontend | ⚠️ Partial | ISSUE-009: `template_name` vs `template_type` field mismatch; ISSUE-010: `search` param not supported |
| Frontend routing (App.tsx) | ✅ OK | `/notifications` route exists, renders `NotificationsPage` |

---

## Fix Priority

| Priority | Issue | Effort |
|----------|-------|--------|
| P0 | ISSUE-001: SMTP UI missing fields | ~30 min |
| P0 | ISSUE-003 + ISSUE-013: OverdueRules API mismatch | ~45 min |
| P0 | ISSUE-004 + ISSUE-012: NotificationPreferences mismatch | ~30 min |
| P0 | ISSUE-005: TemplateEditor UUID vs template_type | ~10 min |
| P0 | ISSUE-008: WofRegoReminders response shape mismatch | ~30 min |
| P1 | ISSUE-006 + ISSUE-007: TemplateEditor SMS support | ~30 min |
| P1 | ISSUE-009: NotificationLog template_name vs template_type | ~5 min |
| P1 | ISSUE-010: NotificationLog search param not supported | ~15 min |
| P1 | ISSUE-011: Settings → Notifications link | ~10 min |
| P2 | ISSUE-014: Bounce webhook receiver endpoints | ~2 hrs |
| P2 | ISSUE-015: Multi-language email template rendering | ~4 hrs |
| Done | ISSUE-002: Twilio auth_token masked field | ✅ Fixed |
