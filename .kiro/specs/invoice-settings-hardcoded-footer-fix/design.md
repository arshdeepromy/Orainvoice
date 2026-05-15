# Invoice Settings Hardcoded Footer Fix — Bugfix Design

## Overview

Four integration gaps exist after the invoice-settings-integration feature was deployed:

1. **Hardcoded footer in 14 PDF templates** — All templates output "Thank you for your business." unconditionally and conditionally output bank transfer instructions when a GST number exists, ignoring the configurable `invoice_footer_text` org setting. The fix replaces hardcoded text with the dynamic `org.invoice_footer` value (already passed to templates but rendered alongside hardcoded text rather than instead of it).

2. **InvoiceList.tsx split-panel missing sections** — The inline preview renders its own footer with the same hardcoded text and lacks Payment Terms + T&C sections that InvoiceDetail.tsx already has.

3. **InvoiceDetailData interface incomplete** — Missing `payment_terms_text`, `terms_and_conditions_enabled`, and `terms_and_conditions` fields causes API data to be silently discarded by TypeScript.

4. **T&C pre-fill timing** — `useState` initializer runs synchronously at mount, but `settings` from TenantContext is `null` until the async fetch completes, so T&C is never pre-filled on new invoices.

## Glossary

- **Bug_Condition (C)**: The set of conditions under which the system produces incorrect output — hardcoded footer text appears, split-panel lacks sections, or T&C fails to pre-fill
- **Property (P)**: The desired correct behavior — footer uses configurable text, split-panel renders all sections, T&C pre-fills after settings load
- **Preservation**: Existing behaviors that must remain unchanged — `org.invoice_footer` custom text still renders when set, notes section continues working, InvoiceDetail.tsx standalone page unaffected, edit mode uses stored values
- **`invoice_footer_text`**: The org setting stored in `organisations.settings` JSONB, passed to templates as `org.invoice_footer`
- **`_invoice_base.html`**: The Jinja2 base template that 12 child templates extend; defines the `{% block footer %}` block
- **Split-panel**: The right-side invoice preview in InvoiceList.tsx (distinct from the standalone InvoiceDetail.tsx page)

## Bug Details

### Bug Condition

The bug manifests across four scenarios: (A) any PDF is generated, (B) any invoice is viewed in the split-panel, (C) the InvoiceDetailData interface is used to type API data, and (D) a new invoice is created before TenantContext finishes loading.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { context: 'pdf' | 'split-panel' | 'interface' | 'create-form', orgSettings: OrgSettings, settingsLoaded: boolean }
  OUTPUT: boolean

  IF input.context == 'pdf' THEN
    // Any PDF render hits the hardcoded footer
    RETURN TRUE
  END IF

  IF input.context == 'split-panel' THEN
    // Split-panel always shows hardcoded footer and never shows Payment Terms / T&C
    RETURN TRUE
  END IF

  IF input.context == 'interface' THEN
    // Interface always missing the fields
    RETURN input.apiResponse HAS 'payment_terms_text' OR input.apiResponse HAS 'terms_and_conditions_enabled'
  END IF

  IF input.context == 'create-form' THEN
    // T&C pre-fill fails when settings not yet loaded at mount
    RETURN input.settingsLoaded == FALSE
           AND input.orgSettings.terms_and_conditions_enabled == TRUE
           AND input.orgSettings.terms_and_conditions IS NOT EMPTY
  END IF

  RETURN FALSE
