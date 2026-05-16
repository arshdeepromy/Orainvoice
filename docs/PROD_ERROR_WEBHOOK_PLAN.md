# Production Error Webhook & Kiro Investigation Pipeline — Detailed Plan

## Overview

This document describes a push-based error notification system that sends production errors to the local development environment in real-time, triggers automated investigation by Kiro, and notifies the developer via Telegram. The system separates concerns into two webhook channels: **operational errors** (user workflow failures) and **security events** (SOC monitoring).

---

## Current Infrastructure Audit

### Error Logging (Already Exists)

| Component | Location | Purpose |
|---|---|---|
| `app/core/errors.py` | `log_error()` function | Writes to `error_log` table with severity, category, PII sanitisation |
| `app/main.py` | `sqlalchemy_exception_handler` | Catches all SQLAlchemy errors, logs to DB |
| `app/main.py` | `general_exception_handler` | Catches all unhandled exceptions, logs to DB |
| `app/tasks/notifications.py` | Background task errors | Logs notification delivery failures |
| `app/modules/notifications/` | Service-level errors | Logs email/SMS delivery issues |

**Severity Levels:** `info`, `warning`, `error`, `critical`

**Categories:** `payment`, `integration`, `storage`, `authentication`, `data`, `background_job`, `application`

### Audit Log (Already Exists)

| Component | Location | Purpose |
|---|---|---|
| `app/core/audit.py` | `write_audit_log()` function | Append-only audit trail, tamper-evident |
| `audit_log` table | PostgreSQL | `REVOKE UPDATE, DELETE` on app role |

**Security-relevant actions already tracked:**
- `auth.login_success` / `auth.login_failed`
- `auth.ip_blocked`
- `auth.anomalous_login_detected`
- `auth.token_reuse_detected`
- `auth.passkey_clone_detected`
- `auth.passkey_login_flagged_rejected`
- `auth.all_sessions_invalidated`
- `auth.session_terminated`
- `auth.mfa_verify_failed`
- `auth.mfa_method_disabled`
- `auth.password_reset_requested` / `auth.password_reset_completed`
- `auth.password_reset_via_backup_code`
- `auth.email_changed`
- `admin.user_status_toggled` / `admin.user_deleted` / `admin.user_mfa_reset`
- `admin.org_context_switched`
- `admin.integration_backup_exported` / `admin.integration_settings_restored`
- `permission_override.deleted`

### Network Topology

| Node | IP | Role |
|---|---|---|
| Local Dev Machine | 192.168.1.168 | DEV primary, Prod Standby, Kiro IDE |
| Raspberry Pi | 192.168.1.90 | PROD primary, Dev Standby |

Both nodes are on the same LAN subnet — direct HTTP communication is possible without port forwarding or tunnelling.

### Docker Services (DEV)

| Service | Exposed Ports |
|---|---|
| app (FastAPI) | 8000 (internal), 2222 (SSH) |
| nginx | 80 |
| postgres | 5434 |
| redis | 6379 |
| frontend | (internal only, served via nginx) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  PROD (Pi 192.168.1.90:8999)                                        │
│                                                                     │
│  exception_handler ──┐                                              │
│  log_error()         ├──► Webhook Dispatcher (fire-and-forget)      │
│  write_audit_log() ──┘         │                                    │
│                                │ HTTP POST (LAN)                    │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DEV Machine (192.168.1.168)                                        │
│                                                                     │
│  ┌─────────────────────────────────────────────┐                    │
│  │  Webhook Receiver (port 9090)               │                    │
│  │  - /webhook/prod-error    → writes JSON     │                    │
│  │  - /webhook/security-event → writes JSON    │                    │
│  └──────────────┬──────────────────────────────┘                    │
│                 │ writes file                                        │
│                 ▼                                                    │
│  .kiro/prod-errors/{id}.json                                        │
│  .kiro/security-events/{id}.json                                    │
│                 │                                                    │
│                 ▼ (Kiro fileCreated hook)                            │
│  ┌─────────────────────────────────────────────┐                    │
│  │  Kiro Agent                                  │                    │
│  │  1. Read error JSON                          │                    │
│  │  2. SSH into Pi, verify error in logs        │                    │
│  │  3. Gather context (stack trace, request)    │                    │
│  │  4. Send Telegram notification               │                    │
│  │  5. Wait for developer chat interaction      │                    │
│  └─────────────────────────────────────────────┘                    │
│                 │                                                    │
│                 ▼ (curl to Telegram Bot API)                         │
│  ┌─────────────────────────────────────────────┐                    │
│  │  Telegram Bot → Developer's Phone            │                    │
│  └─────────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Webhook Channel 1: Operational Errors

### Purpose
Capture all errors that affect user workflows — database failures, unhandled exceptions, integration timeouts, payment processing errors, background job failures.

