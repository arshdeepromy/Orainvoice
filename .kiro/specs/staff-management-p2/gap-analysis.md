# Staff Management Phase 2 — Internal Spec Alignment Gap Analysis

Date: 2026-05-31
Reviewed: `requirements.md`, `design.md`, `tasks.md` cross-checked for internal consistency AND against codebase touchpoints (`app/modules/auth/rbac.py`, `app/modules/auth/permission_overrides.py`, `app/middleware/rbac.py`, `app/modules/admin/models.py::AuditLog` and `PublicHoliday`, `app/modules/scheduling_v2/models.py`, alembic `0023`).

The G1, G2, G3, G6, G9 closure tags from prior reviews all hold up. The findings below (P2-N1...P2-N12) are NEW alignment gaps uncovered by checking Phase 2's three docs against each other and against the actual code shapes they rely on.

## Alignment gap tagging

Tagged `P2-N#` to keep them distinct from prior `G#` closure tags and the Phase 1 / Phase 4 `P1-N#` / `N#` tags.

---

## REAL ALIGNMENT GAPS

### P2-N1. Permission key naming is inconsistent between docs and within the same doc

**Where it bites:** requirements.md R4.9 + STAFF-002-resolved entry, design.md §4.3 step 3, tasks.md A1 backfill, multiple other places.

**Spec says:** the permission key takes **three** different forms across the spec:
- `leave.fv_view` — appears in design.md `FV_LEAVE_VIEW_PERMISSION` constant (§4.3 line 401), design.md §4.4 docstring, design.md §9.1, tasks.md A1 backfill SQL, tasks.md B3a, tasks.md B6a — **majority form**.
- `leave:family_violence:view` — appears in **requirements.md STAFF-002-resolved entry** (line 265) AND **design.md §4.3 step 3** (line 339).
- `leave.family_violence.view` (dot-separated three-part form) — implied by the requirements.md R4.9 phrasing "permission key `leave:family_violence:view`" but contradicted by the next paragraph which says "Introduce a permission key `leave.fv_view`".

**Reality:** the only key that works with the existing `app/modules/auth/rbac.py::has_permission` helper is one that:
1. Matches the `module.action` convention used everywhere in `ROLE_PERMISSIONS` (e.g. `invoices.create`, `customers.read`).
2. Resolves correctly under the wildcard match logic at line 124-126 of rbac.py: `perm_domain = permission.split(".")[0]`. For `leave.fv_view`, `perm_domain == 'leave'`. The wildcard match looks for `leave.*` in the role's permissions list — and **NO existing role has `leave.*` in `ROLE_PERMISSIONS`** (verified). Same for `leave:family_violence:view` — the colon-separated form has no `.` so `perm_domain == 'leave:family_violence:view'`, and the wildcard logic never fires.

So both key forms behave identically at runtime today (neither is matched by a role wildcard), but the spec is internally contradictory and the documented "the `leave.*` wildcard automatically grants this permission to roles configured for full leave-module access" claim in requirements.md R4.9 is **false** — no role has that wildcard.

**Fix applied:**
- Standardised on **`leave.fv_view`** (dot-separated, two-part) everywhere.
- Removed the false claim about the `leave.*` wildcard auto-granting access. The actual mechanism is direct override row in `user_permission_overrides` per user.
- Updated the STAFF-002-resolved entry in requirements.md to use the canonical `leave.fv_view` form.
- Updated design.md §4.3 step 3 — it was the only place using the colon form in the whole design doc, and `_apply_confidential_filter` 50 lines later already uses `leave.fv_view`.
- Added a clarifying sentence: "Granting `leave.fv_view` is **always** explicit per-user via `user_permission_overrides` rows; there is no role-level shortcut. Phase 2's migration backfill seeds the override for current org_admins as a one-off."

### P2-N2. `audit_logs` (plural) used in design + tasks; real table is `audit_log` (singular)

