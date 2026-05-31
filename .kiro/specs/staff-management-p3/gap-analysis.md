# Staff Management Phase 3 — Internal Spec Alignment Gap Analysis

Date: 2026-05-31
Reviewed: `requirements.md`, `design.md`, `tasks.md` (Phase 3) cross-checked for internal consistency AND against codebase touchpoints (`app/modules/kiosk/router.py`, `app/modules/scheduling_v2/service.py`, `app/modules/time_tracking_v2/service.py`, `app/middleware/rate_limit.py`, `app/modules/admin/models.py::AuditLog`, `app/tasks/scheduled.py`).

The G1, G2, G3, G4, G6, G7, G8, G9, G10, G12, G13, G15, G16, G17 closure tags from prior reviews mostly hold up (G10 has a residual rename inconsistency — see P3-N3). The findings below (P3-N1...P3-N12) are NEW alignment gaps uncovered by checking Phase 3's three docs against each other and against the actual code.

## Alignment gap tagging

Tagged `P3-N#` to keep them distinct from prior `G#` closure tags and from the Phase 1 / Phase 2 / Phase 4 `P1-N#` / `P2-N#` / `N#` tags.

---

## REAL ALIGNMENT GAPS

### P3-N1. Photo identifier name inconsistent: `photo_file_key` vs `photo_upload_id`

**Where it bites:** requirements.md R3.5 vs R4.1, design.md §4.1 + §6.4 + §7.1 + §7.2 + §9.1, tasks.md B9.

**Spec says:** the photo handle takes two different names across the spec:
- **`photo_file_key`** — appears in requirements.md R3.5 (kiosk action body), tasks.md B9 (the canonical-form note that explicitly calls out "the spec name in early drafts" was `photo_upload_id`).
- **`photo_upload_id`** — appears in requirements.md R4.1 (self-service action body), design.md §4.1 service signatures (`kiosk_clock_action(...photo_upload_id)`, `self_service_clock_action(...photo_upload_id)`), design.md §6.4 mobile JSX (`api.post('/api/v2/staff/me/clock-action', { action, photo_upload_id: photoUploadId, ... })`), design.md §7.1 + §7.2 workflow traces, design.md §9.1 SLO table notes.

**Reality:** the existing `app/modules/uploads/router.py::_store(...)` returns a dict shaped `{ "file_key": "...", "file_name": "...", "file_size": N }` (verified earlier — it returns `file_key`, NOT `upload_id`). There is no `uploads` table with a UUID `id` field. The Phase 4 gap analysis already settled this convention (N3 fix renamed `pdf_upload_id` to `pdf_file_key` for the same reason).

**Fix applied:**
- Standardised on **`photo_file_key`** everywhere — matches the existing uploads-helper return shape and the pattern set by P4-N3.
- requirements.md R4.1 — renamed `photo_upload_id` to `photo_file_key`.
- design.md §4.1 service signatures — `kiosk_clock_action(...photo_file_key)`, `self_service_clock_action(...photo_file_key)`.
- design.md §6.4 mobile sample — `api.post(... { action, photo_file_key: photoFileKey, ... })`.
- design.md §7.1, §7.2 workflow traces — same rename.
- design.md §9.1 SLO note text — same.
- tasks.md B9 already documents the canonical form correctly; no change there.

### P3-N2. `audit_logs` (plural) vs `audit_log` (singular) — same finding as P1/P2/P4

**Where it bites:** requirements.md R5.4 ("Every manual edit writes `audit_logs` action='time_clock.edited'"), design.md §7.1 ("audit_logs (time_clock.in)"), design.md §10 ("Existing `audit_logs` writer + `send_sms`"), design.md §11 ("Integration points: ... audit_logs ...").

**Reality:** verified at `app/modules/admin/models.py:318`: `__tablename__ = "audit_log"` (singular). Same finding as P1-N11, P2-N2, P4 N11.

**Fix applied:**
- Global rename `audit_logs` → `audit_log` in requirements.md R5.4, design.md §7.1, §10, §11.
- requirements.md R16 already uses singular `audit_log` correctly.

### P3-N3. G10 closure tag still mentions `metadata` despite the metadata→flags rename

