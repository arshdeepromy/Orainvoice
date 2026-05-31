# Staff Management Phase 1 — Internal Spec Alignment Gap Analysis

Date: 2026-05-31
Reviewed: `requirements.md`, `design.md`, `tasks.md` (Phase 1) cross-checked for internal consistency AND against the relevant codebase touchpoints (`app/modules/staff/`, `app/middleware/rate_limit.py`, `app/modules/feature_flags/models.py`, `app/modules/module_management/models.py`, `app/modules/organisations/service.py`, `app/modules/scheduling_v2/router.py`, `alembic/versions/`).

The G1-G8 gap-closure tags from the prior review all hold up. The findings below (P1-N1 ... P1-N15) are NEW alignment gaps uncovered by checking the Phase 1 spec against itself and against the actual code shapes it relies on.

## Alignment gap tagging

Tagged `P1-N#` to keep them distinct from:
- `G#` — original closure tags from a prior gap analysis.
- `N#` — Phase 4 code-vs-spec gap analysis tags.

---

## REAL ALIGNMENT GAPS

### P1-N1. Migration `0203` `feature_flags` INSERT uses non-existent columns

**Where it bites:** design.md §3.1 migration code.

**Spec says (design.md §3.1):**

```sql
INSERT INTO feature_flags (id, key, description, default_enabled, scope)
VALUES
    (gen_random_uuid(), 'staff_management', 'Staff Management module', false, 'org'),
    (gen_random_uuid(), 'payroll', 'Payroll & Payslips module', false, 'org')
ON CONFLICT (key) DO NOTHING;
```

**Reality (`app/modules/feature_flags/models.py` + migration `0010`):** the `feature_flags` table is `(id, key, display_name NOT NULL, description, default_value, is_active, targeting_rules, created_by, created_at, updated_at)` plus `category, access_level, dependencies` added in 0067. There is **no `default_enabled` column** — it's `default_value`. There is **no `scope` column** at all. And `display_name` is NOT NULL — the spec's INSERT would fail at migration time with `null value in column "display_name" violates not-null constraint`.

The verified-against-code addendum (design.md §16) ALREADY says:

> ✅ `feature_flags` table key is `key` (not `slug`), scope column exists, default_enabled column exists.

— which contradicts the actual schema. Two errors: (1) `scope` does not exist, (2) `default_enabled` does not exist (real name is `default_value`).

