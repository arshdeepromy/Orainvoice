# Test Scenarios: Portal Features

Covers Requirements 16-24 (feature coverage) and 49-51 (additional features).

---

## TS-4.1: Jobs tab displays job cards

**Precondition:** Customer has jobs in various statuses.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Jobs" tab | Job list loads |
| 2 | Check pending job | Shows "Pending" badge (warning colour) |
| 3 | Check in-progress job | Shows "In Progress" badge (info colour) |
| 4 | Check completed job | Shows "Completed" badge, linked invoice number visible |
| 5 | Check assigned staff name | Displayed when assigned |
| 6 | Check vehicle rego | Displayed when linked |

**Req:** 16.1, 16.2, 16.3, 16.4

---

## TS-4.2: Claims tab displays claims with timeline

**Precondition:** Customer has claims in various statuses.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Claims" tab | Claims list loads |
| 2 | Check claim card | Shows claim type, status badge, description |
| 3 | Check resolved claim | Shows resolution type and notes |
| 4 | Check action timeline | Timeline entries with status transitions and dates |

**Req:** 17.1, 17.2, 17.3

---

## TS-4.3: Invoice PDF download

**Precondition:** Customer has issued invoices.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Invoices" tab | Invoice list loads |
| 2 | Click "Download PDF" on an invoice | PDF downloads with correct filename (invoice-INV-0042.pdf) |
| 3 | Open the PDF | Contains correct invoice data |
| 4 | Try to download another customer's invoice | Returns error (ownership validation) |

**Req:** 18.1, 18.2, 18.3, 18.4

---

## TS-4.4: Compliance documents tab

**Precondition:** Customer has invoices with linked compliance documents.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Documents" tab | Document list loads |
| 2 | Check document card | Shows type badge, description, linked invoice number |
| 3 | Click "Download" | Document downloads |
| 4 | Customer with no documents | Shows "No compliance documents found" |

**Req:** 19.1, 19.2, 19.3

---

## TS-4.5: Payment — full payment flow

**Precondition:** Invoice with $350 balance, org has Stripe Connect.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Pay Now" on the invoice | Payment page opens |
| 2 | Amount field pre-filled with $350 | Correct |
| 3 | Click "Pay $350.00" | Redirected to Stripe Checkout |
| 4 | Complete Stripe payment | Redirected to payment success page |
| 5 | Check success page | Shows "Payment received" with link back to invoices |

**Req:** 4.1, 4.2, 5.1, 5.2, 5.3

---

## TS-4.6: Payment — partial payment

**Precondition:** Invoice with $500 balance.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Pay Now" | Payment page opens, amount = $500 |
| 2 | Change amount to $200 | Accepted |
| 3 | Click "Pay $200.00" | Redirected to Stripe Checkout for $200 |
| 4 | Try amount $0 | Validation error: "Minimum payment is $0.01" |
| 5 | Try amount $600 | Validation error: "Amount cannot exceed the balance due" |

**Req:** 20.1, 20.2, 20.3, 20.4

---

## TS-4.7: Payment — error states

**Precondition:** Various invoice states.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Try to pay a "paid" invoice | Error message displayed |
| 2 | Try to pay with no Stripe Connect | Error: "Organisation has not connected a Stripe account" |
| 3 | Try to pay a "voided" invoice | Error displayed |
| 4 | Double-click "Pay Now" | Button disabled after first click (loading state) |

**Req:** 4.3, 4.4

---

## TS-4.8: Contact details self-service update

**Precondition:** Customer has email and phone on file.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Check "My Details" section | Shows current email and phone |
| 2 | Click "Edit" | Form fields appear |
| 3 | Change email to "new@example.com" | Save succeeds, success message shown |
| 4 | Enter invalid email "notanemail" | Error: "Invalid email format" |
| 5 | Enter invalid phone "ab" | Error: "Invalid phone format" |
| 6 | Click "Cancel" | Reverts to original values |

**Req:** 21.1, 21.2, 21.3, 21.4

---

## TS-4.9: Booking cancellation

**Precondition:** Customer has a "confirmed" booking.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Bookings" tab | Booking list loads |
| 2 | Check confirmed booking | "Cancel" button is visible |
| 3 | Click "Cancel" | Booking status changes to "cancelled" |
| 4 | Check completed booking | No "Cancel" button (not cancellable) |
| 5 | Check cancelled booking | No "Cancel" button |

