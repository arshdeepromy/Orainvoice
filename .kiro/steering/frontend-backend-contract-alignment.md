---
inclusion: auto
---

# Frontend–Backend Contract Alignment

This steering file prevents the most common class of bugs in this codebase: mismatches between what the frontend sends/expects and what the backend accepts/returns. This pattern caused ISSUE-001 (MFA field name mismatch, login payload mismatch, missing response fields), ISSUE-006 (systemic endpoint shape mismatches across 8+ pages), ISSUE-012/013/017/018/020 (response shape mismatches crashing pages), and ISSUE-022 (dashboard calling wrong endpoints).

## Rule 1: Read the Pydantic Schema Before Writing Frontend Code

Before writing any `apiClient.post()`, `apiClient.put()`, or `apiClient.get()` call, open the corresponding Pydantic request/response schema in the backend and match field names exactly.

Backend schemas live in:
- `app/modules/{module}/schemas.py` — dedicated schema files
- `app/modules/{module}/router.py` — inline `Body()` params or response_model declarations

Do not guess field names from conventions. The MFA bug was `mfa_session_token` vs `mfa_token` — both are reasonable names, but only one matches the schema.

## Rule 2: Validate Response Shape Before Accessing Nested Properties

Every API response must be validated before accessing nested properties. This codebase has had 10+ crashes from accessing `.items`, `.modules`, `.branches`, `.monthly_breakdown` etc. on undefined responses.

Pattern to follow:
```typescript
// WRONG — crashes if data is null or shape is different
const items = res.data.items

// RIGHT — defensive access
const items = res.data?.items ?? []
```

For paginated endpoints, the backend wraps arrays in objects like `{ items: [...], total: N }` or `{ modules: [...], total: N }`. Never assume the response is a bare array.

## Rule 3: Check the API Version Prefix

The `apiClient` base URL is `/api/v1`. Endpoints on `/api/v2/` need a baseURL override:
```typescript
// v1 endpoint (default) — just use the path
apiClient.get('/vehicles/search')

// v2 endpoint — override baseURL
apiClient.get('/admin/branding', { baseURL: '/api/v2' })
```

The v2 interceptor in `api/client.ts` handles `/v2/` and `/api/v2/` prefixed paths automatically, but be explicit when adding new v2 calls.

## Rule 4: Match Auth Flow Field Names Exactly

Auth endpoints are the highest-risk area for field name mismatches because they're called early and failures are silent (no data, no error UI).

Key contracts to verify:
- Login: `{ email, password, remember_me }` — not `remember`
- Token refresh: `{ refresh_token }` in body — not empty body
- MFA verify: `{ mfa_token, code }` — not `mfa_session_token`
- MFA challenge: check `app/modules/auth/router.py` for the current schema

After MFA verify or login, use the shared `handleAuthResponse` flow that decodes user info from JWT claims. Do not create separate response handlers.

## Rule 5: Check the Issue Tracker Before Touching Shared Files

Before modifying any of these high-traffic files, search `#[[file:docs/ISSUE_TRACKER.md]]` for previous issues:

- `frontend/src/api/client.ts` — touched by ISSUE-001, 006, 007
- `frontend/src/contexts/AuthContext.tsx` — touched by ISSUE-001
- `frontend/src/contexts/ModuleContext.tsx` — touched by ISSUE-002, 003, 012, 014
- `frontend/src/contexts/TenantContext.tsx` — touched by ISSUE-003, 014
- `frontend/src/App.tsx` — touched by ISSUE-004, 005, 008, 009, 011
- `app/modules/auth/router.py` — auth endpoints, MFA flows
- `app/core/database.py` — touched by ISSUE-007

## Rule 6: When Adding a New Endpoint, Verify Both Sides

When creating a new backend endpoint:
1. Define the Pydantic request schema with explicit field names and defaults
2. Define the response model or document the response shape
3. On the frontend, import or reference the exact field names from the schema
4. Add null/undefined guards on every response field access
5. Test with an actual API call, not just type assumptions

When consuming an existing endpoint from new frontend code:
1. Read the router function to see what it actually returns
2. Check if the response is wrapped (`{ items: [...] }`) or bare (`[...]`)
3. Check the HTTP method — some endpoints are POST even for "read" operations (e.g., report generation)

## Rule 8: Adding Fields to API Responses — Pydantic Schema Gate

**CRITICAL**: When adding a new field to an API response in a service function, you MUST also add it to the corresponding Pydantic response schema. Pydantic silently drops fields not defined in the schema.

This pattern caused a production bug where `terms_and_conditions_enabled`, `payment_terms_text`, and `org_invoice_footer_text` were added to the invoice detail dict in `service.py` but never added to `InvoiceResponse` in `schemas.py`. The API appeared to work (no errors), but the fields were silently stripped from the JSON response, causing the frontend to never receive them.

