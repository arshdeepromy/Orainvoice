# Bugfix Requirements Document

## Introduction

This spec consolidates all findings from two independent audits of the OraInvoice Universal Platform:

1. **SMTP & Notifications Audit** (`docs/SMTP_AND_NOTIFICATIONS_AUDIT.md`) — 15 issues, primarily frontend-backend contract mismatches in the notifications subsystem. The backend is complete; the frontend sends/expects wrong field names, API shapes, or endpoints.

2. **OraInvoice Developer Audit Report** (`OraInvoice_Developer_Audit_Report.md`) — Critical security vulnerabilities (SQL injection, hardcoded secrets, insecure token storage, disabled SSL) and architecture/code quality issues (router duplication, poor error handling, rate limiter fail-open).

Combined, these represent ~20 distinct bugs across security, frontend contract mismatches, and code quality. ISSUE-002 (Twilio masked fields) is already fixed and excluded.

---

## Bug Analysis

### Current Behavior (Defect)

**Security Vulnerabilities (from Developer Audit)**

1.1 WHEN the database session sets the RLS org context THEN the system uses string interpolation (`f"SET LOCAL app.current_org_id = '{validated}'"`) in `app/core/database.py:87`, creating a SQL injection vector despite UUID validation

1.2 WHEN the application starts with default configuration THEN the system uses hardcoded secrets `JWT_SECRET = "change-me-in-production"` and `ENCRYPTION_KEY = "change-me-in-production"` in `app/config.py:25,74`, allowing complete authentication bypass if defaults are not overridden

1.3 WHEN a user authenticates THEN the system stores refresh tokens in localStorage (`frontend/src/api/client.ts`), making them accessible to any XSS attack

1.4 WHEN the application establishes database SSL connections THEN the system disables hostname checking and certificate verification (`app/core/security.py:90-91`), enabling man-in-the-middle attacks

**Architecture / Code Quality (from Developer Audit)**

1.5 WHEN the application registers API routers in `app/main.py` THEN the system includes 393 lines of duplicate router registrations, wasting memory and causing confusion

1.6 WHEN any service-layer function encounters an error THEN the system catches it with blanket `except Exception:` patterns, swallowing error details and masking root causes

1.7 WHEN Redis is unavailable and the rate limiter is invoked THEN the system fails open, allowing unlimited requests through without rate limiting

**SMTP & Integrations UI (from Notifications Audit)**

1.8 WHEN a user opens the SMTP configuration panel in admin Integrations THEN the system only shows 4 fields (`api_key`, `domain`, `from_name`, `reply_to`) instead of the 10 fields the backend `SmtpConfigRequest` expects (`provider`, `from_email`, `host`, `port`, `username`, `password`, `api_key`, `domain`, `from_name`, `reply_to`), making it impossible to configure any SMTP provider

**Overdue Rules (from Notifications Audit)**

1.9 WHEN the OverdueRules page loads THEN the system expects a bulk-update API shape (`{ enabled, rules: [...] }`) but the backend returns `{ rules: [...], total, reminders_enabled }` with individual CRUD endpoints, causing the page to fail

1.10 WHEN the OverdueRules page displays or saves rules THEN the system uses a `channel` field (`'email' | 'sms' | 'both'`) but the backend uses separate `send_email`/`send_sms` boolean fields, causing rules to display and save incorrectly

**Notification Preferences (from Notifications Audit)**

1.11 WHEN the NotificationPreferences page loads THEN the system expects a flat `{ preferences: [...] }` response with `{ type, label, category, enabled, channels: { email, sms } }` items, but the backend returns grouped `{ categories: [{ category, preferences: [{ notification_type, is_enabled, channel }] }] }`, causing the page to fail to render

1.12 WHEN the NotificationPreferences page groups preferences by category THEN the system matches on snake_case keys (`invoicing`, `payments`, `vehicle_reminders`, `system`) but the backend returns display names (`Invoicing`, `Payments`, `Vehicle Reminders`, `System Alerts`), so categories never match

**Template Editor (from Notifications Audit)**

1.13 WHEN a user saves a notification template THEN the system sends a PUT request using the template's UUID (`selected.id`) but the backend route expects a `template_type` string like `"invoice_issued"`, causing a 400 error

1.14 WHEN the TemplateEditor loads templates THEN the system only fetches email templates from `GET /notifications/templates` and ignores SMS templates served from `GET /notifications/sms-templates`, so SMS templates never appear despite the UI having an SMS filter tab

