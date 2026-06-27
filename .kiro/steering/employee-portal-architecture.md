---
inclusion: fileMatch
fileMatchPattern: "app/modules/employee_portal/**,frontend-v2/src/**/employee-portal/**,frontend-v2/src/**/EmployeePortal*"
---

# Organisation Employee Portal Architecture

This file is loaded when editing employee-portal code. The portal is a **separate authentication surface** for an organisation's employees (distinct from the main staff/admin app). Treat its isolation from the main `users` auth as a hard requirement.

## Separate Identity Store

- Portal accounts live in their **own table `employee_portal_users`** (`app/modules/employee_portal/models.py`) — NOT the main `users` table. This keeps seat/security/billing isolation between platform users and employee-portal users.
- A staff member may have BOTH a main `users` login and an employee-portal account; they are independent. Enabling portal access for a staff member provisions an `employee_portal_users` row, it does not grant main-app access.

## URL & API Surface

- Portal pages are served under **`/e/{slug}/...`** where `{slug}` identifies the organisation.
- Portal API surface is **`/e/api/*`** (e.g. `POST /e/api/auth/login`, `POST /e/api/auth/logout`, `GET /e/api/auth/me`, accept-invite + password-reset under `/e/api/auth/...`, `GET /e/api/branding/{slug}`, `GET /e/api/profile`, `GET /e/api/roster`).
- Login resolves the org by slug, applies an enablement gate and lockout, and returns a generic 401 on failure (anti-enumeration).

## Cookie & CSRF Scoping (critical)

- Auth is via the **HttpOnly `emp_portal_session` cookie**, set with **`path=/e`**. The `/e` cookie path deliberately keeps portal cookies off the main app paths so a user logged into both surfaces doesn't cross sessions.
- State-changing endpoints additionally require a **double-submit CSRF cookie/header pair**.
- Post-login redirect lands on `/e/{slug}/home` (not the bare `/e/{slug}/`).

## Accept-Invite & Recovery

- Invite emails link to `/e/{slug}/accept-invite/{token}` — this page must render a set-password flow, NOT bounce to a login page.
- `resend_access` refreshes the token in place (does not orphan the prior token).
- Password reset request always returns a byte-for-byte identical response (anti-enumeration); reset token is single-use.

## Middleware Integration (per `implementation-completeness-checklist.md` Rule 6)

When adding or changing portal auth surfaces, verify the full middleware chain:
- `/e/api/...` public auth paths must be in `PUBLIC_PREFIXES` so the main JWT middleware does not block them.
- Portal auth endpoints must be CSRF-exempt where appropriate (login) and CSRF-protected elsewhere (state-changing).
- For cross-org lookups before authentication (login by slug, accept-invite by token), reset the RLS GUC before the query and set the correct org_id from the resolved row afterwards (per `implementation-completeness-checklist.md` Rule 7).

## Rules

- Never merge employee-portal auth into the main `users` table or the main session cookie.
- Keep portal cookies scoped to `path=/e`; never widen to `/`.
- Test any portal auth change against a user who is ALSO logged into the main staff app — the two sessions must not interfere.
- Follow `safe-api-consumption.md` for portal React code.