END FUNCTION
```

### Examples

- **PDF footer**: Org has `invoice_footer_text = "All prices include GST"` → PDF outputs both "All prices include GST" AND "Thank you for your business." (expected: only "All prices include GST")
- **PDF footer empty**: Org has `invoice_footer_text = null` → PDF still outputs "Thank you for your business." (expected: no footer text at all)
- **Split-panel footer**: User views invoice → sees hardcoded "Thank you for your business." instead of org's configured footer text
- **Split-panel missing sections**: Invoice has `payment_terms_text = "Net 14 days"` from API → section not rendered (expected: "Payment Terms" section visible)
- **Interface discard**: API returns `{ ..., payment_terms_text: "Net 14", terms_and_conditions_enabled: true }` → TypeScript discards unknown fields
- **T&C pre-fill**: User clicks "New Invoice", settings load 200ms later → T&C field stays empty (expected: pre-fills once settings arrive)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `org.invoice_footer` conditional rendering (`{% if org.invoice_footer %}`) continues to work — the custom footer text still appears when configured
- Notes section in both InvoiceDetail.tsx and split-panel continues rendering `notes_customer`
- InvoiceDetail.tsx standalone page Payment Terms and T&C sections remain unchanged
- Edit mode continues using stored invoice `terms_and_conditions` value regardless of org settings
- `payment_terms_enabled` toggle continues to control whether `payment_terms_text` is included in API response
- Default notes pre-fill continues working as implemented
- All 12 child templates that override `{% block footer %}` maintain their visual styling (border, colours, layout)

**Scope:**
All inputs that do NOT involve PDF footer rendering, split-panel preview, the InvoiceDetailData interface, or new invoice creation with pending settings are completely unaffected by this fix.

## Hypothesized Root Cause

Based on code analysis, the root causes are confirmed:

1. **PDF Footer — Template authoring oversight**: When `_invoice_base.html` and all child templates were created, the footer block was written with hardcoded text as a "nice default." The `org.invoice_footer` conditional was added later but placed ABOVE the hardcoded lines rather than replacing them. The `invoice_footer_text` setting is correctly passed as `org.invoice_footer` in the template context (confirmed in `service.py` line 3729), but the template renders it alongside hardcoded text.

2. **Split-panel — Incomplete feature rollout**: The invoice-settings-integration feature added Payment Terms and T&C to InvoiceDetail.tsx but the split-panel in InvoiceList.tsx has its own separate rendering code that was never updated. The footer section was copy-pasted from an early version.

3. **Interface — TypeScript strictness**: The `InvoiceDetailData` interface was defined before the invoice-settings-integration feature added `payment_terms_text` and `terms_and_conditions_enabled` to the API response. TypeScript silently drops fields not in the interface when the response is typed.

4. **T&C pre-fill — React lifecycle mismatch**: `useState(() => ...)` initializer runs exactly once at component mount. At that point, `settings` from `useTenant()` is `null` because `fetchSettings` is async (triggered by a `useEffect` in TenantProvider). The initializer evaluates `settings?.invoice?.terms_and_conditions_enabled` as `undefined`, so the condition is falsy and the field initializes to `''`.

## Correctness Properties

Property 1: Bug Condition - PDF Footer Uses Configurable Text Only

_For any_ PDF template render where `invoice_footer_text` is set in org settings, the generated PDF footer SHALL contain only the `invoice_footer_text` content and SHALL NOT contain "Thank you for your business." or "Payments can be paid by direct bank transfer..." hardcoded text.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Bug Condition - PDF Footer Empty When No Setting

_For any_ PDF template render where `invoice_footer_text` is empty or null, the generated PDF footer SHALL NOT contain any text content (no "Thank you for your business.", no bank transfer instructions).

**Validates: Requirements 2.1, 2.2**

Property 3: Bug Condition - Split-Panel Uses Configurable Footer

_For any_ invoice viewed in the InvoiceList.tsx split-panel, the footer section SHALL display the `invoice_footer_text` from org settings when present, and SHALL NOT display hardcoded "Thank you for your business." or bank transfer text.

**Validates: Requirements 2.4**

Property 4: Bug Condition - Split-Panel Renders Payment Terms and T&C

_For any_ invoice viewed in the split-panel where `payment_terms_text` is present in the invoice data, the split-panel SHALL render a "Payment Terms" section. For any invoice where `terms_and_conditions_enabled` is true and `terms_and_conditions` content exists, the split-panel SHALL render a "Terms & Conditions" section with HTML content.

**Validates: Requirements 2.5, 2.6**

Property 5: Bug Condition - T&C Pre-fills After Settings Load

_For any_ new invoice creation where `terms_and_conditions_enabled` is true and `terms_and_conditions` content exists in org settings, the T&C field SHALL be populated with the org settings content once settings finish loading, regardless of whether settings were available at initial component mount.

**Validates: Requirements 2.8**

Property 6: Preservation - Existing Custom Footer Still Renders

_For any_ org that has `invoice_footer_text` configured, the PDF templates and split-panel SHALL continue to render that custom text in the footer area (the `{% if org.invoice_footer %}` conditional is preserved).

**Validates: Requirements 3.1**

Property 7: Preservation - Notes and Other Sections Unchanged

_For any_ invoice with `notes_customer` content, the Notes section SHALL continue to render in both InvoiceDetail.tsx and the split-panel. The standalone InvoiceDetail.tsx page SHALL remain completely unchanged.

**Validates: Requirements 3.2, 3.3**

Property 8: Preservation - Edit Mode Uses Stored Values

_For any_ existing invoice being edited, the T&C field SHALL use the invoice's stored `terms_and_conditions` value regardless of org settings or settings loading state.

**Validates: Requirements 3.4**

## Fix Implementation

### Changes Required

#### 1. PDF Templates — Remove Hardcoded Footer Text (14 files)

**Files**: All 14 templates in `app/templates/pdf/`

**Change**: In each template's `{% block footer %}`, remove the hardcoded "Thank you for your business." line and the conditional bank transfer instructions. Keep only the `{% if org.invoice_footer %}` conditional rendering.

**Base template** (`_invoice_base.html`) — current:
```html
{% block footer %}
<div style="margin-top:24px; padding-top:10px; border-top:1px solid #eee; text-align:center;">
  {% if org.invoice_footer %}<p class="footer-text">{{ org.invoice_footer }}</p>{% endif %}
  <p class="footer-text">Thank you for your business.</p>
  {% if org.gst_number %}
  <p class="footer-text">Payments can be paid by direct bank transfer...</p>
  {% endif %}
