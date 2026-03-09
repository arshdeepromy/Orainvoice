# Organization Management - Global Admin Features

## Overview
Global admins can manage organizations through the admin API with comprehensive controls for activation, deactivation, soft delete, and hard delete operations.

## Available Actions

### 1. Suspend (Temporary Deactivation)
**Endpoint:** `PUT /api/v1/admin/organisations/{org_id}`

**Action:** `suspend`

**Description:** Temporarily suspend an organisation, preventing access while preserving all data.

**Requirements:**
- Reason (required, stored in audit log)
- Optional: notify_org_admin flag

**Status Change:** Any active status → `suspended`

**Use Case:** Temporary suspension for non-payment, policy violations, or maintenance.

```json
{
  "action": "suspend",
  "reason": "Non-payment of subscription",
  "notify_org_admin": true
}
```

---

### 2. Reinstate (Reactivate from Suspended)
**Endpoint:** `PUT /api/v1/admin/organisations/{org_id}`

**Action:** `reinstate`

**Description:** Reactivate a suspended organisation.

**Requirements:**
- Organisation must be in `suspended` status
- Optional: notify_org_admin flag

**Status Change:** `suspended` → `active`

**Use Case:** Restore access after suspension reason is resolved.

```json
{
  "action": "reinstate",
  "notify_org_admin": true
}
```

---

### 3. Activate (General Activation)
**Endpoint:** `PUT /api/v1/admin/organisations/{org_id}`

**Action:** `activate`

**Description:** Activate an organisation from any non-deleted state (trial, grace_period, suspended).

**Requirements:**
- Organisation must NOT be in `deleted` status
- Optional: notify_org_admin flag

**Status Change:** Any non-deleted status → `active`

**Use Case:** Activate from trial, grace period, or suspended state.

```json
{
  "action": "activate",
  "notify_org_admin": true
}
```

---

### 4. Deactivate (Permanent Deactivation)
**Endpoint:** `PUT /api/v1/admin/organisations/{org_id}`

**Action:** `deactivate`

**Description:** Deactivate an organisation (similar to suspend but semantically different).

**Requirements:**
- Reason (required, stored in audit log)
- Optional: notify_org_admin flag

**Status Change:** Any active status → `suspended`

**Use Case:** Permanent deactivation for closed accounts or policy violations.

```json
{
  "action": "deactivate",
  "reason": "Account closed by customer request",
  "notify_org_admin": true
}
```

---

### 5. Soft Delete (Mark as Deleted)
**Endpoint:** 
1. `PUT /api/v1/admin/organisations/{org_id}` (Step 1: Request)
2. `DELETE /api/v1/admin/organisations/{org_id}` (Step 2: Confirm)

**Action:** `delete_request` → `DELETE` with confirmation token

**Description:** Mark organisation as deleted (soft delete). Data remains in database but organisation is inaccessible.

**Requirements:**
- Step 1: Reason (required)
- Step 2: Confirmation token from step 1
- Optional: notify_org_admin flag

**Status Change:** Any status → `deleted`

**Use Case:** Soft delete for data retention compliance, potential recovery.

**Step 1 - Request Deletion:**
```json
{
  "action": "delete_request",
  "reason": "Customer requested account deletion",
  "notify_org_admin": true
}
```

**Response:**
```json
{
  "message": "Soft deletion confirmation required...",
  "organisation_id": "uuid",
  "organisation_name": "Example Org",
  "confirmation_token": "token_here",
  "expires_in_seconds": 300
}
```

**Step 2 - Confirm Deletion:**
```json
{
  "reason": "Customer requested account deletion",
  "confirmation_token": "token_from_step_1",
  "notify_org_admin": true
}
```

---

### 6. Hard Delete (Permanent Removal)
**Endpoint:** 
1. `PUT /api/v1/admin/organisations/{org_id}` (Step 1: Request)
2. `DELETE /api/v1/admin/organisations/{org_id}/hard` (Step 2: Confirm)

**Action:** `hard_delete_request` → `DELETE /hard` with confirmation token

**Description:** PERMANENTLY delete organisation and ALL related data from database. This is IRREVERSIBLE.

**Requirements:**
- Step 1: Reason (required)
- Step 2: Confirmation token from step 1
- Step 2: User must type "PERMANENTLY DELETE" exactly

**Deletes:**
- Organisation record
- All users in the organisation
- All vehicles, customers, invoices, quotes, etc.
- Audit logs are KEPT for compliance