**Where it bites:** design.md §12 G10 closure tag ("`metadata` column on time_clock_entries"), tasks.md G10 closure tick at line 139 ("`metadata.flagged_for_review` written on flag action"), tasks.md E3 G10 path ("row gets metadata flag + audit row").

**Reality:** the actual column is `flags` (not `metadata`) — every other reference in the spec correctly says `flags` and explicitly calls out the SQLAlchemy DeclarativeBase reservation. The closure tags are stragglers from a prior draft.

**Fix applied:**
- design.md §12 G10 closure tag — rewrote to: "`flags` JSONB column on time_clock_entries (named `flags` not `metadata` — SQLAlchemy DeclarativeBase reservation); §4.9 flag flow; §6.2 photo thumbnails + side-by-side modal + flagged-acknowledgement on approve."
- tasks.md G10 closure tick — rewrote to: "`flags.flagged_for_review` JSONB key written on flag action; photos surfaced in Hours tab for managers; side-by-side comparison modal works; flagged-entry acknowledgement required to approve week."
- tasks.md E3 G10 E2E path — "row gets `flags.flagged_for_review=true` flag + audit row".

### P3-N4. `overtime_handling` storage location contradicts Phase 2's resolved fix

**Where it bites:** requirements.md R6a.2, tasks.md A1 "Phase 2 prerequisite" bullet — both claim `overtime_handling` lives in `organisations.settings` JSONB. design.md §3.1 (line 163-166) inline comment says "the overtime_handling enum from Phase 2 (organisations.overtime_handling text column) stays where it is — typed at the column level, not nested" — typed column.

**Reality:** the Phase 2 internal-alignment audit (`staff-management-p2/gap-analysis.md` P2-N5) settled this as a **typed column on `organisations`** (`organisations.overtime_handling text NOT NULL DEFAULT 'pay_cash'` with CHECK constraint). The Phase 4 audit's N5 fix layered on top: P4 reads via a `_org_setting('overtime_handling', ...)` helper that tries the typed column first, then falls back to JSONB — exactly to handle this kind of cross-phase ambiguity.

P3 design.md is correct; P3 requirements.md and tasks.md are stale, pointing at a "Phase 2 code-verification §2.5 should-fix" recommendation that the Phase 2 audit explicitly REJECTED in favour of the typed column.

**Fix applied:**
- requirements.md R6a.2 — rewrote to point at the typed column: "THE SYSTEM SHALL re-use Phase 2's `organisations.overtime_handling` typed text column (`pay_cash | toil | employee_chooses`, default `pay_cash`, CHECK enum). Phase 3 reads it directly via `org.overtime_handling` (or `(await db.get(Organisation, org_id)).overtime_handling`). Phase 2's gap-analysis P2-N5 settled this as a typed column on `organisations`, not a JSONB key. Phase 3 does NOT duplicate this — and does NOT use `get_org_settings()` for this particular field."
- tasks.md A1 "Phase 2 prerequisite" bullet — rewrote: "**Phase 2 prerequisite (P2-N5):** `organisations.overtime_handling` typed text column with CHECK enum `IN ('pay_cash','toil','employee_chooses')` and default `'pay_cash'`. Phase 3 reads it directly via the ORM."
- tasks.md B5 description — replaced `get_org_settings(...).get('overtime_handling', 'pay_cash')` with a direct ORM read. The Phase 2 audit's typed-column resolution makes the fallback unnecessary.

### P3-N5. R5.4 says "before/after JSON" but `audit_log` columns are `before_value` / `after_value`

**Where it bites:** requirements.md R5.4: "Every manual edit writes `audit_logs` action='time_clock.edited' with before/after JSON."

**Reality:** the `audit_log` table columns (verified at `app/core/audit.py:35-47`) are `before_value` and `after_value` (singular, JSONB). The spec's "before/after JSON" phrasing is informal but a future implementer could try writing to nonexistent columns named `before` and `after`.

**Fix applied:**
- requirements.md R5.4 — rewrote: "Every manual edit writes an `audit_log` row with `action='time_clock.edited'`, `before_value` capturing the pre-edit ORM dict, `after_value` capturing post-edit values."

