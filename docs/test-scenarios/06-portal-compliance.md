# Test Scenarios: Portal Compliance & Privacy

Covers Requirements 44-48 (compliance, privacy, operational features).

---

## TS-6.1: Cookie consent banner — first visit

**Precondition:** Clear localStorage, open portal in incognito.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal page | Cookie consent banner appears at the bottom |
| 2 | Check banner content | Explains cookie usage, has "Accept" and "Decline" buttons |
| 3 | Banner does not block page content | Portal is usable behind the banner |

**Req:** 44.1, 44.2

---

## TS-6.2: Cookie consent — accept

**Precondition:** Cookie consent banner visible.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Accept" | Banner dismisses |
| 2 | Check localStorage | `portal_cookie_consent` = "accepted" |
| 3 | Reload page | Banner does NOT reappear |

**Req:** 44.3

---

## TS-6.3: Cookie consent — decline

**Precondition:** Cookie consent banner visible.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Decline" | Banner dismisses |
| 2 | Check localStorage | `portal_cookie_consent` = "declined" |
| 3 | Reload page | Banner does NOT reappear |
| 4 | Only essential cookies remain | Non-essential cookies not set |

**Req:** 44.4

---

## TS-6.4: Cookie consent — returning visitor

**Precondition:** Previously accepted cookies.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal page | No cookie consent banner shown |

**Req:** 44.3

---

## TS-6.5: DSAR — request data export

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Scroll to "My Privacy" section | "Request Data Export" and "Request Account Deletion" buttons visible |
| 2 | Click "Request Data Export" | Confirmation dialog appears (blue) |
| 3 | Click "Confirm Request" | Success message: "Your data export request has been submitted…" |
| 4 | Check org admin's email | Notification received with customer name and request type |

**Req:** 45.1, 45.2, 45.3, 45.4

---

## TS-6.6: DSAR — request account deletion

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Request Account Deletion" | Confirmation dialog appears (red, warning tone) |
| 2 | Click "Confirm Deletion Request" | Success message shown |
| 3 | Check org admin's email | Notification with "Account Deletion" request type |

**Req:** 45.5

---

## TS-6.7: DSAR — cancel confirmation

**Precondition:** Confirmation dialog open.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Cancel" in the confirmation dialog | Dialog closes, no request submitted |

**Req:** 45.2

---

## TS-6.8: DSAR — error handling

**Precondition:** Simulate API failure.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Submit DSAR with network disconnected | Error message: "Failed to submit request. Please try again." |

**Req:** 45.2

---

## TS-6.9: DSAR — no admin user

**Precondition:** Org has no active org_admin user.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Submit DSAR from portal | Request succeeds (audit logged) |
| 2 | No email notification sent | Correct (gracefully skipped) |

**Req:** 45.4

---

## TS-6.10: Global portal toggle — disable

**Precondition:** Org admin, portal currently enabled.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Org Settings > Portal | Toggle is ON |
| 2 | Toggle OFF | Warning banner appears |
| 3 | Save settings | Portal disabled |
| 4 | Try any customer's portal link | Returns 403: "Customer portal is not available" |

**Req:** 46.1, 46.2

---

## TS-6.11: Global portal toggle — re-enable

**Precondition:** Portal disabled at org level.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Toggle portal ON in org settings | Save |
| 2 | Try customer's portal link | Portal loads successfully |

**Req:** 46.3

---

## TS-6.12: Portal access updates last_portal_access_at

**Precondition:** Customer with portal enabled.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Note customer's `last_portal_access_at` (null or old date) | Noted |
| 2 | Access portal via token link | Portal loads |
| 3 | Check customer record | `last_portal_access_at` updated to current time |

**Req:** 48.1

---

## TS-6.13: Analytics tracks portal view event

**Precondition:** Redis running, org admin access.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Access portal as customer | View event tracked in Redis |
| 2 | Check analytics endpoint | Today's "view" count incremented |

**Req:** 47.1

---

## TS-6.14: Analytics tracks all event types

**Precondition:** Active portal session.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Accept a quote | "quote_accepted" counter incremented |
| 2 | Create a booking | "booking_created" counter incremented |
| 3 | Initiate a payment | "payment_initiated" counter incremented |
| 4 | Check analytics endpoint | All counters reflect the actions |

**Req:** 47.1