**Use Case:** Complete data removal for GDPR compliance, legal requirements.

**Step 1 - Request Hard Deletion:**
```json
{
  "action": "hard_delete_request",
  "reason": "GDPR data deletion request"
}
```

**Response:**
```json
{
  "message": "PERMANENT deletion confirmation required. This will remove ALL data...",
  "organisation_id": "uuid",
  "organisation_name": "Example Org",
  "confirmation_token": "token_here",
  "expires_in_seconds": 300
}
```

**Step 2 - Confirm Hard Deletion:**
```json
{
  "reason": "GDPR data deletion request",
  "confirmation_token": "token_from_step_1",
  "confirm_text": "PERMANENTLY DELETE"
}
```

**Response:**
```json
{
  "message": "Organisation 'Example Org' and all related data permanently deleted from database",
  "organisation_id": "uuid",
  "organisation_name": "Example Org",
  "records_deleted": {
    "organisations": 1,
    "users": 5,
    "audit_logs_kept": 150
  }
}
```

---

### 7. Move Plan
**Endpoint:** `PUT /api/v1/admin/organisations/{org_id}`

**Action:** `move_plan`

**Description:** Move organisation to a different subscription plan.

**Requirements:**
- new_plan_id (required, UUID of target plan)
- Optional: notify_org_admin flag

**Use Case:** Upgrade/downgrade subscription, migrate to new pricing.

```json
{
  "action": "move_plan",
  "new_plan_id": "uuid-of-new-plan",
  "notify_org_admin": true
}
```

---

## Organisation Status Values

The `status` field in the organisations table supports these values:

- `trial` - Organisation in trial period
- `active` - Active, paying organisation
- `grace_period` - Payment failed, grace period active
- `suspended` - Temporarily suspended (by admin or system)
- `deleted` - Soft deleted (data retained)

---

## Security Features

### Multi-Step Confirmation
Both soft delete and hard delete require a two-step process:
1. Request deletion (generates confirmation token)
2. Confirm deletion with token (expires in 5 minutes)

### Hard Delete Extra Protection
Hard delete requires:
1. Confirmation token
2. User must type "PERMANENTLY DELETE" exactly
3. Only accessible to Global_Admin role

### Audit Logging
All actions are logged in the audit_log table with:
- Action type
- User who performed the action
- Timestamp
- Reason (if provided)
- Before/after values
- IP address

---

## API Endpoints Summary

| Action | Method | Endpoint | Steps |
|--------|--------|----------|-------|
| Suspend | PUT | `/api/v1/admin/organisations/{id}` | 1 |
| Reinstate | PUT | `/api/v1/admin/organisations/{id}` | 1 |
| Activate | PUT | `/api/v1/admin/organisations/{id}` | 1 |
| Deactivate | PUT | `/api/v1/admin/organisations/{id}` | 1 |
| Soft Delete | PUT + DELETE | `/api/v1/admin/organisations/{id}` | 2 |
| Hard Delete | PUT + DELETE | `/api/v1/admin/organisations/{id}/hard` | 2 |
| Move Plan | PUT | `/api/v1/admin/organisations/{id}` | 1 |

---

## Testing

### Test Suspend
```bash
curl -X PUT http://localhost:8080/api/v1/admin/organisations/{org_id} \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"action": "suspend", "reason": "Test suspension"}'
```

### Test Hard Delete (Step 1)
```bash
curl -X PUT http://localhost:8080/api/v1/admin/organisations/{org_id} \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"action": "hard_delete_request", "reason": "Test deletion"}'
```

### Test Hard Delete (Step 2)
```bash
curl -X DELETE http://localhost:8080/api/v1/admin/organisations/{org_id}/hard \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Test deletion",
    "confirmation_token": "token_from_step_1",
    "confirm_text": "PERMANENTLY DELETE"
  }'
```

---

## Files Modified

- `app/modules/admin/schemas.py` - Added OrgHardDeleteRequest, OrgHardDeleteResponse schemas
- `app/modules/admin/service.py` - Added activate, deactivate, hard_delete_request actions, hard_delete_organisation function
- `app/modules/admin/router.py` - Added hard delete endpoint, updated PUT endpoint documentation

---

## Notes

- Soft delete preserves all data in the database (status = 'deleted')
- Hard delete permanently removes data (cannot be recovered)
- Audit logs are kept even after hard delete for compliance
- All actions require Global_Admin role
- Email notifications to Org_Admin are optional
- Confirmation tokens expire after 5 minutes
