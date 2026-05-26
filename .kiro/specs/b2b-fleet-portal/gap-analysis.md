# B2B Fleet Portal — Spec Gap Analysis

**Date:** 2026-05-22
**Reviewer:** Audit against `.kiro/steering/*.md` and existing codebase state.
**Status:** Findings before task execution.

This document captures gaps found in `requirements.md` and `design.md` after loading every steering doc and cross-checking against the live codebase. Gaps are grouped by severity. Each gap names the affected file(s) and the fix required before the spec can be safely executed.

---

## Severity legend

- **BLOCKER** — will cause runtime errors, data loss, or compliance failures if executed as written.
- **HIGH** — will cause significant frontend-backend mismatch or missing user-facing UI.
- **MEDIUM** — non-critical but will leave the implementation off the project's standards.
- **LOW** — nice-to-have polish.

---

## BLOCKER 1 — Wrong Alembic migration number

**Where:** `tasks.md` task 1.1 says "create migration `0183_b2b_fleet_portal.py`".
**Why it's a blocker:** The actual current head is **0190** (`2026_05_17_0900-0190_create_pending_qr_sessions.py`). Project overview steering doc says 0182 but it is out of date — verified by listing `alembic/versions/`. Creating a migration with revision `0183` while the head is `0190` will either fail Alembic's linear history check or, if forced, will break the chain on every other environment.

**Fix:** Migration must be `0191_b2b_fleet_portal.py` with `down_revision = '0190'`.

---

## BLOCKER 2 — `portal_accounts` table does not exist yet

**Where:** `design.md` "Data Models" → `portal_accounts` (extended); `tasks.md` task 1.1 says "Extend `portal_accounts` with new columns".
**Why it's a blocker:** The portal_accounts table is documented in `docs/future/portal-password-login.md` as a future proposal — it has never been migrated, no model exists, and `grepSearch portal_accounts` against `alembic/versions/` returns zero matches. The current portal infrastructure uses `PortalSession` keyed by a token-link, with no portal account at all.

**Fix:** The migration must **create** `portal_accounts` from scratch (not extend), with all the foundation columns from `docs/future/portal-password-login.md` plus the fleet-specific extensions. The design and tasks must be updated to reflect creation, not extension.

---

## BLOCKER 3 — `trade_family_required` column on `module_registry` does not exist

**Where:** `design.md` "Module Gating Architecture", `tasks.md` task 1.1.
**Why it's a blocker:** The setup-guide spec explicitly chose **not** to add a `trade_family_gated` column to `module_registry` and instead to use a hardcoded set inside the router (matching the `CORE_MODULES` pattern in `app/core/modules.py`). The b2b-fleet-portal spec adds a different column with similar semantics, contradicting the established pattern.

**Fix:** Either:
- (a) Reuse the setup-guide pattern: add `b2b-fleet-management` to a `TRADE_FAMILY_REQUIRED_MODULES: dict[str, str]` constant in `app/core/modules.py` mapping slug → required trade family, and gate visibility/enablement against the org's `tradeFamily`. **No DB column.**
- (b) If a DB column is justified (e.g. multiple modules will need this), add it once with proper migration and update the setup-guide spec at the same time.

The spec should pick (a) for consistency. Update design.md and tasks.md accordingly.

---

## BLOCKER 4 — `db.commit()` / `db.rollback()` mentions in spec contradict project rule

**Where:** `design.md` "Transactional Boundaries" section is correct; but `tasks.md` task 5.1 mentions `await db.flush()` then `await db.refresh()` which is correct. However, **no task explicitly forbids `db.commit()` in service functions**. ISSUE-044 documents that staff routers crashed because they called `db.commit()` inside `session.begin()` context manager.

**Why it's a blocker:** Without an explicit reminder, the implementation agent will likely add `await db.commit()` to fleet portal services (matching the bad pattern from ISSUE-024 and ISSUE-040 quotes router) and crash with "Can't operate on closed transaction" (ISSUE-044, ISSUE-102).

**Fix:** Add an explicit "Transaction discipline" line to every service-implementing task: services must use `db.flush()` and `db.refresh()` only, never `db.commit()` or `db.rollback()`. Routers must NOT call commit/rollback either — the `get_db_session` dependency (`session.begin()`) handles it.

---

## BLOCKER 5 — Fleet portal users have NO security parity with org users

**Where:** `requirements.md` Requirement 3 (auth), Requirement 4 (provisioning).
**Why it's a blocker (compliance):** Org users get the full `OrgSecuritySettings` (MfaPolicy, PasswordPolicy, LockoutPolicy, SessionPolicy) via `app/modules/auth/security_settings_schemas.py`. Fleet portal users (Fleet_Account_Admin and Driver_User) get a hard-coded minimum 8 chars and 5-strikes lockout. For ISO/SOC2/PCI-DSS readiness the user explicitly called out, this is insufficient:

| Org user has | Fleet portal user has |
|---|---|
| MFA: TOTP, SMS, Backup codes, Passkeys | None |
| Configurable min length (8–128) | Hardcoded 8 |
| Configurable complexity rules (upper/lower/digit/special) | None |
| Configurable expiry days | None |
| Configurable history count (no reuse of last N) | None |
| Configurable lockout (temp + permanent thresholds) | Hardcoded 5/30min, no permanent |
| Session policy (max sessions, idle timeout, refresh expiry) | Hardcoded 4-hour idle |
| HIBP-style breached-password check | None |
| Password change audit log entries | None |

**Fix:** Add a new requirement section "Requirement 21: Security Settings Parity for Portal Users" that:

