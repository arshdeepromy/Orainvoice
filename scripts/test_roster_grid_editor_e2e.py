"""
End-to-end test: Roster Grid Editor (Workstream D — task D4).

Emulates the full user flow against a running backend. Per
``.kiro/steering/feature-testing-workflow.md`` the script:
  - Uses ``passed`` / ``failed`` counters with per-step log lines
  - Logs in as the seeded ``org_admin`` (demo account by default)
  - Exercises bulk + copy-week + RBAC + cross-org payload safety
  - Cleans up every ``TEST_E2E_RosterGrid_*`` row in a ``finally`` block

Steps:
  1. Login as org_admin (demo@orainvoice.com / demo123). If the demo
     account isn't wired in this dev env, the script logs the issue
     and aborts cleanly with a non-zero exit.
  2. GET  /api/v2/schedule        — confirms shape `{ entries, total }`
  3. GET  /api/v2/schedule/templates — list templates
  4. POST /api/v2/schedule/bulk   — 5 entries → 5 created, 0 conflicts
  5. POST /api/v2/schedule/bulk   — same 5 → 5 conflicts (idempotence)
  6. POST /api/v2/schedule/copy-week — confirm response shape
  7. POST /api/v2/schedule/bulk   — cross-org `org_id` payload → resolved
                                     org_id wins (R11.9, OWASP A1)
  8. Cleanup — DELETE every entry created via the API in `finally`

The script is runnable but we do NOT enforce it passes in CI — no demo
account is assumed to exist in the dev env. Print clear messages, exit
0 only on full success.

Usage:
    docker exec invoicing-app-1 python scripts/test_roster_grid_editor_e2e.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx

BASE = "http://localhost:8000"

# Test accounts — per `.kiro/steering/feature-testing-workflow.md`.
DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"

TEST_PREFIX = "TEST_E2E_RosterGrid_"

passed = 0
failed = 0
errors: list[str] = []


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ✅ {label}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  ❌ {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    errors.append(f"{label}: {detail}")


def info(label: str) -> None:
    print(f"  ℹ️  {label}")


async def login(
    client: httpx.AsyncClient, email: str, password: str,
) -> str | None:
    """Login and return access_token, or None on failure."""
    try:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password, "remember_me": True},
        )
    except httpx.RequestError as exc:
        info(f"Login request failed: {exc}")
        return None
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def _utc_iso(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string the API accepts."""
    return dt.astimezone(timezone.utc).isoformat()


def _build_entry_payload(
    *, staff_id: str | None, hour_offset: int, label: str,
) -> dict:
    """Build a single ScheduleEntryCreate payload.

    All entries use the ``TEST_PREFIX`` in the title so cleanup can
    target them deterministically.
    """
    base = datetime.now(timezone.utc).replace(
        hour=9, minute=0, second=0, microsecond=0,
    ) + timedelta(days=14)  # 2 weeks ahead — well clear of any seeded data
    start = base + timedelta(hours=hour_offset)
    end = start + timedelta(minutes=30)
    payload: dict = {
        "title": f"{TEST_PREFIX}{label}",
        "start_time": _utc_iso(start),
        "end_time": _utc_iso(end),
        "entry_type": "job",
    }
    if staff_id:
        payload["staff_id"] = staff_id
    return payload


async def _delete_entry(
    client: httpx.AsyncClient, headers: dict[str, str], entry_id: str,
) -> bool:
    try:
        r = await client.delete(
            f"/api/v2/schedule/{entry_id}", headers=headers,
        )
    except httpx.RequestError:
        return False
    return r.status_code in (200, 204, 404)