**Checklist when adding fields to a service response dict:**
1. Add the field to the service dict: `result["new_field"] = value`
2. Add the field to the Pydantic response schema: `new_field: str | None = None`
3. Verify the router passes the dict through the schema (check `response_model` or explicit schema instantiation like `InvoiceResponse(**result)`)
4. Restart the backend container (schema changes require process restart)
5. Verify the field appears in the actual API response (curl or browser devtools)

**Common locations for response schemas:**
- `app/modules/invoices/schemas.py` → `InvoiceResponse`
- `app/modules/customers/schemas.py` → `CustomerResponse`, `CustomerSearchResult`
- `app/modules/quotes/schemas.py` → `QuoteResponse`
- `app/modules/organisations/schemas.py` → `OrgSettingsResponse`

**Why this is silent**: Pydantic's default `model_config` does not raise errors for extra fields — it just ignores them. The service function runs fine, the dict has the data, but `InvoiceResponse(**result)` drops any keys not in the model. No error, no warning, no log entry.

## Rule 9: Frontend Build Deployment in Dev

The dev frontend container uses a watch-build pattern (not Vite HMR dev server):
- Source files are mounted at `/app/src/`
- A file watcher detects `.tsx`/`.ts`/`.css` changes
- Runs `npx vite build --outDir /tmp/dist-new --emptyOutDir`
- Copies output to `/app/dist/` (served by nginx)
- Browser must be refreshed to pick up new chunks (hashed filenames)

**Key implications:**
- Changes to source files trigger a rebuild automatically
- The browser serves static built files — no HMR websocket
- After a rebuild, a hard refresh (Ctrl+Shift+R) is needed to load new chunks
- If the build fails (TypeScript errors), the old chunks remain served
- Check `docker logs invoicing-frontend-1 --tail 20` to verify build success
- The entry point `index.html` references the main chunk by hash — new builds produce new hashes

## Rule 7: Rate Limiting Awareness for Dev

Development rate limits are 5x production (set in ISSUE-016). React Strict Mode doubles all requests. When implementing features that make multiple API calls on mount (like MFA settings loading multiple method statuses), be aware that:

- Each context provider fires requests on mount
- Strict Mode doubles them
- Rapid navigation can stack requests

Use AbortController cleanup in useEffect hooks (pattern established in ISSUE-014) and avoid firing unnecessary requests.

## Rule 10: PDF Templates — Jinja2 Fallback Defaults

When rendering configurable text in PDF templates (WeasyPrint), always use Jinja2's `or` operator to provide a sensible default. Never use `{% if %}` conditionals that result in empty space when the setting is not configured.

```jinja2
{# WRONG — shows nothing when setting is empty/null #}
{% if org.invoice_footer %}<p>{{ org.invoice_footer }}</p>{% endif %}

{# RIGHT — shows default when setting is empty/null #}
<p>{{ org.invoice_footer or 'Thank you for your business.' }}</p>
```

This applies to all user-configurable text fields rendered in PDFs: footer text, payment terms, notes, etc. The frontend split-panel preview should use the same fallback pattern (`value || 'default'`) to ensure PDF and preview always match.

**Key locations for PDF templates:**
- `app/templates/pdf/invoice.html` — default standalone template (used when no template_id is set)
- `app/templates/pdf/_invoice_base.html` — base template extended by themed templates
- `app/templates/pdf/invoice_share.html` — public share/portal view
- `app/templates/pdf/*.html` — 12 themed child templates

**Important:** The default template used for PDF generation is `invoice.html` (standalone), NOT `_invoice_base.html`. When fixing template issues, always check `invoice.html` first — it's what most orgs use.

## Rule 11: Whitespace Preservation for Multi-Line Text Fields

Any text field that accepts multi-line input (textarea) must preserve formatting when displayed:

- **Frontend (Tailwind):** Add `whitespace-pre-wrap` class to the rendering element
- **PDF templates (WeasyPrint):** Add `white-space: pre-wrap;` to the inline style

Fields that need this treatment: `payment_terms_text`, `notes_customer`, `terms_and_conditions` (if plain text), item `description`. The pattern is already established for `notes_customer` — apply it consistently to all multi-line fields.

## Rule 12: Navigation with location.state — Ensure Complete Data

When navigating from a create/edit page to a list/detail page using `navigate('/path', { state: { invoice: data } })`, the passed data MUST include all fields needed for the preview to render correctly.

The create endpoint (`POST /invoices`) returns `_invoice_to_dict()` which only has basic invoice columns — it does NOT include `org_name`, `customer` object, `payments`, etc. The detail endpoint (`GET /invoices/{id}`) returns the full enriched response.

**Pattern to follow:**
```typescript
// After creating/updating, fetch full detail before navigating
const createRes = await apiClient.post('/invoices', payload)
const newId = (createRes.data as any)?.invoice?.id
// Fetch full detail for instant preview
const detailRes = await apiClient.get(`/invoices/${newId}`)
const fullInv = (detailRes.data as any)?.invoice || detailRes.data
navigate(`/invoices/${newId}`, { state: { invoice: fullInv } })
```

This ensures the split-panel renders instantly with all data (org name, customer, payments) instead of showing an empty template while the background refresh loads.