1. Reuses the org-level `MfaPolicy`, `PasswordPolicy`, `LockoutPolicy`, `SessionPolicy` schemas applied to portal users.
2. Provides MFA enrolment (TOTP at minimum; SMS optional based on Connexus availability) for `fleet_admin` and optionally for `driver` based on policy.
3. Adds a per-org `portal_security_policy` JSONB key (or reuses `org_security_settings` with a `portal_overrides` block) so Workshop_Admins can configure portal user policies independently.
4. Adds password complexity, expiry, history, and HIBP check.
5. Adds permanent lockout in addition to temporary.
6. Adds an audit log entry for every portal auth event (`portal_auth.login_success`, `portal_auth.login_failed_*`, `portal_auth.password_changed`, `portal_auth.mfa_verified`, `portal_auth.session_revoked`, etc.).
7. Adds a portal "My Security" page where the Fleet_Account_Admin / Driver_User can manage their MFA, view active sessions, and change their password.

Update design.md to include the security architecture (mirror of org-user MFA flow but rooted at `portal_accounts`), and add tasks for it.

---

## HIGH 1 — Workshop_Admin "Fleet Portal" sidebar item not actually wired

**Where:** `tasks.md` task 17.1 says "Add a sidebar link 'Fleet Portal' in `OrgLayout`" but does not call out the existing `OrgLayout.tsx` `navItems` array nor mention the `<ModuleGate>` wrapping pattern documented in the setup-guide steering doc.

**Fix:** Update task 17.1 to:
- Read `frontend/src/layouts/OrgLayout.tsx` first (per `no-shortcut-implementations.md`).
- Add the new sidebar item to the `navItems` array with the existing module-gating pattern (`requiredModule: 'b2b-fleet-management'`).
- Add a sub-route registration in `frontend/src/App.tsx` for `/fleet-portal-admin/*` with `RequireOrgAdmin` guard.

---

## HIGH 2 — No frontend `MFA setup` flow specified for portal users

**Where:** `requirements.md` Requirement 3, `design.md` "Authentication & Session Architecture".
**Why it's a high gap:** The user said "all the users need to have all the security feature control like we have in org users like MFA password length and all the requirements for any framework for compliance purposes". The current spec has no MFA enrolment screen, no QR-code TOTP flow, no backup-codes display, no SMS verification ladder.

**Fix:** Add to Requirement 3 (or new Requirement 21) acceptance criteria:
- Fleet_Account_Admin and Driver_User MFA enrolment matches the org-user TOTP flow (`UserMfaMethod` foundation, but new `PortalAccountMfaMethod` table or shared `mfa_methods` table with `subject_type IN ('user','portal_account')`).
- Portal SPA pages: `/fleet/security`, `/fleet/security/mfa/enroll/{method}`, `/fleet/security/mfa/backup-codes`.
- Admin-side enforcement: `Workshop_Admin` can set portal MFA policy to `optional`, `mandatory_all_admins`, `mandatory_all` per fleet account or globally.

---

## HIGH 3 — No "Workshop_Admin Portal Settings" page specified

**Where:** Requirement 16 covers Workshop_Admin console for queues, but doesn't include a "Portal Settings" page where the Workshop_Admin can configure the portal-user security policy.

**Fix:** Add to Requirement 16 a sub-requirement for a `/fleet-portal-admin/settings` page with:
- Password policy editor (min length, complexity flags, expiry days, history count).
- MFA policy editor (mode: optional / mandatory all / mandatory admins only).
- Lockout policy editor.
- Session policy editor (idle timeout, max sessions per portal user).
- "Force re-login all portal users" button.

---

## HIGH 4 — No GUI for managing/reviewing portal accounts (audit & compliance)

**Where:** Requirement 4.7 says display Portal_User status as text only.

**Fix:** Extend Requirement 4 to require a `/fleet-portal-admin/accounts/{portal_account_id}` detail page showing:
- Current status, last login, last password change, last MFA verification.
- Active sessions list with revoke button per session.
- Audit log of portal events for this portal account (last 90 days).
- Password reset (admin-initiated, per `kiosk-password-reset` spec pattern).
- Force MFA re-enrolment.

---

## HIGH 5 — No CSP / security headers requirement for the new portal SPA

**Where:** Requirement 2 describes URL routing only; design.md "Architecture" doesn't mention security headers.

**Fix:** Add to Requirement 2 acceptance criteria:
- Fleet portal pages MUST be served with `Cache-Control: no-store, Pragma: no-cache` (matches `PortalCacheRoute` pattern in `app/modules/portal/router.py`).
- Strict CSP headers (no `unsafe-inline` for scripts).
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.
- HSTS at the nginx layer for the fleet host.

---

## HIGH 6 — Frontend bundle / browser-cache invalidation strategy missing

**Where:** Per the `frontend-backend-contract-alignment.md` Rule 9 and the recent dev/prod rebuild work (mentioned in conversation summary), frontends served from nginx require version-bumping and a clear refresh story for users.

**Fix:** Add Requirement 19.7 (or new Requirement 22) covering:
- Fleet portal HTML serves a `<meta name="x-app-version" ...>` tag.
- A version-check endpoint `GET /fleet/api/version` returns the current backend's git-sha.
- The frontend polls this endpoint on every navigation and shows a "New version available — reload to update" toast when it differs from the loaded value.
- Reuses the existing org-app version-bump infrastructure (per `versioning-and-changelog.md`).

---

## HIGH 7 — Pydantic schema parity missing from tasks

**Where:** `tasks.md` task 2.3 lists the Pydantic schemas to create but does not name the `frontend-backend-contract-alignment.md` Rule 8 ("when adding a new field, you MUST also add it to the Pydantic schema or it'll be silently dropped").

**Fix:** Add to task 2.3 an explicit reminder: every field added to a service dict must also be added to the Pydantic response schema, and `response_model=` must be set on every endpoint so FastAPI validates against the schema. Add to every service-implementing task (5.1, 6.1, 7.1, 8.1, 9.1, 10.1, 12.1, 12.2, 13.1, 13.2): "If new fields are added to the response, also add them to the matching Pydantic schema; verify by curl that the field appears in the actual JSON response."