**Where it bites:** tasks.md B3 ("All methods write `audit_logs` rows"), design.md §12 ("Existing `audit_logs` table model is in `app/modules/admin/models.py::AuditLog`"), design.md §13 ("audit_logs, user_permission_overrides").

**Reality:** verified at `app/modules/admin/models.py:318`: `__tablename__ = "audit_log"` (singular). Same finding as Phase 1 P1-N11 and Phase 4 N11. The `write_audit_log` helper doesn't take a table name so the implementation will work, but the spec text is wrong.

**Fix applied:**
- Global rename `audit_logs` → `audit_log` in tasks.md B3 and design.md §12 + §13.
- requirements.md R15 already uses singular `audit_log` correctly — no change.

### P2-N3. Spec instructs creation of UNIQUE index that already exists from migration 0023

**Where it bites:** tasks.md A1 backfill block.

**Spec says:**

> Note the unique index `(user_id, permission_key)` is created in 0206 (A2) before the backfill — A1 must be split so the unique index is created in a CONCURRENTLY pre-step OR the migration uses a deduplicating CTE pattern. Recommended: create the unique index inline in 0205 via `CREATE UNIQUE INDEX IF NOT EXISTS uq_user_perm_overrides_user_perm ON user_permission_overrides (user_id, permission_key)` (acceptable here because the table is small and no CONCURRENTLY constraint applies to UNIQUE on a small table), THEN run the backfill — the `ON CONFLICT` resolves cleanly.

**Reality:** verified at `alembic/versions/2025_01_15_0023-0023_create_user_permission_overrides.py:36-40` — the migration ALREADY adds `op.create_unique_constraint("uq_user_permission_overrides_user_perm", "user_permission_overrides", ["user_id", "permission_key"])`. The constraint has been live since revision 0023; no need to recreate it.

Worse: the spec's recommended index name `uq_user_perm_overrides_user_perm` differs from the existing constraint name `uq_user_permission_overrides_user_perm` — running `CREATE UNIQUE INDEX IF NOT EXISTS uq_user_perm_overrides_user_perm ...` would succeed (because there's no index by that exact name) but leave two unique enforcement points on the same column pair. Wasteful but not broken.

**Fix applied:**
- tasks.md A1 backfill block reduced to a one-liner: "The UNIQUE constraint `uq_user_permission_overrides_user_perm` on `(user_id, permission_key)` already exists from migration 0023; the `ON CONFLICT (user_id, permission_key)` clause in the backfill SQL resolves cleanly without any pre-step." Removed the multi-paragraph "split-the-migration" recommendation.

### P2-N4. tasks.md A1 backfill SQL uses string `'leave.fv_view'` but the spec elsewhere uses inconsistent forms

**Where it bites:** tasks.md A1 backfill SQL — already uses the canonical form correctly. But the requirements.md STAFF-002-resolved entry uses the colon form. Tied to P2-N1.

**Fix applied:** covered by P2-N1 unification.

### P2-N5. `org_settings.overtime_handling` storage location contradicts itself

**Where it bites:** requirements.md R10.2, design.md §3.1 + §1, tasks.md A1.

**Spec says:**
- requirements.md R10.2: "`org_settings.overtime_handling` enum"
- design.md §1 architecture: "ADP snapshot column on staff_members; **org_settings.overtime_handling**"
- design.md §3.1: "`org_settings.overtime_handling` lives in the existing org_settings JSONB or its own column — **design uses a new column on `organisations`**" (and proceeds to write `ALTER TABLE organisations ADD COLUMN ... overtime_handling text NOT NULL DEFAULT 'pay_cash'`)
- tasks.md A1: "`organisations.overtime_handling` column with CHECK enum"

So requirements.md and the §1 summary use the misleading name `org_settings.overtime_handling`, but the actual implementation places it on the `organisations` table as a typed column. There's no `org_settings` table — settings are either columns on `organisations` or a JSONB blob in `organisations.settings`. The Phase 4 gap analysis (N5) flagged this exact ambiguity affecting payroll's overtime-handling read.