</div>
{% endblock %}
```

**After fix**:
```html
{% block footer %}
<div style="margin-top:24px; padding-top:10px; border-top:1px solid #eee; text-align:center;">
  {% if org.invoice_footer %}<p class="footer-text">{{ org.invoice_footer }}</p>{% endif %}
</div>
{% endblock %}
```

Same pattern for all 12 child templates that override `{% block footer %}` plus the 2 standalone templates (`invoice.html`, `invoice_share.html`). Each template keeps its unique styling but removes hardcoded text lines.

#### 2. InvoiceDetailData Interface — Add Missing Fields

**File**: `frontend/src/pages/invoices/InvoiceList.tsx`

**Change**: Add three fields to the `InvoiceDetailData` interface:
```typescript
payment_terms_text?: string | null
terms_and_conditions_enabled?: boolean
terms_and_conditions?: string | null
```

#### 3. Split-Panel Preview — Add Payment Terms, T&C, Fix Footer

**File**: `frontend/src/pages/invoices/InvoiceList.tsx`

**Change**: In the split-panel rendering section:

1. Replace the hardcoded footer with configurable text from org settings (accessed via `useTenant()` which is already imported)
2. Add Payment Terms section (matching InvoiceDetail.tsx pattern)
3. Add Terms & Conditions section with `dangerouslySetInnerHTML` (matching InvoiceDetail.tsx pattern)

```tsx
{/* Payment Terms */}
{invoice?.payment_terms_text && (
  <div className="border-t border-gray-100 pt-4 mb-4">
    <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Payment Terms</p>
    <p className="text-sm text-gray-600">{invoice.payment_terms_text}</p>
  </div>
)}

