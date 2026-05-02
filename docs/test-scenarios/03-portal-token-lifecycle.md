# Test Scenarios: Portal Token Lifecycle

Covers Requirements 12-15 (token lifecycle & delivery) and 52 (self-service recovery).

---

## TS-3.1: Token auto-generated on enable_portal toggle

**Precondition:** Customer has `enable_portal = false`, `portal_token = null`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Edit customer, set `enable_portal = true` | Save succeeds |
| 2 | Check customer record | `portal_token` is populated (URL-safe string) |
| 3 | Check `portal_token_expires_at` | Set to now + org's TTL (default 90 days) |

**Req:** 12.1

---

## TS-3.2: Token revoked on disable

**Precondition:** Customer has portal enabled with a valid token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Edit customer, set `enable_portal = false` | Save succeeds |
| 2 | Check customer record | `portal_token = null`, `portal_token_expires_at = null` |
| 3 | Try the old portal link | Error: "Invalid or expired portal token" |

**Req:** 12.3

---

## TS-3.3: Existing token preserved on re-enable

**Precondition:** Customer has portal enabled with token "abc123".

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Disable portal, then re-enable | Token is regenerated (new token, not "abc123") |
| 2 | Alternative: enable portal when token already exists | Existing token is preserved |

**Req:** 12.1

---

## TS-3.4: Role access — org_admin and salesperson can toggle portal

**Precondition:** Users with different roles.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | As `org_admin`, enable portal for a customer | Succeeds |
| 2 | As `salesperson`, enable portal for a customer | Succeeds |
| 3 | As `technician`, try to enable portal | Fails (insufficient permissions) |

**Req:** 12.2

---

## TS-3.5: Send portal link via email

**Precondition:** Customer has portal enabled, valid token, and email "jane@example.com".

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Send Link" in customer detail | API call succeeds |
| 2 | Check email inbox | Email received with portal URL containing the token |
| 3 | Click the link in the email | Portal loads correctly |

**Req:** 13.1, 13.2

---

## TS-3.6: Send portal link — no email address

**Precondition:** Customer has portal enabled but no email address.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Send Link" | Error: "Customer has no email address on file" |

**Req:** 13.3

---

## TS-3.7: Send portal link — portal not enabled

**Precondition:** Customer has `enable_portal = false`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Call send-portal-link endpoint | Error: "Portal access is not enabled for this customer" |

**Req:** 13.4

---

## TS-3.8: Copy portal link in customer detail

**Precondition:** Customer has portal enabled with a valid token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open customer detail modal | Portal Access section shows the full URL |
| 2 | Click "Copy Link" | URL copied to clipboard, button shows "Copied" briefly |
| 3 | Paste in browser | Portal loads correctly |

**Req:** 14.1, 14.2

---

## TS-3.9: Portal access disabled state in customer detail

**Precondition:** Customer has `enable_portal = false`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open customer detail modal | Shows "Portal Access: Disabled" |
| 2 | No "Copy Link" or "Send Link" buttons visible | Correct |

**Req:** 14.3

---

## TS-3.10: Last portal access shown in customer detail

**Precondition:** Customer has accessed the portal recently.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open customer detail modal | "Last Seen" date is displayed in the portal section |
| 2 | Customer accesses portal again | "Last Seen" updates to current time |

**Req:** 48.2, 48.3

---

## TS-3.11: Configurable token TTL in org settings

**Precondition:** Org admin access.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Org Settings > Portal tab | "Portal Token TTL (days)" field is visible |
| 2 | Set TTL to 30 days, save | Settings saved successfully |
| 3 | Enable portal for a new customer | Token expires in 30 days (not default 90) |

**Req:** 15.1, 15.2, 15.3

---

## TS-3.12: Default TTL is 90 days

**Precondition:** Org has no `portal_token_ttl_days` configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Enable portal for a customer | Token expires in 90 days from now |

**Req:** 15.1

---

## TS-3.13: Token recovery — valid email

**Precondition:** Customer "jane@example.com" has portal enabled.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to `/portal/recover` | Recovery form is shown |
| 2 | Enter "jane@example.com", submit | Shows "Check your email" confirmation |
| 3 | Check email inbox | Portal link email received |

**Req:** 52.1, 52.2

---

## TS-3.14: Token recovery — unknown email (no enumeration)

**Precondition:** No customer with "nobody@example.com".

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Enter "nobody@example.com" on recovery page | Shows same "Check your email" message (no indication email doesn't exist) |
| 2 | No email sent | Correct (but user can't tell) |

**Req:** 52.3

---

## TS-3.15: Token recovery — multiple customers same email

**Precondition:** Two customers at different orgs share "jane@example.com".

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Submit recovery for "jane@example.com" | Two emails sent (one per org) |
| 2 | Each email contains the correct portal link | Links work for their respective orgs |

**Req:** 52.2

---

## TS-3.16: Token recovery — portal disabled customer skipped

**Precondition:** Customer has email but `enable_portal = false`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Submit recovery for that email | Generic success message shown |
| 2 | No email sent | Correct (customer's portal is disabled) |

**Req:** 52.3