---

## HIGH 8 — Fleet portal admin "View as Portal User" missing

**Where:** Requirement 16 covers the Workshop_Admin console but does not include impersonation parity with the existing global-admin "View as Org" flow (ISSUE-011).

**Fix:** Add to Requirement 16: a "View as Portal User" button on the FleetAccountList page that simulates a fleet portal session for that account (audit-logged, time-bounded, banner-marked), letting the Workshop_Admin see what the customer sees without requiring the customer's password.

---

## MEDIUM 1 — Frontend route guards not enumerated

**Where:** `tasks.md` task 14.1 mentions a top-level switch in `App.tsx` based on host/path but does not enumerate the route guards (`RequireFleetSession`, `RequireFleetAdmin`, `RequireDriverOrAdmin`) symmetric with `RequireOrgAdmin` / `RequireGlobalAdmin`.

**Fix:** Update task 14.1 to enumerate the React route guards and follow the existing pattern from `App.tsx` (no shortcuts).

---

## MEDIUM 2 — Frontend safe-API consumption rule not echoed in tasks

**Where:** Multiple frontend tasks (15.x, 16.x) describe pages but don't restate the `safe-api-consumption.md` mandatory patterns.

**Fix:** Add to every frontend page task a checklist item: "API consumption uses `?.` and `?? []` / `?? 0` on every property; useEffect uses AbortController; no `as any`."

---

## MEDIUM 3 — Performance & resilience patterns not echoed

**Where:** No mention of `pool_pre_ping`, async timeouts on Connexus / CarJam calls, or `httpx.AsyncClient` cleanup in the integration tasks.

**Fix:** Add to task 6.1 (vehicle service: CarJam), task 10.1 (reminder service: SMS), and task 18 (notifications) a note: external HTTP calls use `httpx.AsyncClient` as context managers, with explicit timeouts, retry-with-backoff, and no synchronous I/O in the request handler (offload to background tasks if heavy).

---

## MEDIUM 4 — RLS context teardown for portal users

**Where:** `design.md` "RLS and Tenant Isolation Architecture" mentions `_set_rls_org_id` and `_set_rls_fleet_account_id` but doesn't address the `SET LOCAL` parameterisation gotcha (ISSUE-007).

**Fix:** Add to design.md a note: portal session dependency must use `SET LOCAL ... = '<validated_uuid>'` (interpolated, after UUID validation), NOT bound parameters. Add the same UUID validation regex used in `app/core/database.py`. Add to task 1.2 / 3.5: "When setting the per-request fleet_account_id RLS variable, follow the ISSUE-007 pattern from `_set_rls_org_id` — never use bound params for SET LOCAL".

---

## MEDIUM 5 — No setup-guide question for the new module

**Where:** `setup-guide-for-new-modules.md` requires every new non-core, non-trade-gated module to ship with a `setup_question` and `setup_question_description`.

**Fix:** Add to task 1.1: insert the module into `module_registry` with explicit `setup_question` and `setup_question_description` text matching the steering doc template (e.g. `"Do your business customers need a self-service portal to manage their vehicle fleet?"` — already in design.md but task only says "with `dependencies = ['vehicles']`"). Also add to task 1.3 a smoke test: setup-guide returns the new question for orgs in the right trade family with the module not yet enabled.

---

## MEDIUM 6 — No dashboard widget for fleet portal owners

**Where:** `dashboard-widget-gating.md` describes how to add new dashboard widgets for the org admin dashboard. The fleet portal feature should expose a "Fleet Portal Activity" widget on the Workshop_Admin's existing org dashboard (pending bookings + pending quotes + recent failures count).

**Fix:** Add a new task 17.3 to add a `FleetPortalActivityWidget` to `frontend/src/pages/dashboard/widgets/` per the steering doc's 10-step process, gated on `b2b-fleet-management`.

---

## MEDIUM 7 — No issue tracker entry plan / spec versioning

**Where:** `issue-tracking-workflow.md` (loaded by reference) requires every spec implementation that changes prod to log fixes in `docs/ISSUE_TRACKER.md`. `versioning-and-changelog.md` requires a version bump in `frontend/package.json` and `app/__init__.py` for any deploy.

**Fix:** Add task 21.x: bump app version (frontend `package.json`, backend `app/__init__.py`, `CHANGELOG.md`) when the feature is shipped.

---

## MEDIUM 8 — Test coverage for security parity missing

**Where:** Properties 6 and 7 in design.md cover the basic lockout state machine and bcrypt rules but not the full `OrgSecuritySettings` parity introduced by BLOCKER 5.

**Fix:** Add new properties to design.md "Correctness Properties":
- Property 35: Configurable password policy enforced on portal user password creation/change.
- Property 36: Configurable lockout policy enforced (temporary + permanent thresholds).
- Property 37: Configurable session policy enforced (max sessions, idle timeout, refresh expiry).
- Property 38: MFA mode enforced for portal users (optional / mandatory_admins / mandatory_all).
- Property 39: HIBP breached-password check on password creation/change (cached, k-anonymity API).

Add corresponding test files under `tests/fleet_portal/`.

---

## LOW 1 — No light/dark mode mock-ups

Spec calls out Tailwind `dark:` variants but no mockups. **Fix:** Use `design-reference-from-screenshots.md` workflow during implementation.

---

## LOW 2 — No mention of Capacitor / mobile app integration

The mobile-app steering doc says mobile is for org users only. Fleet portal users won't have the mobile app — but the spec should explicitly note that the fleet portal is web-only (via responsive PWA) for now.

**Fix:** Add to Requirement 20 (Out of Scope): "The Fleet Portal is web-only. Native mobile apps (iOS/Android) for portal users are out of scope; the kiosk and mobile-phone use cases are served by responsive web design."

---

## LOW 3 — No production data backup / migration story

