# Implementation Plan: Connexus SMS Integration

## Overview

Replace Twilio and AWS SNS with WebSMS Connexus as the sole SMS sending provider. Introduces shared SMS types, Connexus client with token management, two-way SMS via webhooks, conversation/message data model with RLS, chat API and frontend UI, billing integration, and admin configuration. Implementation proceeds bottom-up: shared types → client → data layer → API layer → frontend → billing wiring → cleanup.

## Tasks

- [x] 1. Create shared SMS types and Connexus client module
  - [x] 1.1 Create `app/integrations/sms_types.py` with `SmsMessage` and `SmsSendResult` dataclasses
    - Extract `SmsMessage` (to_number, body, from_number) and `SmsSendResult` (success, message_sid, error, metadata) from existing Twilio client into provider-agnostic module
    - _Requirements: 1.2_

  - [x] 1.2 Create `app/integrations/connexus_sms.py` with `ConnexusConfig` dataclass
    - Implement `ConnexusConfig` with `client_id`, `client_secret`, `sender_id`, `api_base_url` fields, plus `from_dict()` and `to_dict()` methods
    - _Requirements: 1.1_

  - [x] 1.3 Implement `ConnexusSmsClient` with token management
    - Implement `_ensure_token()` and `_refresh_token()` methods that POST to `{api_base_url}/auth/token`
    - Cache Bearer token in memory with expiry tracking
    - Proactively refresh when within 5 minutes of 1-hour expiry
    - On 401 response: refresh token and retry the failed call exactly once
    - Include `Authorization: Bearer <token>` header on all API calls except token request
    - Use 30-second HTTP timeout for all API calls
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 1.8_

  - [x] 1.4 Implement `ConnexusSmsClient.send()` method
    - POST to `{api_base_url}/sms/out` with `to`, `body`, and optional `from` parameters
    - Return `SmsSendResult(success=True, message_sid=message_id)` on "accepted" status
    - Return `SmsSendResult(success=False, error=...)` on error HTTP responses
    - Catch network/timeout exceptions, log, and return `SmsSendResult(success=False)`
    - Include `parts_count` from Connexus response in `SmsSendResult.metadata`
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.9_

  - [x] 1.5 Implement `check_balance()`, `validate_number()`, and `configure_webhooks()` methods
    - `check_balance()`: POST to `{api_base_url}/sms/balance`, return `{balance, currency}`, handle errors gracefully
    - `validate_number(number)`: POST to `{api_base_url}/number/lookup`, return structured result with carrier/porting/network info
    - `configure_webhooks(mo_webhook_url, dlr_webhook_url)`: POST to `{api_base_url}/configure`
    - All methods return descriptive errors on failure instead of raising unhandled exceptions
    - _Requirements: 11.1, 11.3, 12.1, 12.2, 12.3, 13.1_

  - [x] 1.6 Write property tests for ConnexusConfig and client (Properties 1-6)
    - **Property 1: ConnexusConfig serialization round-trip** — `from_dict(config.to_dict())` produces identical fields
    - **Validates: Requirement 1.1**
    - **Property 2: Send payload construction** — HTTP payload contains correct `to`, `body`, `from` fields
    - **Validates: Requirement 1.4**
    - **Property 3: API failures return structured error results** — non-success responses return `success=False` with non-empty error
    - **Validates: Requirements 1.6, 1.7, 11.3, 12.3**
    - **Property 4: Successful send includes parts metadata** — `metadata["parts_count"]` equals Connexus response parts value
    - **Validates: Requirement 1.9**
    - **Property 5: Token caching and Authorization header** — cached token reused across calls within validity window
    - **Validates: Requirements 2.2, 2.6**
    - **Property 6: Proactive token refresh before expiry** — new token requested when within 5-minute margin of expiry
    - **Validates: Requirement 2.3**
    - Create test file at `tests/properties/test_connexus_properties.py` using Hypothesis