**Fix applied:**
- requirements.md R10.2 — renamed to `organisations.overtime_handling` to match the design.
- design.md §1 — same rename.
- The design's §3.1 "lives in the existing org_settings JSONB or its own column" prose is removed in favour of the unambiguous "added as a typed column on `organisations`".
- This decision aligns with Phase 4's N5 fix (P4 reads via a `_org_setting('overtime_handling', ...)` helper that tries the typed column first; with this fix, P2 ships the typed column and P4's helper resolves it directly).

### P2-N6. Confidential-leave audit-redaction rule is mentioned but not specified

**Where it bites:** design.md §4.3 step 9 ("Audit `leave_request.submitted` with redacted PII (no free-text reason in audit row for `confidential_visibility=true` types)"), step 10 ("Audit `leave_request.approved` (redacted for confidential types)"). tasks.md B3 ("confidential-leave audits redact free-text fields").

**Reality:** the spec says "redacted" but never enumerates **what** the redacted shape looks like, unlike Phase 4 which spelled out the explicit `after_value` shape per audit action (Phase 4 §4.5). Without an explicit rule, the implementer might leak the `reason` text for family-violence leave into `audit_log.after_value`, defeating the whole confidentiality feature.

**Fix applied:**
- Added new design.md §4.3.1 enumerating the redacted `after_value` shapes for confidential-leave audits:
  - `leave_request.submitted` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence', date_range: '<start>..<end>', hours_requested }` — NO `reason`, NO `relationship_to_subject`, NO `attachment_upload_id`.
  - `leave_request.approved` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence', decided_at }` — NO `decision_notes`.
  - `leave_request.rejected` → `{ leave_request_id, staff_id, leave_type_code: 'family_violence', decided_at }` — NO `decision_notes`.
  - For non-confidential types, full payload is allowed (existing behaviour).
- Added a verify step in tasks.md B3: "When the leave_type has `confidential_visibility=true`, the audit row's `after_value` MUST NOT contain `reason`, `decision_notes`, `relationship_to_subject`, or `attachment_upload_id`. Lint test: a unit test parses every `write_audit_log(...)` call site in `app/modules/leave/service.py` and asserts the dict-literal `after_value` for `leave_request.*` actions is gated by a `_redact_for_confidential(leave_type)` helper."

### P2-N7. `_apply_confidential_filter` Pydantic-vs-SQLAlchemy import unclear

**Where it bites:** design.md §4.4 (the `_apply_confidential_filter` helper signature uses `Select` and `or_` from SQLAlchemy plus `Request` from Starlette/FastAPI). Importing `Select` directly is fine but the spec doesn't show the import block.

**Reality:** the spec uses `from sqlalchemy import select` patterns elsewhere; the typical idiom is `from sqlalchemy.sql import Select`. Without explicit imports, a reviewer might miss that `or_` needs `from sqlalchemy import or_`. Minor but would cause lint warnings.

**Fix applied:**
- Added an import block at the top of the §4.4 code sample: `from sqlalchemy import or_, select` and `from sqlalchemy.sql import Select`. This is housekeeping but prevents the implementer from guessing.

### P2-N8. Days-to-hours fallback (`8h/day`) is inconsistent with R7.4 banner phrasing

**Where it bites:** design.md §4.1.1 says "Fallback when `standard_hours_per_week` is NULL: 8h/day (industry default)". But R6.2 says "On first day past the 6-month mark, grant the full **80 hours (10 days × 8h)** for permanent employees, OR pro-rata for variable-hours staff (`standard_hours_per_week × 2 weeks`)" — also assuming 40h/week / 8h/day.

**Reality:** the math is consistent (`80h = 10 × 8h = 40h × 2 weeks`), but the fallback rule and the explicit 80h grant should reference the same `standard_hours_per_week` source so a future change (e.g., 4-day week trial) flows through. R6.2 currently treats `80` as a literal, not a derived value.