### Trigger Conditions
Fire the webhook when `log_error()` is called with:
- `severity` = `error` OR `critical`
- Any `category` (data, payment, integration, storage, background_job, application)

Do NOT fire for:
- `severity` = `info` or `warning` (these are informational, not actionable)

### Payload Schema

```json
{
  "channel": "operational_error",
  "error_id": "uuid",
  "timestamp": "2026-05-16T03:08:24Z",
  "severity": "error|critical",
  "category": "data|payment|integration|storage|background_job|application",
  "module": "sqlalchemy",
  "function_name": "exception_handler",
  "message": "Database error: null value in column 'invoice_id'...",
  "http_method": "POST",
  "http_endpoint": "/api/v1/invoices/bulk-delete",
  "org_id": "uuid|null",
  "user_id": "uuid|null",
  "stack_trace_preview": "first 500 chars of stack trace",
  "environment": "prod"
}
```

### Implementation Location
Modify `app/core/errors.py` → `log_error()` function. After the INSERT succeeds, fire the webhook as an `asyncio.create_task()` (fire-and-forget).

### Deduplication
- Include a 60-second cooldown per unique `(module, function_name, http_endpoint)` tuple
- Use Redis key `webhook:dedup:{hash}` with 60s TTL
- Prevents flood during cascading failures (e.g., DB connection pool exhaustion)

---

## Webhook Channel 2: Security Events

### Purpose
Capture security-relevant events for SOC monitoring — failed logins, IP blocks, token reuse, anomalous access patterns, privilege escalation, MFA failures, admin actions on sensitive resources.

### Trigger Conditions
Fire the webhook when `write_audit_log()` is called with any of these actions:

**Authentication Threats (High Priority):**
- `auth.login_failed` (especially repeated)
- `auth.ip_blocked`
- `auth.anomalous_login_detected`
- `auth.token_reuse_detected`
- `auth.passkey_clone_detected`
- `auth.passkey_login_flagged_rejected`
- `auth.mfa_verify_failed`

**Session Security:**
- `auth.all_sessions_invalidated`
- `auth.session_terminated`

**Credential Changes (Medium Priority):**
- `auth.password_reset_requested`
- `auth.password_reset_via_backup_code`
- `auth.email_changed`
- `auth.mfa_method_disabled`

**Administrative Actions (Medium Priority):**
- `admin.user_status_toggled`
- `admin.user_deleted`
- `admin.user_mfa_reset`
- `admin.org_context_switched`
- `admin.integration_backup_exported`
- `admin.integration_settings_restored`
- `permission_override.deleted`

**Configuration Changes (Low Priority):**
- `admin.stripe_config_updated`
- `admin.smtp_config_updated`
- `admin.sms_provider_credentials_saved`

### Payload Schema

```json
{
  "channel": "security_event",
  "event_id": "uuid",
  "timestamp": "2026-05-16T03:08:24Z",
  "priority": "high|medium|low",
  "action": "auth.token_reuse_detected",
  "entity_type": "session",
  "entity_id": "uuid|null",
  "org_id": "uuid|null",
  "user_id": "uuid|null",
  "ip_address": "203.0.113.42",
  "device_info": "Mozilla/5.0...",
  "before_value": {},
  "after_value": {},
  "environment": "prod"
}
```

### Implementation Location
Modify `app/core/audit.py` → `write_audit_log()` function. After the INSERT, check if the action is in the security-relevant set. If yes, fire the webhook.

### Priority Classification
- **High:** Immediate threats — token reuse, passkey clone, IP block, anomalous login
- **Medium:** Credential/privilege changes — password resets, MFA disable, admin user actions
- **Low:** Configuration changes — integration credential updates

---

## Webhook Dispatcher (Shared Component)

### Location
New file: `app/core/webhook_dispatcher.py`

### Behaviour
- Async fire-and-forget (`asyncio.create_task`)
- 2-second timeout per request
- Silent failure (never crash the main request)
- Configurable target URL via environment variable: `WEBHOOK_RECEIVER_URL`
- Default: `http://192.168.1.168:9090` (local dev machine)
- Disabled when `WEBHOOK_RECEIVER_URL` is empty or unset (safe for environments without a receiver)

### Retry Policy
- No retries (fire-and-forget)
- If the dev machine is off, the error is still in the `error_log` table — nothing is lost
- The webhook is a notification mechanism, not a persistence layer

### Rate Limiting
- Operational errors: max 10 webhooks per minute (Redis counter)
- Security events: no rate limit (every security event matters)
- If rate limit exceeded, log a warning locally but don't fire

---

## Webhook Receiver (Local Dev Machine)

### Purpose
Lightweight HTTP server that receives webhooks from PROD and writes them to files that Kiro can watch.

