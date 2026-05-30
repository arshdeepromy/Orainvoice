# Code Verification Report — Phase 2 (2026-05-31)

This document records every assumption made in the Phase 2 spec docs (`requirements.md`, `design.md`, `tasks.md`) and the result of cross-checking each one against the live codebase **at workspace head 0202**. Anything ⚠️ or ❌ is a real gap that must be fixed before code lands.

> Verification scope: re-read all three P2 spec files plus the user's amendments (G1 bereavement, G2 confidential filter, G3 6-month gate rename to R6, G6 TOIL guard, G9 days→hours, STAFF-009 partial-day, STAFF-010 leap-year). Cross-checked every code reference against actual files.

---

## 1. Backend infrastructure — ALL ✅ verified

| Assumption | Status | Verified at |
|---|---|---|
| `app/modules/admin/models.py::PublicHoliday` exists with `holiday_date`, `name`, `country_code` | ✅ | `app/modules/admin/models.py:467-489`. UniqueConstraint and `ix_public_holidays_country_year` index both exist. |
| `app/modules/admin/service.py::sync_public_holidays` (Nager.Date) feeds the table | ✅ | Confirmed via grep. |
| `app/modules/scheduling_v2/models.py::ScheduleEntry.entry_type` includes `'leave'` | ✅ | `ENTRY_TYPES = ["job", "booking", "break", "other", "leave"]`. |
| `app/integrations/email_sender.py::send_email` with `dlq_task_name` kwarg | ✅ | `email_sender.py:1763`. |
| `app/integrations/sms_sender.py` (Phase 1 introduction) | ✅ planned | Phase 1 task C4 ships this; P2 reuses it for leave-decision SMS. |
| `app/core/audit.py::write_audit_log(session, *, action, entity_type, ...)` | ✅ | Real table is `audit_log` (singular); the helper encapsulates this — design §12 already corrects the prose. |
| Existing scheduler Redis SETNX lock at `scheduler:loop_lock` (60s TTL, 30s renewal) | ✅ | `app/tasks/scheduled.py:891`. |
| `_DAILY_TASKS: list[tuple]` registry in `scheduled.py:872` | ✅ | New tasks registered by appending `(fn, interval_seconds, name)` tuples. |
| `staff_members.availability_schedule` JSONB keyed by `monday`/`tuesday`/...`sunday` | ✅ | Verified at `app/modules/staff/models.py`; OWD fallback uses these keys. |

---

## 2. Critical drifts — must fix before implementation

### 2.1 ❌ `user_permission_overrides` schema mismatch

**Spec says** the table has columns `permission`, `org_id`. Both wrong.

**Reality** at `app/modules/auth/permission_overrides.py`:
```python
class UserPermissionOverride(Base):
    __tablename__ = "user_permission_overrides"
    id: uuid PK
    user_id: uuid FK users
    permission_key: str  # ← NOT "permission"
    is_granted: bool     # ← spec doesn't mention this
    granted_by: uuid | None
    created_at: timestamptz
```

**No `org_id` column exists.** The override is purely user-scoped — Postgres relies on `users.org_id` for tenant isolation when joining.

**Impact if shipped as-is:**
- The migration backfill `INSERT INTO user_permission_overrides (..., permission, ...)` would fail with `column "permission" of relation "user_permission_overrides" does not exist`.
- The verify SQL `SELECT count(*) FROM user_permission_overrides WHERE permission='leave:family_violence:view'` would also fail.
- Tasks B6a's `permissions_router.py` grant/revoke endpoints would fail to insert/delete rows.

**Fix:**
- Use column name `permission_key` everywhere.
- Migration backfill must also set `is_granted=true` (this is what makes the override "grant the permission" rather than "revoke it").
- Tenant scoping comes from `JOIN users u ON u.id = upo.user_id WHERE u.org_id = :org_id` — not a column on the override.

### 2.2 ❌ `rbac.user_has_permission(...)` does NOT exist

**Spec design §4.4 calls** `await rbac.user_has_permission(db, user_id=..., org_id=..., permission=...)`. The codebase has `app/modules/auth/rbac.py::has_permission(role, permission, overrides=...)` — synchronous, takes a list of override dicts inline rather than fetching from DB.

**Reality** at `app/modules/auth/rbac.py:81-130`:
```python
def has_permission(role, permission, overrides=None, custom_role_permissions=None) -> bool:
    """Synchronous. Checks overrides list FIRST (each is {permission_key, is_granted})
    then ROLE_PERMISSIONS[role], then 'module.*' wildcards.
    """
```