### P3-N6. R8.4 references "approved-week" lock but the canonical lock target is `time_clock_entries`

**Where it bites:** requirements.md R8.4 ("WHEN admin THE SYSTEM SHALL render an "Approve hours" button at the week-end (visible Sunday onward).") and R9.3 (the actual locking spec) plus R9.5 (edit-after-approval flip).

**Reality:** R9.3 is correctly scoped to `time_clock_entries` only (G7 fix). But R9.5 ("WHEN any underlying time_clock_entries row is edited (admin manual flow) AFTER approval THE SYSTEM SHALL flip status to `'edited_after_approval'`") doesn't reference any other tables — fine. The wording is internally consistent; not a real bug, but worth noting that the spec previously had R9.3 referring to "time_entries locking" which has been correctly scrubbed.

**Fix applied:** none needed — verified consistency. Logged here only because earlier drafts of the spec had the broader lock scope; the current text is correct after G7 was applied.

### P3-N7. `find_in_window_shift` in design.md §4.7 references `entry.status != 'cancelled'` — but `ScheduleEntry.status` enum is `'scheduled'|'completed'|'cancelled'`

**Where it bites:** design.md §4.7 helper.

**Reality:** the helper filter `ScheduleEntry.status != 'cancelled'` is correct in spirit but expressing it as a positive set (`status IN ('scheduled','completed')`) matches the codebase's established convention. Verified at `app/modules/scheduling_v2/models.py:21`: `ENTRY_STATUSES = ["scheduled", "completed", "cancelled"]`. Negative filtering is fine but a future state addition would silently include the new state.

**Fix applied:**
- design.md §4.7 `find_in_window_shift` filter — rewrote `ScheduleEntry.status != 'cancelled'` → `ScheduleEntry.status.in_(['scheduled', 'completed'])`. Future state additions then explicitly opt-in.

### P3-N8. Eligibility filter G6 in `cover.py` doesn't define what "skills_overlap" means when shift has no required skills

**Where it bites:** requirements.md R13.2 step 4 ("skills overlap when the shift has any required skills (else step is a no-op — all otherwise-eligible staff get the SMS)") and tasks.md B6 cover bullet ("`skills_overlap`").

**Reality:** the shift's "required skills" need a concrete source. The existing `schedule_entries` model (verified) has no `required_skills` column. The `staff_members.skills` JSONB list exists from Phase 1. Without a per-shift requirement, the filter is a no-op — which the spec acknowledges. But a future implementer might add a `required_skills` column to `schedule_entries` and the filter wouldn't know.

**Fix applied:**
- requirements.md R13.2 step 4 — clarified: "skills overlap is keyed off `schedule_entries.required_skills` (JSONB array, NOT YET PRESENT in the schema — added if/when shift-skill-tagging ships in a later phase). For Phase 3, since no such column exists, this step is currently a NO-OP and ALL otherwise-eligible staff receive the broadcast SMS. The filter is included so a future schema addition flips it on without code changes."
- tasks.md B6 cover bullet — same clarification.
- design.md does not need a change here; the helper is already documented as "skills_overlap" in the abstract.

### P3-N9. `_check_kiosk_rate_limit` interaction with the new G12 lookup-rate-limit is unclear

**Where it bites:** requirements.md R3.3 says "This is on TOP OF the existing `_check_kiosk_rate_limit` (30/min/kiosk-user) — both apply." design.md §1 architecture says staff clock routes use the same `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]` pattern.

