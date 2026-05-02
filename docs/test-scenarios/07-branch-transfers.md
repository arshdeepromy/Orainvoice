# Test Scenarios: Branch Transfers

Covers Requirements 31-35 (transfer gaps) and 53-55 (additional transfer gaps).

---

## TS-7.1: Reject a pending transfer

**Precondition:** Pending stock transfer exists.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Stock Transfers page | Transfer list loads |
| 2 | Find pending transfer | "Approve" and "Reject" buttons visible |
| 3 | Click "Reject" | Transfer status changes to "rejected" |
| 4 | Check transfer row | Status badge shows "Rejected" (red) |

**Req:** 31.1, 31.2, 31.3, 31.4

---

## TS-7.2: Cannot reject non-pending transfer

**Precondition:** Transfer in "approved" status.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Try to call reject endpoint via API | Returns 400: "Cannot reject transfer in 'approved' status" |

**Req:** 31.4

---

## TS-7.3: Product search dropdown in transfer form

**Precondition:** Products exist in the system.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Request Transfer" | Form appears |
| 2 | Type "oil" in the Product field | Dropdown shows matching products with name + SKU |
| 3 | Select a product | Product name displayed, `product_id` set |
| 4 | Click "✕" to clear | Product field resets to search mode |
| 5 | Type less than 2 characters | No dropdown shown |

**Req:** 32.1, 32.2, 32.3

---

## TS-7.4: Receive confirmation — full receive

**Precondition:** Transfer in "executed" status, user at destination location.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Find executed transfer | "Receive" button visible |
| 2 | Click "Receive" | Receive dialog opens with quantity pre-filled |
| 3 | Confirm with full quantity | Status changes to "received" |

**Req:** 33.1, 33.2, 33.3

---

## TS-7.5: Receive button only at destination

**Precondition:** Transfer in "executed" status, user NOT at destination location.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Find executed transfer | "Receive" button is NOT visible |

**Req:** 33.3

---

## TS-7.6: Transfer detail view

**Precondition:** Existing transfers in various statuses.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click on a transfer row | Navigates to `/stock-transfers/{id}` |
| 2 | Check detail page | Shows all fields: source, destination, product, quantity, status, notes, requested by, approved by, dates |
| 3 | Check action buttons for pending | "Approve" and "Reject" buttons |
| 4 | Check action buttons for approved | "Execute" button |
| 5 | Check action buttons for executed (at destination) | "Receive" button |
| 6 | Check action buttons for received | No action buttons |
| 7 | Click "← Back" | Returns to transfer list |

**Req:** 34.1, 34.2, 34.3

---

## TS-7.7: Sidebar "Branch Transfers" link works

**Precondition:** User with branch_management module access.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Branch Transfers" in sidebar | Navigates to `/branch-transfers` |
| 2 | Page renders | Stock transfers page loads without 404 |

**Req:** 35.1, 35.2

---

## TS-7.8: Transfer audit trail

**Precondition:** Transfer that has gone through multiple status transitions.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open transfer detail page | Audit trail section visible |
| 2 | Check timeline entries | Shows "Transfer Created", "Transfer Approved", "Transfer Executed" etc. |
| 3 | Each entry has timestamp | Correct |
| 4 | Each entry has performer ID | Shows who performed the action |
| 5 | Partial receive entry has notes | Shows discrepancy details |

**Req:** 53.1, 53.2, 53.3

---

## TS-7.9: Audit trail for new transfer

**Precondition:** Create a new transfer.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create a stock transfer | Succeeds |
| 2 | Open transfer detail | Audit trail shows "Transfer Created" entry |
| 3 | Approve the transfer | "Transfer Approved" entry added |
| 4 | Execute the transfer | "Transfer Executed" entry added |
| 5 | Receive the transfer | "Transfer Received" entry added |

**Req:** 53.2

---

## TS-7.10: Partial transfer receive