1.15 WHEN the TemplateEditor displays template information THEN the system uses a `name` field from the `NotificationTemplate` interface but the backend returns `template_type` (no `name` field), causing template names to show as undefined

**WOF/Rego Reminders (from Notifications Audit)**

1.16 WHEN the WofRegoReminders page loads THEN the system expects separate fields (`wof_enabled`, `wof_days_in_advance`, `rego_enabled`, `rego_days_in_advance`) but the backend returns a single combined setting (`enabled`, `days_in_advance`, `channel`), causing all toggles and inputs to be undefined

**Notification Log (from Notifications Audit)**

1.17 WHEN the NotificationLog page displays log entries THEN the system reads `template_name` from each entry but the backend returns `template_type`, causing the Template column to show `undefined` for every row

1.18 WHEN a user searches in the NotificationLog THEN the system sends a `search` query parameter that the backend silently ignores (only `status`, `channel`, `page`, `page_size` are supported), so search has no effect

**Settings Navigation (from Notifications Audit)**

1.19 WHEN a user views the Settings page THEN the system shows no link or tab for Notifications/Email configuration, making the notifications pages undiscoverable from settings

**Missing Backend Endpoints (from Notifications Audit)**

1.20 WHEN an email bounces at Brevo or SendGrid THEN the system has no webhook receiver endpoint to receive the bounce event, so the `email_bounced` flag on customer records is never automatically set despite the service function `flag_bounced_email_on_customer()` existing

1.21 WHEN an organisation is configured for a non-English language THEN the system always renders email templates in English because there is no locale-aware template selection or rendering


### Expected Behavior (Correct)

**Security Vulnerabilities**

2.1 WHEN the database session sets the RLS org context THEN the system SHALL use parameterized queries (e.g., `text("SET LOCAL app.current_org_id = :org_id").bindparams(org_id=validated)`) to eliminate SQL injection risk

2.2 WHEN the application starts THEN the system SHALL require `JWT_SECRET` and `ENCRYPTION_KEY` to be set via environment variables, raising a startup error if they contain the default placeholder values

2.3 WHEN a user authenticates THEN the system SHALL store refresh tokens in secure httpOnly cookies instead of localStorage, preventing XSS-based token theft

2.4 WHEN the application establishes database SSL connections THEN the system SHALL enable hostname checking and certificate verification (`check_hostname = True`, `verify_mode = ssl.CERT_REQUIRED`)

**Architecture / Code Quality**

2.5 WHEN the application registers API routers in `app/main.py` THEN the system SHALL have a single, deduplicated set of router registrations with no repeated `include_router` calls

2.6 WHEN service-layer functions encounter errors THEN the system SHALL catch specific exception types and log meaningful error details instead of using blanket `except Exception:` patterns

2.7 WHEN Redis is unavailable and the rate limiter is invoked THEN the system SHALL fail closed by denying the request (or applying a conservative fallback limit) rather than allowing unlimited requests

**SMTP & Integrations UI**

2.8 WHEN a user opens the SMTP configuration panel THEN the system SHALL display a provider dropdown (Brevo/SendGrid/Custom SMTP), `from_email` field, and conditionally show `host`/`port`/`username`/`password` fields when provider is "smtp", matching all 10 fields of the backend `SmtpConfigRequest` schema

**Overdue Rules**

2.9 WHEN the OverdueRules page loads THEN the system SHALL use the backend's individual CRUD endpoints (`GET /notifications/overdue-rules` for listing, `POST` for create, `PUT /{rule_id}` for update, `DELETE /{rule_id}` for delete) and the toggle endpoint (`PUT /notifications/overdue-rules-toggle?enabled=`) and correctly map `reminders_enabled` to the UI's enabled state

2.10 WHEN the OverdueRules page displays or saves rules THEN the system SHALL map between the backend's `send_email`/`send_sms` booleans and the UI's `channel` concept (`send_email && send_sms` → `'both'`, etc.)

**Notification Preferences**

2.11 WHEN the NotificationPreferences page loads THEN the system SHALL consume the backend's grouped response `{ categories: [{ category, preferences: [{ notification_type, is_enabled, channel }] }] }` and render preferences grouped by category

2.12 WHEN the NotificationPreferences page groups preferences by category THEN the system SHALL match on the backend's display-name category strings (`"Invoicing"`, `"Payments"`, `"Vehicle Reminders"`, `"System Alerts"`) instead of snake_case keys