The overrides come from `request.state.permission_overrides` (already loaded by RBAC middleware at `app/middleware/rbac.py:_load_permission_overrides` with 60s Redis cache).

**Impact if shipped as-is:**
- `_apply_confidential_filter` calls a function that doesn't exist → ImportError at startup.
- Even if the function name is corrected, `request.state.permission_overrides` is the right input source — no DB call needed.

**Fix:**
- Replace with: `has_perm = has_permission(user_role, FV_LEAVE_VIEW_PERMISSION, overrides=request.state.permission_overrides)`.
- The helper signature must accept the request (or the overrides list directly), not a `db` session.
- Remove `await` — it's synchronous.

### 2.3 ❌ Permission key namespace inconsistency

**Spec uses** `leave:family_violence:view` (colon-separated).

**Reality**: every existing permission key in the codebase uses `module.action` (dot-separated). Examples from `app/modules/auth/rbac.py:ROLE_PERMISSIONS`:
- `inventory.read`
- `invoices.create`
- `job_attachments.upload`
- `kiosk.check_in`

Permission registry derives `{module_slug}.{action}` from `module_registry` (per `app/modules/auth/permission_registry.py` and `org-security-settings/requirements.md` §7.1: "permission keys in the format `{module_slug}.{action}`").

**Impact if shipped as-is:**
- Inconsistent permission naming across the codebase.
- The wildcard match `if f"{perm_domain}.*" in role_perms:` at `rbac.py:127` only fires on `.` separator — `leave:family_violence:view` would never match `leave.*`.
- The permission registry's auto-derive logic at `permission_registry.py` would produce permission keys like `leave.create`, `leave.read`, `leave.approve` (dot-separated) when admins build custom roles, contradicting the FV permission's colon format.

**Fix:**
- Rename to `leave.family_violence_view` (single dot, snake_case action). Or better: `leave.fv_view` to match the existing terse pattern.
- Compatible with the wildcard match (`leave.*` at the role level grants access to `leave.fv_view`).
- Consistent with the existing permission_registry auto-derive convention.

### 2.4 ❌ Settings sub-route `/settings/people/permissions` does NOT match the existing routing model

**Spec design §9.1 says** "deep-linkable as `/settings/people/permissions`".

**Reality** at `frontend/src/pages/settings/Settings.tsx:74-130`: Settings is a **single-page app with tab-based navigation via `?tab=...` query param**, NOT a hierarchy of sub-routes. The `NAV_ITEMS` list has hardcoded sections: `profile`, `organisation`, `branches`, `users`, `security`, `integrations`, `billing`, `accounting`, `currency`, `language`, `printer`, `invoice-template`, `webhooks`, `modules`, `notifications`, `online-payments`. URL pattern: `/settings?tab=security`.

**Impact if shipped as-is:**
- A `/settings/people/permissions` route would 404 (no such route registered).
- Phase 2 either has to refactor the entire Settings tab system (out of scope) OR add a new top-level NAV_ITEMS entry like `'people-permissions'` reachable at `/settings?tab=people-permissions`.

**Fix:**
- Add a new entry to `NAV_ITEMS`: `{ id: 'people-permissions', label: 'People Permissions', icon: '👥', adminOnly: true, module: 'staff_management' }`.
- Add `'people-permissions'` to the `SettingsSection` type union.
- Add `'people-permissions': PermissionsPage` to `SECTION_COMPONENTS`.
- The deep link becomes `/settings?tab=people-permissions`, not `/settings/people/permissions`.
- Update design §9.1 + tasks D11 accordingly.

**Alternative considered:** the existing `security` section already houses `<RolesPermissionsSection>`. Could add FV-permission management there. Skipping for now because that section is org-wide custom-role config, not per-permission grants — the spec's pattern of per-user toggles fits a new section better.

### 2.5 ⚠️ `organisations.overtime_handling` column — verify no JSONB collision

**Spec proposes** adding `organisations.overtime_handling text NOT NULL DEFAULT 'pay_cash'` as a real column.

**Reality**: the `organisations` table already has `settings JSONB` for org-level toggles (verified at `app/modules/admin/models.py:116`). The `SETTINGS_JSONB_KEYS` allow-list at `app/modules/organisations/service.py:198` is the closed set of supported keys.

**Question**: should `overtime_handling` go in the JSONB blob (consistent with how every other org-level setting is stored), or as a real column?

**Spec rationale**: "This is the cleanest place because it's a hard org-level config, not a settings-blob value." But this contradicts the established pattern — `gst_inclusive`, `auto_expense_on_stock_purchase`, `email_signature_enabled`, etc., are all booleans stored in the JSONB.