**Precondition:** Transfer with quantity 100, in "executed" status.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Receive" | Dialog opens with quantity = 100 |
| 2 | Change quantity to 95 | Discrepancy warning: "Discrepancy: 5.000" |
| 3 | Confirm receive | Status changes to "partially_received" |
| 4 | Check detail page | Shows `received_quantity: 95`, `discrepancy_quantity: 5` |
| 5 | Audit trail | Shows "Partially Received" with discrepancy notes |

**Req:** 54.1, 54.2, 54.3

---

## TS-7.11: Partial receive — exceeding quantity

**Precondition:** Transfer with quantity 100.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Enter received quantity 101 | Error: "Received quantity cannot exceed the transfer quantity" |

**Req:** 54.1

---

## TS-7.12: Default receive is full quantity

**Precondition:** Transfer with quantity 50, in "executed" status.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Receive", don't change quantity | Pre-filled with 50 |
| 2 | Confirm | Status = "received", received_quantity = 50, discrepancy = 0 |

**Req:** 54.3

---

## TS-7.13: Transfer notification — create

**Precondition:** Two locations with managers, create a transfer.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create transfer from Location A to Location B | Transfer created |
| 2 | Check Location B manager's email | Notification received about new transfer |
| 3 | Location A manager | NOT notified (only destination on create) |

**Req:** 55.1

---

## TS-7.14: Transfer notification — approve/execute

**Precondition:** Pending transfer between two locations.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Approve the transfer | Both source and destination managers notified |
| 2 | Execute the transfer | Both managers notified again |

**Req:** 55.2

---

## TS-7.15: Transfer notification content

**Precondition:** Transfer notification sent.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Check notification email | Contains: action type, source branch, destination branch, quantity |

**Req:** 55.3

---

## TS-7.16: Transfer notification — no managers

**Precondition:** Locations with no assigned managers.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create a transfer | Transfer created successfully |
| 2 | No notification emails sent | Correct (gracefully skipped) |

**Req:** 55.1

---

## TS-7.17: Status filter on transfer list

**Precondition:** Transfers in various statuses.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Select "Pending" from status filter | Only pending transfers shown |
| 2 | Select "Partially Received" | Only partially received transfers shown |
| 3 | Select "All" | All transfers shown |

**Req:** 54.2

---

## TS-7.18: Transfer detail — partial receive fields

**Precondition:** Partially received transfer.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open transfer detail | "Received Quantity" field shown |
| 2 | "Discrepancy" field shown in orange | Correct |
| 3 | For fully received transfer | Discrepancy field not shown (or shows 0) |

**Req:** 54.2

---

## TS-7.19: Transfer detail — receive dialog from detail page

**Precondition:** Executed transfer, user at destination.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open transfer detail page | "Receive" button visible |
| 2 | Click "Receive" | Receive dialog opens (same as list view) |
| 3 | Enter quantity, confirm | Transfer received, page refreshes |

**Req:** 33.2, 54.1

---

## TS-7.20: Location manager scoping

**Precondition:** Location manager assigned to Location A only.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Stock Transfers page | Only transfers involving Location A are shown |
| 2 | Transfers between Location B and C | NOT visible |

**Req:** 33.3

---

## TS-7.21: Transfer workflow — full lifecycle

**Precondition:** Two locations, products in stock.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create transfer (A → B, 10 units) | Status: pending |
| 2 | Approve | Status: approved |
| 3 | Execute | Status: executed, stock moved |
| 4 | Receive (full) | Status: received |
| 5 | Check audit trail | 4 entries: created, approved, executed, received |

**Req:** 31-35, 53

---

## TS-7.22: Transfer workflow — rejection path

**Precondition:** Pending transfer.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Reject the transfer | Status: rejected |
| 2 | No stock movement | Correct |
| 3 | Audit trail | Shows "created" and "rejected" entries |

**Req:** 31.4, 53.2