**Template Editor**

2.13 WHEN a user saves a notification template THEN the system SHALL use `selected.template_type` (e.g., `"invoice_issued"`) in the PUT URL path instead of `selected.id`

2.14 WHEN the TemplateEditor loads templates THEN the system SHALL fetch both email templates (`GET /notifications/templates`) and SMS templates (`GET /notifications/sms-templates`) and merge them into a unified list, using the correct endpoint for saves based on channel

2.15 WHEN the TemplateEditor displays template information THEN the system SHALL use the `template_type` field from the backend response for display and API calls, with the `NotificationTemplate` interface updated to include `template_type`

**WOF/Rego Reminders**

2.16 WHEN the WofRegoReminders page loads THEN the system SHALL correctly consume the backend's combined setting (`enabled`, `days_in_advance`, `channel`) and map it to the UI controls, OR the backend SHALL be extended to support separate WOF and rego preferences with independent `enabled`/`days_in_advance` fields

**Notification Log**

2.17 WHEN the NotificationLog page displays log entries THEN the system SHALL read `template_type` from each entry (matching the backend schema) and display it in the Template column

2.18 WHEN a user searches in the NotificationLog THEN the system SHALL either remove the non-functional search box OR the backend SHALL add a `search` query parameter that filters by recipient, subject, or template_type

**Settings Navigation**

2.19 WHEN a user views the Settings page THEN the system SHALL include a "Notifications" tab or link that navigates to the notifications configuration pages

**Missing Backend Endpoints**

2.20 WHEN an email bounces at Brevo or SendGrid THEN the system SHALL expose webhook receiver endpoints (`POST /notifications/webhooks/brevo-bounce` and `POST /notifications/webhooks/sendgrid-bounce`) that verify webhook signatures and call `flag_bounced_email_on_customer()` to automatically flag the customer's email as bounced

2.21 WHEN an organisation is configured for a non-English language THEN the system SHALL select and render email templates in the organisation's configured locale, falling back to English if no translation exists


### Unchanged Behavior (Regression Prevention)

**Security — Existing Functionality**

3.1 WHEN the RLS org context is set with a valid UUID THEN the system SHALL CONTINUE TO correctly scope all database queries to the specified organisation

3.2 WHEN valid JWT tokens are presented THEN the system SHALL CONTINUE TO authenticate and authorize requests correctly

3.3 WHEN users log in and out THEN the system SHALL CONTINUE TO issue and revoke tokens with the same session lifecycle

3.4 WHEN the application connects to the database over SSL THEN the system SHALL CONTINUE TO establish encrypted connections successfully

**Architecture — Existing Functionality**

3.5 WHEN API requests are routed to any existing endpoint THEN the system SHALL CONTINUE TO route them to the correct handler with the same URL paths and HTTP methods

3.6 WHEN service-layer functions complete successfully THEN the system SHALL CONTINUE TO return the same response shapes and status codes

3.7 WHEN Redis is available THEN the system SHALL CONTINUE TO enforce rate limits with the same thresholds and behavior

**SMTP & Integrations — Existing Functionality**

3.8 WHEN a user saves SMTP configuration with all required fields THEN the system SHALL CONTINUE TO store the encrypted config and return a success response via `PUT /api/v1/admin/integrations/smtp`

3.9 WHEN a user tests SMTP configuration THEN the system SHALL CONTINUE TO send a test email via `POST /api/v1/admin/integrations/smtp/test`

**Notifications Backend — Existing Functionality**

3.10 WHEN the backend receives valid requests to notification CRUD endpoints THEN the system SHALL CONTINUE TO create, read, update, and delete overdue rules, notification preferences, templates, and WOF/rego settings with the same API contracts

3.11 WHEN the backend sends email or SMS notifications THEN the system SHALL CONTINUE TO dispatch via Brevo/SendGrid/SMTP and Twilio with retry and exponential backoff

3.12 WHEN the backend logs notification deliveries THEN the system SHALL CONTINUE TO record entries with `status`, `channel`, `template_type`, `recipient`, and pagination support via `GET /notifications/log`

3.13 WHEN the backend stores integration configs THEN the system SHALL CONTINUE TO use envelope encryption in the `integration_configs` table

3.14 WHEN existing frontend pages that are NOT part of this bugfix (invoicing, inventory, POS, jobs, etc.) make API calls THEN the system SHALL CONTINUE TO function identically with no changes to their behavior