**Req:** 22.1, 22.2, 22.3, 22.4

---

## TS-4.10: Quote acceptance with notification

**Precondition:** Customer has a "sent" quote, org admin has email.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Quotes" tab | Quote list loads |
| 2 | Click "Accept" on a sent quote | Quote status changes to "accepted" |
| 3 | Check org admin's email | Notification received with quote number, customer name, accepted date |

**Req:** 23.1, 23.2, 23.3

---

## TS-4.11: Booking creation with confirmation

**Precondition:** Org has booking rules configured.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Bookings" tab, then "New Booking" | Booking form appears |
| 2 | Enter service type "Oil Change" | Field accepts input |
| 3 | Enter notes "Please use synthetic oil" | Field accepts input |
| 4 | Select a date and time slot | Slot selected |
| 5 | Submit booking | Booking created with status "confirmed" (not "pending") |
| 6 | Check org admin's email | Notification about new portal booking |

**Req:** 24.1, 24.2, 24.3, 28.1, 28.2, 28.3

---

## TS-4.12: Projects tab

**Precondition:** Customer has projects in various statuses.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Projects" tab | Project list loads |
| 2 | Check project card | Shows name, status badge, description |
| 3 | Check financial details | Contract value, budget, start/end dates displayed |
| 4 | Customer with no projects | Shows "No projects found" |

**Req:** 49.1, 49.2, 49.3

---

## TS-4.13: Recurring schedules tab

**Precondition:** Customer has recurring invoice schedules.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Recurring" tab | Schedule list loads |
| 2 | Check schedule card | Shows frequency, status, next billing date |
| 3 | Check line items summary | Descriptions and computed total displayed |
| 4 | Check auto-issue indicator | "Auto-issue" label shown when enabled |

**Req:** 50.1, 50.2, 50.3

---

## TS-4.14: Progress claims tab

**Precondition:** Customer has projects with progress claims.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Progress Claims" tab | Claims list loads |
| 2 | Check claim card | Shows claim number, status badge |
| 3 | Check progress bar | Shows completion percentage visually |
| 4 | Check financial details | Contract value, work completed, materials, retention, amount due |
| 5 | Draft claims not shown | Only submitted/approved/rejected visible |

**Req:** 51.1, 51.2, 51.3

---

## TS-4.15: Pay Now button visibility

**Precondition:** Various invoice states, org with Stripe Connect.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Check "issued" invoice with balance | "Pay Now" button visible |
| 2 | Check "partially_paid" invoice | "Pay Now" button visible |
| 3 | Check "overdue" invoice | "Pay Now" button visible |
| 4 | Check "paid" invoice | No "Pay Now" button |
| 5 | Check "voided" invoice | No "Pay Now" button |
| 6 | Org without Stripe Connect | No "Pay Now" buttons on any invoice |

**Req:** 4.1, 4.4

---

## TS-4.16: Empty states for all tabs

**Precondition:** Customer with no data in various modules.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Jobs tab (no jobs) | "No jobs found" |
| 2 | Claims tab (no claims) | "No claims found" |
| 3 | Documents tab (no docs) | "No compliance documents found" |
| 4 | Projects tab (no projects) | "No projects found" |
| 5 | Recurring tab (no schedules) | "No recurring schedules found" |
| 6 | Progress Claims tab (no claims) | "No progress claims found" |
| 7 | Messages tab (no messages) | "No messages found" |
| 8 | Vehicles tab (no vehicles) | "No vehicles found" |
| 9 | Invoices tab (no invoices) | "No invoices found" |

**Req:** All feature tabs

---

## TS-4.17: Error states for all tabs

**Precondition:** Simulate API failure (e.g., disconnect network).

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click any tab with network disconnected | Error banner: "Failed to load [feature]" |
| 2 | Reconnect and retry | Data loads successfully |

**Req:** All feature tabs

---

## TS-4.18: Invoice "Already Paid" display

**Precondition:** Invoice with $500 total, $300 already paid, $200 balance.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Pay Now" on the invoice | Payment page shows |
| 2 | Check "Already Paid" line | Shows "$300.00" |
| 3 | Check "Amount Due" line | Shows "$200.00" |
| 4 | Amount field pre-filled with $200 | Correct |

**Req:** 20.1