**Fix applied:**
- Replace the INSERT with the correct column list — matching the canonical seed pattern in `alembic/versions/2025_01_15_0067-0067_seed_comprehensive_feature_flags.py` and the b2b_fleet_portal migration `0191_b2b_fleet_portal.py:800-805`.
- Update §16 verified-against-code addendum to remove the false claims about `scope` and `default_enabled`.
- requirements.md "Steering compliance" bullet that says "Mirror feature_flags row inserted alongside" stays as-is at the requirement level (it's correct in intent), but the implementation needs the column-name fix.
- Updated tasks.md A1 verify line to confirm the corrected INSERT shape.

### P1-N2. `subscription_plans` UPDATE heuristic is too broad and unverified

**Where it bites:** design.md §3.1 migration code, §16 (already flagged as STAFF-001 but the migration ships the wrong WHERE clause).

**Spec says (design.md §3.1):**

```sql
UPDATE subscription_plans
SET enabled_modules = (...)
WHERE name ILIKE '%default%' OR name ILIKE '%starter%' OR is_archived = false;
```

**Reality:** The `OR is_archived = false` clause makes this update touch **every non-archived plan**, not just "default" or "starter". The first two ILIKE conditions are then redundant. This means every subscription tier (starter, pro, enterprise, etc.) gets `staff_management` + `payroll` added to its `enabled_modules` JSONB — which may or may not be intended. STAFF-001 in the open-questions list says "is 'default' the right slug to target — confirm in design", and the design just shrugged and applied to all unarchived plans.

**Fix applied:**
- Resolved STAFF-001 explicitly: Phase 1 SHALL update **all unarchived subscription plans** to include both `staff_management` and `payroll` modules. This matches existing platform behaviour (modules ship enabled in every plan unless explicitly removed; per-org disablement is the gate). The redundant ILIKE clauses are removed for clarity — the WHERE becomes simply `WHERE is_archived = false`.
- requirements.md R11.3 updated to reflect the resolved scope.
- design.md §16 STAFF-001 marked "resolved — all unarchived plans".

### P1-N3. `staff_roster_view_tokens` schema documented in two places with subtle differences

**Where it bites:** design.md §3.1 vs §3.1.1, requirements.md R9.4, tasks.md A1 + C5.

**Spec says (design.md §3.1):** the migration upgrade body adds `staff_pay_rates` and module/feature-flag inserts but does NOT include the `staff_roster_view_tokens` CREATE TABLE statement. The downgrade ON THE OTHER HAND does drop `staff_roster_view_tokens`. The CREATE statement is documented in §3.1.1 separately as if it lives in the same migration.

**Reality:** if the migration is implemented literally as design.md §3.1 shows, the table will never be created (downgrade tries to drop a non-existent table — harmless via IF EXISTS, but the upgrade is broken).

**Fix applied:**
- Added an explicit comment to design.md §3.1 noting that the §3.1.1 block must be inlined into the upgrade body.
- tasks.md A1 already calls out "Creates `staff_roster_view_tokens` table per design §3.1.1 with `CREATE TABLE IF NOT EXISTS`, RLS policy, **and `ON DELETE CASCADE` on both `org_id` and `staff_id` FKs (G8)**. Includes the `UNIQUE (staff_id, week_start)` constraint" — which is correct, but it should reference §3.1.1 specifically rather than letting the implementer follow §3.1 alone.

### P1-N4. Module-disabled HTTP code says 404 in requirements but not in design or middleware

**Where it bites:** requirements.md R11.5 says "endpoints return HTTP 404 `not_enabled`". design.md §2 doesn't say which code. tasks.md C1 says "raises 404 `not_enabled` when disabled".

**Reality:** the existing `app/middleware/modules.py` returns **HTTP 403** for the path-prefix gated paths (`/api/v2/staff` is in `MODULE_ENDPOINT_MAP` keyed to `staff` module — verified during Phase 4 gap analysis). The Phase 1 work intentionally introduces a **separate module gate** (`staff_management`) that is NOT in `MODULE_ENDPOINT_MAP` — it's enforced inside the service layer via `ModuleService.is_enabled`.

**Decision required:**
- Use 404 (the spec's choice) → rationale: this is a "soft" feature gate where the legacy single-form view should still render. 404 with body `{ "detail": "not_enabled", "module": "staff_management" }` makes the new endpoints invisible without revealing the module's existence. The tabbed UI handles this gracefully (see design.md §6.1 — `if (!moduleEnabled) return <LegacyStaffDetail />`).
- Use 403 (matches everything else) → consistent but more visible.

The spec's framing (legacy fallback exists) supports the 404 choice. **Status: resolved as 404 with explicit rationale documented.**

**Fix applied:**
- requirements.md R11.5 — kept 404, added rationale text: "404 (not 403) is the deliberate choice here because the legacy `staff` module gate at the path-prefix level already controls broad access (returns 403); the `staff_management` sub-feature gate uses 404 to hide the new sub-endpoints without leaking that the feature exists. Frontend swaps to the legacy view based on the same flag, so users never see a 404 in the UI."
- design.md §2 — added a note explaining the dual-gate design (existing path-prefix `staff` 403, new sub-feature `staff_management` 404).
- tasks.md C1 — kept 404 as-is, no change needed.

### P1-N5. `useStaffRoster` Axios baseURL is wrong

**Where it bites:** design.md §6.3 sample code:

```tsx
const res = await apiC[lient].get(?, {
  baseURL: '/api/v2',
  signal: controller.signal,
  params: { staff_id, start, end },
})
```

**Reality:** the platform's `apiClient` (`frontend/src/api/client.ts`) is configured with `baseURL: '/api/v1'` and an interceptor that strips the baseURL when the URL starts with `/api/`. Every other v2 call in the codebase uses an absolute path — `apiClient.get('/api/v2/...')` — never an explicit `baseURL: '/api/v2'` override. The override would work but it's inconsistent and surprises future devs.

**Fix applied:**
- design.md §6.3 — rewrote the sample to use the canonical absolute-path pattern: `apiClient.get('/api/v2/schedule', { signal: controller.signal, params: {...} })`.
- design.md §6.5 — removed any references to the override pattern.
- mobile-app.md steering rule (already in `.kiro/steering/mobile-app.md`) confirms `baseURL: '/api/v1'`; v2 endpoints use absolute paths.

### P1-N6. `RosterTab.tsx` ScheduleCalendar prop signature is asserted but the underlying component doesn't take props

**Where it bites:** design.md §6.3, tasks.md E4.

**Spec says (design.md §6.3):**

```tsx
<ScheduleCalendar
  entries={entries}
  focusStaffId={staffId}
  readOnly={false}
  onChange={refresh}
/>
```

And tasks.md E4 says "extend its signature to accept `focusStaffId?: string`".

**Reality:** the existing `ScheduleCalendar` is `export default function ScheduleCalendar()` taking **no props** and managing its own state internally (verified in design.md §6.3 itself, which acknowledges this: "ScheduleCalendar today is a self-contained `export default function ScheduleCalendar()` with no props"). The spec says the Phase 1 task E4 will add a `focusStaffId` prop — fine — but the same §6.3 sample also passes `entries`, `readOnly`, `onChange` props that are **not enumerated** in the prop-extension plan.

This is a real gap: either the sample is wrong (the four-prop call) or the task is incomplete (only one prop extension listed). The likely intent is: pass through `focusStaffId` only, let the existing internal state continue to manage `entries`/`readOnly`.

**Fix applied:**
- design.md §6.3 — rewrote the JSX to show ONLY `focusStaffId={staffId}` being passed, with a brief comment: "the calendar continues to fetch its own data and manage its own read/write state — Phase 1 only constrains the staff visibility filter via the new prop". The `useStaffRoster` hook is removed from the JSX (it was wiring data the component fetches itself).
- Or alternatively, if Phase 1 wants to drive the data from outside, the prop list needs to expand to include `entries`, `readOnly`, `onChange` — but that's a much bigger refactor and contradicts the "additive Phase 1" intent. Chose the smaller change.
- tasks.md E4 already says "extend its props if needed: `focusStaffId?: string`" — kept that single prop.

### P1-N7. The `useStaffRoster` hook contradicts the "let the calendar self-manage" choice

**Where it bites:** design.md §6.3 — both the JSX sample AND a `useStaffRoster` hook implementation.

The `useStaffRoster` hook fetches `entries` itself, but if the calendar self-manages (per P1-N6 fix), the hook is redundant. The spec needs to commit to one or the other.

**Fix applied:**
- design.md §6.3 — kept `useStaffRoster` but only for the **toolbar's "Email roster" / "Send roster SMS" actions** (which need to know the active week). The calendar component continues to fetch its own data. The hook now only tracks `weekStart` (controlled by `WeekNavigator`) — no entries fetched. Renamed to `useRosterWeek(staffId)` for clarity.
- The data-fetching example was kept as a reference for E4 implementation if the team later decides to drive data from outside, but marked `// reference only — not used in Phase 1 default path`.

### P1-N8. `StaffMemberListResponse` shape change risk

**Where it bites:** requirements.md (only the steering bullet at the top mentions it), design.md §5.1, tasks.md C9.

**Spec says (design.md §5.1):**

> Compliance counters in response payload: `compliance_summary: { probation_ending_soon: N, ... }`.

The steering compliance bullet at the top of requirements.md says:

> The pre-existing `GET /api/v2/staff` list endpoint already returns `{ staff: [...], total, page, page_size }` — Phase 1 does NOT rename `staff` to `items`; the new `compliance_summary` field is added as a parallel top-level key.

This is correct! BUT the steering bullet exists ONLY in requirements.md. design.md §5.1 just says "Compliance counters in response payload" without restating the shape. tasks.md C9 has a full description but says "DOES NOT rename `staff` to `items`" — also good.

**Risk:** a future developer reading design.md alone might assume the shape becomes `{ items: [...], total, compliance_summary: {...} }` (matching the project-overview rule "all API responses wrap arrays in objects: `{ items: [...], total: N }`") and break the existing frontend consumer.

**Fix applied:**
- design.md §5.1 — added the explicit shape note: "The list response shape stays `{ staff: [...], total, page, page_size }` (NOT renamed to `items` — would break existing consumers). The new field is `compliance_summary` as a parallel top-level key."
- design.md §16 — added a verified-against-code line confirming the current schema field name is `staff` (per `app/modules/staff/schemas.py:92`, the existing `StaffMemberListResponse`).

### P1-N9. Steering compliance bullet about SMS path is internally inconsistent

**Where it bites:** requirements.md "Steering compliance" bullets.

**Spec says:**

> All SMS routes through the existing SMS provider stack (`app/integrations/connexus_sms.py` via the SmsVerificationProvider model — same pattern other modules use).

But the **same spec** introduces a brand-new `app/integrations/sms_sender.py` thin wrapper (tasks.md C4) and design.md §16 says:

> ⚠️ ... There is no module-level "send_sms" function today; Phase 1 introduces a thin helper in `app/integrations/sms_sender.py` (new file, mirroring email_sender's shape).

So the steering bullet says "use the existing stack" but the work plan ALSO ships a new wrapper. These don't contradict each other in technical terms (the wrapper calls the existing stack), but the steering bullet should be transparent about the new wrapper.

**Fix applied:**
- requirements.md "Steering compliance" — updated the bullet to: "All SMS routes through a new thin wrapper `app/integrations/sms_sender.py::send_sms` (introduced in Phase 1, mirrors `email_sender.py`'s shape), which loads the active `SmsVerificationProvider` row and dispatches via the existing `connexus_sms` provider stack." Removes the "use existing stack" misdirection.

### P1-N10. Rate-limit middleware policy reference contradicts the actual middleware shape

**Where it bites:** requirements.md R9.8, design.md §5.3 ("`app/middleware/rate_limit.py`'s policy map under key `public_staff_roster`"), tasks.md C7.

**Spec says (design.md §5.3):**

> Configured by adding a new rule to `app/middleware/rate_limit.py`'s policy map under key `public_staff_roster`.

**Reality:** there is **no policy map** in `app/middleware/rate_limit.py` — it uses hardcoded path-prefix conditionals (the HA-heartbeat block at lines 252-265 is the canonical pattern for new per-IP limits). tasks.md C7 actually got this RIGHT and called out the contradiction:

> Implementation: `app/middleware/rate_limit.py` does NOT have a "policy map" data structure today — it uses hardcoded path-prefix conditionals inside `_apply_rate_limits` (e.g., the HA-heartbeat block at lines 252-265). Add a NEW conditional block following the same pattern...

So the gap is internal: design.md and requirements.md reference a non-existent abstraction; tasks.md got it right.

**Fix applied:**
- design.md §5.3 — rewrote to match tasks.md C7's accurate description: "Add a new conditional block to `_apply_rate_limits` in `app/middleware/rate_limit.py` mirroring the existing HA-heartbeat per-IP limit pattern (lines 252-265). Constants `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` and `_PUBLIC_STAFF_ROSTER_RATE_LIMIT = 30` (per minute), Redis key `rl:public_staff_roster:ip:{client_ip}`."
- requirements.md R9.8 — clarified "rate-limit middleware policy file" to "rate-limit middleware (per-IP conditional in `_apply_rate_limits`)".

### P1-N11. Audit log table name discrepancy: `audit_logs` vs `audit_log`

**Where it bites:** requirements.md R12 + multiple action lists.

**Spec says (requirements.md R12):**

> THE SYSTEM SHALL call `app/core/audit.py::write_audit_log(session, action=..., entity_type=...)` (which writes to the `audit_log` table) for every state change in this phase.

But the action lists later in the same file refer to "audit_logs" (plural). For example, R7.6 says "writes an `audit_logs` row", R8.4 says "write an `audit_logs` row", R9.6 says "write an `audit_logs` row". Same in design.md §7.1.

**Reality:** the actual table is `audit_log` (singular), per `app/modules/admin/models.py:317`:

```python
__tablename__ = "audit_log"
```

The spec is consistently referring to "audit_logs" (plural) in 8+ places but the actual table is singular. Implementation will work because `write_audit_log` doesn't take a table name — but the spec text is wrong and a future reader running `psql ... \dt audit_logs` will be confused.

**Fix applied:**
- requirements.md — replaced every occurrence of "audit_logs row" / "audit_logs entry" with "audit_log row" / "audit_log entry" (singular).
- design.md — same global rename.
- tasks.md — same.

### P1-N12. SMS audit row metadata (G7) — column doesn't exist

**Where it bites:** requirements.md R9.3 (G7 acknowledgement), tasks.md F1 G7 path.

**Spec says (requirements.md R9.3):**

> THE SYSTEM SHALL log the segment count in the audit row's `metadata` (e.g., `{ "segments": 2, "encoding": "ucs2" }`) for ops visibility.

**Reality:** the `audit_log` table doesn't have a `metadata` column. Per `app/core/audit.py::write_audit_log`, the available structured fields are `before_value` and `after_value` (both JSONB). There's no separate `metadata` column.

**Fix applied:**
- requirements.md R9.3 — corrected to: "THE SYSTEM SHALL log the segment count + encoding in the audit row's `after_value` JSONB (e.g., `{ "segments": 2, "encoding": "ucs2", "phone_number_masked": "*****1234" }`) for ops visibility."
- tasks.md F1 G7 path — same correction: assert `after_value.encoding == 'ucs2'` and `after_value.segments >= 1`.

### P1-N13. tasks.md C9 says "seven" counters but only six are listed in some places

**Where it bites:** tasks.md C9, requirements.md R6.1.

**Cross-check:** R6.1 enumerates 5 counters (probation, visa, pay_review, missing_employee_id, missing_start_date). design.md §6.5 enumerates 7 (those 5 + `below_minimum_wage` + `missing_agreement`). tasks.md C9 enumerates 7. tasks.md E8 says "Renders **7** clickable counters".

So requirements.md R6.1 is missing two counters: `below_minimum_wage` (from R4.4) and `missing_agreement` (from R5.5). They're each defined in their own R# block, so there's no implementation gap, but the cross-references and the unified counter count differ between docs.

**Fix applied:**
- requirements.md R6.1 — explicitly listed all 7 counters under R6 so a single requirement enumerates the full Compliance Banner shape. The cross-refs to R4.4 (below_minimum_wage) and R5.5 (missing_agreement) are kept; R6.1 just collects them in one place for the API response shape.

### P1-N14. `feature_flags` mirror — duplicates a flag the platform already has?

**Where it bites:** requirements.md R11.4, design.md §3.1.

**Spec says (R11.4):**

> THE SYSTEM SHALL insert mirror rows into `feature_flags` for both keys, `default_enabled=false`, `scope='org'`.

**Reality:** Migration `0067_seed_comprehensive_feature_flags.py` already seeded ~45 module-name feature flags. Migration `0171_fix_feature_flag_defaults.py` later flipped most of them to `default_value=true` (because the module gate is the real gate — flags became redundant). The Phase 1 plan re-introduces feature flags for `staff_management` and `payroll` which aren't already in the seed list (correct — verified by a `grep "staff_management\|payroll"` in `0067` returning no matches), but with `default_enabled=false`. This contradicts the policy from `0171`: "set `default_value = true` for all non-admin feature flags" because the module gate is the source of truth.

The flag will be functionally inert — `ModuleService.is_enabled` is the gate, and the org-level flag override is the secondary lever. But shipping it disabled by default goes against the established convention.

**Fix applied:**
- requirements.md R11.4 — flipped to `default_value=true` to match the policy from migration `0171`. The org-level enablement is still gated by `ModuleService.is_enabled` checking `module_registry` + `org_modules` — the feature flag is just a mirror for the admin GUI.
- design.md §3.1 — INSERT corrected (combined with P1-N1 fix).
- Note added: "The feature flag is a passive mirror for the admin GUI; the actual gate is `ModuleService.is_enabled`. Setting `default_value=true` follows the convention established in migration `0171_fix_feature_flag_defaults.py` — the module gate is the real lever, the flag is informational."

### P1-N15. Steering compliance bullet "All `db.flush()` followed by `await db.refresh(obj)` before Pydantic serialization" — partially actionable, partially aspirational

**Where it bites:** requirements.md "Steering compliance" bullet.

**Reality:** the pattern is correct, but `app/modules/staff/service.py::create_staff` (and `update_staff`) ALREADY follow this — `await self.db.flush()` is called and the ORM object is returned, but there's NO `await self.db.refresh(obj)`. The router uses `StaffMemberResponse.from_orm(staff)` (or equivalent), which can fail with `MissingGreenlet` when relationships are accessed lazily after the flush. The refresh is the documented fix per project-overview.md.

**Decision:** the existing service should be patched as part of B4, but the spec doesn't enumerate "fix the missing refresh in the existing create/update" as a sub-task. tasks.md B4 says "Always call `await db.refresh(obj)` after `db.flush()`" — good, it's there, just buried in the bullet list.

**Fix applied:**
- tasks.md B4 — promoted this from a one-liner to an explicit Verify step: "Verify: `pytest tests/unit/test_staff_service_phase1.py` includes a regression case asserting that `staff.location_assignments` (the only existing eager-loaded relationship) is accessible on the returned object without raising MissingGreenlet — covers both create and update paths after the explicit `db.refresh(obj)`."
- requirements.md steering compliance bullet — kept as-is (the high-level rule is correct).

---

## ALSO VERIFIED (no fix needed)

These were checked and are consistent across the three docs:

- ✅ `module_registry` columns include `setup_question` + `setup_question_description` (verified at `app/modules/module_management/models.py:42-43`).
- ✅ `module_registry.slug` is the unique key for `ON CONFLICT (slug)` in the INSERT.
- ✅ `app/integrations/email_sender.py::send_email` accepts `dlq_task_name` + `dlq_task_args` per project-overview / quick-win #10.
- ✅ Existing `/api/v2/schedule` endpoint accepts `staff_id`, `start`, `end`, `location_id` query params and returns `{ entries, total }` — verified at `app/modules/scheduling_v2/router.py:47-65`.
- ✅ `DELETE /api/v2/staff/:id/permanent` exists for hard-delete — verified at `app/modules/staff/router.py:237`.
- ✅ `app/core/encryption.py::envelope_encrypt(value)` exists and accepts str/bytes returning bytes.
- ✅ `app/modules/portal/service.py` is the right reference for the public-token pattern (`secrets.token_urlsafe(32)` + `expires_at`).
- ✅ `app/modules/organisations/service.py::SETTINGS_JSONB_KEYS` is the right allow-list to extend for `minimum_wage_threshold_nzd` (verified at `app/modules/organisations/service.py:198`).
- ✅ Latest alembic head pre-Phase-1 is `0202` — new migrations correctly numbered `0203`, `0204`.
- ✅ `staff_members.user_id` exists (Phase 4's gap analysis found this); P1 doesn't depend on it but the partial UNIQUE index would be welcome here too — flagged as a soft cross-phase recommendation.
- ✅ `audit_log` table exists at `app/modules/admin/models.py:317`.
- ✅ `_run_outside_tx` + `autocommit_block()` pattern from migration 0202 is the canonical CONCURRENT INDEX template.
- ✅ Sub-feature module gating via service-layer call to `ModuleService.is_enabled('staff_management', org_id)` is the right pattern (the path-prefix middleware only handles the broad `staff` module gate).
- ✅ G1-G8 closure tags are all valid and have corresponding tasks + verify steps.

---

## Summary of fixes applied

| # | Gap | File touched | Section |
|---|---|---|---|
| P1-N1 | feature_flags INSERT uses non-existent columns | design.md | §3.1, §16 |
| P1-N2 | subscription_plans WHERE clause too broad — STAFF-001 resolved | requirements.md, design.md | R11.3, §3.1, §16 |
| P1-N3 | staff_roster_view_tokens schema in two places | design.md, tasks.md | §3.1, §3.1.1, A1 |
| P1-N4 | 404 vs 403 module-disabled — kept 404, documented rationale | requirements.md, design.md | R11.5, §2 |
| P1-N5 | Wrong Axios baseURL pattern | design.md | §6.3 |
| P1-N6 | ScheduleCalendar prop signature mismatch | design.md, tasks.md | §6.3, E4 |
| P1-N7 | useStaffRoster hook redundant — repurposed | design.md | §6.3 |
| P1-N8 | StaffMemberListResponse shape risk | design.md | §5.1, §16 |
| P1-N9 | Steering bullet about SMS contradicts new wrapper | requirements.md | Steering compliance |
| P1-N10 | Rate-limit middleware policy map doesn't exist | requirements.md, design.md | R9.8, §5.3 |
| P1-N11 | audit_logs (plural) vs audit_log (singular) | requirements.md, design.md, tasks.md | global rename |
| P1-N12 | audit_log has no `metadata` column — use after_value | requirements.md, tasks.md | R9.3, F1 |
| P1-N13 | counter-count mismatch (5 vs 7) | requirements.md | R6.1 |
| P1-N14 | feature_flags default_enabled=false contradicts policy | requirements.md, design.md | R11.4, §3.1 |
| P1-N15 | db.refresh missing — promoted to verify | tasks.md | B4 |

All fixes applied in this commit alongside this gap analysis.

## Recommendation

Phase 1 is internally consistent enough to start implementation once these 15 alignment gaps are addressed. The spec was already well-structured — most of the gaps are precision issues (column names, table singular/plural, false claims in the verified-against-code addendum) rather than structural problems. The G1-G8 closure tags from prior reviews remain valid.


---

## Task A1 implementation observations (2026-05-31)

### A1-O1. Task description says "23 new columns" but R2 + R5.1 + R6.3 sum to 22

**Where it bites:** tasks.md A1 first bullet ("Adds **23 new columns** to `staff_members` ... the previous 22 plus `residency_type` per G2").

**Reality:** R2.1 enumerates 20 columns; R5.1 adds `employment_agreement_upload_id`; R6.3 adds `last_pay_review_date`. Total = **22 columns**, not 23. The design.md §3.1 `ALTER TABLE staff_members` block also lists exactly 22 columns. R2.1 already includes `residency_type` (line 68 of requirements.md), so the "previous 22 plus residency_type" math in the task bullet is inadvertent double-counting.

**Resolution:** Migration `0203_staff_phase1_schema.py` adds the **22** columns enumerated in design.md §3.1 + R2/R5/R6 — matches the spec body but not the task's count claim. Verified post-migration: `SELECT count(*) FROM information_schema.columns WHERE table_name='staff_members' AND column_name IN (... all 22 ...)` returns 22. No code-level gap; the task description's "23" is a typo. tasks.md A1 Verify step reads `\d+ staff_members` shows the **23 new columns (incl. `residency_type`)` — should read **22**. Recommend updating the task description in a follow-up commit; not material to A1 completion.

### A1-O2. Task A1 verify step ran cleanly

- `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T app alembic upgrade head` → ran 0202 → 0203 with exit 0.
- `SELECT slug FROM module_registry WHERE slug IN ('staff_management','payroll')` → 2 rows.
- `SELECT key FROM feature_flags WHERE key IN ('staff_management','payroll')` → 2 rows.
- `\d+ staff_members` → 22 new columns present (incl. `residency_type` with `NOT NULL DEFAULT 'citizen'`).
- `\d+ staff_pay_rates` → table present with `tenant_isolation` RLS policy + ON DELETE CASCADE on org_id/staff_id FKs.
- `\d+ staff_roster_view_tokens` → table present with `tenant_isolation` RLS policy + ON DELETE CASCADE on org_id and staff_id FKs (G8 verified) + `UNIQUE (staff_id, week_start)` constraint.
- `SELECT constraint_name FROM information_schema.check_constraints WHERE constraint_name LIKE 'ck_staff_residency_type'` → 1 row (also confirmed `ck_staff_employment_type` and `ck_staff_tax_code`).

**A1 status: complete.**

---

## Task A2 implementation observations (2026-05-31)

### A2-O1. Verify wording says "returns 10 indexes" but `LIKE 'idx_staff_%'` matches 15

**Where it bites:** tasks.md A2 Verify step (`SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx_staff_%'` returns 10 indexes).

**Reality:** the dev DB had 5 pre-existing `idx_staff_*` indexes before A2 ran (`idx_staff_loc_location`, `idx_staff_loc_staff`, `idx_staff_members_active`, `idx_staff_members_employee_id`, `idx_staff_members_org`). After 0204 the same `LIKE` query returns **15 rows** — the 5 pre-existing + the 10 new. The 10 new indexes A2 was meant to add are all present and `indisvalid = true`:

| # | Index | Unique | Valid |
|---|---|---|---|
| 1 | idx_staff_pay_rates_staff_effective | f | t |
| 2 | idx_staff_pay_rates_org | f | t |
| 3 | idx_staff_review_due | f | t |
| 4 | idx_staff_probation_end | f | t |
| 5 | idx_staff_visa_expiry | f | t |
| 6 | idx_staff_roster_email_optin | f | t |
| 7 | idx_staff_roster_sms_optin | f | t |
| 8 | idx_staff_missing_employee_id | f | t |
| 9 | idx_staff_missing_start_date | f | t |
| 10 | idx_staff_roster_view_tokens_token | **t** | t |

**Resolution:** No code-level gap; the task's verify-step expected count is imprecise (it should say "the 10 new indexes from A2 are present" rather than "returns 10 indexes"). A scoped query `WHERE indexname LIKE 'idx_staff_%' AND indexname NOT IN ('idx_staff_loc_location', 'idx_staff_loc_staff', 'idx_staff_members_active', 'idx_staff_members_employee_id', 'idx_staff_members_org')` returns exactly 10. Recommend tightening the verify wording in a follow-up; not material to A2 completion.

### A2-O2. EXPLAIN shows Seq Scan on near-empty staff_members (2 rows)

**Where it bites:** tasks.md A2 Verify step EXPLAIN clause.

**Reality:** the dev DB has only 2 rows in `staff_members`, so `EXPLAIN SELECT count(*) FROM staff_members WHERE org_id=$1 AND is_active=true AND employee_id IS NULL` chooses `Seq Scan` (cost 0.00..1.02) regardless of available indexes — the planner correctly avoids index access for trivially small tables. Same shape for `employment_start_date IS NULL`. The task description explicitly anticipates this: *"The verify EXPLAIN may not pick the partial index if the table is empty — that's acceptable; just verify that the 10 indexes exist via the pg_indexes query."* The partial indexes `idx_staff_missing_employee_id` and `idx_staff_missing_start_date` are present and `indisvalid = true`; planner will use them once the active staff count grows past the seq-scan threshold.

### A2-O3. Verify step ran cleanly

- `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T app alembic upgrade head` → ran `0203 -> 0204` with exit 0; all 10 `CREATE INDEX CONCURRENTLY` statements logged with `[0204]` prefix.
- `SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx_staff_%' ORDER BY indexname` → all 10 new indexes present alongside 5 pre-existing.
- `pg_index.indisvalid = true` for all 10 new indexes (no INVALID-state CONCURRENTLY failures).
- `idx_staff_roster_view_tokens_token` confirmed `indisunique = true` (UNIQUE constraint per G8).
- EXPLAIN on near-empty table shows Seq Scan as expected; partial indexes verified present and valid.

**A2 status: complete.**


---

## Task C8 implementation observations (2026-05-31)

### C8-O1. Spec assumed an `uploads` ORM table / model that doesn't exist (P1-N16)

**Where it bites:** tasks.md C8 first sub-bullet ("Validates the upload exists, belongs to the org") + requirements.md R5.1 ("FK to `uploads.id`") + design.md §5.2 (the row in the new endpoints table reads "Multipart upload OR JSON `{ upload_id }` after a separate `/uploads` POST").

**Reality:** there is **no `uploads` table** in the database and **no `Upload` ORM model** anywhere in `app/modules/`. The existing `/api/v2/uploads/{receipts,attachments}` POST endpoints (`app/modules/uploads/router.py`) are filesystem-only:

- They write the encrypted+compressed bytes to disk under `${UPLOAD_DIR}/{category}/{org_id}/{uuid.hex}{ext}`.
- They return `{"file_key": "...", "file_name": "...", "file_size": N}` — there is no `id` or `upload_id` field in the response.
- The `StorageManager` tracks per-org quota usage but does NOT persist any per-file metadata row.

The migration `0203` declared `staff_members.employment_agreement_upload_id` as a free-standing `uuid` column (no FK constraint to a hypothetical `uploads.id`) — confirmed in the migration source, no `ForeignKey` clause. So the column is `uuid NULL` with no referential integrity at the database level.

**Resolution applied (this commit, task C8):**
- The router treats the `upload_id` body field as the UUID portion of the on-disk `file_key`. The frontend (E5 DocumentsTab) extracts the hex segment between the `org_id` path and the file extension from the `file_key` returned by the existing `/uploads/attachments` POST and sends it as a real `UUID` here.
- Org isolation is enforced via the file path itself: the router globs `${UPLOAD_DIR}/attachments/{org_id}/{upload_id.hex}.*` against the **requesting org's** folder. A file uploaded by org A lives at `attachments/<orgA>/...`, so org B looking under `attachments/<orgB>/...` will never find it — the cross-org test `test_employment_agreement_upload_from_other_org_returns_404` proves this.
- Audit row records both `before_value` (the prior upload_id, if any) and `after_value` (the new upload_id) so the "Replace" workflow leaves a complete trail.
- Phase 1 keeps the column as a free-standing `uuid` (no FK). If a future phase introduces a real `uploads` ORM table, the column can be promoted to a FK with a follow-up migration; the current shape is forward-compatible.

**Frontend implication for task E5:** the DocumentsTab needs to parse `file_key` from the `/uploads/attachments` response into a UUID before posting to this endpoint. Concretely:
```ts
// file_key = "attachments/<org_id>/<32-hex>.<ext>"
const hex = file_key.split('/').pop()!.split('.')[0]
const upload_id = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20,32)}`
```
Recommend documenting this in tasks.md E5 when that frontend task gets picked up; not material to C8 completion.

### C8-O2. Verify step ran cleanly

- `docker compose exec -T app pytest tests/test_staff_router.py -v -k 'employment_agreement'` → **6 passed, 29 deselected, 0 failed**.
- Module-disabled gate fires before any other work (returns 404 `not_enabled`).
- Unknown-staff returns 404 even when the upload exists on disk.
- Missing upload returns 404 `"Upload not found"`.
- Cross-org upload returns 404 (org-isolation via the path glob proven).
- Happy path: `staff_members.employment_agreement_upload_id` set, `db.flush` + `db.refresh` both called, audit row written with `action='staff.employment_agreement_uploaded'` + `entity_type='staff_member'` + `before_value=None` + `after_value={'upload_id': ...}`, response is masked `StaffMemberResponse`.
- Replace path: `before_value` carries the prior upload_id, `after_value` carries the new one — full swap audit trail.

**C8 status: complete.**