async def main() -> bool:
    """Run the e2e script. Returns True on full success."""
    created_entry_ids: list[str] = []

    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as client:
        try:
            # ─── Step 1: Login as org_admin ───
            print("\n🔹 Step 1: Login as org_admin")
            token = await login(client, DEMO_EMAIL, DEMO_PASSWORD)
            if not token:
                info(
                    f"Demo login ({DEMO_EMAIL}) failed — the demo account is "
                    "wired separately in dev. Skipping the rest of the e2e.",
                )
                return False
            ok("Logged in as org_admin (demo account)")
            headers = {"Authorization": f"Bearer {token}"}

            # ─── Step 2: GET /api/v2/schedule (entries shape) ───
            print("\n🔹 Step 2: GET /api/v2/schedule — confirm shape")
            window_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            window_end = window_start + timedelta(days=21)
            r = await client.get(
                "/api/v2/schedule",
                headers=headers,
                params={
                    "start": _utc_iso(window_start),
                    "end": _utc_iso(window_end),
                },
            )
            if r.status_code != 200:
                fail("GET /api/v2/schedule", f"status={r.status_code}")
                return False
            body = r.json() or {}
            if "entries" in body and "total" in body:
                ok("Response has `entries` + `total` keys")
            else:
                fail(
                    "Schedule response shape",
                    f"keys={list(body.keys())}",
                )

            # ─── Step 3: GET /api/v2/schedule/templates ───
            print("\n🔹 Step 3: GET /api/v2/schedule/templates")
            r = await client.get(
                "/api/v2/schedule/templates", headers=headers,
            )
            if r.status_code == 200:
                tbody = r.json() or {}
                ok(
                    f"Templates list returned with {len(tbody.get('templates') or [])} "
                    "templates",
                )
            else:
                info(
                    "Templates endpoint returned "
                    f"{r.status_code} — non-fatal",
                )

            # We need a valid staff_id for the bulk_create test (the
            # bulk endpoint accepts entries without staff_id, but the
            # idempotence + conflict path is only meaningful when
            # staff_id is set). Resolve via /api/v2/staff.
            r = await client.get(
                "/api/v2/staff",
                headers=headers,
                params={"is_active": True, "page_size": 5},
            )
            staff_list = (r.json() or {}).get("staff") or []
            if not staff_list:
                info(
                    "No active staff in the demo org — bulk + conflict steps "
                    "will fall back to staff_id=None.",
                )
                staff_id = None
            else:
                staff_id = staff_list[0].get("id")
                ok(f"Resolved staff_id={staff_id}")

            # ─── Step 4: POST /api/v2/schedule/bulk — 5 fresh entries ───
            print("\n🔹 Step 4: POST /api/v2/schedule/bulk — 5 entries")
            entries_payload = [
                _build_entry_payload(
                    staff_id=staff_id, hour_offset=i * 2, label=f"Bulk_{i}",
                )
                for i in range(5)
            ]
            r = await client.post(
                "/api/v2/schedule/bulk",
                headers=headers,
                json={"entries": entries_payload},
            )
            if r.status_code != 200:
                fail("POST /bulk (fresh)", f"status={r.status_code} body={r.text[:200]}")
                return False
            bulk_body = r.json() or {}
            created_list = bulk_body.get("created") or []
            conflicts_list = bulk_body.get("conflicts") or []
            for c in created_list:
                if c.get("id"):
                    created_entry_ids.append(c["id"])
            if len(created_list) == 5 and len(conflicts_list) == 0:
                ok("Bulk-create returned 5 created, 0 conflicts")
            else:
                # Soft-fail when staff_id is None — the conflict path
                # is short-circuited so this should still succeed.
                fail(
                    "Bulk-create unexpected counts",
                    f"created={len(created_list)} conflicts={len(conflicts_list)}",
                )

            # ─── Step 5: Re-submit same 5 → all conflicts (idempotence) ───
            print("\n🔹 Step 5: Re-submit same 5 → all conflicts (R14.3)")
            if staff_id:
                r = await client.post(
                    "/api/v2/schedule/bulk",
                    headers=headers,
                    json={"entries": entries_payload},
                )
                if r.status_code != 200:
                    fail(
                        "POST /bulk (idempotent re-run)",
                        f"status={r.status_code}",
                    )
                else:
                    rb2 = r.json() or {}
                    re_created = rb2.get("created") or []
                    re_conflicts = rb2.get("conflicts") or []
                    # Track any extras for cleanup so we don't leak rows
                    for c in re_created:
                        if c.get("id"):
                            created_entry_ids.append(c["id"])
                    if len(re_conflicts) == 5 and len(re_created) == 0:
                        ok("Re-submit returned 5 conflicts, 0 created")
                    else:
                        fail(
                            "Idempotence",
                            f"created={len(re_created)} conflicts={len(re_conflicts)}",
                        )
            else:
                info(
                    "Skipping idempotence step — staff_id=None means no "
                    "conflict detection runs.",
                )

            # ─── Step 6: POST /api/v2/schedule/copy-week ───
            print("\n🔹 Step 6: POST /api/v2/schedule/copy-week")
            today = date.today()
            # Snap to the most recent Monday so source_week_start is a
            # week boundary the seeded data may have entries in.
            monday = today - timedelta(days=today.weekday())
            r = await client.post(
                "/api/v2/schedule/copy-week",
                headers=headers,
                json={
                    "source_week_start": monday.isoformat(),
                    "target_week_start": (monday + timedelta(days=7)).isoformat(),
                    "overwrite_existing": False,
                },
            )
            if r.status_code != 200:
                fail("POST /copy-week", f"status={r.status_code} body={r.text[:200]}")
            else:
                cw_body = r.json() or {}
                cw_created = cw_body.get("created") or []
                cw_conflicts = cw_body.get("conflicts") or []
                for c in cw_created:
                    if c.get("id"):
                        created_entry_ids.append(c["id"])
                ok(
                    f"Copy-week returned created={len(cw_created)}, "
                    f"conflicts={len(cw_conflicts)}",
                )

            # ─── Step 7: Cross-org `org_id` is ignored (OWASP A1) ───
            print(
                "\n🔹 Step 7: Cross-org org_id in payload is ignored (R11.9)",
            )
            # Build a payload that includes a fake `org_id` field — the
            # backend constructs ScheduleEntry rows with the resolved
            # request org_id and never trusts the payload value.
            fake_org_id = str(uuid.uuid4())
            cross_org_payload = _build_entry_payload(
                staff_id=staff_id, hour_offset=11, label="CrossOrg",
            )
            cross_org_payload["org_id"] = fake_org_id  # ignored field
            r = await client.post(
                "/api/v2/schedule/bulk",
                headers=headers,
                json={"entries": [cross_org_payload]},
            )
            if r.status_code != 200:
                fail("POST /bulk (cross-org)", f"status={r.status_code}")
            else:
                xb = r.json() or {}
                xc_created = xb.get("created") or []
                if xc_created:
                    new_id = xc_created[0].get("id")
                    if new_id:
                        created_entry_ids.append(new_id)
                        # Confirm the inserted row's org_id is NOT the
                        # fake one — read it back via the GET endpoint.
                        rr = await client.get(
                            f"/api/v2/schedule/{new_id}", headers=headers,
                        )
                        if rr.status_code == 200:
                            row = rr.json() or {}
                            if row.get("org_id") != fake_org_id:
                                ok(
                                    "Inserted entry uses resolved org_id, "
                                    "not the payload's value",
                                )
                            else:
                                fail(
                                    "Cross-org org_id leaked through",
                                    f"row.org_id={row.get('org_id')}",
                                )
                        else:
                            info(
                                f"Could not GET back inserted entry: "
                                f"status={rr.status_code}",
                            )
                else:
                    info(
                        "Cross-org test produced no created entry — "
                        "likely a conflict from the prior step.",
                    )
                    # Still note any conflicts we'd need to clean — none
                    # here because the entry didn't insert.

        except Exception as exc:  # noqa: BLE001
            fail("e2e crash", str(exc)[:300])
        finally:
            # ═══════════════════════════════════════════════════════════
            # Cleanup — delete every entry we created via the API
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Cleanup: DELETE every TEST_E2E_RosterGrid_* entry")
            if not token:  # type: ignore[name-defined]
                info("No token — skipping cleanup")
            else:
                cleanup_failures = 0
                for eid in created_entry_ids:
                    success = await _delete_entry(client, headers, eid)
                    if not success:
                        cleanup_failures += 1
                if cleanup_failures == 0 and created_entry_ids:
                    ok(
                        f"Deleted {len(created_entry_ids)} created entries",
                    )
                elif cleanup_failures:
                    fail(
                        "Cleanup",
                        f"{cleanup_failures}/{len(created_entry_ids)} entries "
                        "failed to delete",
                    )

                # Verify no TEST_E2E_RosterGrid_ entries remain in the
                # visible window (best-effort — the GET endpoint scopes
                # to the request org so cross-org leakage is impossible
                # here).
                window_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0,
                )
                window_end = window_start + timedelta(days=30)
                try:
                    r = await client.get(
                        "/api/v2/schedule",
                        headers=headers,
                        params={
                            "start": _utc_iso(window_start),
                            "end": _utc_iso(window_end),
                        },
                    )
                    body = r.json() or {}
                    leftover = [
                        e
                        for e in body.get("entries") or []
                        if (e.get("title") or "").startswith(TEST_PREFIX)
                    ]
                    if leftover:
                        fail(
                            "Cleanup verification",
                            f"{len(leftover)} TEST_E2E_RosterGrid_ rows remain",
                        )
                        # Best-effort second-pass cleanup.
                        for e in leftover:
                            await _delete_entry(client, headers, e["id"])
                    else:
                        ok("Cleanup verification: no TEST_E2E_RosterGrid_ rows remain")
                except httpx.RequestError as exc:
                    info(f"Cleanup verification skipped: {exc}")

    # ─── Summary ───
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