- [x] 2. Checkpoint — Verify Connexus client module
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Database migration and data models
  - [x] 3.1 Create Alembic migration for `sms_conversations` and `sms_messages` tables
    - Create `sms_conversations` table with all columns: id (UUID PK), org_id (FK), phone_number, contact_name, last_message_at, last_message_preview, unread_count, is_archived, created_at, updated_at
    - Create `sms_messages` table with all columns: id (UUID PK), conversation_id (FK), org_id (FK), direction, body, from_number, to_number, external_message_id, status, parts_count, cost_nzd, sent_at, delivered_at, created_at
    - Add UNIQUE constraint on `sms_conversations(org_id, phone_number)`
    - Add CHECK constraints: direction IN ('inbound', 'outbound'), status IN ('pending', 'accepted', 'queued', 'delivered', 'undelivered', 'failed')
    - Create indexes: `sms_conversations(org_id, last_message_at)`, `sms_messages(conversation_id, created_at)`, `sms_messages(external_message_id)` WHERE NOT NULL
    - Enable RLS on both tables with policy `org_id = current_setting('app.current_org_id')::uuid`
    - Seed Connexus provider record (`provider_key='connexus'`, `is_active=false`) and remove `twilio_verify` and `aws_sns` seed records
    - Update `integration_configs` check constraint to remove 'twilio': `name IN ('carjam','stripe','smtp')`
    - Include `downgrade()` function that reverses all changes
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 3.5_

  - [x] 3.2 Create SQLAlchemy models in `app/modules/sms_chat/models.py`
    - Define `SmsConversation` and `SmsMessage` ORM models matching the migration schema
    - Follow existing model patterns in the codebase
    - _Requirements: 7.1, 7.2_

- [x] 4. Create SMS chat module structure and service layer
  - [x] 4.1 Create `app/modules/sms_chat/` module with `__init__.py` and `schemas.py`
    - Create Pydantic schemas for: conversation list response, message list response, reply request, new conversation request, incoming webhook payload, delivery status webhook payload, usage summary response, number validation response
    - _Requirements: 8.10_

  - [x] 4.2 Implement `app/modules/sms_chat/service.py` — conversation and message operations
    - `list_conversations(db, org_id, page, per_page, search)` — paginated, ordered by `last_message_at` DESC, with optional search on phone_number/contact_name
    - `get_messages(db, org_id, conversation_id, page, per_page)` — paginated, ordered by `created_at` ASC
    - `send_reply(db, org_id, conversation_id, body)` — create outbound message record (status=pending), update conversation last_message_at/preview, increment `sms_sent_this_month`, send via Connexus, update message with external_message_id/status/parts_count/cost_nzd
    - `start_conversation(db, org_id, phone_number, body)` — upsert conversation, create outbound message, send via Connexus
    - `mark_read(db, org_id, conversation_id)` — set unread_count to 0
    - `archive_conversation(db, org_id, conversation_id)` — set is_archived to true
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [x] 4.3 Implement webhook handlers in `app/modules/sms_chat/service.py`
    - `handle_incoming_sms(db, payload)` — validate payload, find org by `to` number, create/update conversation, create inbound message record (deduplicate on external_message_id), increment unread_count. Store with null org_id if `to` number unmatched.
    - `handle_delivery_status(db, payload)` — find message by external_message_id, map Connexus status codes (1→delivered, 2→undelivered, 4→queued, 8→accepted, 16→undelivered), update status and delivered_at. Log warning if messageId not found.
    - Both handlers are idempotent
    - _Requirements: 5.2, 5.3, 5.4, 5.7, 6.2, 6.3, 6.4, 6.6, 8.9_

  - [x] 4.4 Implement `get_usage_summary()` in service layer
    - Return: total_sent (outbound count this month), total_cost (sum of cost_nzd), included_quota, package_credits_remaining, overage_count, overage_charge
    - Include warning flag when usage exceeds 80% of effective quota
    - _Requirements: 14.2, 14.5_

  - [x] 4.5 Write property tests for SMS chat and webhook logic (Properties 7-19)
    - **Property 7: Incoming SMS creates conversation and inbound message** — **Validates: Requirements 5.2, 5.3, 8.9**
    - **Property 8: Malformed webhook payloads are rejected** — **Validates: Requirement 5.6**
    - **Property 9: Webhook idempotency** — **Validates: Requirements 5.7, 6.6**
    - **Property 10: Delivery status code mapping** — **Validates: Requirements 6.2, 6.3**
    - **Property 11: Conversation uniqueness per org and phone number** — **Validates: Requirement 7.3**
    - **Property 12: RLS tenant isolation** — **Validates: Requirements 7.4, 7.5**
    - **Property 13: Conversations ordered by last message time** — **Validates: Requirement 8.1**
    - **Property 14: Messages ordered by creation time** — **Validates: Requirement 8.2**
    - **Property 15: New conversation upsert** — **Validates: Requirement 8.4**
    - **Property 16: Outbound SMS creates record and updates state** — **Validates: Requirements 8.5, 8.6, 10.1**
    - **Property 17: Mark as read resets unread count** — **Validates: Requirement 8.7**
    - **Property 18: Archive sets is_archived flag** — **Validates: Requirement 8.8**
    - **Property 19: Conversation search filtering** — **Validates: Requirement 9.8**
    - Create test file at `tests/properties/test_sms_chat_properties.py` using Hypothesis

