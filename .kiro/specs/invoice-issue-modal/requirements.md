# Invoice Issue Modal — Requirements

## Summary
Replace the current "Create Invoice" button + inline payment method field with a confirmation modal that appears when the user clicks "Create Invoice". The modal gives the user control over payment method and whether to email the invoice.

## Requirements

### REQ-1: Remove Payment Method from Invoice Form
- Remove the "Payment Method" radio buttons (Cash, EFTPOS, Bank Transfer, Stripe) from the invoice creation/edit form body
- The payment method selection moves into the issue modal

### REQ-2: Issue Invoice Modal
- When user clicks "Create Invoice" button, a modal/popup appears instead of immediately creating the invoice
- Modal title: "Issue Invoice"
- Modal contains:
  1. **Payment Method** selection (radio buttons or dropdown):
     - Cash
     - EFTPOS
     - Bank Transfer
     - Online Payment (renamed from "Stripe")
  2. **Email Invoice** checkbox (checked by default if customer has email)
     - Label: "Email invoice to customer"
     - Shows the customer email address below when checked
  3. **Issue Invoice** button (primary action)
  4. **Cancel** button

### REQ-3: Rename "Stripe" to "Online Payment"
- Everywhere "Stripe" appears as a payment method label visible to users, rename to "Online Payment"
- Internal code/API can still use "stripe" as the value

### REQ-4: Conditional Email Send
- If "Email invoice" checkbox is checked → issue invoice AND send email
- If "Email invoice" checkbox is unchecked → issue invoice only (no email sent)
- Currently the system always emails on create — this gives user control

### REQ-5: Button Rename
- The primary action button in the modal: "Issue Invoice"
- The trigger button on the form can remain "Create Invoice" (it opens the modal)

### REQ-6: Preserve Existing Flows
- "Save as Draft" button remains unchanged (saves without issuing)
- "Mark Paid & Email" button remains unchanged — it does NOT use the issue modal (it has its own flow that marks paid + always emails)
- "QR Payment" button remains unchanged
- "Cancel" button remains unchanged

### REQ-7: Online Payment Generates Payment Link
- When "Online Payment" is selected as payment method, the backend generates a Stripe payment link (existing infrastructure)
- This payment link is used in the email CTA button and on the public HTML page

### REQ-8: Edit Mode Behavior
- When editing an existing draft invoice, the "Create Invoice" button text changes to "Issue Invoice"
- Clicking it opens the same Issue Invoice modal
- The modal behavior is identical in both create and edit flows
- After confirming in the modal, the invoice is updated (PUT) then issued

### REQ-9: Modal Loading State
- While the API call is in progress after clicking "Issue Invoice" in the modal, the button shows a loading spinner and is disabled
- The "Cancel" button is also disabled during submission
- If the API call fails, the modal stays open and shows an error message below the buttons