{/* Terms & Conditions */}
{invoice?.terms_and_conditions_enabled && invoice?.terms_and_conditions && (
  <div className="border-t border-gray-100 pt-4 mb-4">
    <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Terms & Conditions</p>
    <div
      className="text-sm text-gray-600 prose prose-sm max-w-none"
      dangerouslySetInnerHTML={{ __html: invoice.terms_and_conditions }}
    />
  </div>
)}

{/* Footer — configurable */}
{settings?.branding?.name && (
  <div className="border-t border-gray-100 pt-4 text-xs text-gray-400">
    {invoice?.org_invoice_footer_text ? (
      <p>{invoice.org_invoice_footer_text}</p>
    ) : null}
  </div>
)}
```

Note: The footer text needs to come from somewhere accessible in the split-panel. Two options:
- **Option A**: Include `invoice_footer_text` in the invoice detail API response (adds a field to the backend)
- **Option B**: Read from TenantContext `settings` (already available via `useTenant()`)

**Chosen approach**: Option B — use TenantContext. The `invoice_footer_text` is an org-level branding setting, not per-invoice data. We'll need to expose it through TenantContext or read it from the existing settings fetch. Since OrgSettings already fetches it and it's available in the settings page form, we can add it to the TenantSettings interface.

Actually, looking at the current TenantContext, it doesn't expose `invoice_footer_text`. The simplest fix: add `invoice_footer_text` to the `/org/settings` API response mapping in TenantContext, or pass it through the invoice detail API. Since the split-panel already fetches invoice detail per-invoice, the cleanest approach is to include it in the invoice detail API response (same as `payment_terms_text` pattern).

**Revised approach**: Add `org_invoice_footer_text` to the invoice detail API response in the backend, and add it to `InvoiceDetailData` interface.

#### 4. Backend — Add `org_invoice_footer_text` to Invoice Detail Response

**File**: `app/modules/invoices/service.py` (in the `get_invoice` / invoice detail builder)

**Change**: Add `org_invoice_footer_text` to the invoice detail response dict, sourced from `settings.get("invoice_footer_text")`.

#### 5. T&C Pre-fill Timing Fix

**File**: `frontend/src/pages/invoices/InvoiceCreate.tsx`

**Change**: Replace the `useState` initializer approach with a `useEffect` that watches for settings to become available:

```typescript
const [termsAndConditions, setTermsAndConditions] = useState('')