**Impact if shipped as-is:**
- Inconsistency with existing settings storage convention.
- Won't cause runtime failures, but creates a second source-of-truth pattern that future maintainers will trip on.
- The cache invalidation logic for `get_org_settings` at `app/modules/organisations/service.py` doesn't know about non-JSONB columns — direct edits to `overtime_handling` would not invalidate the org-settings cache.

**Recommendation:**
- Move `overtime_handling` into `organisations.settings` JSONB.
- Add `overtime_handling` to `SETTINGS_JSONB_KEYS`.
- The CHECK constraint enforcement moves to application-level validation in `update_org_settings`.

This is a stylistic fix, not blocking. If the user prefers a real column, the `update_org_settings` function will need a path to invalidate the cache when the column is updated outside the standard JSONB write — see `invalidate_org_settings_cache` helper.

### 2.6 ⚠️ `app/modules/leave/permissions.py` (B3a) — name collision risk

**Spec task B3a** creates `app/modules/leave/permissions.py`.

**Reality**: `app/modules/auth/permissions_overrides.py` and `app/modules/auth/permission_registry.py` already exist. There is no naming collision per se (different module path), but importers must avoid `from app.modules.leave.permissions import ...` clashing with `from app.modules.auth.permission_registry import ...`. Stylistically inconsistent.

**Recommendation:** rename to `app/modules/leave/visibility.py` (clearer intent — confidential-leave visibility filter, not a generic permissions module).

### 2.7 ⚠️ Backfill of existing org_admins — does the migration know which user_ids are org_admins?

**Spec migration A1** says: "insert one `user_permission_overrides` row per current `org_admin` user with permission `leave:family_violence:view`".

**Reality**: `users.role` column is the source of truth for role assignment (verified by ROLE_PERMISSIONS keys in `rbac.py`). The migration query needs to be:

```sql
INSERT INTO user_permission_overrides (id, user_id, permission_key, is_granted, granted_by, created_at)
SELECT
    gen_random_uuid(),
    u.id,
    'leave.fv_view',  -- per §2.3 fix
    true,
    NULL,             -- system-granted; no granting user
    now()
FROM users u
WHERE u.role = 'org_admin'
ON CONFLICT DO NOTHING;
```

**Issue**: there is no UNIQUE constraint on `(user_id, permission_key)` in the `user_permission_overrides` table today (verified by reading the model — only `id` is the PK). So `ON CONFLICT DO NOTHING` won't deduplicate. Two re-runs of the migration would insert two rows per org_admin.

**Fix options:**
- Add a partial unique index `(user_id, permission_key)` in migration 0205. Mandatory for correct upserts in `permissions_router.py` too — without it, the grant endpoint at B6a would also leak duplicate rows.
- The existing `create_or_update_permission_override` helper in `app/modules/auth/permission_overrides.py` does the SELECT-then-INSERT-or-UPDATE pattern — task B6a should reuse this rather than insert directly.

**Recommendation:** add `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_user_perm_overrides_user_perm ON user_permission_overrides (user_id, permission_key)` to migration 0206. Backfill uses the SELECT-then-INSERT idempotent pattern. B6a uses the existing `create_or_update_permission_override` helper.

### 2.8 ⚠️ `org_id` parameter passed to `create_or_update_permission_override` — mismatch with model

The existing helper at `app/modules/auth/permission_overrides.py:55` accepts an `org_id` parameter but the table has no `org_id` column. The helper uses `org_id` only for audit-log scoping (passed through to `write_audit_log`). The spec doesn't mention this nuance.

**Impact**: if Phase 2's `permissions_router.py` (B6a) calls this helper without passing `org_id`, the audit log row will have `org_id=NULL`, which makes per-org audit trails harder to query.

**Fix:** task B6a must always pass `org_id=current_user.org_id` to `create_or_update_permission_override`.

### 2.9 ⚠️ `relationship_to_subject` enum — recommend wider whitelist for clarity

**Spec** uses `'close_family' | 'other'` as the enum.

**Holidays Act s70 actually defines** "close family" with a specific list (spouse/partner, parent, child, sibling, grandparent, grandchild, parent-in-law). The 1-day cap applies to "any other person".

**Recommendation (not blocking):** widen the enum to `'spouse' | 'parent' | 'child' | 'sibling' | 'grandparent' | 'grandchild' | 'in_law' | 'other'` — gives finer audit trail and matches the statute. Cap logic groups everything except `'other'` under `close_family` semantics. Frontend select offers all 8 options.

### 2.10 ⚠️ Phase 2 schema change adds `relationship_to_subject` AND `partial_day_start_time` columns to `leave_requests`