**Fix applied:**
- Updated R6.2 to phrase the grant in terms of `standard_hours_per_week`: "On first day past the 6-month mark, grant `(staff.standard_hours_per_week or 40) × 2` hours (80h for the standard 40h/week worker, 60h for a 30h/week part-timer, etc.)."
- Same phrasing in R6.3 for family violence.
- design.md §4.1 sick-leave grant block now references `(staff.standard_hours_per_week or 40) * 2` instead of a literal 80.

### P2-N9. Public-holiday cache-key TTL contradicts itself

**Where it bites:** R8.3 says "cache OWD computations in Redis keyed `staff:owd:{staff_id}:{holiday_date}` with **24h TTL**". design.md §4.2 `is_otherwise_working_day` writes the cache with `redis.setex(..., 86400, ...)` (= 24h). Steering compliance bullet at top of requirements.md says "Public-holiday computations cached in Redis for **1 hour** (org × upcoming-window) to avoid repeated `public_holidays` table scans".

**Reality:** the steering compliance bullet describes a different cache (the public-holiday-list scan, org-keyed) than the per-staff OWD cache (24h TTL). The two caches don't conflict, but reading the steering bullet then R8.3 + §4.2 makes the reader think there's a 1h-vs-24h contradiction.

**Fix applied:**
- Clarified the steering compliance bullet: "Public-holiday list (org × upcoming-window of `public_holidays` rows) cached in Redis for 1 hour. Per-staff OWD computations cached separately for 24h (R8.3, §4.2) — they're stable for the holiday's lifetime so a longer TTL is safe."
- Added the same note to design.md §4.2 immediately above `is_otherwise_working_day`.

### P2-N10. R3.4 ledger ordering and R4.7 bereavement audit trail conflict

**Where it bites:** R3.4 says "THE SYSTEM SHALL surface the ledger via `GET /api/v2/staff/:id/leave/ledger?leave_type_id=...` with `{ items, total }` shape." R4.7 says "The ledger remains the audit trail for who took how much per-event" — implying bereavement consumers will query the ledger.

**Reality:** the ledger is currently the same object regardless of leave_type. For a bereavement query (`leave_type_id=<bereavement_id>`), the response includes `delta_hours` (always negative for `request_approved`) but NOT the `relationship_to_subject` (that lives on `leave_requests`). To reconstruct "who took 3 days for close family", the consumer needs to JOIN the ledger row's `request_id` to `leave_requests.relationship_to_subject`. The spec doesn't say whether the ledger response should pre-join this field.

**Fix applied:**
- Added a clarifying note to R3.4: "When `leave_type_id` filters to a leave type with per-event semantics (e.g., bereavement), each ledger item additionally surfaces `request_relationship_to_subject` (resolved via JOIN to `leave_requests.relationship_to_subject` when `request_id IS NOT NULL`). For other leave types this field is `null`."
- design.md §5 endpoint table updated to mention the join.
- tasks.md B3 `list_ledger` description updated to include the join.

### P2-N11. Settings tab id collides with existing Settings.tsx scheme

**Where it bites:** design.md §9.1 + tasks.md D11 use tab id `'people-permissions'`. Without checking the existing `Settings.tsx`, this might collide.

**Reality:** I cannot verify this from the files I've already read, but the spec text says (verified at `Settings.tsx:74-130`) the existing pattern is `?tab=...` with ids like `'profile'`, `'security'`, etc. The new id `'people-permissions'` looks distinctive. This isn't a real gap, just a recommendation: confirm the id isn't already used.

**Fix applied:**
- Added a verify step to tasks.md D11: "Before merge, grep `frontend/src/pages/settings/Settings.tsx` for `'people-permissions'` to confirm the id doesn't already exist as a tab. If it does, rename to `'staff-permissions'` or similar."

### P2-N12. `_apply_confidential_filter` semantics break self-service requests when `requested_by != current_user.staff_id`

