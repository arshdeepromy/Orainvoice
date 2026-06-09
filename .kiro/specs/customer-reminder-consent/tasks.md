# Customer Reminder Consent — Tasks

Each task is independently mergeable, has a `**Verify:**` line per `implementation-completeness-checklist.md`, and references back to a requirement.

## Execution policy

- **Scoped tests only.** Every `**Verify:**` block runs only the tests that exercise the files this spec touches — never the full repo suite. Pytest paths are explicit (e.g. `tests/property/test_consent_persistence_integrity.py`); vitest paths are explicit (e.g. `frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.default.test.tsx`). Do NOT use `pytest tests/unit/ -k '...'` style filters that scan every test file before excluding — pass the file paths directly.
- **Backend tests run inside the app container** per `.kiro/steering/windows-shell-and-docker.md`. The canonical command is:
  ```
  docker compose -p invoicing exec -T app python -m pytest <path> -v
  ```
  Every backend `**Verify:**` block in this tasks.md is written using `pytest <path> -v` for brevity; when actually executing, prefix with `docker compose -p invoicing exec -T app python -m` so the test runs inside the same container the app uses (same Python interpreter, same DB connection, same RLS context).
- **Frontend tests run from `frontend-v2/`.** Vitest: `npx vitest run <path> --run`. TypeScript: `npx tsc --noEmit -p tsconfig.json`. Do NOT touch the archived `frontend/` tree (see `frontend/ARCHIVED.md`).
- **No watchers.** Use `pytest`, `npx vitest run`, `npx tsc --noEmit`. Never `--watch` flags or dev-server commands.
- **No interactive prompts.** Every CLI uses `--yes` / `-y` / `--non-interactive` where applicable.
- **No git push, no PR creation, no deploy.** Per the user's explicit instruction, this spec must NOT push branches or open PRs. Phase J3 is local-only; the `git push`/`gh pr create` steps that normally close out a release are deliberately omitted.
- **Failure handling.** Log the failure detail to a `gap-analysis.md` adjacent to this `tasks.md` AND open an `ISSUE-XXX` row in `docs/ISSUE_TRACKER.md` per `.kiro/steering/issue-tracking-workflow.md`, mark the task `[~]`, continue with the next non-dependent task. Stop only after 3 consecutive failures on the same root cause.
- **Project conventions.**
  - `{ items, total }` list shape on every list response (NFR-2, `safe-api-consumption.md`).
  - `?.` + `?? []` / `?? 0` on every frontend API field read (NFR-1, `safe-api-consumption.md`).
  - Typed generics on every `apiClient.get<T>(...)` / `.post<T>(...)` call. No `as any` to bypass typing (NFR-1).
  - AbortController cleanup on every `useEffect` that issues an API call.
  - **Inside `session.begin()` (which `get_db_session` already enters): never call `db.commit()` or `db.rollback()`.** Use `await db.flush()` then `await db.refresh(obj)` and let the context manager handle commit/rollback. This is `.kiro/steering/performance-and-resilience.md` Rule 1; violating it has caused ISSUE-024, ISSUE-040, ISSUE-044 in the past.
  - Audit table is `audit_log` (singular). Use `app.core.audit.write_audit_log`.
  - All consent-related audit `after_value` payloads are stripped of `ip_address`, `user_agent`, `recorded_by_user_id`, `recorded_by_user_email` (Req 7.1 / 7.2 / NFR-5). Lint-enforced by H4.
- **No Alembic migration.** Per Out-of-Scope item 1 of the requirements, the consent record is JSONB-only inside `customer.custom_fields`. Do not create or modify migrations.
- **No mobile changes in this spec.** The `mobile/` package is web-only-touched: J1 bumps its `package.json` `version` for lockstep parity, but no mobile feature code is added (per `.kiro/steering/mobile-app.md` — the mobile customer profile does NOT receive the consent section in v1; defer to a future Phase 2).
- **Trade-family universality.** Every UI surface added by this spec is rendered for every `tradeFamily` value (NFR-6). The kiosk consent step uses `useTenant().tradeFamily` to hide WOF/COF/registration sub-checkboxes for non-vehicle trades and show only `service_due` (Req 1.5e). The Customer Profile section and the Configure Reminders modal are rendered universally — they are gated by the customers module, never by trade family.

## Code-truth audit (assumptions verified against actual code)

The tasks below have been audited against the live backend, frontend-v2, models, and steering docs. The following code-truth findings shaped the task list and are surfaced inline within each affected task:

