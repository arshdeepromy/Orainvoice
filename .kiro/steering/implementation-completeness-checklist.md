---
inclusion: auto
---

# Implementation Completeness Checklist

**Lesson learned (2026-05-23, B2B Fleet Portal):** A spec with 180 acceptance criteria was implemented with all tasks marked "done", but end-to-end testing revealed 15+ integration failures: middleware blocking requests, RLS filtering out data, email not sending, wrong URLs in emails, placeholder pages shipped as "complete", and env-var dependencies violating the credentials architecture. This steering doc exists to prevent that class of failure from recurring.

---

## Rule 1: Never Mark a Task Done Without a Browser Test

Before marking ANY frontend task as complete:

1. **Open the page in the browser** at the actual URL the user will visit
2. **Perform the primary action** (submit a form, click a button, navigate)
3. **Verify the backend response** in the browser Network tab (not just "app boots")
4. **Check for console errors** — any red text in the console means it's not done

If you cannot test in the browser (e.g. the container isn't running), say so explicitly and mark the task as "code written, not browser-tested".

---

## Rule 2: Trace the Full Request Path Before Writing Code

Before implementing any new endpoint or page, trace the request through EVERY layer:

```
Browser → Nginx → Middleware Stack → FastAPI Router → Dependency → Service → DB
```

Check each layer for potential blockers:

| Layer | What to check |
|-------|---------------|
| **Nginx** | Does a `location` block exist for this path? Will it proxy to backend or serve SPA HTML? |
| **CSRF Middleware** | Is this path exempt? Does the user have a session cookie that triggers the check? |
| **Auth Middleware** | Is this path in `PUBLIC_PATHS` or `PUBLIC_PREFIXES`? Will it reject without a JWT? |
| **Rate Limit** | Does the rate limiter know about this user type? |
| **RLS (Postgres)** | Is `app.current_org_id` set before the query runs? Which dependency sets it? |
| **Module Middleware** | Does it check module enablement on this path? |

**If any layer is unclear, test with curl BEFORE writing frontend code.**

---

## Rule 3: No Env Var Dependencies for Runtime Configuration

Per `integration-credentials-architecture.md`:

- **Credentials** → stored encrypted in DB, configured via GUI
- **Email providers** → `email_providers` table, configured via Admin > Email Providers
- **Feature toggles** → `feature_flags` table, configured via Admin > Feature Flags
- **Module enablement** → `org_modules` table, configured via Settings > Modules
- **Org resolution** → query the DB (org_modules, feature_flags, organisations)

The ONLY things that belong in `.env`:
- Database URL, Redis URL, port numbers
- `SECRET_KEY` / `ENCRYPTION_MASTER_KEY` (infrastructure secrets)
- `ENVIRONMENT` (development/staging/production)

**Never** add a new env var for:
- API keys (use `integration_configs` table)
- Feature flags (use `feature_flags` table)
- Org-specific config (use `organisations.settings` JSONB)
- Default org slugs (query the DB for the active org)

---

## Rule 4: Frontend Pages Must Have Real Forms, Not Placeholders

A frontend page is NOT complete until it has:

1. **A form or action button** that calls the backend API
2. **Loading state** (spinner or skeleton)
3. **Error state** (red banner with the error message from the API)
4. **Empty state** (meaningful message when no data exists)
5. **Success feedback** (toast, redirect, or inline confirmation)

A page that shows "Coming soon" or "This feature will be available in the next update" is NOT done. It is a placeholder and must be tracked as incomplete.

---

## Rule 5: Test Email/SMS Delivery End-to-End

When a feature sends emails or SMS:

1. **Verify the email provider is configured** — query `email_providers` for an active row
2. **Check the `send_email_task` result** — it returns `{ success: bool, error: str }`
3. **Verify the URL in the email** uses the request origin (not `settings.frontend_base_url`)
4. **Test with a real email address** and confirm delivery

Common failures:
- `"Email infrastructure not configured"` → no active row in `email_providers`
- `"Unknown provider: custom_smtp"` → provider key not in the send method's switch
- `localhost` in the URL → using `settings.frontend_base_url` instead of request origin
- Email queued but never sent → `send_email_task` failed silently in try/except

---

## Rule 6: New Auth Surfaces Must Be Tested Against the Middleware Stack

When adding a new authentication surface (like the fleet portal cookie auth):

1. **Add the path prefix to `PUBLIC_PREFIXES`** in `app/middleware/auth.py` so the JWT middleware doesn't block it
2. **Add auth endpoints to CSRF exemptions** in `app/middleware/security_headers.py`
3. **Add a nginx location block** if the path doesn't match an existing one
4. **Test with a user who is ALSO logged into the staff app** — their staff session cookie must not interfere

---

## Rule 7: RLS Bypass for Cross-Org Lookups

When a query needs to find data across orgs (e.g. login by email, accept-invite by token):

1. **Reset the RLS GUC** before the query: `await db.execute(text("RESET app.current_org_id"))`
2. **Set the correct org_id AFTER** finding the row (from the row's own `org_id` column)
3. **Never filter by a "resolved org"** when the user hasn't authenticated yet — the resolver may pick the wrong org in multi-org deployments

---

## Rule 8: Feature Flag ↔ Module Enablement Must Be Bridged

The project has two parallel systems:
- `feature_flags` table (Global Admin toggles)
- `org_modules` table (per-org module enablement)

When adding a new module:
1. Insert into BOTH `module_registry` AND `feature_flags`
2. The module-enabled check must query BOTH tables (either being true = enabled)
3. Document which system is the "source of truth" for the feature

---

## Rule 9: Spec Tasks Must Include Integration Verification Steps

Every spec task that touches a user-facing flow must include:

```
**Verify**: Navigate to [URL] in the browser. Perform [action]. 
Expected: [specific outcome]. Check backend logs for [specific log line].
```

Tasks without verification steps will be treated as incomplete even if the code compiles.

---

## Rule 10: Gap Analysis Before Marking a Spec Complete

Before marking a spec as "all tasks done":

1. **Read every acceptance criterion** in requirements.md
2. **For each criterion**, verify it works by either:
   - Testing in the browser, OR
   - Running a curl command against the live API, OR
   - Pointing to the specific test that covers it
3. **Document any gaps** in a `gap-analysis.md` file in the spec folder
4. **Do NOT mark the spec complete** until the gap analysis shows zero critical gaps

---

## Anti-Patterns to Avoid

| Anti-Pattern | What Happens | Correct Approach |
|---|---|---|
| "Backend done, frontend placeholder" | Users see "coming soon" | Build the real form in the same task |
| "Tests pass, ship it" | Middleware blocks the request in production | Test through nginx + browser |
| "Added env var for config" | Config doesn't load in container | Use DB table + GUI |
| "Marked task done" without testing | 15 integration failures discovered later | Browser-test every task |
| "RLS will handle isolation" | Queries return empty because org_id not set | Trace the GUC-setting path |
| "Same pattern as staff app" | Staff uses JWT, new surface uses cookies — middleware conflicts | Check every middleware layer |
| "Email sent successfully" | URL in email points to localhost | Use request origin for URLs |