- [x] 5. Checkpoint — Verify data layer and service logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. API layer — webhook and chat routers
  - [x] 6.1 Create `app/modules/sms_chat/router_webhooks.py` — Connexus webhook endpoints
    - `POST /api/webhooks/connexus/incoming` — validate payload structure (reject malformed with 400), call `handle_incoming_sms()`, return HTTP 200 within 5 seconds
    - `POST /api/webhooks/connexus/status` — validate payload, call `handle_delivery_status()`, return HTTP 200 within 5 seconds
    - No auth middleware (external Connexus callbacks)
    - Idempotent: deduplicates on messageId
    - _Requirements: 5.1, 5.5, 5.6, 5.7, 6.1, 6.5, 6.6_

  - [x] 6.2 Create `app/modules/sms_chat/router.py` — org-scoped SMS chat endpoints
    - `GET /org/sms/conversations` — paginated list, requires authenticated org user
    - `GET /org/sms/conversations/{id}/messages` — paginated message history
    - `POST /org/sms/conversations/{id}/reply` — send reply via Connexus
    - `POST /org/sms/conversations/new` — create conversation + send first message
    - `POST /org/sms/conversations/{id}/read` — mark as read
    - `POST /org/sms/conversations/{id}/archive` — archive conversation
    - `POST /org/sms/validate-number` — number validation via Connexus IPMS lookup
    - `GET /org/sms/usage-summary` — org SMS usage summary (org_admin role)
    - All endpoints scoped via RLS tenant middleware
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 12.4, 14.2_

  - [x] 6.3 Create `app/modules/sms_chat/router_admin.py` — admin Connexus endpoints
    - `GET /admin/integrations/connexus/balance` — return Connexus account balance (global_admin role)
    - `POST /admin/integrations/connexus/configure-webhooks` — configure webhook URLs via Connexus API (global_admin role)
    - _Requirements: 11.2, 13.2_

  - [x] 6.4 Register all SMS chat routers in `app/main.py`
    - Include `router_webhooks`, `router`, and `router_admin` from `app/modules/sms_chat/`
    - _Requirements: 8.10_

- [x] 7. Legacy provider removal and Connexus provider wiring
  - [x] 7.1 Delete `app/integrations/twilio_sms.py` and update all imports
    - Delete the Twilio SMS client file
    - Update `app/integrations/sms_types.py` imports if any code still references the old Twilio module
    - Remove all imports of `twilio_sms` across the codebase
    - _Requirements: 3.6_

  - [x] 7.2 Update `app/modules/sms_providers/service.py` — remove Twilio/AWS SNS, add Connexus
    - Remove `_test_twilio()` and `_test_aws_sns()` functions
    - Add `_test_connexus()` function that sends a test SMS via `ConnexusSmsClient`
    - Update `test_sms_provider()` dispatch to route `connexus` provider_key to `_test_connexus()`, removing Twilio/AWS SNS branches
    - _Requirements: 3.7_

  - [x] 7.3 Update `app/tasks/notifications.py` — replace Twilio with Connexus dispatch
    - Remove `from app.integrations.twilio_sms import send_org_sms` import
    - Update `send_sms_task()` to resolve active SMS provider from `sms_verification_providers` table
    - Instantiate `ConnexusSmsClient` with decrypted credentials and call `client.send(SmsMessage(...))`
    - _Requirements: 3.4, 3.8_

