# Future: Portal Password-Based Login (Zoho-Style)

**Priority:** Low — not needed now, planned for a future release
**Status:** Proposal
**Date:** 2026-05-03

---

## Summary

Replace (or supplement) the current token-link portal access with a Zoho-style password-based login flow. Customers would have a dedicated login page, set their own password on first invite, and log in with email + password on return visits.

## Current State

The portal currently uses a **link-based access model**:
- Admin enables portal → token generated → link sent via email
- Customer clicks link → token in URL validates access → session cookie set
- No password, no account creation, no login page
- Token removed from address bar after load for security
- "Forgot your link?" recovery page at `/portal/recover`

This works well for simplicity but doesn't match the Zoho experience where customers have proper accounts.

## Target State (Zoho Model)

1. **Invitation** — Admin enables portal for a contact → invitation email sent with portal URL and username
2. **Accept Invite** — Customer clicks invite link → lands on accept page → creates a password
3. **Login** — Customer visits `/portal/login` → enters email + password → accesses their portal
4. **Activity Tracking** — Admins see "Viewed" status icons on invoices/quotes and receive in-app notifications when customers access documents

## What Needs to Change

### Backend

#### New: `portal_accounts` table

```sql
CREATE TABLE portal_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organisations(id),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255),          -- bcrypt hash, NULL until invite accepted
    invite_token VARCHAR(255) UNIQUE,    -- one-time invite token
    invite_sent_at TIMESTAMPTZ,
    invite_accepted_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login_at TIMESTAMPTZ,
    failed_login_attempts INT DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, email)
);
```

#### New: `document_views` table

```sql
CREATE TABLE document_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portal_account_id UUID NOT NULL REFERENCES portal_accounts(id),
    document_type VARCHAR(50) NOT NULL,  -- 'invoice', 'quote', 'job_card'
    document_id UUID NOT NULL,
    first_viewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_viewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    view_count INT NOT NULL DEFAULT 1,
    UNIQUE(portal_account_id, document_type, document_id)
);
```

#### New endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/portal/invite` | Admin sends invite (internal, authenticated) |
| GET | `/portal/accept-invite/{invite_token}` | Validate invite token |
| POST | `/portal/accept-invite/{invite_token}` | Set password, activate account |
| GET | `/portal/login` | Login page (frontend route) |
| POST | `/portal/login` | Authenticate with email + password |
| POST | `/portal/forgot-password` | Send password reset email |
| POST | `/portal/reset-password/{reset_token}` | Set new password |
| GET | `/api/v2/customers/{id}/portal-activity` | Admin view of customer's document views |

#### Modified: invitation flow

When admin enables portal for a customer:
1. Create `portal_accounts` record with `email`, `invite_token = secrets.token_urlsafe(32)`
2. Send invitation email with link to `/portal/accept-invite/{invite_token}`
3. Customer clicks link → sets password → `invite_accepted_at` set, `password_hash` stored
4. Redirect to `/portal/login`

#### Modified: authentication

- `/portal/login` accepts `{ email, password, org_slug }` (org_slug needed for multi-tenant)
- Validates password via bcrypt
- Returns session cookie (reuse existing `portal_sessions` table)
- Account lockout after 5 failed attempts (30-minute lock)

### Frontend

#### New pages

- `/portal/login` — email + password form with org branding
- `/portal/accept-invite/{token}` — password creation form
- `/portal/forgot-password` — email input form
- `/portal/reset-password/{token}` — new password form

#### Modified: PortalPage.tsx

- Remove token-from-URL access (or keep as fallback)
- Check session cookie on load — if no session, redirect to `/portal/login`

#### New: document view tracking

- When customer opens Invoices tab → record view for each visible invoice
- When customer opens a specific invoice detail → record view
- Same for quotes, job cards

#### New: admin-side "Viewed" indicators

- Invoice list: show eye icon + "Viewed" badge when `document_views` record exists
- Quote list: same
- Customer detail: "Portal Activity" section showing recent document views
- In-app notification: "Jane Smith viewed Invoice INV-0042" in the notification bell

### Migration Strategy

Since customers currently access via token links:

1. **Phase 1**: Add portal accounts + login page alongside existing token access. Both work.
2. **Phase 2**: When admin enables portal, send invite email (new flow). Existing token links continue to work.
3. **Phase 3**: Existing token-only customers get a prompt to set a password on their next visit.
4. **Phase 4** (optional): Deprecate token-only access, require password login.

This avoids breaking existing portal links while transitioning to the new model.

## Security Considerations

- Passwords hashed with bcrypt (cost factor 12)
- Account lockout after 5 failed attempts
- Password reset tokens expire after 1 hour
- Invite tokens expire after 7 days
- Rate limit on login endpoint (10/min per IP)
- Rate limit on forgot-password (3/min per email)
- CSRF protection on all forms (already implemented)
- Session management (already implemented — 4h inactivity timeout)

## Effort Estimate

| Component | Estimate |
|-----------|----------|
| Portal accounts table + model | 1 day |
| Invite flow (backend + email) | 1 day |
| Login/logout endpoints | 1 day |
| Password reset flow | 1 day |
| Frontend: login, invite, reset pages | 2 days |
| Document view tracking (backend) | 1 day |
| Document view tracking (frontend indicators) | 1 day |
| In-app notifications for admins | 1 day |
| Migration from token-only to dual mode | 1 day |
| Testing | 2 days |
| **Total** | **~12 days** |

## Dependencies

- Existing portal session infrastructure (already built)
- Existing email sending infrastructure (already built)
- Existing in-app notification system (needs to be extended for portal events)

## References

- Zoho Books Customer Portal: invitation → password → login model
- Current implementation: `.kiro/specs/platform-feature-gaps/` (token-based access)
- Portal sessions: `app/modules/portal/models.py` → `PortalSession`
- Portal service: `app/modules/portal/service.py`
