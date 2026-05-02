# Test Scenarios: Portal UX Polish

Covers Requirements 25-30 (UX polish), 63 (SMS messages).

---

## TS-5.1: Mobile share portal link — correct URL format

**Precondition:** Mobile app, customer with portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open invoice detail on mobile | "Share Portal Link" button visible |
| 2 | Tap "Share Portal Link" | Share sheet opens with URL `/portal/{customer_portal_token}` |
| 3 | Verify URL does NOT contain `/portal/invoices/{id}` | Correct format |
| 4 | Open quote detail on mobile | Same correct URL format |

**Req:** 25.1, 25.2

---

## TS-5.2: Mobile share link hidden when no portal token

**Precondition:** Customer with `enable_portal = false` or no token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open invoice detail for this customer on mobile | "Share Portal Link" button is NOT visible |

**Req:** 25.3, 25.4

---

## TS-5.3: Pagination on invoice list

**Precondition:** Customer with 50 invoices.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Invoices tab | First 20 invoices shown |
| 2 | Check API response in Network tab | `total: 50`, 20 items in array |
| 3 | Load next page (if pagination controls exist) | Next 20 invoices shown |

**Req:** 26.1, 26.2, 26.3

---

## TS-5.4: Pagination on all list endpoints

**Precondition:** Customer with data in multiple tabs.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Check `/portal/{token}/invoices?limit=5&offset=0` | Returns 5 items + total count |
| 2 | Check `/portal/{token}/vehicles?limit=5&offset=0` | Returns 5 items + total count |
| 3 | Check `/portal/{token}/quotes?limit=5&offset=0` | Returns 5 items + total count |
| 4 | Check `/portal/{token}/bookings?limit=5&offset=0` | Returns 5 items + total count |
| 5 | Check `/portal/{token}/jobs?limit=5&offset=0` | Returns 5 items + total count |

**Req:** 26.1, 26.2, 26.3

---

## TS-5.5: Portal i18n — locale applied to formatters

**Precondition:** Org has `locale: "de-DE"` configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal | `lang="de-DE"` attribute on root element |
| 2 | Check date formatting | Uses German date format (e.g., "15. Jun. 2025") |
| 3 | Check currency formatting | Uses German number format (e.g., "1.234,56 €") |

**Req:** 27.1, 27.2, 27.3

---

## TS-5.6: Portal i18n — default locale

**Precondition:** Org has no locale configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal | `lang="en-NZ"` attribute on root element |
| 2 | Check date formatting | Uses NZ format (e.g., "15 Jun 2025") |
| 3 | Check currency formatting | Uses NZ format (e.g., "$1,234.56") |

**Req:** 27.1, 27.4

---

## TS-5.7: Booking form includes service_type and notes

**Precondition:** Portal with booking capability.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "New Booking" | Form appears |
| 2 | Check form fields | "Service Type" input and "Notes" textarea are present |
| 3 | Fill in service type "WOF" and notes "Please check brakes" | Fields accept input |
| 4 | Submit booking | Check API request body includes `service_type` and `notes` |
| 5 | Check created booking | Shows "WOF" as service type and notes |

**Req:** 28.1, 28.2, 28.3

---

## TS-5.8: Refund status display

**Precondition:** Customer has refunded and partially refunded invoices.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Invoices tab | Invoice list loads |
| 2 | Check refunded invoice | Shows "Refunded" badge (blue/teal) |
| 3 | Check partially refunded invoice | Shows "Partially Refunded" badge (blue/teal) |
| 4 | Badges are not raw lowercase strings | Correct — user-friendly labels |

**Req:** 29.1, 29.2

---

## TS-5.9: PortalLayout dead code removed

**Precondition:** Check codebase.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Search for `PortalLayout.tsx` in `frontend/src/layouts/` | File does not exist |
| 2 | Search for "WorkshopPro NZ" hardcoded text | Not found in portal components |
| 3 | Check portal footer | Uses configurable `PoweredByFooter` component |

**Req:** 30.1, 30.2

---

## TS-5.10: SMS messages tab — chat layout

**Precondition:** Customer has SMS conversation history.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Messages" tab | Message list loads |
| 2 | Check inbound messages | Left-aligned, grey background |
| 3 | Check outbound messages | Right-aligned, accent-tinted background |
| 4 | Check message content | Body text, date, and status displayed |
| 5 | Messages ordered chronologically | Oldest first, newest at bottom |

**Req:** 63.1, 63.2, 63.3, 63.4

---

## TS-5.11: SMS messages — no phone number

**Precondition:** Customer has no phone number on file.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Messages" tab | Shows "No messages found" (not an error) |

**Req:** 63.1

---

## TS-5.12: SMS messages — no conversation

**Precondition:** Customer has phone but no SMS conversation.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Messages" tab | Shows "No messages found" |

**Req:** 63.1

---

## TS-5.13: Portal analytics displayed in org settings

**Precondition:** Org admin, portal has been accessed.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Org Settings > Portal tab | Analytics section visible |
| 2 | Check summary cards | Portal Views, Quotes Accepted, Bookings Created, Payments Initiated — all with 30-day totals |
| 3 | Check daily breakdown table | Shows days with activity, newest first |

**Req:** 47.2, 47.3

---

## TS-5.14: Portal analytics — no activity

**Precondition:** New org with no portal activity.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Org Settings > Portal tab | Analytics section shows all zeros |
| 2 | Daily breakdown table | Empty or shows "No activity" |

**Req:** 47.3

---

## TS-5.15: Last portal access in customer list

**Precondition:** Customer has accessed portal.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open customer list page | "Last Portal Access" column visible |
| 2 | Check customer who accessed portal | Date/time shown |
| 3 | Check customer who never accessed | Column is empty/dash |

**Req:** 48.1, 48.2

---

## TS-5.16: Portal analytics counter increments

**Precondition:** Org admin, Redis running.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Note current "Portal Views" count | e.g., 5 |
| 2 | Access portal as a customer | View event tracked |
| 3 | Refresh analytics page | "Portal Views" incremented to 6 |
| 4 | Accept a quote via portal | "Quotes Accepted" incremented |

**Req:** 47.1

---

## TS-5.17: Org portal toggle in settings

**Precondition:** Org admin access.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Org Settings > Portal tab | "Customer Portal" toggle visible |
| 2 | Toggle is ON by default | Shows "Enabled" |
| 3 | Toggle OFF | Warning banner appears about impact |
| 4 | Save | Portal disabled for all customers |
| 5 | Toggle ON, save | Portal re-enabled |

**Req:** 46.1, 46.3

---

## TS-5.18: Download PDF button on every invoice

**Precondition:** Customer with invoices.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Invoices tab | Each invoice row has a "Download PDF" button |
| 2 | Button appears for all statuses (issued, paid, overdue, etc.) | Correct |
| 3 | Button does NOT appear for draft invoices | Correct (drafts excluded from portal) |

**Req:** 18.4