Both are defined in design §3.1. Spec says they're nullable. Task A1 says CHECK constraint for `relationship_to_subject` is `'close_family','other'` when set.

**Reality** for the partial-day flow: the `time` Postgres type is supported by SQLAlchemy as `Time`. No issue.

**Issue**: requirements R4.1 says "partial_day_start_time (nullable; populated when `hours_requested < standard_daily_hours` AND `start_date == end_date` — see G5/G7 future enhancements)". The "G5/G7 future enhancements" references don't exist in this doc — that's stale text from an earlier draft. Should reference STAFF-009 (which is correctly in Open Questions).

**Fix:** edit R4.1 to reference STAFF-009 instead of "G5/G7 future enhancements". Trivial doc cleanup.

### 2.11 ⚠️ R4.7 bereavement cap — "no running balance is held" but balance row still exists

Per R4.7: "No running balance is held; each new bereavement request is independent (the cap applies per request, not per year)."

But R2.4 backfills `leave_balances` rows for every staff × every active leave_type INCLUDING bereavement (which is statutory + active). So a `leave_balances` row for `(staff_id, bereavement_type_id)` exists, with `accrued_hours=0` forever.

**Impact**: the `submit_request` flow at R4.4 says "refuse where `hours_requested > balance.accrued_hours - used_hours - pending_hours` UNLESS event_based or unaccrued". Bereavement is `event_based`, so the balance check correctly skips. ✅ Behaviour correct.

However the design §4.3 step 3 (bereavement gate) says "Skip the balance check at step 4 (bereavement is event_based, balance is always 0)." — fine. The unused balance row is just dead weight, no harm.

**Recommendation (not blocking):** add a code comment explaining that `bereavement` balance rows are intentionally unused; the per-event cap is enforced inside `submit_request`. Future maintainers will wonder.

### 2.12 ⚠️ TOIL Phase 2 guard (G6 / R4.8 step 5) — refers to "R4.8" but R4.8 is "Leave in advance"