- [x] 8. SMS billing integration
  - [x] 8.1 Wire Connexus SMS cost tracking into message records
    - On successful send, calculate `cost_nzd = parts_count × 0.115` (GST inclusive) and store on `sms_messages` record
    - Ensure `sms_sent_this_month` counter incremented by 1 per outbound SMS
    - Ensure existing FIFO package credit deduction logic applies to Connexus-sent SMS
    - Verify existing `compute_sms_overage` and `report_sms_overage_task()` work without modification
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 14.1_

  - [x] 8.2 Write property tests for SMS billing (Properties 20-24)
    - **Property 20: SMS cost calculation** — `cost_nzd` equals `parts_count × 0.115`
    - **Validates: Requirements 10.2, 14.1**
    - **Property 21: FIFO package credit deduction** — oldest package depleted first
    - **Validates: Requirement 10.3**
    - **Property 22: Usage summary aggregation** — total_sent, total_cost, overage_count match message records
    - **Validates: Requirement 14.2**
    - **Property 23: Quota warning threshold** — warning flag true when usage exceeds 80% of effective quota
    - **Validates: Requirement 14.5**
    - **Property 24: Template variable substitution** — rendered body contains no placeholders, all values substituted
    - **Validates: Requirement 15.2**
    - Create test file at `tests/properties/test_sms_billing_properties.py` using Hypothesis

- [x] 9. Checkpoint — Verify backend integration end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Frontend — Admin SMS provider configuration updates
  - [x] 10.1 Update `frontend/src/pages/admin/SmsProviders.tsx` for Connexus
    - Remove `twilio_verify` and `aws_sns` entries from `CREDENTIAL_FIELDS` map
    - Add `connexus` entry with `client_id`, `client_secret`, `sender_id` fields
    - Add Connexus balance display section (call `GET /admin/integrations/connexus/balance`)
    - Add webhook URL display showing `/api/webhooks/connexus/incoming` and `/api/webhooks/connexus/status` for copy-paste
    - Add "Configure Webhooks" button calling `POST /admin/integrations/connexus/configure-webhooks`
    - Add "Test Connection" button wired to existing `POST /admin/sms-providers/{id}/test` endpoint
    - Display error messages for invalid/missing credentials
    - Show visual warning when balance below threshold
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 11.4, 13.3, 13.4, 13.5_

- [x] 11. Frontend — SMS Chat UI
  - [x] 11.1 Create `frontend/src/pages/sms/SmsChat.tsx` — conversation list and chat view
    - Split-panel layout: conversation list (left), message thread (right)
    - Conversation list: show phone_number/contact_name, last_message_preview, timestamp, unread badge, ordered by most recent
    - Message thread: scrollable chat view, inbound messages left-aligned, outbound right-aligned
    - Each message shows body, timestamp, delivery status indicator (pending/accepted/delivered/undelivered)
    - Compose bar with text input and send button at bottom
    - Optimistic message display with "pending" status, update on API response
    - "New Conversation" button opening dialog for phone number + initial message, with number validation via `/org/sms/validate-number`
    - Search functionality to filter conversations by phone_number or contact_name
    - Template selector in compose area listing available SMS templates, populating input on selection
    - 15-second polling for new messages
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.10, 9.11, 12.5, 15.3, 15.4_

  - [x] 11.2 Add SMS navigation entry to `frontend/src/layouts/OrgLayout.tsx`
    - Add "SMS" menu item to organisation navigation with proper module gating
    - Route to the SmsChat page
    - _Requirements: 9.9_

  - [x] 11.3 Create `frontend/src/pages/sms/SmsUsageSummary.tsx` — org admin usage display
    - SMS usage card: total sent, total cost, quota remaining, overage status
    - Monthly cost trend chart with daily/weekly aggregation
    - 80% quota warning indicator
    - _Requirements: 14.2, 14.3, 14.4, 14.5_

- [x] 12. SMS templates integration
  - [x] 12.1 Wire existing `NotificationTemplate` system for Connexus SMS dispatch
    - Ensure SMS templates render with provided variables and send rendered body via Connexus
    - Template rendering uses existing template logic
    - _Requirements: 15.1, 15.2_

- [x] 13. Final checkpoint — Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document (Properties 1-24)
- The backend uses Python (FastAPI, SQLAlchemy, httpx, Hypothesis for property tests)
- The frontend uses TypeScript (React, Vite)
- Checkpoints ensure incremental validation at key integration boundaries