The deployment-environments steering doc says all DB schema changes need a backup and verification step in prod. The spec should call this out.

**Fix:** Add to the spec a "Deployment Notes" section: before applying migration `0191`, run a full pg_dump of the prod DB; after applying, verify all 132 tables become 142 tables; verify the `b2b-fleet-management` row in `module_registry`; verify zero existing customer/vehicle records are altered.

---

## Summary of required updates to the spec

1. **Renumber migration** to `0191` (fix in `tasks.md` task 1.1, `design.md` Data Models).
2. **Create** `portal_accounts` (don't extend) — fix in design.md and task 1.1.
3. **Drop the `trade_family_required` column** approach; use the in-code constant pattern from setup-guide spec — fix in design.md and tasks 1.1, 1.3.
4. **Add explicit transaction discipline** rule to every service task.
5. **Add Requirement 21: Security Settings Parity for Portal Users** with full MFA / password policy / lockout / session / audit story — major addition to requirements.md, design.md, tasks.md.
6. **Add Requirement 22: Frontend Version-Check & Cache Busting** for deployable updates.
7. **Add 5 new properties (35–39)** for security parity, with test files.
8. **Strengthen the Workshop_Admin console** with: Portal Settings page, Account Detail page, View-as-Portal-User, dashboard widget.
9. **Echo the steering rules** (`safe-api-consumption`, `frontend-backend-contract-alignment`, `performance-and-resilience`, `database-migration-checklist`, `setup-guide-for-new-modules`, `dashboard-widget-gating`) inside relevant tasks.
10. **Add deployment / versioning / issue-tracker entries** to the closing tasks.

The agent will not start task execution until these gaps are resolved in the spec files.


---

# ROUND 2 — Code-vs-spec verification audit (2026-05-22)

After the Round 1 fixes, we cross-checked every assumption in the spec against actual code in `app/`, `frontend/src/`, and `mobile/src/`. Found further mismatches that would cause runtime errors if executed as written. Each finding below is fixed in the relevant spec file.

## R2-BLOCKER 1 — `_set_rls_org_id` already migrated to `set_config()`; spec's "ISSUE-007 string-interpolation" guidance is obsolete

**What the spec said (Round 1):** Tasks 1.2 and the "Project conventions" block instructed: `text(f"SET LOCAL app.current_fleet_account_id = '{validated}'")` with string interpolation, "never use bound parameters for SET LOCAL".

**What the code actually does:** `app/core/database.py:75-99` already uses the much safer `SELECT set_config('app.current_org_id', :org_id, true)` form — bound parameters DO work with `set_config()`, unlike `SET LOCAL`. The ISSUE-007 fix was to switch from `SET LOCAL ... = $1` (broken) to `set_config(:name, :value, true)` (works), not to switch to string interpolation.

**Why it matters:** Following the spec as written would re-introduce a DIFFERENT class of risk (string interpolation) and break the consistency with the existing `_set_rls_org_id` implementation.

**Fix:** Update the spec to direct the implementer to the existing `set_config()` pattern from `app/core/database.py:75-99`.

## R2-BLOCKER 2 — `next_service_due_at` does not exist; the actual column is `service_due_date` on `org_vehicles` (and on `global_vehicles`)

**What the spec said:** Requirements 7.2, 10.6, 15.2, design Properties 17 and 27, multiple tasks all use `next_service_due_at` as a column on `customer_vehicles`.

**What the code actually has:** `app/modules/vehicles/models.py:63` defines `service_due_date: Mapped[date | None]` on `OrgVehicle`. The same column exists on `GlobalVehicle` (matching pattern, line 57-63 area of OrgVehicle confirms parity). `customer_vehicles` does NOT have any service-due column at all — it's a link table with `id`, `org_id`, `customer_id`, `global_vehicle_id` / `org_vehicle_id`, `odometer_at_link`, `linked_at`.

**Why it matters:** Adding a `next_service_due_at` column would either (a) duplicate `service_due_date` (data drift) or (b) crash because the migration would have to add it on `customer_vehicles` while existing reminder code reads `service_due_date` from `org_vehicles`/`global_vehicles`.

**Fix:** Replace every `next_service_due_at` reference in requirements.md, design.md, and tasks.md with `service_due_date` on `global_vehicles` / `org_vehicles` (whichever the customer_vehicle row links to). The reminder service already reads this column. The fleet driver hours / odometer flow updates the existing column, not a new one.

## R2-BLOCKER 3 — `customer_vehicles.fleet_checklist_template_id` does NOT exist and won't be added by the existing schema

**What the spec said:** Task 8.1 and design Property 20 set `customer_vehicles.fleet_checklist_template_id` to choose a template per vehicle.

**What the code has:** The `customer_vehicles` schema (`app/modules/vehicles/models.py:98-138`) has no template-id column. Task 8.1 already includes a "verify first" guard, but it should be elevated to the migration spec (task 1.1) so the column is added in the same migration, not as an afterthought in the service layer.

**Fix:** Add an explicit line in task 1.1 to add `fleet_checklist_template_id UUID NULL REFERENCES fleet_checklist_templates(id) ON DELETE SET NULL` to `customer_vehicles` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Remove the conditional language from task 8.1.

## R2-BLOCKER 4 — Existing reminder system uses pre-rendered queue body; the spec underestimates the integration

**What the spec said:** Task 10.2 "Extend `notifications.reminder_queue_service` to read `fleet_reminder_preferences`. Add a fleet-preference scan path next to the existing org-rule scan."

**What the code actually does (per `notification-template-integration` spec and `docs/SCHEDULED_TASKS.md`):**
- The reminder system is a **two-phase queue**: Phase 1 (`enqueue_customer_reminders`) renders the email/SMS body at queue time using the org's notification templates and writes it to the `body` field. Phase 2 (`process_reminder_queue_scheduled`, every 60 s) sends the pre-rendered body.
- Reminder types are: `wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, `service_due_reminder` — defined in `app/modules/notifications/schemas.py:27-32`.
- The settings live at `notifications/wof-rego-settings` (org-wide) — there's no per-vehicle override yet.
- Templates resolve via `resolve_template(db, org_id=..., template_type=..., channel=..., variables=...)` from the recently-shipped `notification-template-integration` spec.

**Why it matters:** A naive "add a fleet-preference scan path" will (a) duplicate templates, (b) write a different body shape than the queue-body rendering pipeline expects, (c) bypass the org-level template overrides, and (d) confuse audit logs. The fleet-preference layer must be a **per-customer override** on top of the existing org-level rules, with the same template resolution logic.

**Fix:** Rewrite task 10.2 to:
- Extend `enqueue_customer_reminders()` to read `fleet_reminder_preferences` rows alongside the existing `wof_rego_settings`. For each enabled preference, enqueue using the same template resolution path.
- Use the existing template variables (`vehicle_rego`, `expiry_date`, `service_due_date`, etc.) — don't invent new ones.
- Use the existing reminder types (`wof_expiry_reminder`, `cof_expiry_reminder`, `service_due_reminder`) — don't add new types.
- Idempotency key changes from `(customer_vehicle_id, reminder_type, expiry_date)` to whatever the existing queue uses (likely `(global_vehicle_id, reminder_type, expiry_date)`); read `app/modules/notifications/reminder_queue_service.py` first to confirm.

## R2-HIGH 1 — Reuse the existing `portal_csrf` cookie pattern, not a new one

**What the spec said:** Tasks 3.5, 4A.1 mention "CSRF double-submit cookie" without naming the cookie.

**What the code has:** `app/modules/portal/router.py:294`, `frontend/src/api/client.ts:40-71`, `tests/test_portal_csrf.py`, and `app/modules/portal/service.py:268-280` all use a cookie named `portal_csrf` (non-HttpOnly, sent as `X-CSRF-Token` header). The fleet portal frontend's `api/client.ts` should reuse the same name (or a parallel `fleet_portal_csrf`) and the same `validate_portal_csrf(request)` helper from `app/modules/portal/service.py:378`.

**Fix:** Update the spec to:
- Name the cookie `fleet_portal_csrf` (parallel to `portal_csrf`, scoped to the fleet host so cookies don't cross origins).
- Reuse `validate_portal_csrf` logic via a new `validate_fleet_portal_csrf(request)` that accepts the fleet cookie name, OR factor out a shared validator that takes the cookie name as a parameter.
- Header name stays `X-CSRF-Token` (matches the staff app pattern).

## R2-HIGH 2 — Mobile app is correctly out of scope but spec needs to verify portal users can't accidentally use it

**What `mobile-app.md` says:** "companion app for organisation users only — field staff, tradespeople, business owners, and org-level managers. It is NOT an admin panel."

**What the code does:** Mobile login at `/auth/login` (mobile/src/contexts/AuthContext.tsx:228) hits the staff JWT endpoint. A `portal_account` row has no matching `User` row, so the lookup fails and the user gets "Invalid credentials" — safe. But there's no UX feedback that says "this app is for staff only, use the fleet portal at fleet.<domain>".

**Fix:** Add a low-priority requirement (under Requirement 20 Out of Scope or as a new requirement note):
- IF a Portal_User attempts to log into the mobile app, the standard "Invalid email or password" message is shown — no special handling needed because `portal_accounts.email` is in a separate table from `users.email`.
- The mobile app's login screen SHOULD include a "I have a fleet portal account" link below the sign-in button that opens `https://fleet.<domain>` in the system browser (Capacitor `App.openUrl`). This is a small mobile-app-side change, NOT a fleet portal change — but document it so the spec is honest about cross-app discoverability.

This is **MEDIUM not HIGH** on reflection. Logged.

## R2-HIGH 3 — Spec assumes `password_changed_at`, `must_change_password`, `is_locked_permanently` are new columns; verify migration adds them all

**What the spec said:** Requirement 21 and design.md `portal_accounts` table list these columns.

**What the code has:** `portal_accounts` table doesn't exist at all (R1-BLOCKER 2 fix). All these columns will be created fresh in migration 0191. No conflict, but task 1.1 must be explicit so they aren't forgotten.

**Fix:** Already covered by R1-B2 fix — the `portal_accounts` table is created from scratch with every column listed in design.md "Data Models" section. No additional change needed beyond the existing R1 fix.

## R2-HIGH 4 — Reminder types in spec don't match existing reminder type names

**What the spec said:** Requirement 10 uses `'wof'`, `'cof'`, `'service_due'` as `reminder_type` values in `fleet_reminder_preferences`.

**What the code has:** Existing template types are `wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, `service_due_reminder` (`app/modules/notifications/schemas.py:27-32`).

**Fix:** Either:
- (a) Use the existing names in the new table's `reminder_type` enum: `'wof_expiry_reminder'`, `'cof_expiry_reminder'`, `'service_due_reminder'`. **Recommended** for naming consistency.
- (b) Map the short names to template names in code. Less clean.

Update the design's `fleet_reminder_preferences` schema and Requirement 10 to use the existing reminder-type names. Note that `'registration_expiry_reminder'` is a fourth type the existing system already supports — should fleet preferences include it? The original spec only listed WOF / COF / service_due. **Recommend including registration_expiry_reminder** for parity with the existing system, gated on whether the workshop tracks rego on this fleet.

## R2-HIGH 5 — `validate_portal_csrf()` and `create_portal_session()` exist; reuse, don't duplicate

**What the spec said:** Tasks 3.5–3.6 describe a CSRF middleware and session creation as if from scratch.

**What the code has:** `app/modules/portal/service.py` already has:
- `create_portal_session(db, customer_id) -> tuple[session_token, csrf_token]` — creates the session row + CSRF token (lines 254-280).
- `validate_portal_csrf(request)` — double-submit validation (lines 378-398).
- The existing `PortalSession` model only has `customer_id` (not `portal_account_id`).

**Fix:** Update tasks 3.5 and 3.6:
- The existing `PortalSession` model needs a new column `portal_account_id UUID NULL FK portal_accounts(id) ON DELETE CASCADE` added in migration 0191. Keep the existing `customer_id` column for backwards compatibility with the existing token-link portal.
- Reuse `create_portal_session` after extending it to optionally accept `portal_account_id` (or add a parallel `create_fleet_portal_session(db, portal_account_id) -> tuple[token, csrf]`).
- Reuse `validate_portal_csrf(request)` — it just checks cookie vs header.

This avoids reimplementing session/CSRF logic and keeps the two portal types (token-link and password-based) on a single `portal_sessions` table with a discriminator (`portal_account_id IS NULL` → token-link; `portal_account_id IS NOT NULL` → password-based).

## R2-MEDIUM 1 — Portal session 4-hour idle timeout is hardcoded

**What the spec said:** Requirement 21.8 makes `idle_timeout_minutes` configurable.

**What the code has:** The existing `portal_sessions` 4-hour idle is hardcoded somewhere in `app/modules/portal/service.py`. Need to migrate to reading from `portal_security_policy.session_policy.idle_timeout_minutes`.

**Fix:** Add to task 4A.6 a step: "Replace the hardcoded 4-hour timeout in `app/modules/portal/service.py` (find by `4` or `4 * 60`) with a read from `portal_security_policy.session_policy.idle_timeout_minutes` for fleet portal sessions; keep the 4-hour default for token-link sessions."

## R2-MEDIUM 2 — `notification_audit_log` table may not exist; verify before referencing

**What the spec said:** Design.md "Reminder Architecture" says "each fired reminder writes a row to `notification_audit_log`".

**What the code has:** Need to verify this table exists. The existing reminder queue uses `reminder_queue` table with `status`, `attempt_count`, `last_error` fields. There is no separate `notification_audit_log` referenced in the bug history.

**Fix:** Add a check task: `grepSearch notification_audit_log` to confirm it exists. If not, either (a) add an idempotency column to the existing `reminder_queue` table, or (b) create a new `notification_audit_log` table in migration 0191. Update design.md to reflect what's actually built.

## R2-MEDIUM 3 — Fleet portal session cookie scope is critical

**What the spec said:** Cookie has `Path=/fleet` (Requirement 23.3).

**Risk:** If the fleet portal is served from a sub-DOMAIN (`fleet.<domain>`) rather than a sub-path (`/fleet/...`), `Path=/fleet` is wrong — should be `Path=/`. The spec allows both deployment modes via `FLEET_PORTAL_HOST` env var.

**Fix:** Update Requirement 23.3 to: "When the fleet portal is served at a subdomain, the cookie has `Domain=fleet.<domain>` and `Path=/`. When served at a sub-path, the cookie has `Path=/fleet` (no Domain attribute, defaults to current host). Code must detect deployment mode at runtime from `FLEET_PORTAL_HOST` and set cookie attributes accordingly."

## R2-MEDIUM 4 — Frontend already has portal_csrf reading code in `frontend/src/api/client.ts`; spec's `frontend/src/fleet-portal/api/client.ts` should follow the same pattern

**What the code has:** `frontend/src/api/client.ts:40-71` reads `portal_csrf` cookie and sends `X-CSRF-Token` on POST/PUT/PATCH/DELETE.

**Fix:** Update task 14.1 description: "Reuse the existing `getPortalCsrfCookie` pattern from `frontend/src/api/client.ts:40` — read from `fleet_portal_csrf` cookie (parallel name) and send as `X-CSRF-Token` header. Same code shape, different cookie name."

## R2-MEDIUM 5 — `app/main.py` already has a stale `FleetAccount` reference in a comment (line 182)

**What the code has:** A comment block in `app/main.py:175-186` says "Without this, lazy mapper resolution fails with InvalidRequestError when a relationship is first accessed via selectinload." mentioning `FleetAccount.organisation`. The class doesn't exist yet — this looks like a previous abandoned attempt.

**Fix:** No action required — the comment is harmless. After we ship the real `FleetAccount` model, the comment becomes accurate. Add an import line for the new fleet_portal models in the same block (line ~196 area, after `_staff_models`): `from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401`. Add to task 2.2.

## R2-MEDIUM 6 — Mobile app overlap with kiosk role

**What the code has:** Mobile app already routes `kiosk` role users to a kiosk screen instead of the standard tabs (`mobile-app.md` line 97). The spec adds a kiosk checklist view at `/fleet/kiosk/checklist` (Requirement 9.11) — this is a **web kiosk** (tablet in browser), not the **mobile-app kiosk** screen. They serve different purposes:

- Mobile app `kiosk` role: native Capacitor app for vehicle check-in (existing).
- Fleet portal kiosk path: web-based pre-trip checklist for depots running on a shared tablet (new).

**Fix:** Add a clarifying note to Requirement 9.11: "The fleet portal kiosk view is web-only, served at `/fleet/kiosk/checklist` after Driver_User authentication. It is distinct from the mobile-app `kiosk` role (which is a separate Capacitor-based vehicle check-in flow). The two MUST NOT share session state — a kiosk role user logging into mobile uses staff JWT auth; a Driver_User running the portal kiosk view uses Fleet_Portal_Session."

## R2-LOW 1 — Frontend version-meta tag injection in Vite

**What the spec said:** Task 19A.2 says "at build time, write the build sha into `index.html` as `<meta name="x-app-version" content="<sha>">`".

**Implementation detail:** Vite supports `define` and HTML transform plugins. Existing pattern in `frontend/vite.config.ts` should be checked for an existing version-injection mechanism before adding a new one.

**Fix:** Add to task 19A.2: "Read `frontend/vite.config.ts` first per `no-shortcut-implementations.md` — if a version-injection plugin already exists, extend it; otherwise add a `transformIndexHtml` plugin."

## R2-LOW 2 — PostgreSQL `set_config()` with bound params is the correct pattern (already noted in R2-BLOCKER 1)

Already covered above. The R1 spec instruction to use string interpolation is updated to use `set_config()`.

---

## Summary of R2 changes applied to spec files

1. **R2-B1** — Updated tasks 1.2, 3.5, conventions block, and Notes to use `set_config()` bound-params (not string interpolation).
2. **R2-B2** — Replaced every `next_service_due_at` with `service_due_date` in requirements.md, design.md, tasks.md, properties (esp. Property 17, 27, Requirement 7.2, 10.6, 15.2).
3. **R2-B3** — Moved `customer_vehicles.fleet_checklist_template_id` add to migration task 1.1.
4. **R2-B4** — Rewrote task 10.2 to integrate with existing `enqueue_customer_reminders` and use existing template resolution.
5. **R2-H1** — Named the CSRF cookie `fleet_portal_csrf`; reuse `validate_portal_csrf` logic.
6. **R2-H4** — Use existing reminder type names (`wof_expiry_reminder`, etc.); added `registration_expiry_reminder` as a fourth optional type.
7. **R2-H5** — Reuse `create_portal_session` and `PortalSession` table; add `portal_account_id` column; discriminator-based.
8. **R2-M1** — Replace hardcoded 4-hour idle with `portal_security_policy.session_policy.idle_timeout_minutes` for fleet sessions.
9. **R2-M2** — Verify `notification_audit_log` exists; if not, use existing `reminder_queue` for idempotency.
10. **R2-M3** — Cookie scope (`Path=/` + `Domain=fleet.<domain>` vs `Path=/fleet`) selected based on `FLEET_PORTAL_HOST` mode.
11. **R2-M4** — Frontend `api/client.ts` for fleet portal mirrors the existing `portal_csrf` reader.
12. **R2-M5** — Added fleet_portal models import to `app/main.py` model-loading block.
13. **R2-M6** — Clarified that fleet portal kiosk view is web-only, distinct from mobile-app kiosk role.
14. **R2-L1** — Read `vite.config.ts` first before adding the version meta-tag injector.

After R2 fixes, the spec aligns with the actual codebase state and will not produce runtime errors from naming mismatches, schema collisions, or pattern duplication.


---

# ROUND 3 — Final code-vs-spec verification (2026-05-22)

After R1 + R2, four more concrete mismatches turned up while verifying every external reference in the spec.

## R3-BLOCKER 1 — `app/modules/push_notifications/` module does not exist

**What the spec said:** Requirement 24.15 and design.md "Native Mobile App Structure" section, plus tasks 19M.9, all assume `app/modules/push_notifications/` is an existing backend module that we extend with portal-account dispatch.

**What the code actually has:**
- `mobile/src/hooks/usePushNotifications.ts` exists (device-side FCM/APNs registration, listeners).
- The original mobile-app redesign prompt (`docs/kiro-konsta-redesign-prompt.md` line 590) says verbatim: **"Do NOT implement the backend FCM dispatcher in this task — only the device-side registration and listeners. Flag the backend work as a follow-up TODO."**
- `fileSearch push_notifications` returns no files. `grepSearch PushNotifications|fcm|apns` shows no Python module under `app/modules/`.

**Why it matters:** The spec promises push notifications for `fleet_booking_accepted`, `fleet_booking_declined`, `fleet_quote_quoted` events. Without a backend FCM dispatcher, mobile devices can register a token but the server has no code to actually send a push.

**Fix:** Either (a) **build the backend FCM dispatcher inside this spec** as part of task 19M.9, or (b) **defer push notifications to a follow-up spec** and replace push with in-app notifications + email for these events. Option (a) is more work but gives a complete feature. Option (b) ships the spec faster with a clean "future enhancement" note.

Going with **(a) plus a fallback**: task 19M.9 now creates the new `app/modules/push_notifications/` module as part of this spec, including FCM HTTP v1 dispatch via Google's REST API (no Celery needed for the MVP — synchronous send from the event emitter, idempotent on the queue table). For this MVP, support **Android (FCM) only**; iOS (APNs) is added in a follow-up. If FCM credentials are not configured for the org, the push send is a no-op (with a log line) and the in-app notification + email still fire as the primary surface.

## R3-BLOCKER 2 — `notification_audit_log` table does not exist

**What the spec said:** Design.md "Reminder Send Failures" section says "the failure is recorded in `notification_audit_log` with status `failed`".

**What the code has:** The reminder system uses a single `reminder_queue` table (`app/modules/notifications/models.py:274`) with `status IN ('pending','locked','sent','failed','skipped')`, `attempt_count`, `last_error`. Idempotency is enforced via `INSERT ... ON CONFLICT DO NOTHING` — there is no separate audit log table. The design's reference to `notification_audit_log` is aspirational.

**Why it matters:** Property 26 (Reminder firing is idempotent per `(vehicle, type, expiry_date)`), Property 29 (Reminder retry policy), and the "Reminder Send Failures" design subsection all reference `notification_audit_log`. If the implementer follows the spec literally they will create a duplicate audit table when the existing `reminder_queue` already provides everything needed.

**Fix:** Update design.md and tasks.md to use the existing `reminder_queue` table for both idempotency and failure recording. No new table. The relevant task (10.2) already gave the implementer flexibility — make it deterministic now: use `reminder_queue` end-to-end.

## R3-BLOCKER 3 — `get_db_session` does not set `app.current_fleet_account_id`

**What the spec said:** Task 1.2 says "Extend `get_db_session` (or add a parallel `get_fleet_db_session`) to also call `_set_rls_fleet_account_id` when a fleet portal session is active."

**What the code does today:** `app/core/database.py:118-123` reads `org_id` from a `_current_org_id` ContextVar and calls `_set_rls_org_id(session, org_id)`. There is no equivalent for fleet account.

**Why it matters:** RLS policies on the new fleet tables depend on `app.current_fleet_account_id` being set per request. If the dependency doesn't set it, every query against fleet tables either returns zero rows (RLS denies) or all rows (RLS unset). Both fail the design's tenant-isolation property.

**Fix:** The cleanest path is to add a parallel `_current_fleet_account_id` ContextVar plus a parallel setter, and have the `require_fleet_portal_session` FastAPI dependency call it on every fleet portal request (just before the underlying `get_db_session` yields the session). The session dependency itself doesn't need to know about fleet — the auth dependency does.

Update task 3.5 to make this explicit.

## R3-MEDIUM 1 — Existing `PortalSession.customer_id` is NOT NULL

**What the spec said:** Task 1.1 adds `portal_account_id UUID NULL FK portal_accounts(id) ON DELETE CASCADE` to the existing `portal_sessions` table.

**What the code has:** `customer_id UUID NOT NULL FK customers(id) ON DELETE CASCADE` on `portal_sessions` (`app/modules/portal/models.py:42-46`).

**Why it matters:** A fleet portal session for a Driver_User doesn't have a single `customer_id` — drivers belong to a Fleet_Account, which links to a customer, but the customer is the fleet admin's customer, not the driver's. Two paths:
- (a) On a fleet portal session, write `customer_id = fleet_account.customer_id` (the fleet admin's customer is the link). This works; RLS and existing portal queries that join via `customer_id` keep working. The driver inherits the fleet admin's customer_id in the session row, which is fine because the driver is logically part of the fleet account.
- (b) Make `customer_id` nullable. Riskier — every existing portal query assumes it's not null.

**Fix:** Go with (a). Update task 1.1 to make this explicit: when creating a fleet portal session, populate both `customer_id = fleet_account.customer_id` AND `portal_account_id = ...` so existing queries see a customer. Add a CHECK constraint: `(portal_account_id IS NOT NULL) OR (customer_id IS NOT NULL)` so we don't accidentally allow rows with neither — actually drop this since `customer_id` is already NOT NULL, just keep both populated for fleet sessions.

## R3-MEDIUM 2 — `reminder_queue.customer_id` may not match per-fleet-vehicle preferences

**What the code has:** `reminder_queue` table is keyed on `customer_id, vehicle_id, reminder_type` (per the INSERT signature in `reminder_queue_service.py:425-427`).

**What the spec needs:** When a `fleet_reminder_preferences` row enqueues a reminder for a vehicle, it writes the same `customer_id, vehicle_id, reminder_type` triple. The fleet account's customer is the customer who owns the vehicle, so this matches naturally. The existing dedup conflict resolution `ON CONFLICT DO NOTHING` keeps both org-wide and fleet-pref enqueues from double-firing.

**No spec change needed** — but document the dedup behaviour in task 10.2 explicitly so the implementer doesn't try to add a second key.

## R3-LOW 1 — `customer_id` on fleet tables vs the `Fleet_Account.customer_id` source of truth

**What the spec said:** Many fleet tables include `fleet_account_id` but not `customer_id` (e.g. `fleet_driver_assignments`, `fleet_checklist_submissions`). Queries that need to filter by customer must join through `fleet_accounts`.

**Why this is a low gap:** Adding a redundant `customer_id` column would let queries skip the join, but it duplicates state and risks drift. Joining through `fleet_accounts` is fine for the read patterns described.

**Fix:** No change. Just document the pattern in design.md — fleet table queries that need customer_id always join `fleet_accounts ON fleet_accounts.id = <fleet_table>.fleet_account_id` and read `fleet_accounts.customer_id`.

## R3-LOW 2 — Migration order across the spec's many table additions

**What the spec said:** Migration 0191 adds 16 tables + 1 column on `customer_vehicles` + 1 column on `portal_sessions` + 1 column on `module_registry` (oh wait, that one was reverted) + a `module_registry` row + RLS policies. That's a lot of work for one migration file.

**Why it could be a problem:** A single failed CREATE TABLE in the middle of the migration would leave the DB partially populated. Alembic migrations are transactional in PostgreSQL, so a failure rolls everything back, but the migration file is large and harder to review.

**Fix:** No spec change — keep it as a single migration for atomicity. Add a note to task 1.1: "If migration is rolled back, ensure the `module_registry` insert is also rolled back (it's in the same transaction, so it will be — but verify)."

---

## Summary of R3 changes applied to spec files

1. **R3-B1**: Task 19M.9 rewritten to create `app/modules/push_notifications/` from scratch (FCM HTTP v1 for Android only in MVP; iOS APNs deferred); fallback policy when FCM is not configured (in-app + email continue as primary).
2. **R3-B2**: Replaced every `notification_audit_log` reference with `reminder_queue`. Property 26 and 29 wording updated. Design.md "Reminder Send Failures" subsection rewritten.
3. **R3-B3**: Task 3.5 explicitly directs the implementer to set `app.current_fleet_account_id` via a new ContextVar inside the `require_fleet_portal_session` dependency, NOT inside `get_db_session`. Task 1.2 updated to match.
4. **R3-M1**: Task 1.1 spells out that fleet portal sessions write BOTH `customer_id = fleet_account.customer_id` AND `portal_account_id = ...` so the existing NOT NULL constraint and existing queries still work.
5. **R3-M2**: Task 10.2 documents the `INSERT ... ON CONFLICT DO NOTHING` reuse and confirms no second dedup key is needed.

After R3, every external reference in the spec maps to code that actually exists or to code this spec creates.
