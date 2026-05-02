# Test Scenarios: Portal Landing Page & Display

Covers Requirements 1-6 (critical bug fixes) and 61-62 (loyalty, branding).

---

## TS-1.1: Portal landing page displays customer name correctly

**Precondition:** Customer "Jane Smith" has portal enabled with a valid token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open `/portal/{token}` in browser | Page loads without errors |
| 2 | Check the welcome header | Shows "Welcome, Jane Smith" (first + last name) |
| 3 | Check the org name in the subtitle | Shows the organisation name from branding |

**Req:** 1.1, 1.2, 1.3

---

## TS-1.2: Summary cards show correct values

**Precondition:** Customer has 5 invoices, $1,200 total paid, $250 outstanding.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal landing page | Summary cards are visible |
| 2 | Check "Outstanding Balance" card | Shows "$250.00" with warning colour |
| 3 | Check "Total Invoices" card | Shows "5" |
| 4 | Check "Total Paid" card | Shows "$1,200.00" with success colour |

**Req:** 1.5, 1.6, 1.7

---

## TS-1.3: Portal applies org branding colours

**Precondition:** Org has `primary_colour: #16a34a` (green) in settings.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal landing page | Page loads |
| 2 | Check active tab indicator colour | Uses green (#16a34a), not default blue |
| 3 | Check summary card left border | Uses the org's primary colour |
| 4 | Check "Pay Now" button colour | Uses the org's primary colour |

**Req:** 1.4, 62.1, 62.2

---

## TS-1.4: Portal displays org logo

**Precondition:** Org has `logo_url` set in branding settings.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal landing page | Org logo appears in the header next to the welcome text |
| 2 | Remove `logo_url` from org settings | Logo is not shown, only text header |

**Req:** 62.3

---

## TS-1.5: Portal falls back to default blue when no colours set

**Precondition:** Org has no `primary_colour` or `secondary_colour` in settings.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal landing page | All accent elements use default blue (#2563eb) |
| 2 | Check tab indicators, buttons, card borders | All consistently blue |

**Req:** 62.4

---

## TS-1.6: Powered By footer renders correctly

**Precondition:** Platform has Powered By config with `show_powered_by: true`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Scroll to bottom of portal page | "Powered by" footer is visible |
| 2 | Check footer content | Shows platform name and logo from config |

**Req:** 1.8

---

## TS-1.7: Vehicle history loads without errors

**Precondition:** Customer has 2 vehicles with service history.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Vehicles" tab | Vehicle list loads without errors |
| 2 | Check vehicle cards | Shows rego, make, model, year, colour |
| 3 | Click a vehicle to expand | Service history table appears with date, invoice number, description, total |

**Req:** 2.1, 2.2

---

## TS-1.8: WOF and Rego expiry badges display correctly

**Precondition:** Vehicle has `wof_expiry: 2025-03-15` and `rego_expiry: 2025-06-01`.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Vehicles tab | Vehicle card shows WOF and Rego badges |
| 2 | Check badge colours | WOF badge is red (expired), Rego badge is warning (within 60 days) |
| 3 | Test with null expiry dates | Badges are not shown (no "undefined" text) |

**Req:** 2.3, 2.4

---

## TS-1.9: Bookings tab loads without crash

**Precondition:** Customer has 3 bookings (1 pending, 1 confirmed, 1 completed).

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Bookings" tab | Booking list loads without errors |
| 2 | Check booking cards | Shows service type, date/time, status badge |
| 3 | Check empty state | Customer with no bookings sees "No bookings found" |

**Req:** 3.1, 3.2, 3.3

---

## TS-1.10: Invoice line items summary displays

**Precondition:** Invoice has line items: "Full service", "Oil filter", "Brake pads".

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Invoices" tab | Invoice list loads |
| 2 | Check invoice row | Shows "Full service, Oil filter, Brake pads" below the invoice number |
| 3 | Test with long descriptions (>120 chars) | Summary is truncated with "…" |
| 4 | Test with no line items | Summary is empty (no error) |

**Req:** 6.1, 6.2, 6.3, 6.4

---

## TS-1.11: Loyalty tab — no programme configured

**Precondition:** Org does NOT have an active loyalty programme.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Loyalty" tab | Shows "This business does not have a loyalty programme" |
| 2 | No points balance or transaction history shown | Correct |

**Req:** 61.1

---

## TS-1.12: Loyalty tab — programme exists, zero balance

**Precondition:** Org has active loyalty programme, customer has 0 points.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Loyalty" tab | Shows "You have 0 points" |
| 2 | Check explanation text | Shows earning explanation ("Earn points by paying invoices…") |

**Req:** 61.2

---

## TS-1.13: Loyalty tab — active balance with tiers

**Precondition:** Customer has 500 points, current tier "Silver", next tier "Gold" at 1000.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Loyalty" tab | Shows points balance "500" |
| 2 | Check tier cards | Shows "Silver" as current, "Gold" as next |
| 3 | Check progress bar | Shows 50% progress toward Gold |
| 4 | Check transaction history | Lists recent point transactions |

**Req:** 61.1, 61.2

---

## TS-1.14: Portal tabs are all present

**Precondition:** Customer has data across all modules.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal landing page | Tab bar is visible |
| 2 | Count tabs | Invoices, Quotes, Assets, Vehicles, Jobs, Claims, Documents, Projects, Progress Claims, Recurring, Bookings, Loyalty, Messages — all present |
| 3 | Click each tab | Each tab loads its content without errors |

**Req:** 16.4, 17.3, 19.3, 49.3, 50.3, 51.3, 63.4

---

## TS-1.15: Portal error state shows "Forgot your link?"

**Precondition:** Use an invalid/expired portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open `/portal/invalid-token-here` | Error message: "Unable to load your portal…" |
| 2 | Check for recovery link | "Forgot your link?" link is visible below the error |
| 3 | Click the link | Navigates to `/portal/recover` |

**Req:** 52.4

---

## TS-1.16: Token is removed from address bar after load

**Precondition:** Valid portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open `/portal/{token}` | Page loads successfully |
| 2 | Check browser address bar | URL has changed to `/portal/dashboard` (token removed) |

**Req:** 43.2

---

## TS-1.17: No-referrer meta tag is present

**Precondition:** Valid portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal page | Page loads |
| 2 | Inspect `<head>` in dev tools | `<meta name="referrer" content="no-referrer" />` is present |

**Req:** 43.1

---

## TS-1.18: Cache-Control headers on portal responses

**Precondition:** Valid portal token.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open portal page with Network tab open | API calls are visible |
| 2 | Check response headers on `/portal/{token}` | `Cache-Control: no-store` and `Pragma: no-cache` are present |
| 3 | Check headers on `/portal/{token}/invoices` | Same cache headers present |

**Req:** 43.3