| # | Finding | Where | Closed by |
|---|---|---|---|
| 1 | `VALID_REMINDER_TYPES = {"service_due", "wof_expiry"}` — only 2 of the 4 categories are accepted by the validator. | `app/modules/customers/service.py:1894` | A0 |
| 2 | `update_customer_reminder_config` signature today is `(db, *, org_id, customer_id, reminders)`. New kwargs (`consent_record`, `current_user`, `ip_address`, `user_agent`) must be added without breaking existing callers. | `app/modules/customers/service.py:1979` | A4 |
| 3 | `get_customer_reminder_config` only seeds default entries for `service_due` + `wof_expiry`. | `app/modules/customers/service.py:1928` | A0 |
| 4 | `audit_log` table has a dedicated `device_info` column — the canonical home for the `User-Agent` string. Do not put `user_agent` into `after_value`; pass it as `device_info=` to `write_audit_log`. | `app/core/audit.py:79–98` | A2 |
| 5 | `request.headers["user-agent"]` raises `KeyError` if absent. Use `request.headers.get("user-agent", "")[:500]`. | Starlette behaviour | A2 / B1 / C3 |
| 6 | Existing `PUT /customers/{id}/reminders` uses `body = await request.json()` (raw dict, no Pydantic body model). The new `consent_record` is added by reading from this raw dict — not by introducing a body schema. | `app/modules/customers/router.py:1327` | B1 |
| 7 | The existing `PUT /reminders` endpoint has NO `dependencies=[require_role(...)]` — RBAC is module-level. The new `POST /reminders/revoke` should mirror the customer-write RBAC: `dependencies=[require_role("org_admin", "salesperson")]`. | `app/modules/customers/router.py:1327, 601` | B2 |
| 8 | Every existing kiosk route uses `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]`. The new `GET /kiosk/consent-text` MUST follow the same pattern (not "no auth" as earlier-draft tasks suggested). | `app/modules/kiosk/router.py:115–119` | C1 |
| 9 | Kiosk router `_extract_org_context(request)` already returns `ip_address` from `request.state.client_ip`. `kiosk_check_in_v2` already accepts `ip_address` as a kwarg. Wiring is half-done; only `user_agent` needs to be added to the kwarg list and threaded from the `check_in` handler. | `app/modules/kiosk/router.py:47, 121, 143` and `app/modules/kiosk/service.py:444–451` | C3 |
| 10 | The legacy v1 `kiosk_check_in` (line 435) calls `await db.commit()`. The v2 `kiosk_check_in_v2` (line 444+) correctly does NOT — it relies on `get_db_session`'s `session.begin()`. C3 must NOT introduce `db.commit()` into v2. | `app/modules/kiosk/service.py:435 vs 690` | C3 |
| 11 | Existing `enqueue_customer_reminders` uses `today = now.date()` (UTC). Spec needs org-local today. Validity-window skip must be added BEFORE the existing `expiry_date != target_date` exact-day match, not in place of it. | `app/modules/notifications/reminder_queue_service.py:60–61, 240–262` | D1 |
| 12 | Organisation timezone is a TOP-LEVEL column on `organisations.timezone` (default `'UTC'`, server_default), NOT inside `organisations.settings` JSONB. `Branch.timezone` exists too (default `'Pacific/Auckland'`) — the spec uses the org-level column, since reminders are org-scoped. | `app/modules/admin/models.py:137` and `app/modules/organisations/models.py:50` | D2 |
| 13 | `enqueue_customer_reminders.REMINDER_TYPE_MAP` already maps all four categories — only the validator (gap #1) is behind. No work needed in the enqueue mapping table. | `app/modules/notifications/reminder_queue_service.py:154–179` | n/a (already aligned) |
| 14 | Frontend `CustomerReminderConfig` interface has `service_due`, `wof_expiry`, `cof_expiry` but is MISSING `registration_expiry`. The Configure Reminders modal in both `CustomerProfile.tsx` and `CustomerList.tsx` only renders three toggle rows. | `frontend-v2/src/pages/customers/CustomerProfile.tsx:158–164` and `CustomerList.tsx:85` | F0 |
| 15 | The "Configure Reminders modal" exists today as INLINE markup inside `CustomerProfile.tsx` (~line 1218) and `CustomerList.tsx` (~line 506) — there is NO standalone `ConfigureRemindersModal.tsx` file. F2/F3/F4 edit these inline modals in place. | `frontend-v2/src/pages/customers/CustomerProfile.tsx:1218`, `CustomerList.tsx:506` | F2 |
| 16 | `CustomerProfileResponse.custom_fields` is `Optional[dict] = Field(default_factory=dict)` — free-form. The new `reminder_consent` and `reminder_consent_revocations` keys round-trip through Pydantic without any schema change. (Pydantic Rule 8 still applies if anyone tightens the type later.) | `app/modules/customers/schemas.py:499` | F2 |
| 17 | `customers_router` is mounted at `/api/v1/customers` AND `/api/v2/customers` in `app/main.py`. New routes added by B2 inherit both prefixes automatically. Same for `kiosk_router` (only v1). No `app.main` edits required. | `app/main.py:330, 365, 409` | F9 |
| 18 | `OrgVehicle` and `GlobalVehicle` both have `inspection_type: Mapped[str \| None]` (`'wof'`, `'cof'`, or null) plus `wof_expiry`, `cof_expiry`, `registration_expiry`, `service_due_date`. Per-vehicle row resolution rule (Req 1.5a–5e) maps cleanly onto these columns. | `app/modules/vehicles/models.py:57–62` and `app/modules/admin/models.py:238–243` | E1 / E3 |
| 19 | `frontend-v2/src/contexts/TenantContext.tsx` exposes `tradeFamily: string \| null` (read from `data.trade_family`). The spec's `useTenant().tradeFamily` reference is correct. | `frontend-v2/src/contexts/TenantContext.tsx:57, 159` | E1 |
| 20 | Kiosk v2 schema vehicle entry (`KioskVehicleEntry`) only carries `global_vehicle_id` + `odometer_km`. The kiosk frontend already has the `inspection_type` / `wof_expiry` / `cof_expiry` data via the prior `vehicle-lookup` step's response (line 92–94 of `app/modules/kiosk/schemas.py` shows these exist on `KioskVehicleLookupResponse`). The frontend has the data it needs to drive the consent step without a backend schema change. | `app/modules/kiosk/schemas.py:90–95, 142+` | E1 / E3 |

## Phase A — Backend foundation

- [x] **A0. Extend `VALID_REMINDER_TYPES` to cover all four categories**
  - **Code-truth gap:** `app/modules/customers/service.py` line 1894 currently has `VALID_REMINDER_TYPES = {"service_due", "wof_expiry"}`. The spec needs all four: `service_due`, `wof_expiry`, `cof_expiry`, `registration_expiry`. The downstream `enqueue_customer_reminders` already maps all four (`reminder_queue_service.py::REMINDER_TYPE_MAP`) — only the validator is behind.
  - Edit `VALID_REMINDER_TYPES` to `{"service_due", "wof_expiry", "cof_expiry", "registration_expiry"}`.
  - In `get_customer_reminder_config`, ensure the returned dict default-includes entries for all four categories (currently only `service_due` and `wof_expiry` are seeded). Use `_default_reminder_entry()` for the new keys.
  - **Files:** `app/modules/customers/service.py` (edit `VALID_REMINDER_TYPES` and `get_customer_reminder_config`).
  - **Refs:** Requirements 1.1, 2.1, 4.2 (this prerequisite is what lets the rest of Phase A reference all four categories without surprise).
  - **Verify:** `pytest tests/integration/test_customer_reminders_consent_gate.py::test_all_four_categories_validate -v` passes — covers each of the four categories accepted by `update_customer_reminder_config`.

- [x] **A1. Create `app/modules/customers/consent_text.py`**
  - Module-level constants `KIOSK_CONSENT_TEXT_VERSION = "2026-06-08-v1"` and `KIOSK_CONSENT_TEXT` (multi-line string with the legally-reviewed wording, including a `{workshop_name}` placeholder).
  - Module docstring explaining the version-update rule (bump on substance change; `{workshop_name}` substitution does not bump the version).
  - **Files:** `app/modules/customers/consent_text.py` (new).
  - **Refs:** Requirements 6.1, 6.2, 6.3.
  - **Verify:** `pytest tests/unit/test_consent_text_constant.py -v` passes — asserts the version string is non-empty, the text contains the three required substrings (categories, revoke-by-phone, withdraw-without-penalty), and `{workshop_name}` placeholder is present.

- [x] **A2. Create `app/modules/customers/consent.py`**
  - Pydantic v2 models `RemindersConsentEntry`, `RemindersConsentRecord`, `RemindersRevocationRecord` (literal types match the design §3.1 tables).
  - Pure helpers `coverage_for(consent: dict | None) -> set[tuple[str, str]]`, `compute_missing_consent(existing_consent, new_config) -> list[dict]`, `union_channel_for_category(entries, category) -> Literal["sms","email","both"]`, `current_consent_text() -> tuple[str, str]`.
  - Side-effecting helpers `record_consent_given(...)` and `record_consent_revoked(...)` per the side-effect summary in design §3.1. Both call `await db.flush()` then `await db.refresh(customer)` then `await write_audit_log(...)` with the `after_value` dict redacted as specified (no `ip_address`/`user_agent` for `.given`, no `recorded_by_user_id`/`recorded_by_user_email` for `.revoked`).
  - Use `app.core.audit.write_audit_log` with `entity_type="customer"`, `entity_id=customer.id`, `action="customer.reminder_consent.given"` or `"customer.reminder_consent.revoked"`.
  - **Code-truth note:** `app/core/audit.py::write_audit_log` accepts a separate `device_info` kwarg (column `audit_log.device_info`) which is the canonical home for the `User-Agent` string. Pass `device_info=user_agent` directly to `write_audit_log` (DO NOT include `user_agent` in `after_value`). The full `ip_address` AND `user_agent` are still preserved on the customer record per Req 7.3.
  - **Code-truth note:** `request.headers["user-agent"]` raises `KeyError` if the header is absent. Use `request.headers.get("user-agent", "")[:500]` everywhere — defensive, truncated to 500 chars per design §3.1.
  - **Files:** `app/modules/customers/consent.py` (new).
  - **Refs:** Requirements 1.13, 1.14, 1.17, 2.2, 2.7, 2.9, 3.4, 3.7, 6.4, 7.1, 7.2, 7.3.
  - **Verify:** `pytest tests/unit/test_consent_helpers.py -v` passes — covers `coverage_for` with both-channel expansion, `compute_missing_consent` with covered/uncovered/already-enabled cases, `union_channel_for_category` for single, mixed, and both-explicit cases, and `current_consent_text` returns the version from `consent_text.py`.

- [x] **A3. Create `app/modules/customers/exceptions.py` with the new exception types**
  - `RemindersConsentRequiredError(missing: list[dict])` — payload is the still-missing `(category, channel)` pairs. Each dict in `missing` SHALL have exactly two keys: `"category"` (one of `"service_due"`, `"wof_expiry"`, `"cof_expiry"`, `"registration_expiry"`) and `"channel"` (one of `"sms"`, `"email"`). Note: `"both"` is expanded into two entries (`(cat, "sms")` AND `(cat, "email")`) by `coverage_for` so the missing list never carries `"both"` directly. This shape is the wire contract for the 409 body in B1.
  - `RemindersRevocationError` — raised when revocation references a non-active pair (mapped to HTTP 422 by the router).
  - **Files:** `app/modules/customers/exceptions.py` (new).
  - **Refs:** Requirements 2.12, 2.13, 3 (revocation guard).
  - **Verify:** `pytest tests/unit/test_consent_helpers.py::test_consent_required_error_carries_missing -v` passes — asserts `RemindersConsentRequiredError(missing=[{"category": "wof_expiry", "channel": "sms"}]).missing` round-trips to the same list with both keys present.

- [x] **A4. Extend `update_customer_reminder_config` for the gate + transactional persistence**
  - **Code-truth gap:** existing signature at `app/modules/customers/service.py` line 1979 is `async def update_customer_reminder_config(db, *, org_id, customer_id, reminders) -> dict`. This task EDITS this function in place — does not add a new function.
  - New kwargs `consent_record: RemindersConsentRecord | None = None`, `current_user: Any = None`, `ip_address: str | None = None`, `user_agent: str | None = None`. All four are keyword-only and default to `None` for backwards compatibility (existing callers — including the legacy `PUT /reminders` body — still work).
  - Body: snapshot existing consent (`customer.custom_fields.get("reminder_consent")`) + config; validate new config (existing `for rtype in VALID_REMINDER_TYPES` loop, now ranging over all four after A0); compute `missing = compute_missing_consent(existing_consent, validated)`; if `missing` is non-empty AND `consent_record is None` raise `RemindersConsentRequiredError(missing=missing)`; if `consent_record` is supplied, validate coverage and raise the same error with still-missing pairs if not covered; call `record_consent_given(...)` first (it does its own `db.flush() + db.refresh()`), then persist `validated` config (existing flush/refresh path is preserved at lines 2020–2021).
  - **Transaction discipline (per `.kiro/steering/performance-and-resilience.md` Rule 1):** This service runs inside `get_db_session`'s `session.begin()` block (`app/core/database.py` lines 172–176). Use `await db.flush()` to push pending writes and `await db.refresh(customer)` before returning. Do NOT call `db.commit()` or `db.rollback()` here — the context manager handles them. Past regressions (ISSUE-024, ISSUE-040, ISSUE-044) all came from violating this rule.
  - **Files:** `app/modules/customers/service.py` (edit existing function — no new function).
  - **Refs:** Requirements 2.2, 2.3, 2.7, 2.8, 2.10, 2.11, 2.12, 2.13.
  - **Verify:** `pytest tests/integration/test_customer_reminders_consent_gate.py -v` passes — covers the no-consent → 409, with-consent → 200, idempotent re-submit, and already-enabled-no-gate cases.

- [x] **A5. Add `revoke_customer_reminders` service function**
  - New function in `app/modules/customers/service.py` (sibling to `update_customer_reminder_config`).
  - Loads customer (same `select(Customer).where(Customer.id == customer_id, Customer.org_id == org_id)` pattern), validates each `category` in `record.categories_affected` is currently `enabled: true` in `custom_fields["reminder_config"]` (early-return with unchanged config if all already disabled — CP-5), delegates to `record_consent_revoked` (which does `flush + refresh + audit`), returns the post-state `reminder_config`.
  - **Source string composition (Req 3.4):** the `source` field on the `RemindersRevocationRecord` SHALL be composed by the router (B2) as `f"manually_recorded_by_staff:{obtained_method}"` where `obtained_method` is the validated value from the `RemindersRevokeRequest` body. The service receives the already-composed `RemindersRevocationRecord` so the composition lives in B2 — A5 simply trusts the record's `source` field. Mirror the same pattern for `record_consent_given` in A2: the manual-edit path (F4 → B1) composes `f"manually_recorded_by_staff:{obtained_method}"`; the kiosk path (C3) sets `source = "kiosk_self_checkin"`.
  - **Failure / rollback (Req 3.6):** if `record_consent_revoked` raises (audit insert fails, JSONB write fails, or any other DB error), the surrounding `session.begin()` rolls back the entire request — neither the `reminder_config` flip nor the revocation append is persisted. The router (B2) maps the exception to `JSONResponse(500, {"error": "revocation_persistence_failed"})`. H3 covers the failure-injection test.
  - **Working-day SLA (Req 3.8 / NFR-7):** the revocation is applied synchronously inside the same HTTP request (no queue, no deferred job), so the same-Working-Day deadline is satisfied trivially. Add a one-line code comment on the function explaining this; no test needed since synchronous-write completion is covered by H3.
  - **Transaction discipline:** Same rule as A4 — `await db.flush()` then `await db.refresh(customer)`; no manual `db.commit()` / `db.rollback()`.
  - **Files:** `app/modules/customers/service.py` (edit — add new function).
  - **Refs:** Requirements 3.4, 3.5, 3.6, 3.8, 3.9, NFR-7.
  - **Verify:** `pytest tests/integration/test_customer_reminders_revoke.py -v` passes — covers single-category revoke, multi-category revoke, idempotent re-confirm, audit-row redaction, AND the new failure-injection rollback case (H3 expanded).

## Phase B — Customer router + endpoints

- [x] **B1. Extend `PUT /customers/{customer_id}/reminders` to accept `consent_record` and map exception**
  - **Code-truth gap:** the existing endpoint at `app/modules/customers/router.py` line 1327 uses `body = await request.json()` (no Pydantic body schema) and calls `update_customer_reminder_config(db, org_id=org_uuid, customer_id=cust_uuid, reminders=body)`. This task EDITS that existing handler in place — it does not introduce a new Pydantic body model. The pop-out is: read `consent_record` from `body` (the raw dict), validate with `RemindersConsentRecord.model_validate(...)` only when present, and pass through as the new kwarg. Everything else in `body` (the per-category dict) becomes `reminders=` exactly like today.
  - Catch `RemindersConsentRequiredError` and return `JSONResponse(status_code=409, content={"error": "consent_required", "missing": exc.missing})`.
  - Keep the existing `except ValueError` → `404` mapping for "Customer not found".
  - Wrap unexpected DB errors in a generic `500 {"error": "consent_persistence_failed"}` response.
  - **`ip_address` + `user_agent` plumbing:** the existing `_extract_org_context(request)` helper at line 47 already returns `ip_address` from `request.state.client_ip`. Pass it as the new `ip_address=` kwarg. For `user_agent`, use `request.headers.get("user-agent", "")[:500]` (Starlette returns `None` if absent — guard with `or ""`).
  - **Transaction discipline:** The `get_db_session` dependency wraps the request in `session.begin()`. Do NOT add `await db.commit()` / `await db.rollback()` in the router — the context manager handles them. (Same rule as A4/A5.)
  - **Files:** `app/modules/customers/router.py` (edit `update_customer_reminders_endpoint`).
  - **Refs:** Requirements 2.12, 2.13, 1.16, 2.8.
  - **Verify:** `pytest tests/integration/test_customer_reminders_consent_gate.py::test_put_returns_409_with_missing_list -v` and `::test_put_with_consent_record_persists_both -v` pass.

- [x] **B2. New endpoint `POST /customers/{customer_id}/reminders/revoke`**
  - New Pydantic body schema `RemindersRevokeRequest` (in `app/modules/customers/schemas.py`) with `obtained_method: Literal["phone","in_person","email_reply","other"]`, `channel: Literal["sms","email","both"]`, `categories_affected: list[Literal["service_due","wof_expiry","cof_expiry","registration_expiry"]]`, `reason_note: str = Field(min_length=1)`.
  - Route handler builds a `RemindersRevocationRecord` (from `app/modules/customers/consent.py`) and calls `revoke_customer_reminders`. Returns the new `reminder_config` on success.
  - **Code-truth note:** the existing `update_customer_reminders_endpoint` does NOT have a `dependencies=[require_role(...)]` decorator — RBAC is enforced module-level at the customers router include. The new endpoint should follow the same pattern (no per-route `require_role`); if any cross-cutting `require_role` is needed it has to match the existing customer write endpoints — e.g., `dependencies=[require_role("org_admin", "salesperson")]` matching `PUT /{customer_id}` (line 601). Add this dependency on the new revoke route to mirror the write-path RBAC.
  - **Files:** `app/modules/customers/router.py` (edit), `app/modules/customers/schemas.py` (add `RemindersRevokeRequest`).
  - **Refs:** Requirements 3.2, 3.4, 3.5.
  - **Verify:** `pytest tests/integration/test_customer_reminders_revoke.py::test_revoke_endpoint_persists_and_audits -v` passes.

## Phase C — Kiosk integration

- [x] **C1. New endpoint `GET /kiosk/consent-text`**
  - Returns `{"text": <text>, "version": <version>}` from `current_consent_text()`. No DB access.
  - **Code-truth note:** every existing kiosk route (`POST /check-in`, `POST /vehicle-lookup`, `GET /customer-lookup`) uses `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]` (`app/modules/kiosk/router.py` lines 115–119). The new `GET /kiosk/consent-text` MUST follow the same pattern to inherit RBAC + rate limit. The endpoint serves a compile-time constant so the rate-limit cost is trivial; the role gate keeps the kiosk surface uniform.
  - **Workshop name interpolation:** `KIOSK_CONSENT_TEXT` carries a `{workshop_name}` placeholder. The endpoint resolves the org name from `request.state.org_id` via the existing organisations service (`get_org_settings`) and substitutes it server-side before returning. The frontend never sees the placeholder.
  - **Files:** `app/modules/kiosk/router.py` (edit).
  - **Refs:** Requirement 6.3.
  - **Verify:** `pytest tests/smoke/test_kiosk_consent_text_endpoint.py -v` passes — single example assertion that returns `{text, version}` with the workshop name substituted.

- [x] **C2. Extend `KioskCheckInRequestV2` with `reminder_consent` field**
  - **Code-truth note:** existing schema is at `app/modules/kiosk/schemas.py` line 142. It uses Pydantic v2 `BaseModel` + `field_validator`. Match the same conventions.
  - New schema `KioskReminderConsentBlock` (in the same file) with `entries: list[RemindersConsentEntry]` and `consent_text_version: str`. Import `RemindersConsentEntry` from `app.modules.customers.consent`.
  - Add optional `reminder_consent: KioskReminderConsentBlock | None = None` field on `KioskCheckInRequestV2`.
  - Add `consent_provided(self) -> bool` convenience method (returns `self.reminder_consent is not None and len(self.reminder_consent.entries) > 0`).
  - **Files:** `app/modules/kiosk/schemas.py` (edit).
  - **Refs:** Requirements 1.13, 1.14, 6.3.
  - **Verify:** `pytest tests/unit/test_kiosk_schemas_consent.py -v` passes — round-trips a sample body with the new field set and unset.

- [x] **C3. Wire kiosk check-in service to call `update_customer_reminder_config` in the same transaction**
  - **Code-truth gap:** existing `kiosk_check_in_v2` at `app/modules/kiosk/service.py` line 444 already accepts `ip_address: str | None = None` as a kwarg (line 451). The router at line 143 already passes it (`kiosk_check_in_v2(db, ..., ip_address=ip_address)`). For `user_agent`, extend the kwarg list to also take `user_agent: str | None = None` and have the router pass `request.headers.get("user-agent", "")[:500]` from the existing `check_in` handler (line 121).
  - In `kiosk_check_in_v2`, after the customer is resolved/created and vehicles have been linked (existing flush at line 690), when `data.consent_provided()` is True: build a `RemindersConsentRecord` (with `ip_address` from the kwarg, `user_agent` from the kwarg, `kiosk_session_id` from a fresh `uuid4()`, `source = "kiosk_self_checkin"`, `consent_text_version` from `record.consent_text_version` carried in by `data.reminder_consent`).
  - **`days_before` resolution (Req 1.14):** for each category present in `data.reminder_consent.entries`, derive the `days_before` value as: (a) the existing `customer.custom_fields["reminder_config"][category]["days_before"]` if present and `> 0`, else (b) `DEFAULT_REMINDER_DAYS = 30` (`app/modules/customers/service.py` line 1891). The kiosk does not expose a `days_before` selector to the customer; it reuses the org's existing default or the customer's last-saved value. The `channel` per category is computed by `union_channel_for_category(entries, category)` (per Req 1.14 union rule). Build the `reminders` dict as `{cat: {"enabled": True, "channel": <union>, "days_before": <resolved>}}` for every distinct category in `entries`.
  - Call `update_customer_reminder_config(db, org_id=org_id, customer_id=customer.id, reminders=derived, consent_record=record, ip_address=ip_address, user_agent=user_agent)`.
  - **Important — no `db.commit()` in the v2 path.** The legacy v1 `kiosk_check_in` (line 435) calls `await db.commit()`. The v2 path correctly does NOT — it relies on `get_db_session`'s `session.begin()` to commit on context exit. DO NOT introduce `db.commit()` into v2.
  - **Master-unchecked path (Req 1.12):** when `data.consent_provided()` is `False` (master checkbox unchecked OR `entries` empty), the service SHALL skip the consent block entirely — neither `reminder_consent` is written nor is `reminder_config` modified. This preserves the existing customer creation/update path for non-consenting check-ins. H1 must include a test case asserting this.
  - On failure inside `update_customer_reminder_config`, the exception bubbles up; the surrounding `session.begin()` rolls back the entire check-in (including any vehicle links written earlier in the same call); the router's existing exception path returns `500`. Add a specific catch in the router for `RemindersConsentRequiredError` that maps to `JSONResponse(500, {"error": "consent_persistence_failed"})` per Req 1.16 — but note that `RemindersConsentRequiredError` only fires on the manual-edit path (the kiosk path always supplies a `consent_record`), so this is a defence-in-depth catch.
  - **Files:** `app/modules/kiosk/service.py` (edit `kiosk_check_in_v2` signature + body), `app/modules/kiosk/router.py` (edit `check_in` handler to pass `user_agent`).
  - **Refs:** Requirements 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 6.4.
  - **Verify:** `pytest tests/integration/test_kiosk_checkin_consent.py -v` passes — covers the happy-path co-persistence, the failure-injection rollback, AND the master-unchecked no-write case (H1 expanded).

## Phase D — Reminder pipeline validity-window gate

- [x] **D1. Edit `enqueue_customer_reminders` to add the `<= today_in_org_tz` skip with debug log**
  - **Code-truth gap:** the existing logic at `app/modules/notifications/reminder_queue_service.py` lines 240–262 reads:
    ```python
    target_date = today + timedelta(days=days_before)
    ...
    for cv, vehicle in vehicle_rows:
        expiry_date = getattr(vehicle, expiry_field, None)
        if expiry_date is None or expiry_date != target_date:
            continue
    ```
    The current `today = now.date()` at line 61 is UTC, not org-local. This task adds the validity-window skip BEFORE the existing exact-day match (`expiry_date != target_date`), not after. The existing exact-match continues to govern when a row is enqueued; the new check governs when a row is *eligible* to be enqueued at all.
  - Inside the inner `for cv, vehicle in vehicle_rows:` loop, after `expiry_date = getattr(vehicle, expiry_field, None)`, add:
    ```python
    if expiry_date is None:
        continue
    if expiry_date <= today_in_org_tz:
        log.debug(
            "skipped: %s for %s — date %s is on or before today (%s) in org tz",
            reminder_type, vehicle.rego or "<unknown>",
            expiry_date, today_in_org_tz,
        )
        continue
    if expiry_date != target_date:
        continue
    ```
    The first `continue` (`expiry_date is None`) preserves the existing null-skip; the second adds the new validity-window skip; the third preserves the existing exact-day match.
  - Do not write to `reminder_config` and do not append to `reminder_consent_revocations` (Req 4.5). No audit row (Req 4.6).
  - **Files:** `app/modules/notifications/reminder_queue_service.py` (edit `enqueue_customer_reminders`).
  - **Refs:** Requirements 4.1, 4.4, 4.5, 4.6.
  - **Verify:** `pytest tests/integration/test_reminder_validity_window.py -v` passes — covers expired-date skip, future-date enqueue, and the debug log assertion via `caplog`.

- [x] **D2. Resolve `today_in_org_tz` from `Organisation.timezone` (top-level column) with `Pacific/Auckland` fallback**
  - **Code-truth gap:** the timezone is a TOP-LEVEL column on the `organisations` table — `Organisation.timezone: Mapped[str]` at `app/modules/admin/models.py` line ≈137 (default `'UTC'`, server_default). It is NOT inside `organisations.settings` JSONB. Read it directly from the existing `org_data` dict that `_get_org_data(org_id)` already builds (lines 81–148) — extend `_get_org_data` to populate `data["timezone"] = org.timezone or "Pacific/Auckland"`.
  - New helper `_today_in_org_tz(tz_name: str) -> date`:
    ```python
    from zoneinfo import ZoneInfo
    def _today_in_org_tz(tz_name: str) -> date:
        try:
            return datetime.now(ZoneInfo(tz_name)).date()
        except Exception:
            log.debug("invalid org timezone %r, falling back to Pacific/Auckland", tz_name)
            return datetime.now(ZoneInfo("Pacific/Auckland")).date()
    ```
  - Compute `today_in_org_tz = _today_in_org_tz(org_data["timezone"])` ONCE per customer iteration (after `org_data = await _get_org_data(org_id)` at line 189), and reuse that local variable inside the inner vehicle loop. This avoids re-resolving the timezone for every vehicle row.
  - **Files:** `app/modules/notifications/reminder_queue_service.py` (edit `_get_org_data` and add `_today_in_org_tz`).
  - **Refs:** Requirement 4.1.
  - **Verify:** Same as D1.

## Phase E — Frontend kiosk

- [x] **E1. Add `ReminderConsentStep.tsx`**
  - Implements the per-vehicle row resolution rules (5a–5e) via `resolveInspectionTypeRow(vehicle)` helper.
  - Master checkbox + per-vehicle sub-checkboxes + per-checkbox channel sub-controls. State explicitly resets on every mount (no localStorage / sessionStorage reads — CP-4).
  - **Trade-family gating (per `.kiro/steering/trade-family-gating-for-new-features.md` + NFR-6 + Req 1.5e):** Read `tradeFamily` from `useTenant()` and compute `isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'`. When `!isAutomotive`, hide WOF, COF, and `registration_expiry` sub-checkboxes for every vehicle row — only `service_due` renders. The master toggle text remains universal ("Send me reminders"). The `vehicles` module gate is implicit: if the org has `vehicles` disabled the kiosk wizard never reaches this step with vehicle rows, so no extra check is needed here.
  - Calls `onChange(block | null)` and `onValidityChange(boolean)` props on every state change.
  - **Files:** `frontend-v2/src/pages/kiosk/ReminderConsentStep.tsx` (new), `frontend-v2/src/pages/kiosk/types.ts` (add `KioskReminderConsentBlock`, `KioskVehicleSummary` already exists).
  - **Refs:** Requirements 1.1, 1.2, 1.3, 1.4, 1.5 (5a–5e), 1.6, 1.7, 1.8, 1.11, NFR-6.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.render.test.tsx --run` passes — covers the 6 inspection-type rendering cases AND the non-automotive trade family case (only `service_due` visible).

- [x] **E2. Boot-time fetch `/kiosk/consent-text` in `KioskPage.tsx`**
  - `useEffect` at mount, AbortController cleanup, typed via `apiClient.get<{ text: string; version: string }>('/kiosk/consent-text', { signal })`.
  - Pass `text` and `version` down to `ReminderConsentStep` as props.
  - **Files:** `frontend-v2/src/pages/kiosk/KioskPage.tsx` (edit), `frontend-v2/src/pages/kiosk/api.ts` (add a typed wrapper).
  - **Refs:** Requirement 6.3.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/KioskPage.consent-text-fetch.test.tsx --run` passes — asserts the endpoint is called once at mount.

- [x] **E3. Per-vehicle row resolution (inspection_type → WOF or COF checkbox)**
  - Implement and unit-test `resolveInspectionTypeRow` as a pure helper inside `ReminderConsentStep.tsx` (or a sibling utility file). Cover null-null hide rule and dual-expiry tie-breaker.
  - **Files:** `frontend-v2/src/pages/kiosk/ReminderConsentStep.tsx` (or `frontend-v2/src/pages/kiosk/consentRules.ts`) (new/edit).
  - **Refs:** Requirements 1.5a, 1.5b, 1.5c, 1.5d, 1.5e.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/consentRules.test.ts --run` passes — covers each of the 5 cases.

- [x] **E4. Per-checkbox channel sub-control with submit-gating**
  - Tri-state inline channel control (SMS / Email / Both) with no preselection. Disable parent submit when any ticked sub-checkbox lacks a channel.
  - **Files:** `frontend-v2/src/pages/kiosk/ReminderConsentStep.tsx` (edit).
  - **Refs:** Requirements 1.6, 1.11.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.gating.test.tsx --run` passes — covers ticked-without-channel disabled state and ticked-with-channel enabled state.

- [x] **E5. Wire to existing kiosk submission to include `reminder_consent` in the body**
  - `frontend-v2/src/pages/kiosk/api.ts::submitCheckIn` accepts an optional `reminder_consent` field on its body type and includes it only when non-null.
  - `KioskPage.tsx` passes the consent block built by `ReminderConsentStep.onChange` into the submit call.
  - **Files:** `frontend-v2/src/pages/kiosk/api.ts`, `frontend-v2/src/pages/kiosk/KioskPage.tsx`, `frontend-v2/src/pages/kiosk/types.ts` (edit).
  - **Refs:** Requirements 1.13, 1.14.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/KioskPage.submit.test.tsx --run` passes — asserts the request body includes `reminder_consent` when present and omits it when not.

- [x] **E6. Accessibility hardening for the kiosk consent step (NFR-4 / Req 1.9 / Req 1.10)**
  - Apply Tailwind classes that satisfy the explicit acceptance criteria:
    - Primary Consent_Text rendered at `text-base` or larger (Tailwind `text-base` = 16px ≥ 14px requirement).
    - Secondary / supporting text rendered at `text-xs` (12px) or larger.
    - Every interactive control (master checkbox, sub-checkboxes, channel sub-controls, submit button) has `min-h-[44px] min-w-[44px]` and accessible padding so the hit area is ≥44×44 CSS px.
    - Body text colour pair satisfies 4.5:1 contrast ratio against background; large text 3:1. Use existing app palette tokens (`text-foreground` on `bg-background` already satisfies this in the Tailwind theme — confirm by visual review and the contrast test below).
    - Every form control has a programmatically associated visible label via `<label htmlFor="...">` or `aria-labelledby="..."` — no orphan checkboxes.
  - **Files:** `frontend-v2/src/pages/kiosk/ReminderConsentStep.tsx` (edit only — same file as E1/E3/E4).
  - **Refs:** Requirements 1.9, 1.10, NFR-4.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.a11y.test.tsx --run` passes — covers (a) every interactive `<button>` / `<input>` rendered by the component has computed `min-height >= 44` and `min-width >= 44` via `getBoundingClientRect()` in jsdom, (b) every checkbox `<input type="checkbox">` has either an associated `<label>` or a non-empty `aria-label` / `aria-labelledby` attribute, (c) the primary Consent_Text element has `font-size >= 14px` and the secondary helper text has `font-size >= 12px`. Contrast ratio is verified in the Playwright e2e (I5) — jsdom can't compute it.

## Phase F — Frontend customer profile

- [x] **F0. Extend `CustomerReminderConfig` type and modal to include `registration_expiry`**
  - **Code-truth gap:** `frontend-v2/src/pages/customers/CustomerProfile.tsx` line 158–164 declares `interface CustomerReminderConfig { service_due, wof_expiry, cof_expiry, vehicles }` — `registration_expiry` is missing from the interface AND from the modal UI (the existing toggles are wired only for the three other categories at lines 1234–1240+). The same gap exists in `frontend-v2/src/pages/customers/CustomerList.tsx` (`DEFAULT_REMINDER_CONFIG` at line 85 only has `service_due` and `wof_expiry`). After A0 the backend persists all four; the frontend must read and write all four.
  - Add `registration_expiry: ReminderEntry` to `CustomerReminderConfig` in both files.
  - Add `registration_expiry: { enabled: false, days_before: 30, channel: 'email' }` to every `defaultReminderConfig` and `DEFAULT_REMINDER_CONFIG` literal.
  - Add a fourth toggle row for `registration_expiry` to the existing inline Configure Reminders modal (mirror the markup of the `cof_expiry` row).
  - Update the `updateReminder` helper at line 429 to widen its `type` arg to `'service_due' | 'wof_expiry' | 'cof_expiry' | 'registration_expiry'`.
  - Update the `hasAny` check at lines 374, 416 to also `||` on `res.data?.registration_expiry?.enabled`.
  - **Files:** `frontend-v2/src/pages/customers/CustomerProfile.tsx` (edit), `frontend-v2/src/pages/customers/CustomerList.tsx` (edit).
  - **Refs:** Requirement 2.1; prerequisite for F2/F3 (the consent gate must see all four categories to compute `missing` correctly).
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/ConfigureRemindersModal.indicators.test.tsx --run` passes (this also exercises F2 and renders all four rows).

- [x] **F1. Add types for the new shapes in `frontend-v2/src/api/customers.ts`**
  - **Code-truth gap:** the spec previously said "edit `frontend-v2/src/api/customers.ts`". This file may not exist today — `CustomerList.tsx` and `CustomerProfile.tsx` both call `apiClient` directly inline. If `frontend-v2/src/api/customers.ts` exists, add the types there; otherwise create it as a new module and lazily migrate the call sites in F2–F7. Do NOT mass-rewrite existing inline calls — only the new consent / revoke calls go through the new module to limit blast radius.
  - TypeScript types matching `RemindersConsentEntry`, `RemindersConsentRecord`, `RemindersRevocationRecord`, the `PUT /reminders` 409 response shape, and the `POST /reminders/revoke` body.
  - Export a pure helper `computeMissingConsent(existing, newConfig): { category; channel }[]` that mirrors the backend logic for client-side preview (Req 2.2 / 5.4). Categories must include all four (`service_due`, `wof_expiry`, `cof_expiry`, `registration_expiry`).
  - **Files:** `frontend-v2/src/api/customers.ts` (new or edit).
  - **Refs:** Requirements 2.2, 2.3, 5.4.
  - **Verify:** `npx vitest run frontend-v2/src/api/__tests__/customers.consent.test.ts --run` passes — covers `computeMissingConsent` for covered/uncovered/already-enabled cases across all four categories.

- [x] **F2. Configure Reminders modal — fetch + display consent indicators per row**
  - **Code-truth note:** the Configure Reminders modal exists today as INLINE markup inside `CustomerProfile.tsx` (lines 1218+) and `CustomerList.tsx` (line 506+) — it is NOT a separate component file. F2/F3/F4 edit these inline modals in place. (The previous sub-component name `ConfigureRemindersModal.tsx` from earlier draft tasks is for the test file path only — the runtime code lives in `CustomerProfile.tsx` and `CustomerList.tsx`.)
  - On modal open, fetch `GET /customers/{id}/reminders` (existing — already wired at `CustomerProfile.tsx` line 372 and `CustomerList.tsx` line 249). The consent block lives on the customer object loaded by the page-level `GET /customers/{id}` call (already issued at the top of `CustomerProfile.tsx`). Pass it down via state.
  - **Pydantic schema gate (per `.kiro/steering/frontend-backend-contract-alignment.md` Rule 8):** Verify that `CustomerProfileResponse` in `app/modules/customers/schemas.py` exposes `custom_fields` as a free-form `dict` (it does — line 499 reads `custom_fields: Optional[dict] = Field(default_factory=dict)`). That means `custom_fields["reminder_consent"]` and `custom_fields["reminder_consent_revocations"]` flow through automatically, and there is **no schema change required** here. If at any point a stricter typed nested model is added to replace `dict`, this task MUST also add `reminder_consent: RemindersConsentRecord | None` and `reminder_consent_revocations: list[RemindersRevocationRecord]` fields to whatever replaces it — Pydantic silently drops fields not in the schema (the bug pattern that caused ISSUE-034's invoice fields).
  - Render a tick / warning indicator beside each `(category, channel)` row.
  - **Files:** `frontend-v2/src/pages/customers/CustomerList.tsx` (edit inline modal), `frontend-v2/src/pages/customers/CustomerProfile.tsx` (edit inline modal). No backend changes expected.
  - **Refs:** Requirements 2.1, 5.4.
  - **Verify:**
    - `npx vitest run frontend-v2/src/pages/customers/__tests__/ConfigureRemindersModal.indicators.test.tsx --run` passes (the test mounts whichever page hosts the inline modal — see test file for the chosen surface).
    - Smoke check: `docker compose -p invoicing exec -T app python -c "from app.modules.customers.schemas import CustomerProfileResponse; print('custom_fields' in CustomerProfileResponse.model_fields)"` prints `True`.

- [x] **F3. Configure Reminders modal — pre-submit `missing` computation**
  - On submit, call `computeMissingConsent`. If non-empty, render the `ConsentConfirmationModal` (F4) instead of issuing the `PUT`.
  - When `missing` is empty, issue `PUT /customers/{id}/reminders` without a `consent_record`.
  - **Files:** `frontend-v2/src/pages/customers/CustomerList.tsx` or modal file (edit).
  - **Refs:** Requirements 2.2, 2.3, 2.10, 2.11.
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/ConfigureRemindersModal.gate.test.tsx --run` passes — asserts the confirmation modal opens iff `missing` is non-empty.

- [x] **F4. Consent Confirmation modal — render, capture obtained_method + manual_note, post**
  - New component `frontend-v2/src/pages/customers/ConsentConfirmationModal.tsx`.
  - Renders the consent text + version (fetched from `/kiosk/consent-text`), lists each `(category, channel)` pair in `missing`, required `obtained_method` select with the 5 options (`verbal_in_person`, `phone`, `email_reply`, `written_form`, `other` per Req 2.4), conditionally-required `manual_note` textarea when `obtained_method === "other"`.
  - **Source string composition (Req 2.7):** the `source` field of the posted `RemindersConsentRecord` is built client-side as `` `manually_recorded_by_staff:${obtained_method}` ``. This matches the pattern used by the revocation flow (Req 3.4 / B2). The backend simply trusts the supplied `source` string — it does NOT re-compose.
  - **Consent text version round-trip (Req 6.4 / 6.5):** the `consent_text_version` posted in the record is the literal string returned by `GET /kiosk/consent-text` at modal open. F5 then renders this version on the Customer Profile so the workshop can correlate the record to the exact text. Lock this round-trip in the test below.
  - On Confirm: build `RemindersConsentRecord`, POST `PUT /customers/{id}/reminders` with `consent_record` in body, refresh parent.
  - On Cancel: close, do nothing else.
  - **Files:** `frontend-v2/src/pages/customers/ConsentConfirmationModal.tsx` (new).
  - **Refs:** Requirements 2.4, 2.5, 2.6, 2.7, 6.4.
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/ConsentConfirmationModal.test.tsx --run` passes — covers Cancel-discards (no PUT issued), Confirm-posts-with-record, "other"-requires-note, AND the body's `consent_record.source` equals `` `manually_recorded_by_staff:${obtained_method}` `` AND the body's `consent_record.consent_text_version` equals the version returned by the mocked `/kiosk/consent-text` fetch.

- [x] **F5. New "Reminder Consent" section on Customer Profile**
  - Renders `source`, `given_at` (org locale), recorded-by user (resolved via existing user-name resolver), `consent_text_version`, entries grid (per-vehicle, per-category, per-channel), revocations table (sorted by `revoked_at` desc).
  - When `reminder_consent` is absent, display "No consent on record".
  - **Files:** `frontend-v2/src/pages/customers/CustomerProfile.tsx` (edit), possibly new sub-component `frontend-v2/src/pages/customers/ReminderConsentSection.tsx`.
  - **Refs:** Requirements 5.1, 5.2, 5.3.
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/ReminderConsentSection.test.tsx --run` passes — covers presence and absence of consent record.

- [x] **F6. "Revoke consent" control + Revocation modal + post**
  - Per-entry "Revoke" button rendered only when `reminder_config[<category>].enabled === true` (Req 3.1).
  - New `RevocationModal.tsx` with required `obtained_method` select, required `reason_note` textarea, and Confirm/Cancel.
  - On Confirm: `POST /customers/{id}/reminders/revoke` with `{obtained_method, channel, categories_affected: [entry.category], reason_note}`. On Cancel: close without writing.
  - **Files:** `frontend-v2/src/pages/customers/RevocationModal.tsx` (new), `frontend-v2/src/pages/customers/CustomerProfile.tsx` or `ReminderConsentSection.tsx` (edit).
  - **Refs:** Requirements 3.1, 3.2, 3.3, 3.4.
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/RevocationModal.test.tsx --run` passes — covers Cancel-discards, Confirm-posts, post-success-refreshes-parent.

- [x] **F7. Optional Customer List "Reminder Consent" column behind org-setting flag**
  - **Code-truth gap:** the org settings JSONB whitelist is `SETTINGS_JSONB_KEYS` at `app/modules/organisations/service.py` line 198. Keys NOT in this set are silently dropped on read AND on write. The new `customers_consent_column_visible` MUST be added to this set or the toggle won't round-trip.
  - **Backend changes:**
    1. Add `"customers_consent_column_visible"` to `SETTINGS_JSONB_KEYS` in `app/modules/organisations/service.py`.
    2. Add `customers_consent_column_visible: Optional[bool] = None` to `OrgSettingsResponse` and `OrgSettingsUpdateRequest` in `app/modules/organisations/schemas.py` (mirror the existing pattern for `sidebar_display_mode`).
    3. Add `has_reminder_consent: bool` to `CustomerSearchResult` in `app/modules/customers/schemas.py` (this is a NEW field — Pydantic Rule 8 applies: the schema MUST be updated in lockstep with the service dict).
    4. Update `_customer_to_search_dict` in `app/modules/customers/service.py` to set `"has_reminder_consent": bool((customer.custom_fields or {}).get("reminder_consent"))`. No extra DB query is needed — the check is a single dict lookup on the row already loaded.
  - **Frontend changes:**
    1. `frontend-v2/src/contexts/TenantContext.tsx` — add `customers_consent_column_visible?: boolean` to the existing `OrgSettings` shape so the flag flows through to the rest of the app (mirror the `sidebar_display_mode` pattern at line 124).
    2. `frontend-v2/src/pages/customers/CustomerList.tsx` — read the flag from `useTenant().settings`, render a "Reminder Consent" column with `Yes`/`No` derived from `c.has_reminder_consent` when `true`, hide the column when `false`/missing.
  - **Refs:** Requirement 5.5.
  - **Verify:**
    - `npx vitest run frontend-v2/src/pages/customers/__tests__/CustomerList.consent-column.test.tsx --run` passes — covers column-hidden when flag false, column-shown when flag true.
    - `pytest tests/integration/test_customer_search_has_reminder_consent.py -v` passes — covers `has_reminder_consent: false` for fresh customer, `: true` after a consent record is written.

- [x] **F8. Safe-API-consumption + typed-generic lint check on every file touched by Phases E and F**
  - Per `.kiro/steering/safe-api-consumption.md` and NFR-1: every API field read must use `?.` and `?? []` / `?? 0`. Every `apiClient.get` / `apiClient.post` / `apiClient.put` call in the files touched by E1–E5 and F1–F7 must carry an explicit generic (`apiClient.get<T>(...)`). No `as any` is allowed in these files. Every `useEffect` that issues an API call must register an `AbortController` and return a cleanup function that calls `controller.abort()`.
  - This task is a verification pass over the diffs introduced by E and F — no new components are added.
  - **Files:** all `.tsx` / `.ts` files touched by E1–E5 and F1–F7 (review only, no rewrites unless violations are found).
  - **Refs:** NFR-1, `safe-api-consumption.md`.
  - **Verify:**
    - `cd frontend-v2 && npx tsc --noEmit -p tsconfig.json` reports zero errors on the changed files.
    - `cd frontend-v2 && grep -RInE "as any|apiClient\\.(get|post|put|delete)\\(" src/pages/kiosk/ReminderConsentStep.tsx src/pages/customers/ConsentConfirmationModal.tsx src/pages/customers/RevocationModal.tsx src/pages/customers/ReminderConsentSection.tsx src/api/customers.ts | grep -v "apiClient\\.(get|post|put|delete)<"` returns no results (i.e., every API call has a generic and there is no `as any`).
    - All `useEffect` blocks in the touched files that issue API calls visibly use `new AbortController()` and pass `{ signal }` to the call.

- [x] **F9. Navigation & Access verification (Customer Profile route + Kiosk consent-text route)**
  - Per `.kiro/steering/spec-completeness-checklist.md` §1, every spec MUST verify route registrations and lazy imports.
  - **Customer Profile**: confirm `/customers/:id` already routes to `CustomerProfile.tsx` in `frontend-v2/src/App.tsx` — this is the only route the new `ReminderConsentSection` mounts under. No new route registration is needed; the section is added inside an existing page.
  - **Kiosk consent-text endpoint**: confirm the kiosk frontend's existing route at `/kiosk` already renders `KioskPage.tsx`. The new `GET /kiosk/consent-text` is fetched by `KioskPage.tsx` at mount — there is no new frontend route.
  - **Configure Reminders modal**: the modal is an INLINE `<Modal>` block inside `CustomerList.tsx` (line 506+) and `CustomerProfile.tsx` (line 1218+) opened by an existing button — F2/F3/F4 edit these inline modals in place. No new sidebar entry, no new route.
  - **Backend route registration**: `customers_router` is mounted at `/api/v1/customers` AND `/api/v2/customers` in `app/main.py`. The new `POST /customers/{id}/reminders/revoke` route added by B2 inherits both prefixes automatically — no `app.main` edit required. Same for `kiosk_router` at `/api/v1/kiosk` (the new `GET /kiosk/consent-text` from C1 inherits this prefix).
  - **No new routes, no new sidebar items, no new lazy imports** — this spec extends existing pages and existing routers only.
  - **Files:** `frontend-v2/src/App.tsx`, `frontend-v2/src/pages/customers/CustomerProfile.tsx`, `frontend-v2/src/pages/customers/CustomerList.tsx`, `frontend-v2/src/pages/kiosk/KioskPage.tsx`, `app/main.py` (read-only inspection).
  - **Refs:** `.kiro/steering/spec-completeness-checklist.md`.
  - **Verify:**
    - `grep -RIn "/customers/:id" frontend-v2/src/App.tsx` returns at least one match.
    - `grep -RIn "ReminderConsentSection" frontend-v2/src/pages/customers/CustomerProfile.tsx` returns the import + render site after F5 lands.
    - `grep -RIn "/kiosk/consent-text" frontend-v2/src/pages/kiosk/KioskPage.tsx` returns the fetch site after E2 lands.
    - `grep -RIn "customers_router" app/main.py` returns the existing v1 and v2 mount points (no new mount needed).

## Phase G — Property-based tests (one per Correctness Property)

- [x] **G1. CP-1 — Consent persistence is transactional** _Validates: CP-1_
  - File: `tests/property/test_consent_persistence_integrity.py`. Hypothesis generator over `(check_in_body | put_body, fail_at_audit | fail_at_config | succeed)`. Asserts both fields co-persisted on success; neither persisted on injected failure. Min 100 iterations. Tag header: `Feature: customer-reminder-consent, Property 1: ...`.
  - **Refs:** Requirements 1.13, 1.14, 1.15, 1.16, 2.7, 2.8, 6.4, 7.3.
  - **Verify:** `pytest tests/property/test_consent_persistence_integrity.py -v` passes 100 iterations.

- [x] **G2. CP-2 — Manual-enable consent gate** _Validates: CP-2_
  - File: `tests/property/test_consent_manual_enable_gate.py`. Hypothesis generator over `(existing_consent, existing_config, new_config, supplied_consent_record)`. Asserts: for any new pair newly transitioning enabled-false → enabled-true without coverage and without `consent_record`, the response is 409 + `reminder_config` unchanged; otherwise 200 + persisted. Min 100 iterations.
  - **Refs:** Requirements 2.2, 2.3, 2.10, 2.11, 2.12, 2.13.
  - **Verify:** `pytest tests/property/test_consent_manual_enable_gate.py -v` passes 100 iterations.

- [x] **G3. CP-3 — Audit completeness for consent events** _Validates: CP-3_
  - File: `tests/property/test_consent_audit_completeness.py`. Hypothesis generator over arbitrary `(consent_record | revocation_record)`. Asserts exactly one `audit_log` row per call, action string matches, `after_value` lacks the redacted keys. Min 100 iterations.
  - **Refs:** Requirements 1.17, 2.9, 3.7, 7.1, 7.2.
  - **Verify:** `pytest tests/property/test_consent_audit_completeness.py -v` passes 100 iterations.

- [x] **G4. CP-4 — Kiosk default-unchecked invariant (frontend, fast-check)** _Validates: CP-4_
  - File: `frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.default.test.tsx`. fast-check generator producing arbitrary `localStorage` / `sessionStorage` / autofill seed states. Mounts `<ReminderConsentStep />` via React Testing Library; asserts master checkbox unchecked, every sub-checkbox unchecked, every channel control empty. Min 100 iterations via `fc.assert(fc.property(...), { numRuns: 100 })`.
  - **Refs:** Requirements 1.2, 1.3.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.default.test.tsx --run` passes.

- [x] **G5. CP-5 — Manual-revocation idempotence** _Validates: CP-5_
  - File: `tests/property/test_consent_manual_revocation_idempotence.py`. Hypothesis generator over `(initial_config, revocation_sequence: list[record])`. Asserts: after the first revocation that hits an active entry the config is updated; subsequent revocations against now-disabled entries leave the config unchanged and append no revocation rows. Min 100 iterations.
  - **Refs:** Requirement 3 / CP-5.
  - **Verify:** `pytest tests/property/test_consent_manual_revocation_idempotence.py -v` passes 100 iterations.

- [x] **G6. CP-6 — Validity-window auto-suppression** _Validates: CP-6_
  - File: `tests/property/test_reminder_validity_window.py`. Hypothesis generator over `(category, expiry_date relative to today, days_before)`. Asserts: when `expiry_date <= today_in_org_tz` zero rows produced; when `expiry_date == today + days_before` exactly the configured row count is produced; updating from past to future restores enqueue without consent re-grant. Min 100 iterations.
  - **Refs:** Requirements 4.1, 4.2, 4.3, 4.7.
  - **Verify:** `pytest tests/property/test_reminder_validity_window.py -v` passes 100 iterations.

## Phase H — Integration tests + audit-redaction lint

- [x] **H1. Backend integration: kiosk check-in writes consent + config + audit row in one transaction**
  - File: `tests/integration/test_kiosk_checkin_consent.py`. Happy-path test asserts post-checkin DB state contains `reminder_consent`, the derived `reminder_config`, and exactly one `customer.reminder_consent.given` audit row. Failure-injection variant patches `write_audit_log` to raise; asserts neither customer field is present after rollback and the response is `500 {"error": "consent_persistence_failed"}`.
  - **Refs:** Requirements 1.13, 1.14, 1.15, 1.16, 1.17.
  - **Verify:** `pytest tests/integration/test_kiosk_checkin_consent.py -v` passes.

- [x] **H2. Backend integration: `PUT /reminders` with no consent_record returns 409, with consent_record persists both**
  - File: `tests/integration/test_customer_reminders_consent_gate.py`. Cases: no-consent-409, with-consent-200-persisted, idempotent-resubmit-no-extra-audit, already-enabled-pair-no-gate.
  - **Refs:** Requirements 2.2, 2.7, 2.10, 2.11, 2.12, 2.13.
  - **Verify:** `pytest tests/integration/test_customer_reminders_consent_gate.py -v` passes.

- [x] **H3. Backend integration: `POST /reminders/revoke` flips reminder_config and appends revocation; audit row redacted**
  - File: `tests/integration/test_customer_reminders_revoke.py`. Cases: single-category-revoke-flip-and-append, multi-category-revoke, idempotent-on-already-revoked, audit-row-after_value-lacks-recorded_by_user_id.
  - **Refs:** Requirements 3.4, 3.5, 3.7, 3.9.
  - **Verify:** `pytest tests/integration/test_customer_reminders_revoke.py -v` passes.

- [x] **H4. Audit-redaction lint test**
  - File: `tests/unit/test_consent_audit_redaction.py`. AST walks `app/modules/customers/consent.py`, finds every call to `write_audit_log(...)`, inspects the literal `after_value=` keyword arg, and rejects any dict literal whose keys include `"ip_address"`, `"user_agent"`, `"recorded_by_user_id"`, or `"recorded_by_user_email"`. Mirrors the analogous staff-payslip redaction lint pattern.
  - **Refs:** Requirements 7.1, 7.2; NFR-5.
  - **Verify:** `pytest tests/unit/test_consent_audit_redaction.py -v` passes.

- [x] **H5. Reminder pipeline integration: validity-window gate end-to-end**
  - File: `tests/integration/test_reminder_validity_window.py`. Insert a vehicle row with `wof_expiry = today - 1 day`, customer with `reminder_config[wof_expiry].enabled = true`. Run `enqueue_customer_reminders`. Assert zero rows in `reminder_queue` for that `(customer, vehicle, wof_expiry)` tuple. Assert the expected debug log line via `caplog`. Update `wof_expiry` to `today + 30 days`. Re-run. Assert at least one row in `reminder_queue`.
  - **Refs:** Requirements 4.1, 4.4, 4.7.
  - **Verify:** `pytest tests/integration/test_reminder_validity_window.py -v` passes.

## Phase I — Frontend integration + e2e

- [x] **I1. Frontend Vitest: kiosk consent step renders correct checkbox per `vehicle.inspection_type`**
  - Tie-breaker rule (5c) and null-null hide rule (5d) covered. Non-vehicle row (5e) covered.
  - **Files:** `frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.render.test.tsx`.
  - **Refs:** Requirements 1.5a, 1.5b, 1.5c, 1.5d, 1.5e.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.render.test.tsx --run` passes.

- [x] **I2. Frontend Vitest: per-checkbox channel sub-control gates the submit button**
  - Mounts the kiosk wizard with a stubbed prior step, ticks one sub-checkbox without choosing a channel, asserts the submit button is disabled. Chooses a channel, asserts enabled. Unticks another row's choice, asserts disabled again.
  - **Files:** `frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.gating.test.tsx`.
  - **Refs:** Requirement 1.11.
  - **Verify:** `npx vitest run frontend-v2/src/pages/kiosk/__tests__/ReminderConsentStep.gating.test.tsx --run` passes.

- [x] **I3. Frontend Vitest: Configure Reminders modal opens Consent Confirmation modal when missing**
  - Mounts the Configure Reminders modal with a stubbed customer that has `reminder_consent` covering only one of two enabled pairs, ticks the second pair, clicks Save, asserts `ConsentConfirmationModal` renders.
  - **Files:** `frontend-v2/src/pages/customers/__tests__/ConfigureRemindersModal.gate.test.tsx`.
  - **Refs:** Requirements 2.2, 2.3.
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/ConfigureRemindersModal.gate.test.tsx --run` passes.

- [x] **I4. Frontend Vitest: Consent Confirmation modal Cancel discards changes**
  - Asserts that clicking Cancel closes the modal AND does NOT issue a `PUT /reminders` (verified via mocked apiClient).
  - **Files:** `frontend-v2/src/pages/customers/__tests__/ConsentConfirmationModal.test.tsx`.
  - **Refs:** Requirement 2.6.
  - **Verify:** `npx vitest run frontend-v2/src/pages/customers/__tests__/ConsentConfirmationModal.test.tsx --run` passes.

- [~] **I5. e2e Playwright: full happy-path**
  - Kiosk new-customer flow → consent step → check-in completes → Customer Profile shows the consent record → admin opens Revocation modal and confirms → asserts the affected `reminder_config[<category>].enabled === false` and an `audit_log` row with `customer.reminder_consent.revoked` exists.
  - **Files:** `tests/e2e/customer_reminder_consent.spec.ts`.
  - **Refs:** Requirements 1, 2, 3, 5.
  - **Verify:** `npx playwright test tests/e2e/customer_reminder_consent.spec.ts --reporter=line` passes.

## Phase J — Versioning + release

- [x] **J1. Bump `pyproject.toml`, `frontend-v2/package.json`, `mobile/package.json` to `1.23.0`**
  - Single-line edits in each file. Keep version lockstep across web + mobile + backend even though there is no mobile work in this spec.
  - **Files:** `pyproject.toml`, `frontend-v2/package.json`, `mobile/package.json`.
  - **Refs:** None — release hygiene.
  - **Verify:** `grep -E '"version"' pyproject.toml frontend-v2/package.json mobile/package.json` shows `1.23.0` in all three.

- [x] **J2. CHANGELOG entry under `## [1.23.0]`**
  - Three primary user-facing capabilities: (1) kiosk consent capture for WOF / COF / registration / service reminders, (2) manual-revocation flow on Customer Profile, (3) automatic suppression of reminders past their relevant date.
  - Note that no Alembic migration is required.
  - **Files:** `CHANGELOG.md`.
  - **Refs:** None — release hygiene.
  - **Verify:** `head -30 CHANGELOG.md | grep -E '## \[1.23.0\]'` returns a match.

- [x] **J3. Local audit only — NO git push, NO PR**
  - Per the user's explicit instruction at the top of this tasks.md (Execution policy → "No git push, no PR creation, no deploy"), this final step is a **local audit** of the staged work. It does not commit, does not push, does not open a PR.
  - Walk the file list emitted by `git status --short` and confirm every changed file is listed in one of the `**Files:**` lines of an A–I task above (no surprise edits).
  - Confirm the three version files match (`pyproject.toml`, `frontend-v2/package.json`, `mobile/package.json` all show `1.23.0`).
  - Confirm the CHANGELOG entry is present (`head -40 CHANGELOG.md | grep '## \[1.23.0\]'`).
  - Confirm no Alembic migration was added under `alembic/versions/` (Out-of-Scope item 1).
  - Confirm no file under `frontend/` (the archived legacy SPA) was modified (`git status --short frontend/` shows nothing — this spec is `frontend-v2/` only).
  - Confirm no file under `mobile/src/` was modified beyond `mobile/package.json` (no mobile feature work in v1).
  - **Files:** N/A (audit only).
  - **Refs:** Execution policy at top of this tasks.md; project-overview.md "Active web app: frontend-v2".
  - **Verify:**
    - `git status --short frontend/ mobile/src/ alembic/versions/` returns no output.
    - `grep -E '"version"' pyproject.toml frontend-v2/package.json mobile/package.json` shows `1.23.0` in all three.
    - `head -40 CHANGELOG.md | grep -E '## \[1.23.0\]'` returns a match.
  - **What this step does NOT do:** it does NOT call `git commit`, `git push`, `gh pr create`, or any deploy command. Pushing the work, opening a PR, and any deploy decisions are deferred to the user out-of-band.

## Requirements traceability matrix

This matrix maps every requirement acceptance criterion (and every NFR + Correctness Property) to the design section that elaborates it AND the task that implements it. If a row's "Task(s)" column is empty, the requirement is not implemented; if "Design" is empty the design doc has a hole; if both are empty the requirement is orphaned. The full audit below shows zero orphans.

### Requirement 1 — Kiosk consent capture

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 1.1 | §5.1 | E1 | I1 / I5 |
| 1.2 | §5.1 | E1 | G4 |
| 1.3 | §5.1 | E1 | G4 |
| 1.4 | §5.1 | E1 | I1 |
| 1.5a–5e | §5.1 (`resolveInspectionTypeRow`) | E1, E3 | I1 |
| 1.6 | §5.1 | E4 | I2 |
| 1.7 | §5.1 | E1 | I1 |
| 1.8 | §5.1 | E2, E1 | I1 |
| 1.9 | §3.3 / NFR-4 | E6 | E6 a11y test |
| 1.10 | §3.3 / NFR-4 | E6 | E6 a11y test |
| 1.11 | §5.1 | E4 | I2 |
| 1.12 | §3.3 | C3 (master-unchecked path) | H1 (no-write case) |
| 1.13 | §3.1 | A2, C3 | H1, G1 |
| 1.14 | §3.1 (`union_channel_for_category`) | A2, C3 (`days_before` resolution) | G1 |
| 1.15 | §3.2 | C3 | H1, G1 |
| 1.16 | §3.3 (Error handling) | C3 (router catch) | H1 (failure-injection) |
| 1.17 | §3.1 | A2 (audit write) | G3, H1 |

### Requirement 2 — Manual enable warning

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 2.1 | §5.2 | F2 (consent indicators) | F2 vitest |
| 2.2 | §3.3 | F1 (`computeMissingConsent`), F3 | G2, F1 vitest |
| 2.3 | §5.2 | F3 (gate) | I3 |
| 2.4 | §5.2 | F4 | F4 vitest |
| 2.5 | §5.2 | F4 | F4 vitest |
| 2.6 | §5.2 | F4 | I4 |
| 2.7 | §3.1, §5.2 | F4 (source composition), A4 (persist) | G1, F4 vitest |
| 2.8 | §3.3 | A4 (raise on persist failure), B1 (500 mapping) | H2 |
| 2.9 | §3.1 | A2 (audit write) | G3, H2 |
| 2.10 | §3.3 | F3 (only triggers when `missing` non-empty) | I3 |
| 2.11 | §3.3 | F3 (skip gate when disabling) | F3 vitest |
| 2.12 | §3.3 | B1 (409 mapping), A3 (exception payload shape) | G2, H2 |
| 2.13 | §3.3 | B1 (idempotent re-issue) | G2, H2 |

### Requirement 3 — Manual revocation

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 3.1 | §5.3 | F6 (control rendered only when active) | F6 vitest |
| 3.2 | §5.4 | F6 | F6 vitest |
| 3.3 | §5.4 | F6 (Cancel discards) | F6 vitest, I5 |
| 3.4 | §3.1, §5.4 | A5 (service), B2 (router + source composition) | H3, I5 |
| 3.5 | §3.2 | A5 (transactional) | H3, G5 |
| 3.6 | §3.3 (Error handling) | A5 (rollback comment), B2 (500 mapping) | H3 (failure-injection) |
| 3.7 | §3.1 | A2 (audit write, redacted) | G3, H3, H4 |
| 3.8 | NFR-7 | A5 (synchronous-write SLA comment) | H3 (synchronous completion) |
| 3.9 | §3.1 | A5 (preserves full PII on customer record) | H3 |

### Requirement 4 — Auto-suppression

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 4.1 | §3.7, §4 (sequence) | D1 (skip), D2 (`today_in_org_tz`) | G6, H5 |
| 4.2 | (existing `REMINDER_TYPE_MAP`) | D1 (refs existing map) | H5 |
| 4.3 | §3.7 | D1 (no config write) | G6, H5 |
| 4.4 | §3.7 | D1 (debug log) | H5 (caplog assertion) |
| 4.5 | §3.7 | D1 (no revocations append) | G6 |
| 4.6 | §3.7 | D1 (no audit row) | G6 |
| 4.7 | §3.7 | D1, D2 (gate is read-time only) | G6, H5 |

### Requirement 5 — Consent visibility

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 5.1 | §5.3 | F5 | F5 vitest, I5 |
| 5.2 | §5.3 | F5 (empty state) | F5 vitest |
| 5.3 | §5.3 | F5 (revocations table) | F5 vitest |
| 5.4 | §5.2 | F2 (per-row indicators) | F2 vitest |
| 5.5 | §5.5 | F7 (settings whitelist + has_reminder_consent + column) | F7 vitest + integration |

### Requirement 6 — Configurable consent text and versioning

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 6.1 | §3.1 (BACKEND CONSTANT decision) | A1 (consent_text.py) | A1 unit test |
| 6.2 | §3.1 / A1 docstring | A1 | A1 unit test |
| 6.3 | §5.1 | C1 (`GET /kiosk/consent-text`), E2 (frontend fetch) | C1 smoke, E2 vitest |
| 6.4 | §3.1 | A2 (`record_consent_given` writes version), C3 (kiosk passes through), F4 (manual passes through) | F4 vitest, G3 |
| 6.5 | §5.3 | F5 (renders version) | F5 vitest |

### Requirement 7 — Audit log shape and PII handling

| AC | Design section | Task(s) | Verified by |
|---|---|---|---|
| 7.1 | §3.1 (redaction summary) | A2 (`record_consent_given` redacts ip + ua) | H4 (AST lint), G3 |
| 7.2 | §3.1 (redaction summary) | A2 (`record_consent_revoked` redacts user_id + email) | H4 (AST lint), G3 |
| 7.3 | §3.1, NFR-3 | A2 (full PII on customer record) | H1, H3 |

### Correctness Properties

| CP | Design section | Task(s) | Verified by |
|---|---|---|---|
| CP-1 | §3 architecture invariants | A2, A4, C3 | G1 (Hypothesis ≥100 iters) |
| CP-2 | §3 architecture invariants | A4 (gate), B1 (409) | G2 (Hypothesis ≥100 iters) |
| CP-3 | §3.1 (audit write) | A2 | G3 (Hypothesis ≥100 iters) |
| CP-4 | §5.1 (state reset on mount) | E1 | G4 (fast-check ≥100 iters) |
| CP-5 | §5.4, §3.1 | A5 (early-return), F6 (UI gate) | G5 (Hypothesis ≥100 iters) |
| CP-6 | §3.7, §4 | D1, D2 | G6 (Hypothesis ≥100 iters) |

### Non-functional Requirements

| NFR | Design section | Task(s) | Verified by |
|---|---|---|---|
| NFR-1 (safe API consumption) | §3.3, §5 | F8 (lint pass) | F8 grep + tsc |
| NFR-2 (wrapped array responses) | (no list endpoint added by this spec — revocations are read from `customer.custom_fields` JSONB, not a separate list endpoint) | n/a — no surface to attach to | n/a |
| NFR-3 (JSONB storage, no app-layer encryption) | §3.1 | A2 (writes to `custom_fields` directly) | (architectural — locked by code review) |
| NFR-4 (kiosk WCAG 2.1 AA) | §3.3 | E6 | E6 a11y test + I5 |
| NFR-5 (audit log redaction shape) | §3.1 | A2 | H4 (AST lint) |
| NFR-6 (trade-family universality) | §5.1 | E1 (`isAutomotive` gate) | E1 vitest (non-automotive case) |
| NFR-7 (revocation latency) | §3.3 | A5 (synchronous completion comment) | H3 |

### Out of Scope items (tasks confirm none of these creep in)

| OOS item | Confirmed not implemented by |
|---|---|
| 1. No new table / column / migration | Execution policy "No Alembic migration"; J3 audit |
| 2. No Configure Reminders modal redesign | F2/F3/F4 edit existing inline modal in place |
| 3. No reminder pipeline change beyond validity-window | D1/D2 add ONE skip line; nothing else changes |
| 4. No self-service unsubscribe | No SMS-STOP / unsubscribe-link / `/unsubscribe` task exists |
| 5. No public consent-management portal | No portal task exists |
| 6. No backfill for existing customers | F3's gate triggers on next manual edit only |
| 7. No coverage of other templates | A0 limits `VALID_REMINDER_TYPES` to the 4 in scope |
| 8. Manual revocation IS in scope | A5, B2, F6 implement it |

**Audit result:** every requirement acceptance criterion, every Correctness Property, and every NFR has at least one task implementing it AND at least one verification test. No orphaned requirements; no orphaned tasks; no out-of-scope work has crept in.
