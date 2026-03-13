# Requirements Document

## Introduction

This feature integrates WebSMS Connexus (https://websms.co.nz/api/connexus/) as the primary SMS sending provider for the BudgetFlow SaaS platform, replacing the existing Twilio and AWS SNS integrations. Firebase Phone Auth is retained for phone number verification (OTP). Connexus becomes the sole provider for outbound/inbound business SMS, two-way SMS chat, and template-based messaging. This spec also removes the Twilio SMS client and AWS SNS provider code, registers Connexus in the existing SMS provider infrastructure, adds webhook endpoints for two-way SMS, introduces a real-time SMS chat/conversation feature for org users, wires Connexus into the existing SMS usage tracking and billing systems, and exposes Connexus balance and number validation capabilities. The existing SMS pricing, package, and overage billing systems remain unchanged — this spec focuses on the Connexus provider integration, legacy provider removal, and the new two-way SMS chat feature.

## Current Implementation Context

The platform currently has the following SMS-related infrastructure that this integration will build upon or replace:

- **Existing Twilio SMS client** at `app/integrations/twilio_sms.py` (to be completely removed)
- **SMS provider system** exists with `SmsVerificationProvider` model, admin service layer, and provider management endpoints
- **SMS billing infrastructure** present with `sms_sent_this_month` usage tracking, `sms_package_purchases` table, and overage calculation
- **Admin UI** exists at `frontend/src/pages/admin/SmsProviders.tsx` for provider configuration (to be extended for Connexus)
- **Notification task system** at `app/tasks/notifications.py` currently uses `twilio_sms.send_org_sms()` (needs updating to use Connexus)
- **SMS provider service** at `app/modules/sms_providers/service.py` contains Twilio and AWS SNS test functions (to be removed)
- **Organization navigation** at `frontend/src/layouts/OrgLayout.tsx` (needs SMS chat menu item)

## Glossary

- **Connexus_Client**: The backend SMS client module (`app/integrations/connexus_sms.py`) that communicates with the WebSMS Connexus REST API for sending SMS, checking balance, validating numbers, and managing webhooks.
- **Connexus_API**: The WebSMS Connexus REST API at `https://websms.co.nz/api/connexus/`.
- **SMS_Provider_System**: The existing provider infrastructure (`SmsVerificationProvider` model, service layer, admin endpoints) that manages multiple SMS providers with priority and fallback.
- **SMS_Conversation**: A threaded record of SMS messages exchanged between an organisation and a specific phone number, enabling two-way chat.
- **SMS_Message_Record**: A single inbound or outbound SMS message stored within an SMS_Conversation, including direction, body, timestamp, delivery status, and cost metadata.
- **Inbound_SMS**: An SMS message received from an external phone number via the Connexus incoming message webhook.
- **Outbound_SMS**: An SMS message sent from the platform to an external phone number via the Connexus send API.
- **Delivery_Status_Webhook**: A webhook callback from Connexus reporting the delivery status of a previously sent Outbound_SMS.
- **Incoming_SMS_Webhook**: A webhook callback from Connexus delivering an Inbound_SMS to the platform.
- **SMS_Chat_UI**: The frontend interface where org users view SMS conversations and send replies in a threaded chat layout.
- **Global_Admin**: A platform administrator with access to provider configuration, integration settings, pricing, and cross-organisation reporting.
- **Org_Admin**: An organisation administrator who manages org settings, views SMS usage, and configures org-level SMS preferences.
- **Org_User**: Any authenticated user within an organisation who can access the SMS chat feature.
- **Organisation**: A tenant record in the multi-tenant platform, identified by `organisations.id`.
- **Connexus_Auth_Token**: A short-lived Bearer token (1 hour expiry) obtained by exchanging `client_id` and `client_secret` with the Connexus auth endpoint.
- **SMS_Part**: A single segment of an SMS message. Standard messages are 160 characters per part; unicode messages are 70 characters per part.
- **Number_Validation**: The Connexus IPMS lookup service that returns carrier, porting status, and network information for a New Zealand mobile number.
- **Connexus_Balance**: The account credit balance retrieved from the Connexus balance API, denominated in NZD.

## Requirements

### Requirement 1: Connexus SMS Client Module

**User Story:** As a developer, I want a Connexus SMS client that serves as the platform's primary SMS sending client, so that the platform can send SMS via the Connexus API after removing Twilio and AWS SNS.

#### Acceptance Criteria

1. THE Connexus_Client SHALL implement a `ConnexusConfig` dataclass containing `client_id`, `client_secret`, `sender_id`, and `api_base_url` fields, with `from_dict()` and `to_dict()` methods.
2. THE Platform SHALL create a shared module `app/integrations/sms_types.py` containing the `SmsMessage` and `SmsSendResult` dataclasses extracted from the existing Twilio client, making them provider-agnostic.
3. THE Connexus_Client SHALL implement a `ConnexusSmsClient` class with an async `send(message: SmsMessage) -> SmsSendResult` method using the shared dataclasses from `sms_types.py`.
4. WHEN sending an SMS, THE Connexus_Client SHALL POST to `{api_base_url}/sms/out` with `to` (international format), `body`, and optional `from` (sender ID) parameters.
5. WHEN the Connexus_API returns status "accepted", THE Connexus_Client SHALL return an `SmsSendResult` with `success=True` and `message_sid` set to the returned `message_id`.
6. IF the Connexus_API returns an error response, THEN THE Connexus_Client SHALL return an `SmsSendResult` with `success=False` and `error` containing the HTTP status code and response body.
7. IF a network or timeout error occurs during the API call, THEN THE Connexus_Client SHALL log the exception and return an `SmsSendResult` with `success=False` and `error` containing the exception message.
8. THE Connexus_Client SHALL use a 30-second HTTP timeout for all API calls.
9. THE Connexus_Client SHALL include the SMS part count from the Connexus response in the `SmsSendResult` metadata for cost tracking.

### Requirement 2: Connexus Authentication and Token Management

**User Story:** As a developer, I want the Connexus client to handle API key authentication with automatic token refresh, so that API calls are always authenticated without manual intervention.

#### Acceptance Criteria

1. THE Connexus_Client SHALL obtain a Bearer token by POSTing `client_id` and `client_secret` to `{api_base_url}/auth/token`.
2. THE Connexus_Client SHALL cache the Bearer token in memory and reuse the cached token for subsequent API calls.
3. WHEN the cached token is within 5 minutes of its 1-hour expiry, THE Connexus_Client SHALL proactively request a new token before the next API call.
4. WHEN an API call returns a 401 Unauthorized response, THE Connexus_Client SHALL request a new token and retry the failed API call exactly once.
5. IF the token refresh request fails, THEN THE Connexus_Client SHALL log the error and return an `SmsSendResult` with `success=False` and `error` describing the authentication failure.
6. THE Connexus_Client SHALL include the Bearer token in the `Authorization` header for all API calls except the token request itself.

### Requirement 3: Register Connexus as an SMS Provider

**User Story:** As a Global Admin, I want Connexus registered as the primary SMS sending provider, so that I can configure it as the active provider alongside Firebase Phone Auth (which handles OTP verification only).

#### Acceptance Criteria

1. THE SMS_Provider_System SHALL include a seed record for Connexus with `provider_key` set to "connexus", `display_name` set to "WebSMS Connexus", and `is_active` set to false by default.
2. WHEN a Global_Admin activates the Connexus provider, THE SMS_Provider_System SHALL store the encrypted `client_id`, `client_secret`, and `sender_id` credentials in the `credentials_encrypted` column.
3. THE SMS_Provider_System SHALL support setting Connexus as the default SMS sending provider, with Firebase Phone Auth remaining available solely for OTP/verification use cases.
4. THE notification task `send_sms_task()` SHALL resolve the active SMS provider from the SMS_Provider_System and dispatch via the Connexus client.
5. THE Migration SHALL remove the Twilio (`twilio_verify`) and AWS SNS (`aws_sns`) seed records from the `sms_verification_providers` table, retaining only Firebase Phone Auth and the new Connexus provider.
6. THE Platform SHALL delete the file `app/integrations/twilio_sms.py` and remove all imports and references to this module from the codebase.
7. THE Platform SHALL remove the `_test_twilio()` and `_test_aws_sns()` functions from `app/modules/sms_providers/service.py` and remove the corresponding test dispatch logic.
8. THE Platform SHALL update the `send_sms_task()` function in `app/tasks/notifications.py` to replace the Twilio `send_org_sms()` import and calls with Connexus provider resolution and dispatch.

### Requirement 4: Connexus Provider Admin Configuration UI

**User Story:** As a Global Admin, I want to configure Connexus credentials and settings through the admin interface, so that I can manage the provider without direct database access.

#### Acceptance Criteria

1. THE Admin_UI SHALL display a Connexus configuration section on the SMS Providers page (`SmsProviders.tsx`) with fields for `client_id`, `client_secret`, and `sender_id`.
2. WHEN a Global_Admin saves Connexus credentials, THE Admin_UI SHALL call the existing `PUT /admin/sms-providers/{provider_id}/credentials` endpoint.
3. THE Admin_UI SHALL provide a "Test Connection" button that sends a test SMS via the `POST /admin/sms-providers/{provider_id}/test` endpoint using the Connexus provider.
4. THE Admin_UI SHALL display the current Connexus account balance (retrieved from the Connexus balance API) on the provider configuration section.
5. WHEN the Connexus credentials are invalid or missing, THE Admin_UI SHALL display a clear error message indicating the authentication failure.
6. THE Admin_UI SHALL allow the Global_Admin to configure the webhook URLs for incoming SMS and delivery status callbacks, displaying the platform's webhook endpoint URLs for copy-paste into the Connexus dashboard.
7. THE Admin_UI SHALL remove the Twilio and AWS SNS credential field configurations from the `CREDENTIAL_FIELDS` map in `SmsProviders.tsx`, retaining only Firebase Phone Auth and Connexus.

### Requirement 5: Connexus Webhook Endpoints for Incoming SMS

**User Story:** As a platform operator, I want to receive incoming SMS from customers via Connexus webhooks, so that the platform can support two-way SMS communication.

#### Acceptance Criteria

1. THE Platform SHALL expose a POST endpoint at `/api/webhooks/connexus/incoming` that accepts incoming SMS payloads from the Connexus_API.
2. WHEN the Incoming_SMS_Webhook receives a valid payload containing `messageId`, `from`, `to`, `body`, and `timestamp`, THE Platform SHALL create or update an SMS_Conversation record linking the sender phone number to the matching Organisation.
3. WHEN the Incoming_SMS_Webhook receives a valid payload, THE Platform SHALL create an SMS_Message_Record with direction "inbound", the message body, sender number, and received timestamp.
4. IF the incoming SMS `to` number does not match any Organisation's configured sender number, THEN THE Platform SHALL log a warning and store the message with a null organisation reference for manual review.
5. THE webhook endpoint SHALL return HTTP 200 to the Connexus_API within 5 seconds to acknowledge receipt, regardless of internal processing outcome.
6. THE webhook endpoint SHALL validate the incoming payload structure and reject malformed requests with HTTP 400.
7. THE webhook endpoint SHALL be idempotent: receiving the same `messageId` twice SHALL NOT create duplicate SMS_Message_Records.

### Requirement 6: Connexus Webhook Endpoints for Delivery Status

**User Story:** As a platform operator, I want to receive delivery status updates from Connexus, so that the platform can track whether outbound SMS messages were delivered successfully.

#### Acceptance Criteria

1. THE Platform SHALL expose a POST endpoint at `/api/webhooks/connexus/status` that accepts delivery status payloads from the Connexus_API.
2. WHEN the Delivery_Status_Webhook receives a payload with `messageId` and `status`, THE Platform SHALL update the corresponding SMS_Message_Record delivery status.
3. THE Platform SHALL map Connexus status codes to internal statuses: 1 (DELIVRD) to "delivered", 2 (UNDELIV) to "undelivered", 4 (QUEUED) to "queued", 8 (ACCEPTD) to "accepted", 16 (UNDELIV) to "undelivered".
4. IF the `messageId` in the delivery status payload does not match any existing SMS_Message_Record, THEN THE Platform SHALL log a warning and discard the update.
5. THE webhook endpoint SHALL return HTTP 200 to the Connexus_API within 5 seconds to acknowledge receipt.
6. THE webhook endpoint SHALL be idempotent: receiving the same status update twice SHALL NOT change the record if the status is already set to the same value.

### Requirement 7: SMS Conversation and Message Data Model

**User Story:** As a developer, I want a data model for SMS conversations and messages, so that two-way SMS communication can be stored, queried, and displayed in the chat UI.

#### Acceptance Criteria

1. THE Platform SHALL create an `sms_conversations` table with columns: `id` (UUID, primary key), `org_id` (UUID, foreign key to organisations), `phone_number` (String, the external party's number in international format), `contact_name` (String, nullable, optional display name), `last_message_at` (DateTime with timezone), `last_message_preview` (String, truncated to 100 characters), `unread_count` (Integer, default 0), `is_archived` (Boolean, default false), `created_at` (DateTime with timezone), `updated_at` (DateTime with timezone).
2. THE Platform SHALL create an `sms_messages` table with columns: `id` (UUID, primary key), `conversation_id` (UUID, foreign key to sms_conversations), `org_id` (UUID, foreign key to organisations), `direction` (String, "inbound" or "outbound"), `body` (Text), `from_number` (String), `to_number` (String), `external_message_id` (String, nullable, the Connexus message_id), `status` (String, default "pending"), `parts_count` (Integer, default 1), `cost_nzd` (Numeric(10,4), nullable), `sent_at` (DateTime with timezone, nullable), `delivered_at` (DateTime with timezone, nullable), `created_at` (DateTime with timezone).
3. THE `sms_conversations` table SHALL have a unique constraint on `(org_id, phone_number)` to ensure one conversation per phone number per organisation.
4. THE `sms_conversations` table SHALL enforce row-level security (RLS) scoped to `org_id`, following the existing multi-tenant pattern.
5. THE `sms_messages` table SHALL enforce row-level security (RLS) scoped to `org_id`, following the existing multi-tenant pattern.
6. THE Platform SHALL create database indexes on `sms_conversations(org_id, last_message_at)` and `sms_messages(conversation_id, created_at)` for efficient query performance.

### Requirement 8: SMS Chat API Endpoints

**User Story:** As an Org User, I want API endpoints to list conversations, view message history, and send replies, so that the frontend chat UI can function.

#### Acceptance Criteria

1. THE Platform SHALL provide a `GET /org/sms/conversations` endpoint that returns paginated SMS_Conversations for the authenticated user's organisation, ordered by `last_message_at` descending.
2. THE Platform SHALL provide a `GET /org/sms/conversations/{conversation_id}/messages` endpoint that returns paginated SMS_Message_Records for a specific conversation, ordered by `created_at` ascending.
3. THE Platform SHALL provide a `POST /org/sms/conversations/{conversation_id}/reply` endpoint that accepts a `body` parameter and sends an Outbound_SMS via the active SMS provider to the conversation's phone number.
4. THE Platform SHALL provide a `POST /org/sms/conversations/new` endpoint that accepts `phone_number` and `body` parameters, creates a new SMS_Conversation if one does not exist for that number, and sends the initial Outbound_SMS.
5. WHEN a reply or new message is sent, THE Platform SHALL create an SMS_Message_Record with direction "outbound", status "pending", and update the SMS_Conversation `last_message_at` and `last_message_preview`.
6. WHEN a reply or new message is sent, THE Platform SHALL increment the Organisation's `sms_sent_this_month` counter (Business_SMS tracking).
7. THE Platform SHALL provide a `POST /org/sms/conversations/{conversation_id}/read` endpoint that resets the conversation's `unread_count` to 0.
8. THE Platform SHALL provide a `POST /org/sms/conversations/{conversation_id}/archive` endpoint that sets `is_archived` to true.
9. WHEN an Inbound_SMS is received via webhook, THE Platform SHALL increment the `unread_count` on the corresponding SMS_Conversation.
10. THE Platform SHALL create the module structure `app/modules/sms_chat/` with `__init__.py`, `router.py`, `service.py`, `models.py`, `schemas.py`, and `router_webhooks.py` files following the existing module patterns.

### Requirement 9: SMS Chat Frontend UI

**User Story:** As an Org User, I want a chat-style interface to view incoming SMS from customers and send replies, so that I can communicate with customers via SMS directly from the application.

#### Acceptance Criteria

1. THE SMS_Chat_UI SHALL display a conversation list panel showing all non-archived SMS_Conversations for the organisation, ordered by most recent message first.
2. THE SMS_Chat_UI SHALL display each conversation list item with the contact phone number (or contact name if set), last message preview, timestamp, and unread message count badge.
3. WHEN an Org_User selects a conversation, THE SMS_Chat_UI SHALL display the full message history in a scrollable chat view with inbound messages aligned left and outbound messages aligned right.
4. THE SMS_Chat_UI SHALL display each message with the message body, timestamp, and delivery status indicator (pending, accepted, delivered, undelivered).
5. THE SMS_Chat_UI SHALL provide a text input and send button at the bottom of the chat view for composing and sending reply messages.
6. WHEN an Org_User sends a reply, THE SMS_Chat_UI SHALL optimistically display the message in the chat view with "pending" status and update the status when the API responds.
7. THE SMS_Chat_UI SHALL provide a "New Conversation" button that opens a dialog to enter a phone number and initial message.
8. THE SMS_Chat_UI SHALL provide search functionality to filter conversations by phone number or contact name.
9. THE SMS_Chat_UI SHALL be accessible via a navigation menu item labeled "SMS" within the organisation dashboard, added to the navigation structure in `frontend/src/layouts/OrgLayout.tsx` with proper module gating.
10. THE SMS_Chat_UI SHALL be implemented as a new component at `frontend/src/pages/sms/SmsChat.tsx` following the existing page component patterns.
11. THE SMS_Chat_UI SHALL poll for new messages every 15 seconds or use server-sent events to receive real-time updates when new Inbound_SMS messages arrive.

### Requirement 10: Wire Connexus into Existing SMS Usage and Billing

**User Story:** As a platform operator, I want Connexus SMS usage to flow through the existing SMS billing system, so that usage tracking, overage calculation, and package credit deduction work seamlessly with the new provider.

#### Acceptance Criteria

1. WHEN an Outbound_SMS is sent via the Connexus_Client, THE SMS_Billing_System SHALL increment the Organisation's `sms_sent_this_month` counter by 1.
2. WHEN an Outbound_SMS is sent via the Connexus_Client, THE SMS_Billing_System SHALL record the SMS part count and cost per part ($0.10 + GST per part) on the SMS_Message_Record for cost tracking.
3. WHEN an Organisation has active SMS_Package credits, THE SMS_Billing_System SHALL deduct from the oldest package first (FIFO) for each Outbound_SMS sent via Connexus, following the existing package deduction logic.
4. THE existing overage calculation (`compute_sms_overage`) SHALL apply identically to SMS sent via Connexus.
5. THE existing `report_sms_overage_task()` SHALL include Connexus-sent SMS in the monthly overage billing calculation without modification.
6. THE `OrgSmsUsageRow` schema SHALL continue to report accurate usage data with Connexus as the sole SMS sending provider.

### Requirement 11: Connexus Balance Checking

**User Story:** As a Global Admin, I want to check the Connexus account balance from within the platform, so that I can monitor credit levels and top up before running out.

#### Acceptance Criteria

1. THE Connexus_Client SHALL implement an async `check_balance()` method that POSTs to `{api_base_url}/sms/balance` and returns the balance amount and currency.
2. THE Platform SHALL provide a `GET /admin/integrations/connexus/balance` endpoint accessible to Global_Admin that returns the current Connexus account balance in NZD.
3. WHEN the balance check API call fails, THE Connexus_Client SHALL return a descriptive error message instead of raising an unhandled exception.
4. THE Admin_UI SHALL display the current Connexus balance on the SMS provider configuration page, with a visual warning indicator when the balance falls below a configurable threshold.

### Requirement 12: Connexus Number Validation Integration

**User Story:** As a developer, I want to validate New Zealand mobile numbers via the Connexus IPMS lookup, so that the platform can verify numbers before sending SMS and display carrier information.

#### Acceptance Criteria

1. THE Connexus_Client SHALL implement an async `validate_number(number: str)` method that POSTs to `{api_base_url}/number/lookup` and returns carrier, porting status, original network, current network, and network code.
2. WHEN the number is valid, THE `validate_number` method SHALL return a structured result with `success=True` and the lookup data.
3. WHEN the number is invalid or the lookup fails, THE `validate_number` method SHALL return a structured result with `success=False` and a descriptive error.
4. THE Platform SHALL provide a `POST /org/sms/validate-number` endpoint that accepts a phone number and returns the validation result, accessible to Org_Admin and Org_User roles.
5. THE SMS_Chat_UI SHALL validate the phone number via the lookup endpoint when starting a new conversation and display carrier information to the user.

### Requirement 13: Connexus Webhook Configuration

**User Story:** As a Global Admin, I want to configure Connexus webhook URLs from the admin interface, so that incoming SMS and delivery status callbacks are routed to the platform automatically.

#### Acceptance Criteria

1. THE Connexus_Client SHALL implement an async `configure_webhooks(mo_webhook_url: str, dlr_webhook_url: str)` method that POSTs to `{api_base_url}/configure` to register both webhook URLs.
2. THE Platform SHALL provide a `POST /admin/integrations/connexus/configure-webhooks` endpoint accessible to Global_Admin that calls the Connexus configure API with the platform's webhook endpoint URLs.
3. THE Admin_UI SHALL display the platform's webhook URLs (`/api/webhooks/connexus/incoming` and `/api/webhooks/connexus/status`) on the Connexus configuration section for reference.
4. WHEN the webhook configuration API call succeeds, THE Admin_UI SHALL display a success confirmation.
5. IF the webhook configuration API call fails, THEN THE Admin_UI SHALL display the error message returned by the Connexus_API.

### Requirement 14: SMS Cost Tracking and Org Admin Usage Display

**User Story:** As an Org Admin, I want to see the cost of SMS usage for my organisation, so that I can monitor spending and make informed decisions about SMS package purchases.

#### Acceptance Criteria

1. THE Platform SHALL track the cost of each Outbound_SMS on the SMS_Message_Record, calculated as `parts_count × cost_per_part` where cost_per_part is the Connexus rate ($0.10 + GST per part).
2. THE Platform SHALL provide a `GET /org/sms/usage-summary` endpoint that returns: total SMS sent this month, total cost this month (sum of all Outbound_SMS costs), included quota from plan, package credits remaining, overage count, and overage charge.
3. THE Org_Admin dashboard SHALL display an SMS usage summary card showing total sent, total cost, quota remaining, and overage status.
4. THE Org_Admin dashboard SHALL display a monthly SMS cost trend chart showing daily or weekly cost aggregation for the current billing period.
5. WHEN the Organisation's SMS usage exceeds 80% of the effective quota (plan included + package credits), THE Platform SHALL display a warning notification to the Org_Admin.

### Requirement 15: Custom SMS Templates for Connexus

**User Story:** As an Org Admin, I want to send custom SMS templates via Connexus, so that I can use pre-defined message formats for common communications.

#### Acceptance Criteria

1. THE existing `NotificationTemplate` system SHALL support SMS templates that can be dispatched via the Connexus provider, using the same template rendering logic as existing SMS templates.
2. WHEN an Org_User sends a templated SMS from the SMS_Chat_UI, THE Platform SHALL render the template with the provided variables and send the rendered body via Connexus.
3. THE SMS_Chat_UI SHALL provide a template selector in the message compose area that lists available SMS templates for the organisation.
4. WHEN a template is selected, THE SMS_Chat_UI SHALL populate the message input with the rendered template text, allowing the user to review and edit before sending.

### Requirement 16: Database Migration for Connexus Integration

**User Story:** As a developer, I want the new tables and columns added via an Alembic migration, so that the schema changes are versioned and reversible.

#### Acceptance Criteria

1. THE Migration SHALL create the `sms_conversations` table with all columns defined in Requirement 7.
2. THE Migration SHALL create the `sms_messages` table with all columns defined in Requirement 7.
3. THE Migration SHALL create the unique constraint on `sms_conversations(org_id, phone_number)`.
4. THE Migration SHALL create indexes on `sms_conversations(org_id, last_message_at)` and `sms_messages(conversation_id, created_at)`.
5. THE Migration SHALL enable row-level security on both `sms_conversations` and `sms_messages` tables, following the existing RLS pattern.
6. THE Migration SHALL seed the Connexus provider record in the SMS provider table with `provider_key` "connexus" and `is_active` false, and remove the `twilio_verify` and `aws_sns` provider seed records.
7. THE Migration SHALL remove the "twilio" entry from the `integration_configs` check constraint, updating it to `name IN ('carjam','stripe','smtp')`.
8. THE Migration SHALL include a `downgrade()` function that drops the created tables, indexes, constraints, restores the removed provider seed records, and restores the original check constraint.