**Reality:** verified — the existing `_check_kiosk_rate_limit` lives at `app/modules/kiosk/router.py:52` and is keyed by user_id (the kiosk JWT's subject). The new G12 lookup-specific limit is keyed by `(org_id, sha256(employee_id))`. Both apply. The spec is correct, but neither doc spells out: what HTTP code does each return, and which one fires first?

The dependency-style `_check_kiosk_rate_limit` runs BEFORE the route body (FastAPI dependency order), so it would return its 429 first if the kiosk JWT is hammering the kiosk endpoints generally. The inline G12 check runs AFTER, and only fires when the same employee_id is being enumerated repeatedly. The two responses are different bodies (`{"detail":"Too many requests"}` vs `{"detail":"kiosk_lookup_rate_limited"}`).

**Fix applied:**
- requirements.md R3.3 — added a clarifying note: "The two limiters layer cleanly: `_check_kiosk_rate_limit` runs as a FastAPI dependency BEFORE the route body and rejects with `{"detail":"Too many requests"}` when the kiosk-user is over the global 30/min budget. The G12 inline check runs INSIDE the route body and rejects with `{"detail":"kiosk_lookup_rate_limited"}` when a specific `(org_id, employee_id)` pair has been queried > 10 times in the last 60s. A real attacker hitting the kiosk endpoint trips the global limit first; a buggy retry loop on a single `employee_id` trips G12 second."
- design.md §4.1 service signature `lookup_for_kiosk` — added inline comment: "Two-layer rate limit: dependency-level `_check_kiosk_rate_limit` (30/min/kiosk-user) runs before service body; inline G12 check (10/min/employee_id, hashed) runs at top of service. Distinct 429 bodies per R3.3."

### P3-N10. `entry.status != 'cancelled'` in §4.6 hook — same issue as P3-N7

**Where it bites:** design.md §4.6 `_emit_roster_change_sms` doesn't filter by `entry.status`. If a schedule_entry is cancelled and then "uncancelled" via re-edit (a separate edge case), the hook fires a "your shift changed" SMS for an entry that just got revived.

**Reality:** the realistic path is: admin sets `status='cancelled'` (entry "deletion") → admin edits start_time on an `cancelled` entry (rare, typically irrelevant) → roster-change SMS fires. The spec doesn't address whether a cancelled entry should still trigger the hook.

**Fix applied:**
- design.md §4.6 `_emit_roster_change_sms` — added: "Skip the hook when `entry_after.status == 'cancelled'` — a cancelled-then-edited entry is effectively dead and SMS-ing the staff would be misleading. The skip writes audit row `roster.change_sms_skipped` with `reason='cancelled_entry'`."
- tasks.md B7a verify — added: "edit a `cancelled` schedule_entry → no SMS sent; audit row `roster.change_sms_skipped` reason=`cancelled_entry`."

### P3-N11. R14a (G2) reschedule-method drift mentions `reschedule_entry` then immediately corrects to `reschedule`

**Where it bites:** design.md §4.6 ("`reschedule` — note real method is named `reschedule` not `reschedule_entry`, verified at `service.py:215`") plus tasks.md B7a ("note: real method is `reschedule`, NOT `reschedule_entry`, verified at `service.py:215`").

**Reality:** verified at `app/modules/scheduling_v2/service.py:215`: `async def reschedule(...)` — confirmed. The spec correctly identifies the method name. This is internally consistent — no fix needed, but worth noting that R14a in requirements.md doesn't repeat the verification (only mentions `update_entry`, `reschedule_entry`, swap acceptance, cover acceptance — and `reschedule_entry` is wrong).

**Fix applied:**
- requirements.md R14a.1 — fixed `reschedule_entry` → `reschedule` to match design.md §4.6 and tasks.md B7a. Verified at `app/modules/scheduling_v2/service.py:215`.

### P3-N12. SLOs §9.1 reference `POST /uploads` for photo upload but the new endpoint is `POST /api/v2/uploads/clock-photos`

**Where it bites:** design.md §9.1 SLO table notes ("Photo upload is async (frontend POSTs to `/uploads` first, then passes `photo_upload_id`)").

**Reality:** the new dedicated upload endpoint is `POST /api/v2/uploads/clock-photos` per design.md §1, requirements.md R3.5, and tasks.md B9. The SLO note's `/uploads` is a vestige.

**Fix applied:**
- design.md §9.1 SLO note — rewrote to use the canonical endpoint: "Photo upload is async — frontend POSTs to `/api/v2/uploads/clock-photos` first, gets `file_key`, then passes it to clock-action as `photo_file_key` (P3-N1 + P3-N12 unification). Clock-action request only does DB writes + scheduled-entry match + Redis ops."

---

## ALSO VERIFIED (no fix needed)

These were checked and are consistent across the three docs and against the codebase:

- ✅ Existing kiosk router pattern at `app/modules/kiosk/router.py:108` uses `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]` — Phase 3's claim verified.
- ✅ `app/modules/scheduling_v2/service.py::reschedule` exists at line 215 (the spec correctly identifies the name).
- ✅ `app/modules/scheduling_v2/service.py::update_entry` exists at line 159.
- ✅ `app/modules/time_tracking_v2/service.py:181-182` raises `ValueError("Cannot update an invoiced time entry")` when `is_invoiced=true` — G7 verified.
- ✅ `app/tasks/scheduled.py:849` defines `WRITE_TASKS: set[str]`; `_DAILY_TASKS` list at line 872; the spec's instructions to add new task names there are consistent with the file's actual structure.
- ✅ `app/modules/scheduling_v2/models.py:21` `ENTRY_STATUSES = ["scheduled", "completed", "cancelled"]` — used by P3-N7 fix.
- ✅ `app/core/audit.py::write_audit_log` accepts `before_value` and `after_value` JSONB kwargs — singular form.
- ✅ Latest migration before Phase 3 will be 0205 + 0206 (Phase 2). Phase 3 lands as 0207, 0208.
- ✅ G1 overtime split logic in §4.2 (designs.md) and R6a.4 (requirements.md) are consistent.
- ✅ G3 running-late helper (`find_in_window_shift`, `resolve_manager`) and rate limit (3/shift) consistent across requirements.md R14b and design.md §4.7.
- ✅ G6 cover broadcast eligibility filter rules consistent across requirements.md R13.2 and tasks.md B6 cover bullet.
- ✅ G8 + G13 swap workflow + notification matrix consistent across requirements.md R12.5 and design.md §4.8.
- ✅ G12 kiosk lookup rate-limit Redis key shape consistent across requirements.md R3.3 and tasks.md B9.
- ✅ G15 photo retention (no cleanup job in P3) consistent across Non-Goals + design §3.1.
- ✅ G17 per-branch vs org-default geofence radius resolution consistent across R6.4 and design.md §3.1.

---

## Summary of fixes applied

| # | Gap | File touched | Section |
|---|---|---|---|
| P3-N1 | `photo_upload_id` vs `photo_file_key` | requirements.md, design.md | R4.1, §4.1, §6.4, §7.1, §7.2, §9.1 |
| P3-N2 | `audit_logs` (plural) vs `audit_log` (singular) | requirements.md, design.md | R5.4, §7.1, §10, §11 |
| P3-N3 | G10 closure tag still mentions `metadata` | design.md, tasks.md | §12, G10 closure ticks |
| P3-N4 | `overtime_handling` JSONB vs typed column | requirements.md, tasks.md | R6a.2, A1, B5 |
| P3-N5 | "before/after JSON" → `before_value`/`after_value` | requirements.md | R5.4 |
| P3-N6 | (verified consistency only — no fix) | — | — |
| P3-N7 | `status != 'cancelled'` → `status.in_([...])` positive set | design.md | §4.7 |
| P3-N8 | `skills_overlap` source unclear | requirements.md, tasks.md | R13.2, B6 |
| P3-N9 | Two-layer rate limit interaction unclear | requirements.md, design.md | R3.3, §4.1 |
| P3-N10 | Cancelled-entry SMS hook edge | design.md, tasks.md | §4.6, B7a verify |
| P3-N11 | `reschedule_entry` typo in R14a | requirements.md | R14a.1 |
| P3-N12 | SLOs reference `/uploads` not `/api/v2/uploads/clock-photos` | design.md | §9.1 |

All fixes applied in this commit alongside this gap analysis.

## Recommendation

Phase 3 is structurally sound — the kiosk + self-service + approvals + swaps + cover surfaces are coherently specified, with G1-G17 closure tags all addressed in spirit. The 12 alignment gaps above are precision issues, mostly stragglers from earlier drafts (the `metadata`→`flags` rename and the `photo_upload_id`→`photo_file_key` rename both have leftover references). The most substantive fix is **P3-N4** — pinning `overtime_handling` to the typed column matching Phase 2's resolved P2-N5 fix, ensuring P3 reads the value Phase 2 actually writes.

The G1-G17 closure tags from prior reviews remain valid. The 12 P3-N# tags layered on top are the new findings from this internal-consistency audit.