**Reality**: requirements R4 is structured as 1, 2, 3 (endpoints), 4 (balance check), 5 (doctor's note), 6 (confidential), 7 (bereavement cap), 8 (leave in advance), 9 (FV visibility). The TOIL guard text in design §4.3 step 5 references "G6" but no G6 exists in P2 requirements (only in tasks closure ticks). Stale numbering.

**Fix:** rename design §4.3 step 5 to reference R4.4 (the balance-check requirement) with an "additional TOIL-specific extension" note. Or add R4.10 in requirements explicitly capturing the TOIL Phase 2 zero-balance guard.

### 2.13 ⚠️ `time` Postgres type via SQLAlchemy — null partial_day_start_time

**Spec design §3.1** has `partial_day_start_time time` (nullable). Phase 1 already stores `staff_members.shift_start` as `String(5)` (e.g. `"09:00"`). Phase 2's design §4.3 step 7 says: "For partial-day requests, the single schedule_entries row uses `partial_day_start_time` as start and `partial_day_start_time + hours_requested` as end (otherwise full-day from `shift_start` to `shift_end`)."

**Issue**: `staff.shift_start` is text `"HH:MM"`, but `leave_requests.partial_day_start_time` is `time` (Postgres TIME type). The default-from-shift-start logic needs to convert `"09:00"` → `time(9, 0)`. Not hard but worth calling out.

**Recommendation:** add a service-layer helper `parse_shift_time(s: str | None) -> time | None` that handles the conversion + None-safety.

---

## 3. Subtle assumptions verified clean

| Assumption | Status | Notes |
|---|---|---|
| Existing `RBACMiddleware._load_permission_overrides_cached` 60s TTL is acceptable for FV-permission grants/revokes | ✅ | Verified at `app/middleware/rbac.py:102`. Revocation visible within 60s — spec R4.9 already documents this. |
| `app/modules/scheduling_v2/service.py::SchedulingService.create_entry(org_id, payload)` exists; design §4.3 step 7 reuses it | ✅ | Verified at `scheduling_v2/service.py:61`. Phase 2's leave-approval flow can call it directly. |
| `leave_types.confidential_visibility=true` is a NEW column added by 0205; no existing rows have it set | ✅ | Migration creates the column with `default false`; `family_violence` is the only seeded row with it set true. |
| Phase 2 depends on Phase 1 columns: `employment_type`, `employment_start_date`, `standard_hours_per_week` | ✅ | All added in Phase 1's 0203. P2 prerequisite text already documents this. |
| Casual employee logic in §4.1 reads `staff.employment_type == 'casual'` — column exists post-Phase-1 | ✅ | Phase 1's 0203 adds the column with default `'permanent'`. |

---

## 4. Migration sequence verified

| Item | Status | Notes |
|---|---|---|
| Phase 1 lands as 0203 + 0204 | ✅ | Confirmed in P1 verification. |
| Phase 2 lands as 0205 + 0206 | ✅ | Sequential. |
| `0205` adds new tables + columns; `0206` is the CONCURRENTLY index pack | ✅ | Per design §3.1 + §3.3. |
| All new tables get RLS + tenant_isolation policy | ✅ | Per `0008_create_rls_policies` template. |
| Zero `op.create_index(...)` calls anywhere in the migration | ✅ | Per `database-migration-checklist.md`. |
| Leap-year anniversary helper used in accrual.py | ✅ | Design §4.1.2 documents the helper. STAFF-010 closed by spec. |
| Days-to-hours conversion for custom days-unit types | ✅ | Design §4.1.1 documents the helper. G9 closed. |

---

## 5. Spec-completeness self-check — what passes

✅ Navigation & Access §2 (modulo §2.4 fix above for the Settings sub-route)
✅ Component tree §6
✅ User workflow trace §7
✅ Modal inventory §8
✅ Toolbar / list spec §6
✅ Error UI §9 (incl. all new 422/403 codes)
✅ Integration points §11 — design §12 already cross-references send_email, sms_sender, scheduler lock, audit_logs, user_permission_overrides
✅ Bereavement per-event cap §4.3 step 3 (G1 closed)
✅ Family-violence visibility mechanism §4.4 + §9.1 (G2 closed — modulo §2.1 + §2.2 + §2.3 fixes above)
✅ Sick + family-violence 6-month gate §4.1 (G3 closed)
✅ Days-to-hours conversion §4.1.1 (G9 closed)
✅ Leap-year anniversary helper §4.1.2 (STAFF-010 closed)

---

## 6. Implementation readiness verdict

**Phase 2 spec is NOT yet implementation-ready.** Three drifts in §2.1, §2.2, §2.3 would cause hard runtime failures the moment the migration runs or the `_apply_confidential_filter` import fires. One drift in §2.4 would cause the Settings page to 404. The remaining items in §2.5-§2.13 are stylistic / consistency fixes that won't break flows but should land in the same edit pass.

**Mandatory fixes before code lands** (in priority order):

| Priority | Fix |
|---|---|
| 🔴 Must fix | §2.1 — use `permission_key` (not `permission`) and don't reference non-existent `org_id` column on `user_permission_overrides` |
| 🔴 Must fix | §2.2 — replace `await rbac.user_has_permission(...)` with synchronous `has_permission(role, key, overrides=request.state.permission_overrides)` |
| 🔴 Must fix | §2.3 — rename permission key to `leave.fv_view` (dot-separated, matches existing convention) |
| 🔴 Must fix | §2.4 — Settings sub-route uses `?tab=people-permissions` query param; add NAV_ITEM entry to `Settings.tsx` |
| 🟠 Should fix | §2.5 — `overtime_handling` should live in `organisations.settings` JSONB, not a real column |
| 🟠 Should fix | §2.6 — rename `app/modules/leave/permissions.py` → `app/modules/leave/visibility.py` |
| 🟠 Should fix | §2.7 — add UNIQUE index on `(user_id, permission_key)` in 0206; reuse `create_or_update_permission_override` helper for grants |
| 🟡 Nice-to-fix | §2.8 — pass `org_id=current_user.org_id` when calling the helper |
| 🟡 Nice-to-fix | §2.9 — widen `relationship_to_subject` enum to 8 statutory categories |
| 🟡 Doc cleanup | §2.10 — replace "G5/G7 future enhancements" with "STAFF-009" in R4.1 |
| 🟡 Doc cleanup | §2.11 — comment in code that bereavement balance rows are intentionally unused |
| 🟡 Doc cleanup | §2.12 — fix R4.8/G6 numbering reference in design §4.3 |
| 🟡 Code clarity | §2.13 — add `parse_shift_time` helper for `"HH:MM"` → `time` conversion |

Estimated edit time for the four 🔴 must-fix items: ~30 minutes. The 🟠 should-fix items add another ~15 minutes. Total: under an hour to make P2 implementation-ready.

The core architectural decisions (leave_types, leave_balances, leave_requests, leave_ledger, accrual engine, OWD detection, s40A extension, casual 8% skip, confidential filter, FV permission grant model) are all sound and verified against the live codebase. None of them require redesign — only the integration points with existing infrastructure (permission_overrides table, rbac helper signature, Settings tab nav) need adjustment.