### Technology
Python + FastAPI (single file, ~80 lines). Runs as a systemd service on the dev machine.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/webhook/prod-error` | POST | Receives operational errors |
| `/webhook/security-event` | POST | Receives security events |
| `/health` | GET | Health check for monitoring |

### File Output

```
.kiro/prod-errors/
  2026-05-16T03-08-24_78aa8b95.json    ← operational error
  2026-05-16T03-10-01_a1b2c3d4.json    ← operational error

.kiro/security-events/
  2026-05-16T03-08-24_sec_f1e2d3.json  ← security event
```

File naming: `{ISO_timestamp}_{short_id}.json` — sortable by time, unique.

### Systemd Service
```ini
[Unit]
Description=OraInvoice Webhook Receiver
After=network.target

[Service]
ExecStart=/usr/bin/python3 /mnt/hindi-tv/Invoicing/scripts/webhook_receiver.py
WorkingDirectory=/mnt/hindi-tv/Invoicing
Restart=always
User=romy

[Install]
WantedBy=multi-user.target
```

Port: 9090 (not conflicting with any existing service)

---

## Kiro Integration

### Hook 1: Operational Error Investigation

**Trigger:** `fileCreated` on `.kiro/prod-errors/*.json`

**Agent Prompt:**
```
A new production error was detected. Read the error file, then:
1. SSH into the Pi (192.168.1.90) and verify the error exists in container logs
2. Check the error_log table for additional context
3. Identify the affected code path and likely root cause
4. Send a Telegram notification with: severity, endpoint, short description, and your initial assessment
5. Do NOT make any changes to PROD — read-only investigation only

After notification, wait for developer instructions.
```

### Hook 2: Security Event Alert

**Trigger:** `fileCreated` on `.kiro/security-events/*.json`

**Agent Prompt:**
```
A security event was detected in production. Read the event file, then:
1. SSH into the Pi and check recent auth logs and container logs for corroborating evidence
2. Assess the threat level: is this a real attack, a misconfiguration, or normal user behaviour?
3. Send a Telegram notification with: priority, action, affected user/org, IP address, and your threat assessment
4. For HIGH priority events, include recommended immediate actions
5. Do NOT make any changes — read-only investigation only

After notification, wait for developer instructions.
```

### Steering File

New file: `.kiro/steering/prod-error-investigation.md`

Contents:
- Rules for read-only PROD access (SSH commands allowed, no writes)
- Telegram bot token and chat ID reference (from env vars)
- Investigation checklist (verify error, gather context, assess impact)
- Notification format template
- How to reproduce errors on local DEV when asked

---

## Telegram Notification

### Setup Required
1. Create bot via @BotFather → get bot token
2. Get your personal chat ID (message @userinfobot)
3. Store as environment variables on dev machine:
   - `TELEGRAM_BOT_TOKEN=<token>`
   - `TELEGRAM_CHAT_ID=<chat_id>`

### Message Format — Operational Error

```
🚨 PROD Error [critical/error]

📍 POST /api/v1/invoices/bulk-delete
💬 NotNullViolation: null value in column 'invoice_id' of relation 'payment_tokens'
🏢 Org: Sidhu Motors
👤 User: romy@example.com
🕐 16 May 2026, 03:08 PM

🔍 Assessment: Missing cascade delete for payment_tokens before invoice deletion. The bulk-delete endpoint doesn't clean up FK references.

💡 Likely fix: Add PaymentToken deletion before invoice delete in bulk_delete_invoices()

Reply in Kiro to investigate further.
```

### Message Format — Security Event

```
🔐 Security Event [HIGH]

⚡ auth.token_reuse_detected
👤 User: john@customer.com
🏢 Org: Sidhu Motors
🌐 IP: 203.0.113.42
📱 Chrome/Windows 11
🕐 16 May 2026, 03:08 PM

🔍 Assessment: A refresh token was presented that has already been rotated. This could indicate token theft or a replay attack. All sessions for this user have been invalidated.

⚠️ Recommended: Monitor for further attempts from this IP. Consider IP block if repeated.
```

---

## Developer Workflow (End-to-End)

### Scenario: PROD throws an error

1. **PROD:** User triggers bulk invoice delete → `payment_tokens` FK violation
2. **PROD:** `exception_handler` catches it → `log_error()` writes to DB → webhook fires to `192.168.1.168:9090`
3. **DEV Machine:** Webhook receiver writes `.kiro/prod-errors/2026-05-16T03-08-24_78aa8b95.json`
4. **Kiro:** `fileCreated` hook fires → agent reads the JSON
5. **Kiro:** SSHs into Pi, runs `docker logs invoicing-app-1 --tail 50`, confirms the error
6. **Kiro:** Queries error_log table for full stack trace and request body
7. **Kiro:** Sends Telegram message with assessment
8. **Developer:** Sees Telegram notification on phone
9. **Developer:** Opens Kiro chat, says "reproduce this on local dev"
10. **Kiro:** Sets up test data on DEV, calls the same endpoint, confirms reproduction
11. **Developer:** "Fix it"
12. **Kiro:** Implements fix, runs tests, commits
13. **Developer:** "Deploy to prod"
14. **Kiro:** Syncs to Pi, rebuilds containers

### Scenario: Security event detected

1. **PROD:** Token reuse detected during auth refresh
2. **PROD:** `write_audit_log()` fires → security webhook to dev machine
3. **Kiro:** Investigates, sends HIGH priority Telegram alert
4. **Developer:** Reviews on phone, decides if action needed
5. **Developer:** "Block that IP" or "It's fine, user just had two tabs open"

---

## Implementation Tasks (Ordered)

### Phase 1: Backend Webhook Dispatcher
1. Create `app/core/webhook_dispatcher.py` — async fire-and-forget HTTP client
2. Add `WEBHOOK_RECEIVER_URL` to `.env` and settings
3. Modify `app/core/errors.py` → `log_error()` to call dispatcher for error/critical
4. Modify `app/core/audit.py` → `write_audit_log()` to call dispatcher for security actions
5. Add Redis-based deduplication for operational errors
6. Add rate limiting (10/min for errors, unlimited for security)

### Phase 2: Webhook Receiver
7. Create `scripts/webhook_receiver.py` — FastAPI app on port 9090
8. Create systemd service file `scripts/webhook-receiver.service`
9. Create `.kiro/prod-errors/` and `.kiro/security-events/` directories
10. Add both directories to `.gitignore`
11. Test end-to-end: trigger error on DEV → verify file appears

### Phase 3: Kiro Hooks & Steering
12. Create Kiro hook for `.kiro/prod-errors/*.json` (fileCreated → askAgent)
13. Create Kiro hook for `.kiro/security-events/*.json` (fileCreated → askAgent)
14. Create `.kiro/steering/prod-error-investigation.md` with investigation rules
15. Test: manually create a JSON file → verify Kiro picks it up

### Phase 4: Telegram Integration
16. Set up Telegram bot via @BotFather
17. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to dev machine env
18. Add Telegram send logic to the Kiro steering/hook prompt (via curl command)
19. Test: trigger error → verify Telegram message arrives

### Phase 5: Production Deployment
20. Deploy webhook dispatcher to PROD (Pi)
21. Start webhook receiver on dev machine
22. Verify full pipeline: PROD error → file → Kiro → Telegram
23. Verify security events: trigger login failure → Telegram alert

---

## Configuration Reference

### Environment Variables (PROD — .env.pi)

```bash
# Webhook receiver on dev machine (empty = disabled)
WEBHOOK_RECEIVER_URL=http://192.168.1.168:9090
```

### Environment Variables (DEV Machine — shell/systemd)

```bash
# Telegram bot for notifications
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_CHAT_ID=<your personal chat ID>
```

### .gitignore Additions

```
.kiro/prod-errors/
.kiro/security-events/
```

---

## Failure Modes & Resilience

| Failure | Impact | Mitigation |
|---|---|---|
| Dev machine off | Webhook silently dropped | Error still in DB; check error_log manually |
| Webhook receiver crashes | File not written | systemd auto-restart; errors still in DB |
| Kiro IDE not open | Hook doesn't fire | Files accumulate; processed when Kiro opens |
| Telegram API down | No phone notification | Kiro still investigates; check IDE directly |
| PROD Redis down | Dedup/rate-limit skipped | Webhook fires without dedup (acceptable) |
| Network partition (Pi ↔ Dev) | Webhook times out (2s) | No impact on PROD request; error in DB |

**Key principle:** The webhook is a best-effort notification layer. The `error_log` and `audit_log` tables remain the source of truth. Nothing is lost if the webhook fails.

---

## Security Considerations

- Webhook payloads are PII-sanitised (same as `error_log` — uses `sanitise_value()`)
- No secrets, passwords, or tokens in webhook payloads
- Communication is LAN-only (192.168.1.x subnet) — not exposed to internet
- Webhook receiver binds to `0.0.0.0:9090` but is only reachable on LAN
- Telegram messages contain org names and user emails (acceptable for private bot)
- Stack traces in Telegram are truncated to 500 chars (no full code paths)
- Security event payloads include IP addresses for threat correlation

---

## Future Enhancements (Not in Scope Now)

- **Webhook retry queue:** Redis-backed retry for guaranteed delivery (overkill for solo dev)
- **Aggregation:** Group related errors into incidents (e.g., 50 of the same error = 1 notification)
- **Auto-remediation:** Kiro automatically applies known fixes for recurring errors
- **Dashboard:** Web UI showing webhook delivery status and error trends
- **Multi-environment:** Separate channels for DEV vs PROD errors
- **WhatsApp fallback:** If Telegram is unreachable, fall back to Connexus SMS
