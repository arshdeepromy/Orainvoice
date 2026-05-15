# Bugfix Requirements Document

## Introduction

After implementing the invoice settings integration feature (toggles for email signature, default notes, payment terms, T&C), several integration gaps were discovered during testing. The core issues are:

1. **Hardcoded footer text in all PDF templates** — "Thank you for your business." and bank transfer payment instructions are hardcoded in all 14 invoice PDF templates, ignoring the configurable `invoice_footer_text` org setting. The bank transfer text is now redundant with the toggle-controlled `payment_terms_text` field.
2. **InvoiceList.tsx split-panel preview missing sections** — The inline preview in the split-panel has its own rendering that was never updated with Payment Terms and T&C sections, and also has the same hardcoded footer text.
3. **InvoiceDetailData interface incomplete** — The `InvoiceDetailData` interface in InvoiceList.tsx doesn't include `payment_terms_text` or `terms_and_conditions_enabled` fields, so the API data is silently discarded.
4. **T&C pre-fill timing issue** — When creating a new invoice, the T&C field doesn't pre-fill from settings because `useState` initializer runs synchronously before TenantContext has finished loading settings asynchronously.

These bugs affect invoice presentation consistency across PDF, web preview (split-panel), and the invoice creation form.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN any of the 14 invoice PDF templates render a footer THEN the system outputs hardcoded "Thank you for your business." text regardless of the `invoice_footer_text` org setting value

1.2 WHEN any of the 14 invoice PDF templates render a footer AND the org has a GST number THEN the system outputs hardcoded "Payments can be paid by direct bank transfer. Please use your Invoice number as your ref number on your bank transfer." text, which is redundant with the now-configurable `payment_terms_text` field

1.3 WHEN the `invoice_footer_text` org setting is empty or not configured THEN the system still displays "Thank you for your business." in the PDF footer instead of showing nothing

1.4 WHEN a user views an invoice in the InvoiceList.tsx split-panel preview THEN the system displays hardcoded "Thank you for your business." and bank transfer text in the footer section

1.5 WHEN a user views an invoice in the InvoiceList.tsx split-panel preview AND the invoice has payment_terms_text from the API THEN the system does NOT display a Payment Terms section (the section is missing from the split-panel rendering)

1.6 WHEN a user views an invoice in the InvoiceList.tsx split-panel preview AND the invoice has terms_and_conditions enabled with content THEN the system does NOT display a Terms & Conditions section (the section is missing from the split-panel rendering)

1.7 WHEN the API returns `payment_terms_text` and `terms_and_conditions_enabled` fields for an invoice detail in the split-panel THEN the system silently discards these fields because the `InvoiceDetailData` interface does not include them

1.8 WHEN a user creates a new invoice AND TenantContext settings have not finished loading (async) AND `terms_and_conditions_enabled` is true with content saved THEN the system initializes the T&C field as empty string because `useState` initializer runs synchronously before settings are available

### Expected Behavior (Correct)

2.1 WHEN any invoice PDF template renders a footer THEN the system SHALL use the `invoice_footer_text` value from org settings as the footer content; if `invoice_footer_text` is empty or null, no footer text SHALL be displayed

2.2 WHEN any invoice PDF template renders a footer THEN the system SHALL NOT output any hardcoded "Thank you for your business." text or hardcoded bank transfer payment instructions

2.3 WHEN the `invoice_footer_text` org setting contains custom text THEN the system SHALL display that custom text in the PDF footer area

2.4 WHEN a user views an invoice in the InvoiceList.tsx split-panel preview THEN the system SHALL use the configurable `invoice_footer_text` from org settings for the footer; if empty, no footer text SHALL be displayed

2.5 WHEN a user views an invoice in the InvoiceList.tsx split-panel preview AND `payment_terms_text` is present in the invoice data THEN the system SHALL display a "Payment Terms" section with the payment terms content, matching the rendering in InvoiceDetail.tsx

2.6 WHEN a user views an invoice in the InvoiceList.tsx split-panel preview AND `terms_and_conditions_enabled` is true AND `terms_and_conditions` content exists THEN the system SHALL display a "Terms & Conditions" section with the HTML content rendered, matching InvoiceDetail.tsx

2.7 WHEN the API returns invoice detail data for the split-panel THEN the `InvoiceDetailData` interface SHALL include `payment_terms_text` and `terms_and_conditions_enabled` and `terms_and_conditions` fields so the data is properly typed and accessible

2.8 WHEN a user creates a new invoice AND `terms_and_conditions_enabled` is true with content saved in org settings THEN the system SHALL pre-fill the T&C field with the org settings content regardless of whether TenantContext was still loading at initial mount

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `org.invoice_footer` (the existing custom footer field) has content THEN the system SHALL CONTINUE TO render it in the PDF footer area (this existing conditional rendering is preserved)

3.2 WHEN an invoice has `notes_customer` content THEN the system SHALL CONTINUE TO display the Notes section in both InvoiceDetail.tsx and the InvoiceList.tsx split-panel preview

3.3 WHEN InvoiceDetail.tsx (the standalone detail page, not the split-panel) renders Payment Terms and T&C sections THEN the system SHALL CONTINUE TO render them as currently implemented (no changes needed to InvoiceDetail.tsx)

3.4 WHEN editing an existing invoice THEN the system SHALL CONTINUE TO use the invoice's stored `terms_and_conditions` value regardless of org settings or timing

3.5 WHEN `payment_terms_enabled` is false THEN the system SHALL CONTINUE TO exclude `payment_terms_text` from the invoice detail API response

3.6 WHEN the PDF templates render notes, payment terms, and T&C sections (above the footer) THEN the system SHALL CONTINUE TO render them based on toggle state as already implemented in the invoice-settings-integration feature

3.7 WHEN `default_notes_enabled` is true THEN the system SHALL CONTINUE TO pre-fill customer notes on new invoices as currently implemented
