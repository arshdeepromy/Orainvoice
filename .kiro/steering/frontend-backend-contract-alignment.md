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

## Rule 7: Rate Limiting Awareness for Dev

Development rate limits are 5x production (set in ISSUE-016). React Strict Mode doubles all requests. When implementing features that make multiple API calls on mount (like MFA settings loading multiple method statuses), be aware that:

- Each context provider fires requests on mount
- Strict Mode doubles them
- Rapid navigation can stack requests

Use AbortController cleanup in useEffect hooks (pattern established in ISSUE-014) and avoid firing unnecessary requests.