// Pre-fill T&C from org settings once loaded (only on create, not edit)
useEffect(() => {
  if (!editId && settings?.invoice?.terms_and_conditions_enabled && settings?.invoice?.terms_and_conditions) {
    setTermsAndConditions(prev => prev || settings.invoice.terms_and_conditions)
  }
}, [editId, settings?.invoice?.terms_and_conditions_enabled, settings?.invoice?.terms_and_conditions])
```

The `prev || ...` guard ensures we don't overwrite if the user has already typed something. Same pattern should be applied to `customerNotes` for consistency (though that bug is less visible since notes pre-fill was already partially working when settings load fast enough).

**Important**: The edit-mode path (loading existing invoice data) must set `termsAndConditions` from the fetched invoice record, which happens in a separate `useEffect` that runs after the invoice is loaded. This takes priority because it runs after the settings pre-fill effect.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm the root cause analysis.

**Test Plan**: Render PDF templates with various `invoice_footer_text` values and assert the output HTML. Check InvoiceList.tsx split-panel rendering. Test InvoiceCreate.tsx T&C initialization timing.

**Test Cases**:
1. **PDF Footer with custom text**: Render `_invoice_base.html` with `org.invoice_footer = "Custom footer"` → assert output contains BOTH "Custom footer" AND "Thank you for your business." (will fail = confirms bug)
2. **PDF Footer empty**: Render with `org.invoice_footer = None` → assert output contains "Thank you for your business." (will fail = confirms bug)
3. **Split-panel missing Payment Terms**: Render split-panel with `payment_terms_text = "Net 14"` in invoice data → assert Payment Terms section NOT present (will fail = confirms bug)
4. **T&C pre-fill timing**: Mount InvoiceCreate with settings initially null, then settings load → assert T&C field remains empty (will fail = confirms bug)

**Expected Counterexamples**:
- PDF output always contains hardcoded "Thank you for your business." regardless of `invoice_footer_text` value
- Split-panel never renders Payment Terms or T&C sections
- T&C field initializes to empty and never updates when settings arrive

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  IF input.context == 'pdf' THEN
    result := renderTemplate(input.template, input.orgSettings)
    ASSERT result DOES NOT CONTAIN "Thank you for your business."
    ASSERT result DOES NOT CONTAIN "Payments can be paid by direct bank transfer"
    IF input.orgSettings.invoice_footer_text IS NOT EMPTY THEN
      ASSERT result CONTAINS input.orgSettings.invoice_footer_text
    END IF
  END IF

  IF input.context == 'split-panel' THEN
    result := renderSplitPanel(input.invoiceData)
    ASSERT result DOES NOT CONTAIN hardcoded footer text
    IF input.invoiceData.payment_terms_text THEN
      ASSERT result CONTAINS "Payment Terms" section
    END IF
    IF input.invoiceData.terms_and_conditions_enabled AND input.invoiceData.terms_and_conditions THEN
      ASSERT result CONTAINS "Terms & Conditions" section
    END IF
  END IF

  IF input.context == 'create-form' THEN
    result := mountInvoiceCreate(input.orgSettings, input.settingsLoadDelay)
    WAIT FOR settings to load
    ASSERT result.termsAndConditions == input.orgSettings.terms_and_conditions
  END IF
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT originalFunction(input) = fixedFunction(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many template context combinations to verify no regressions in non-footer sections
- It catches edge cases in the split-panel rendering (e.g., invoices without notes, without payments)
- It provides strong guarantees that edit-mode T&C loading is unchanged

**Test Plan**: Observe behavior on UNFIXED code first for notes rendering, edit-mode T&C loading, and non-footer PDF sections, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Notes Section Preservation**: Verify `notes_customer` renders in split-panel before and after fix
2. **Edit Mode T&C Preservation**: Verify editing an invoice loads stored `terms_and_conditions` regardless of org settings
3. **InvoiceDetail.tsx Unchanged**: Verify standalone detail page renders Payment Terms and T&C identically before and after fix
4. **PDF Non-Footer Sections**: Verify notes, payment terms, T&C sections above footer render identically before and after fix
5. **Custom Footer Text Preserved**: Verify `org.invoice_footer` conditional still renders custom text when set

### Unit Tests

- Test each of the 14 PDF templates renders only `org.invoice_footer` in footer (no hardcoded text)
- Test `InvoiceDetailData` interface accepts `payment_terms_text`, `terms_and_conditions_enabled`, `terms_and_conditions` fields
- Test split-panel renders Payment Terms section when `payment_terms_text` is present
- Test split-panel renders T&C section when enabled with content
- Test split-panel footer shows `org_invoice_footer_text` when present, nothing when absent
- Test T&C `useEffect` pre-fills when settings load after mount
- Test T&C `useEffect` does NOT overwrite user-entered content

### Property-Based Tests

- Generate random `invoice_footer_text` values (including empty/null) and verify PDF footer contains only that text or nothing
- Generate random invoice data combinations and verify split-panel renders correct sections based on field presence
- Generate random settings load timing and verify T&C pre-fill works regardless of delay
- Generate random invoice edit scenarios and verify stored T&C is always used over org defaults

### Integration Tests

- Full flow: Set `invoice_footer_text` in settings → generate PDF → verify footer content
- Full flow: Set `invoice_footer_text` to empty → generate PDF → verify no footer text
- Full flow: Enable payment terms + T&C → view invoice in split-panel → verify both sections render
- Full flow: Create new invoice with T&C enabled → verify T&C pre-fills after settings load
- Full flow: Edit existing invoice → verify stored T&C displayed regardless of org settings