**Where it bites:** design.md §4.4. The filter says:

```python
return query.where(
    or_(
        LeaveRequest.leave_type_id.notin_(confidential_type_ids),
        LeaveRequest.requested_by == user_id,
    )
)
```

**Reality:** `LeaveRequest.requested_by` is `users.id` (the user who submitted). But staff can submit for themselves OR another staff (e.g., manager submits on behalf of a staff member who can't access the system). In that case, the `staff_id` on the leave request is the SUBJECT, but `requested_by` is the proxy submitter. The filter as written would HIDE confidential requests from the subject staff member if they were submitted by their manager — exactly the opposite of intent.

The right filter for "self-service: show me my own family-violence requests" is `LeaveRequest.staff_id == staff_id_for_user(user_id)`, NOT `requested_by == user_id`.

**Fix applied:**
- Rewrote the filter to use `staff_id` lookup, not `requested_by`:
  ```python
  # Resolve current user's staff_id (NULL if user is not a staff member, e.g., global_admin or office user)
  current_staff_id_subq = (
      select(StaffMember.id).where(StaffMember.user_id == user_id).limit(1).scalar_subquery()
  )
  return query.where(
      or_(
          LeaveRequest.leave_type_id.notin_(confidential_type_ids),
          LeaveRequest.staff_id == current_staff_id_subq,
      )
  )
  ```
- Added the explanation: "subject access (the staff member's right to see their own confidential leave) is keyed by `staff_id`, not `requested_by`. A manager submitting on behalf of staff is `requested_by`, but the staff member is still the subject and must see the request when they log in."
- Added verify step to tasks.md F3a: "test confidential filter: log in as a staff member whose family-violence request was submitted ON THEIR BEHALF by a manager (`requested_by != current user`); confirm the staff sees their own request despite the proxy submission. Same flow but as the manager (without `leave.fv_view`) — manager does NOT see the request after the fact (they submitted it on behalf of a confidential subject)."

This last clause is contentious — should the proxy submitter retain visibility? My read of the law (DV-VPA 2018 + privacy principles) says the subject controls visibility, and the proxy is a one-time courier. I've documented the choice and added it to the open questions list.

---

## ALSO VERIFIED (no fix needed)

These were checked and are consistent across the three docs and against the codebase:

- ✅ `app/modules/scheduling_v2/models.py::ScheduleEntry.entry_type` already includes `'leave'` (verified line 19).
- ✅ `app/modules/admin/models.py::PublicHoliday` exists with `country_code, holiday_date, name, year, is_fixed, synced_at` columns + UNIQUE on `(country_code, holiday_date, name)`.
- ✅ `app/modules/admin/service.py::sync_public_holidays` exists at line 4839.
- ✅ `app/integrations/email_sender.py::send_email` accepts `dlq_task_name`.
- ✅ Phase 1's new `app/integrations/sms_sender.py` is the right path for leave-decision SMS — Phase 2 reuses it.
- ✅ `user_permission_overrides` table exists with `(id, user_id, permission_key, is_granted, granted_by, created_at)` columns. NO `org_id` column. UNIQUE on `(user_id, permission_key)` from migration 0023.
- ✅ `create_or_update_permission_override` and `delete_permission_override` exist at `app/modules/auth/permission_overrides.py:56-170` with the documented signatures (both accept `org_id=None` for the audit log).
- ✅ `app/middleware/rbac.py::RBACMiddleware._load_permission_overrides_cached` populates `request.state.permission_overrides` (verified line 94). 60s Redis TTL per `_PERM_CACHE_*` constants.
- ✅ `app/modules/auth/rbac.py::has_permission(role, permission, overrides=None, custom_role_permissions=None)` is the synchronous helper. Wildcard logic only matches when permission is dot-separated AND `<domain>.*` is in the role's permission list.
- ✅ Latest migration before Phase 2 will be 0203 + 0204 (Phase 1). Phase 2 lands as 0205, 0206.
- ✅ `staff_members.availability_schedule` JSONB pattern keyed by weekday.
- ✅ G1, G2, G3, G6, G9 closure tags from prior reviews remain valid.
- ✅ The Phase 2 prerequisite "Phase 1 must ship before Phase 2" is correctly stated; the `staff_members.employment_start_date` column added in P1 is what `accrue_for_staff` reads.

---

## Summary of fixes applied

| # | Gap | File touched | Section |
|---|---|---|---|
| P2-N1 | Permission-key naming inconsistent (3 forms across docs) | requirements.md, design.md, tasks.md | R4.9, STAFF-002, §4.3 step 3 |
| P2-N2 | `audit_logs` (plural) vs `audit_log` (singular) | design.md, tasks.md | §12, §13, B3 |
| P2-N3 | UNIQUE constraint already exists from 0023 | tasks.md | A1 backfill |
| P2-N4 | covered by P2-N1 | — | — |
| P2-N5 | `org_settings.overtime_handling` ambiguity | requirements.md, design.md | R10.2, §1, §3.1 |
| P2-N6 | Confidential audit redaction shapes were unspecified | design.md, tasks.md | new §4.3.1, B3 |
| P2-N7 | `_apply_confidential_filter` missing imports | design.md | §4.4 |
| P2-N8 | 8h/day fallback inconsistency with R6.2 phrasing | requirements.md, design.md | R6.2, R6.3, §4.1 |
| P2-N9 | Cache TTL ambiguity (1h vs 24h) | requirements.md, design.md | Steering, §4.2 |
| P2-N10 | Bereavement ledger needs JOIN to relationship | requirements.md, design.md, tasks.md | R3.4, §5, B3 |
| P2-N11 | Settings tab id collision check | tasks.md | D11 verify |
| P2-N12 | Confidential filter uses `requested_by` instead of `staff_id` | design.md, tasks.md | §4.4, F3a |

All fixes applied in this commit alongside this gap analysis.

## Recommendation

Phase 2 is structurally sound — the leave engine, accrual job, and approval queue are coherently specified. The 12 alignment gaps above are precision issues plus one substantive correctness fix (P2-N12: the self-service visibility filter would have hidden requests from their own subjects when the request was submitted on their behalf). Get these fixes in before implementation starts and Phase 2 is ready to ship.

The G1-G9 closure tags from prior reviews remain valid. The 12 P2-N# tags layered on top are the new findings from this internal-consistency audit.


---

## Implementation Deferrals

### F5: `scripts/test_staff_leave_e2e.py` — DEFERRED to Phase 3 cut-over

- **Date**: 2026-05-31
- **Status**: deferred
- **Rationale**: The full Hypothesis-driven property suite (`tests/property/test_leave_balance_invariants.py`, F4) plus the unit suites (`test_leave_request_workflow.py`, `test_leave_accrual.py`, `test_public_holiday_engine.py`, `test_leave_audit_redaction.py`, `test_leave_confidential_filter.py`) cover every backend invariant called out in F5's brief — submit/approve/cancel cycle, bereavement-cap rejection, confidential filter (subject + non-permitted + permitted + revocation + P2-N12 proxy regression), accrual idempotency, OWD detection, and ledger sum equals balance. The frontend D10 vitest covers the confidential-filter UI rendering. F5 was scoped as a browser-driven Playwright run; running it requires the dev server + a seeded test org, which is impractical inside the auto-advance loop. Will land alongside Phase 3's E2E suite (clock-in/out + leave together) where the test org bootstrap is shared. Tracked in `docs/future/staff-management-system.md` Phase 2 status.
- **Coverage already in place**: F1 (accrual unit), F2 (workflow unit), F3 (public-holiday unit), F3a (confidential filter unit), F4 (property invariants), D10 (UI confidential rendering).
- **Not blocking**: All pre-merge gate items are satisfied by the existing tests.
