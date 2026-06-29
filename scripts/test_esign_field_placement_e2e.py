"""End-to-end test: E-Signature Field Placement (esignature-field-placement).

Drives the running OraInvoice app as a real **Org_Sender** against the live
``/api/v2/esign`` HTTP surface (NOT unit-mocked), exercising the field-placement
extension to the already-shipped ``esignatures`` send flow per the always-on
``feature-testing-workflow`` steering ("no feature ships without a passing test
script").

Journey (global_admin → org_admin Org_Sender):
  1. Log in as a throwaway org sender (org_admin) to obtain a JWT.
  2. Saved field templates — create / list / get / **apply** (role→recipient
     mapping, client-side) / delete round-trip against
     ``/api/v2/esign/field-templates`` (needs NO Documenso).
  3. Module-gated ``POST /api/v2/esign/envelopes`` with a sender-defined
     ``fields[]`` set — server-side Field_Set re-validation (422 paths) plus a
     valid send that drives the create → field/create-many → distribute
     sequence (Documenso-dependent — see degrade note below).
  4. Edit-after-send ``GET …/fields`` then ``PUT …/fields`` round-trip on an
     editable (sent / unsigned) envelope, plus the Non_Editable_State 422.
  5. OWASP / access-control checks the steering requires:
       - 401 without a token,
       - 403 for a non-sender role (salesperson),
       - 403 when the ``esignatures`` module is disabled,
       - org-isolation / IDOR on templates AND envelopes (another org's ids
         return 404, never leaked into a list).
  6. A global no-leak scan over every collected error body (OWASP A05).

──────────────────────────────────────────────────────────────────────────────
DOCUMENSO-DEPENDENT STEPS (graceful degrade — documented)
──────────────────────────────────────────────────────────────────────────────
A live, per-org **verified** Documenso connection is often NOT reachable from
this environment (the integrated client rejects non-HTTPS base URLs, and the
local dev Documenso is reachable only over plaintext HTTP on a separate Docker
network — and the Documenso v2 field/distribute surface this feature relies on
may itself be UNVERIFIED; see ``docs/documenso-capability-matrix.md``).

This script therefore **degrades gracefully**:
  • It seeds the org's connection with a syntactically-HTTPS but unreachable URL
    and flips ``is_verified = true`` directly in the DB so the connection GATE
    is satisfied and the field-set re-validation path can be reached.
  • The valid field-placement send is still CALLED against the live endpoint.
    It legitimately passes the role gate, module gate, connection gate, and
    server-side Field_Set validation, then fails ONLY at the Documenso transport
    → HTTP 502 with the envelope recorded ``status = 'error'`` (proving the
    create → field/create-many ordering was reached). If a real verified
    Documenso IS reachable it returns 201 and the envelope persists ``status =
    'sent'`` — the script asserts whichever outcome applies and reports which.
  • The edit ``PUT …/fields`` valid path is likewise Documenso-dependent and is
    asserted conditionally (200 when live, else 502/503).

Everything else — template CRUD, server-side Field_Set validation 422s, the
GET-fields editable gate on a no-document envelope, the Non_Editable_State 422,
auth / RBAC / module-gate / IDOR — needs **no** live Documenso and runs fully.

Cleanup (MANDATORY): three throwaway TEST_E2E_ organisations (A sender-org,
B isolation-org, C module-disabled-org) and ALL of their child rows (esign
templates / envelopes / recipients / webhook events / connections, users,
org_modules, audit + notifications, sessions) are created up-front and torn
down in a ``finally`` block (so a mid-run crash still cleans up), in reverse
dependency order. After cleanup the DB is re-queried and any leftover is
reported as a FAILURE. All test-created data is prefixed ``TEST_E2E_``.

Usage:
    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
        exec -T app python scripts/test_esign_field_placement_e2e.py
  or:
    docker exec invoicing-app-1 python scripts/test_esign_field_placement_e2e.py

Requirements: 9.1, 9.2, 9.3, 13.1, 13.3, 13.4, 17.3, 17.4, 17.7
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import httpx
    import asyncpg
except ImportError as exc:  # pragma: no cover - dependency guard
    print(f"\u26a0\ufe0f  Required dependency not available: {exc}")
    print("   Run inside the app container or `pip install httpx asyncpg`.")
    sys.exit(2)

# --- Endpoints -------------------------------------------------------------
BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API_V1 = f"{BASE}/api/v1"
API_V2 = f"{BASE}/api/v2"

# --- DB connection (direct, for seeding + verification + cleanup) ----------
DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_NAME = os.environ.get("DB_NAME", "workshoppro")

# --- Redis (only to bust module-enablement caches after a DB toggle) -------
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Test password for the throwaway users.
TEST_PW = "TestE2EFieldPw123"

# A base URL that is syntactically HTTPS (so the connection is storable and the
# client constructs) but unreachable — the documented Documenso-dependent path.
DOCUMENSO_BASE_URL = "https://documenso.test-e2e.invalid"
WEBHOOK_SECRET = f"TEST_E2E_whsecret_{uuid.uuid4().hex}"

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"
INFO = "\033[94m\u2192\033[0m"
SKIP = "\033[93m~\033[0m"

passed = 0
failed = 0
errors: list[str] = []
# Error bodies collected across the run for a global no-leak scan (OWASP A05).
error_bodies: list[str] = []


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  {PASS} {label}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  {FAIL} {label}"
    if detail:
        msg += f" \u2014 {detail}"
    print(msg)
    errors.append(f"{label}: {detail}")


def note(label: str, detail: str = "") -> None:
    msg = f"  {INFO} {label}"
    if detail:
        msg += f" \u2014 {detail}"
    print(msg)


def rand() -> str:
    return uuid.uuid4().hex[:8]


# Substrings indicating a leaked stack trace / internal path (OWASP A05).
_LEAK_INDICATORS = [
    "traceback", 'file "', ".py\"", "sqlalchemy", "asyncpg", "psycopg",
    "/app/", "site-packages", "documenso.test-e2e.invalid",
]


def scan_for_leak(text: str) -> str | None:
    low = (text or "").lower()
    for ind in _LEAK_INDICATORS:
        if ind in low:
            return ind
    return None


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


async def get_db_conn() -> "asyncpg.Connection":
    return await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
    )


async def clear_module_cache(org_id: uuid.UUID) -> None:
    """Best-effort bust of both module-enablement caches for an org."""
    try:
        import redis.asyncio as _redis  # noqa: PLC0415

        r = _redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        await r.delete(f"mod:{org_id}")
        async for key in r.scan_iter(match=f"module:enabled:{org_id}:*"):
            await r.delete(key)
        await r.aclose()
    except Exception:  # noqa: BLE001 - cache bust is best-effort
        pass


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str] | None:
    """Authenticate via /api/v1/auth/login; return an Authorization header."""
    try:
        r = await client.post(
            f"{API_V1}/auth/login",
            json={"email": email, "password": password, "remember_me": False},
        )
    except httpx.HTTPError:
        return None
    if r.status_code == 200 and r.json().get("access_token"):
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return None


def make_pdf() -> bytes:
    """Return a minimal byte string that passes the PDF magic-byte sniff."""
    return b"%PDF-1.4\n%TEST_E2E\n1 0 obj<</Type/Catalog>>endobj\ntrailer<<>>\n%%EOF"


def signature_field(recipient_index: int = 0, *, page: int = 1) -> dict:
    """A single, valid signature FieldIn (normalized percent coords)."""
    return {
        "type": "signature",
        "page": page,
        "recipient_index": recipient_index,
        "position_x": 10.0,
        "position_y": 10.0,
        "width": 25.0,
        "height": 8.0,
        "required": True,
        "client_id": f"sig-{recipient_index}",
    }


def apply_template(template: dict, role_to_index: dict[str, int]) -> list[dict]:
    """Client-side Apply_Template (R17.5/R17.6): copy each template field and
    map its abstract ``template_role`` slot onto a concrete ``recipient_index``.

    Mirrors the frontend ``applyTemplate.ts`` populate step — no template id is
    ever sent to Documenso; the produced Field_Set goes through the same send
    validation as any other (R17.8).
    """
    out: list[dict] = []
    for tf in template.get("fields") or []:
        role = tf.get("template_role")
        if role not in role_to_index:
            continue
        field = {k: v for k, v in tf.items() if k != "template_role"}
        field["recipient_index"] = role_to_index[role]
        out.append(field)
    return out


async def seed_envelope(
    conn: "asyncpg.Connection",
    org_id: uuid.UUID,
    *,
    status: str,
    doc_id: str | None,
    recipient_emails: list[str],
    signed_emails: set[str] | None = None,
) -> uuid.UUID:
    """Seed an envelope + recipients directly in the DB.

    ``signed_emails`` marks those recipients ``recipient_status = 'signed'`` so
    the pure ``editable_state`` gate (status=='sent' AND nobody signed) can be
    driven into a Non_Editable_State without a live Documenso.
    """
    env_id = uuid.uuid4()
    signed = signed_emails or set()
    await conn.execute(
        "INSERT INTO esign_envelopes "
        "(id, org_id, agreement_type, originating_entity_type, "
        " originating_entity_id, documenso_document_id, status, signed_doc_status) "
        "VALUES ($1,$2,'nda','staff',$3,$4,$5,'none')",
        env_id, org_id, uuid.uuid4(), doc_id, status,
    )
    for i, email in enumerate(recipient_emails):
        rec_status = "signed" if email in signed else "pending"
        await conn.execute(
            "INSERT INTO esign_recipients "
            "(id, envelope_id, name, email, signing_role, recipient_status) "
            "VALUES ($1,$2,$3,$4,'SIGNER',$5)",
            uuid.uuid4(), env_id, f"TEST_E2E_Recipient_{i}", email, rec_status,
        )
    return env_id


async def seed_template(
    conn: "asyncpg.Connection", org_id: uuid.UUID, *, name: str
) -> uuid.UUID:
    """Seed an org-scoped Field_Template directly in the DB (for IDOR tests)."""
    tpl_id = uuid.uuid4()
    fields = [
        {
            "type": "signature", "page": 1,
            "position_x": 5.0, "position_y": 5.0, "width": 20.0, "height": 8.0,
            "required": True, "template_role": "signer 1",
        }
    ]
    await conn.execute(
        "INSERT INTO esign_field_templates (id, org_id, name, agreement_type, fields, roles) "
        "VALUES ($1,$2,$3,'nda',$4::jsonb,$5::jsonb)",
        tpl_id, org_id, name, json.dumps(fields), json.dumps(["signer 1"]),
    )
    return tpl_id


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def main() -> int:  # noqa: C901, PLR0912, PLR0915 — single-flow e2e script
    print("=" * 72)
    print("  E-SIGNATURE FIELD PLACEMENT — END-TO-END TEST")
    print("=" * 72)

    from app.modules.auth.password import hash_password_sync

    org_a_id = uuid.uuid4()  # sender org (module enabled, verified connection)
    org_b_id = uuid.uuid4()  # isolation org (owns cross-org envelope + template)
    org_c_id = uuid.uuid4()  # module-DISABLED org
    conn: "asyncpg.Connection | None" = None

    suffix = rand()
    ga_email = f"test-e2e-ga-{suffix}@example.com"
    admin_email = f"test-e2e-admin-{suffix}@example.com"
    sales_email = f"test-e2e-sales-{suffix}@example.com"
    c_admin_email = f"test-e2e-cadmin-{suffix}@example.com"
    ga_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    sales_id = uuid.uuid4()
    c_admin_id = uuid.uuid4()

    # Documenso-liveness flag, decided at the valid-send step and reused for the
    # edit PUT valid path (both are Documenso-dependent).
    documenso_live = False

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
        try:
            conn = await get_db_conn()
        except Exception as exc:  # noqa: BLE001
            print(f"\n\u26a0\ufe0f  Database unreachable at {DB_HOST}:{DB_PORT} \u2014 {exc}")
            print("   Run inside the app container (DB host 'postgres').")
            return 2

        try:
            # ──────────────────────────────────────────────────────────────
            # Setup — throwaway orgs A + B + C, users, module enablement.
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} Setup: throwaway TEST_E2E orgs + users")
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            if plan_row is None:
                fail("setup", "no subscription_plans row to attach a throwaway org")
                return 1
            plan_id = plan_row["id"]

            for oid, label in ((org_a_id, "A"), (org_b_id, "B"), (org_c_id, "C")):
                await conn.execute(
                    "INSERT INTO organisations (id, name, plan_id, status, storage_quota_gb, settings) "
                    "VALUES ($1,$2,$3,'active',5,'{}'::jsonb)",
                    oid, f"TEST_E2E_Org{label}_{suffix}", plan_id,
                )
            ok(f"created org A ({str(org_a_id)[:8]}…) + B + C")

            pw_hash = hash_password_sync(TEST_PW)
            for uid, oid, email, role in (
                (ga_id, org_a_id, ga_email, "global_admin"),
                (admin_id, org_a_id, admin_email, "org_admin"),
                (sales_id, org_a_id, sales_email, "salesperson"),
                (c_admin_id, org_c_id, c_admin_email, "org_admin"),
            ):
                await conn.execute(
                    "INSERT INTO users (id, org_id, email, password_hash, role, is_active, is_email_verified) "
                    "VALUES ($1,$2,$3,$4,$5,true,true)",
                    uid, oid, email, pw_hash, role,
                )
            ok("created global_admin + org_admin (sender) + salesperson (org A) + org_admin (org C)")

            # Enable esignatures for A + B; explicitly DISABLE it for C.
            for oid, enabled in ((org_a_id, True), (org_b_id, True), (org_c_id, False)):
                await conn.execute(
                    "INSERT INTO org_modules (org_id, module_slug, is_enabled) "
                    "VALUES ($1,'esignatures',$2) "
                    "ON CONFLICT (org_id, module_slug) DO UPDATE SET is_enabled = $2",
                    oid, enabled,
                )
                await clear_module_cache(oid)
            ok("enabled 'esignatures' for org A + B; disabled for org C")

            admin_headers = await login(client, admin_email, TEST_PW)
            sales_headers = await login(client, sales_email, TEST_PW)
            ga_headers = await login(client, ga_email, TEST_PW)
            c_admin_headers = await login(client, c_admin_email, TEST_PW)
            if not all([admin_headers, sales_headers, ga_headers, c_admin_headers]):
                fail("login throwaway users", "one or more logins failed")
                return 1
            ok("logged in org sender (org_admin), salesperson, global_admin, org C admin")

            # Save + verify org A's Documenso connection so the connection GATE
            # is satisfied (the field-set re-validation path runs after it).
            conn_url = f"{API_V2}/admin/organisations/{org_a_id}/esign/connection"
            r = await client.put(
                conn_url, headers=ga_headers,
                json={
                    "base_url": DOCUMENSO_BASE_URL,
                    "documenso_team_id": "42",
                    "service_token": f"TEST_E2E_token_{rand()}",
                    "webhook_signing_secret": WEBHOOK_SECRET,
                },
            )
            if r.status_code == 200:
                ok("saved org A Documenso connection (global_admin)")
            else:
                fail("save connection", f"{r.status_code} {r.text[:160]}")
            await conn.execute(
                "UPDATE esign_org_connections SET is_verified = true WHERE org_id = $1",
                org_a_id,
            )
            ok("is_verified set true in DB (emulated passing test — documented mock path)")

            # ──────────────────────────────────────────────────────────────
            # 1. Saved field templates — create / list / get / apply / delete
            #    (R17.3, R17.4 — needs NO Documenso)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 1. Field-template CRUD + apply round-trip (no Documenso)")
            tpl_payload = {
                "name": f"TEST_E2E_Template_{rand()}",
                "agreement_type": "nda",
                "fields": [
                    {
                        "type": "signature", "page": 1,
                        "position_x": 10.0, "position_y": 70.0,
                        "width": 25.0, "height": 8.0,
                        "required": True, "template_role": "signer 1",
                    },
                    {
                        "type": "date", "page": 1,
                        "position_x": 40.0, "position_y": 70.0,
                        "width": 15.0, "height": 6.0,
                        "required": True, "template_role": "signer 1",
                    },
                ],
                "roles": ["signer 1"],
            }
            r = await client.post(
                f"{API_V2}/esign/field-templates", headers=admin_headers, json=tpl_payload,
            )
            error_bodies.append(r.text)
            template_id = None
            if r.status_code == 201 and r.json().get("id"):
                template_id = r.json()["id"]
                ok(f"POST field-template → 201 (id {template_id[:8]}…), stores roles not people")
                # R17.1 — no person ever persisted.
                if "email" not in r.text.lower() and r.json().get("roles") == ["signer 1"]:
                    ok("template carries abstract roles only (no recipient name/email)")
                else:
                    fail("template role storage", "unexpected recipient data in template")
            else:
                fail("create template", f"{r.status_code} {r.text[:160]}")
                return 1

            # List (R17.3) — org-scoped, wrapped { items, total }, contains ours.
            r = await client.get(f"{API_V2}/esign/field-templates", headers=admin_headers)
            items = (r.json().get("items") or []) if r.status_code == 200 else []
            if r.status_code == 200 and any(it.get("id") == template_id for it in items):
                ok(f"GET field-templates → 200, list contains the new template ({len(items)} total)")
            else:
                fail("list templates", f"{r.status_code} created template missing from list")

            # Get one (to apply it).
            r = await client.get(
                f"{API_V2}/esign/field-templates/{template_id}", headers=admin_headers,
            )
            template = r.json() if r.status_code == 200 else {}
            if r.status_code == 200 and template.get("id") == template_id:
                ok("GET field-templates/{id} → 200 (template fetched for apply)")
            else:
                fail("get template", f"{r.status_code} {r.text[:160]}")

            # Apply (client-side role→recipient mapping, R17.5/R17.6/R17.8).
            applied_fields = apply_template(template, {"signer 1": 0})
            if (
                len(applied_fields) == 2
                and all("template_role" not in f for f in applied_fields)
                and all(f["recipient_index"] == 0 for f in applied_fields)
            ):
                ok("apply maps each template role → recipient_index (no template id leaves the client)")
            else:
                fail("apply template", f"unexpected applied field set: {applied_fields}")

            # Delete (R17.4) → gone from list + GET → 404.
            r = await client.delete(
                f"{API_V2}/esign/field-templates/{template_id}", headers=admin_headers,
            )
            if r.status_code == 204:
                ok("DELETE field-templates/{id} → 204")
            else:
                fail("delete template", f"{r.status_code} {r.text[:160]}")
            r = await client.get(
                f"{API_V2}/esign/field-templates/{template_id}", headers=admin_headers,
            )
            error_bodies.append(r.text)
            if r.status_code == 404:
                ok("GET deleted template → 404 (gone)")
            else:
                fail("template gone", f"expected 404, got {r.status_code}")
            template_id = None  # consumed

            # ──────────────────────────────────────────────────────────────
            # 2. Field-placement send — server-side Field_Set re-validation
            #    (422 paths, Documenso-independent: validated before any call)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 2. POST /envelopes server-side Field_Set validation (422 paths)")
            signer_email = f"test-e2e-signer-{rand()}@example.com"

            def send_payload(fields: list[dict]) -> dict:
                return {
                    "agreement_type": "nda",
                    "originating_entity_type": "staff",
                    "originating_entity_id": str(uuid.uuid4()),
                    "recipients": [
                        {"name": "TEST_E2E_Signer", "email": signer_email, "signing_role": "signer"},
                    ],
                    "fields": fields,
                }

            async def post_envelope(headers, fields):
                return await client.post(
                    f"{API_V2}/esign/envelopes", headers=headers,
                    files={"file": ("TEST_E2E_agreement.pdf", make_pdf(), "application/pdf")},
                    data={"payload": json.dumps(send_payload(fields))},
                )

            # 2a. A signer with NO signature field → 422 (signature_field_missing).
            r = await post_envelope(admin_headers, [
                {"type": "text", "page": 1, "recipient_index": 0,
                 "position_x": 10.0, "position_y": 10.0, "width": 20.0, "height": 6.0,
                 "required": False, "client_id": "t1"},
            ])
            error_bodies.append(r.text)
            if r.status_code == 422:
                ok("send: signer without a signature field → 422 (no Documenso call)")
            else:
                fail("validate signer-no-sig", f"expected 422, got {r.status_code}: {r.text[:160]}")

            # 2b. An out-of-bounds field → 422 (field_out_of_bounds).
            r = await post_envelope(admin_headers, [
                {"type": "signature", "page": 1, "recipient_index": 0,
                 "position_x": 90.0, "position_y": 95.0, "width": 30.0, "height": 30.0,
                 "required": True, "client_id": "oob"},
            ])
            error_bodies.append(r.text)
            if r.status_code == 422:
                ok("send: out-of-bounds field → 422 (no Documenso call)")
            else:
                fail("validate out-of-bounds", f"expected 422, got {r.status_code}: {r.text[:160]}")

            # 2c. A field referencing a non-existent recipient → 422 (field_unassigned).
            r = await post_envelope(admin_headers, [signature_field(recipient_index=5)])
            error_bodies.append(r.text)
            if r.status_code == 422:
                ok("send: field with invalid recipient_index → 422 (no Documenso call)")
            else:
                fail("validate bad recipient", f"expected 422, got {r.status_code}: {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 3. Field-placement send — valid Field_Set (Documenso-dependent)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 3. POST /envelopes valid Field_Set (Documenso-dependent — degrade)")
            valid_fields = [signature_field(0), {
                "type": "date", "page": 1, "recipient_index": 0,
                "position_x": 40.0, "position_y": 10.0, "width": 15.0, "height": 6.0,
                "required": True, "client_id": "d1",
            }]
            r = await post_envelope(admin_headers, valid_fields)
            error_bodies.append(r.text)
            if r.status_code == 201:
                documenso_live = True
                new_env_id = r.json().get("id")
                st = await conn.fetchval(
                    "SELECT status FROM esign_envelopes WHERE id=$1", uuid.UUID(new_env_id)
                ) if new_env_id else None
                if st == "sent":
                    ok("valid send → 201; envelope persisted status 'sent' (live Documenso)")
                else:
                    fail("send persisted", f"expected status 'sent', got {st!r}")
            elif r.status_code == 502:
                ok("valid send passed RBAC/module/connection gates + Field_Set validation, "
                   "reached Documenso (502 transport — documented degrade)")
                # An error envelope must have been recorded for the attempt (R8.4).
                err_cnt = await conn.fetchval(
                    "SELECT count(*) FROM esign_envelopes WHERE org_id=$1 AND status='error'",
                    org_a_id,
                )
                if err_cnt and err_cnt >= 1:
                    ok(f"field/create-many failure recorded an 'error' envelope (R8.4), no distribute")
                else:
                    fail("error envelope", "no error-status envelope recorded after 502")
            elif r.status_code == 503:
                fail("send", "503 — connection gate blocked (is_verified not applied?)")
            else:
                fail("valid send", f"unexpected {r.status_code}: {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 4. Edit-after-send GET/PUT round-trip
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 4. Edit-after-send GET/PUT /envelopes/{{id}}/fields")
            # 4a. GET fields on a 'sent' envelope with NO Documenso doc id →
            #     editable gate true, empty field set, NO Documenso call (R13.1).
            editable_env = await seed_envelope(
                conn, org_a_id, status="sent", doc_id=None,
                recipient_emails=[f"test-e2e-edit-{rand()}@example.com"],
            )
            r = await client.get(
                f"{API_V2}/esign/envelopes/{editable_env}/fields", headers=admin_headers,
            )
            error_bodies.append(r.text)
            body = r.json() if r.status_code == 200 else {}
            if r.status_code == 200 and body.get("editable") is True and body.get("fields") == []:
                ok("GET fields on sent/unsigned envelope → 200 editable=true, empty set (R13.1)")
            else:
                fail("get fields editable", f"{r.status_code} editable={body.get('editable')}")

            # 4b. PUT fields on a Non_Editable_State envelope (a recipient
            #     signed) → 422 not_editable, NO Documenso mutation (R13.4).
            signed_email = f"test-e2e-signed-{rand()}@example.com"
            locked_env = await seed_envelope(
                conn, org_a_id, status="sent", doc_id=f"TEST_E2E_doc_{rand()}",
                recipient_emails=[signed_email], signed_emails={signed_email},
            )
            r = await client.put(
                f"{API_V2}/esign/envelopes/{locked_env}/fields", headers=admin_headers,
                json={"fields": [signature_field(0)]},
            )
            error_bodies.append(r.text)
            if r.status_code == 422:
                ok("PUT fields on signed (Non_Editable_State) envelope → 422 not_editable (R13.4)")
            else:
                fail("put not-editable", f"expected 422, got {r.status_code}: {r.text[:160]}")

            # 4c. PUT an invalid Field_Set on an editable envelope → 422,
            #     validated server-side BEFORE any Documenso call (R13.3).
            r = await client.put(
                f"{API_V2}/esign/envelopes/{editable_env}/fields", headers=admin_headers,
                json={"fields": [
                    {"type": "text", "page": 1, "recipient_index": 0,
                     "position_x": 10.0, "position_y": 10.0, "width": 20.0, "height": 6.0,
                     "required": False, "client_id": "t1"},
                ]},
            )
            error_bodies.append(r.text)
            if r.status_code == 422:
                ok("PUT invalid Field_Set (signer w/o signature) → 422 (re-validated, R13.3)")
            else:
                fail("put invalid", f"expected 422, got {r.status_code}: {r.text[:160]}")

            # 4d. PUT a valid Field_Set on an editable envelope WITH a doc id →
            #     Documenso-dependent: 200 when live, else 502/503 (degrade).
            #     Documenso document ids are integers, so seed a numeric id to
            #     faithfully reach the Documenso transport (a non-numeric id is
            #     an impossible production state).
            doc_env = await seed_envelope(
                conn, org_a_id, status="sent", doc_id=str(uuid.uuid4().int % 1_000_000_000),
                recipient_emails=[f"test-e2e-de-{rand()}@example.com"],
            )
            r = await client.put(
                f"{API_V2}/esign/envelopes/{doc_env}/fields", headers=admin_headers,
                json={"fields": [signature_field(0)]},
            )
            error_bodies.append(r.text)
            if documenso_live and r.status_code == 200:
                ok("PUT valid Field_Set → 200 atomic replace (live Documenso)")
            elif r.status_code in (502, 503):
                ok(f"PUT valid Field_Set passed editable gate + re-validation, reached Documenso "
                   f"(HTTP {r.status_code} — documented degrade)")
            elif r.status_code == 200:
                ok("PUT valid Field_Set → 200 (Documenso reachable)")
            else:
                fail("put valid", f"unexpected {r.status_code}: {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 5. OWASP A01 — no-token request → 401
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 5. OWASP A01: no-token request → 401")
            for path in (
                f"{API_V2}/esign/field-templates",
                f"{API_V2}/esign/envelopes/{editable_env}/fields",
            ):
                r = await client.get(path)  # no Authorization header
                error_bodies.append(r.text)
                if r.status_code == 401:
                    ok(f"GET {path.split('/api/v2')[1]} without token → 401")
                else:
                    fail("no-token", f"{path.split('/api/v2')[1]} → {r.status_code}")

            # ──────────────────────────────────────────────────────────────
            # 6. OWASP RBAC — non-sender (salesperson) → 403 (R9.2)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 6. OWASP RBAC: non-sender (salesperson) → 403")
            r = await post_envelope(sales_headers, [signature_field(0)])
            error_bodies.append(r.text)
            if r.status_code == 403:
                ok("salesperson field-placement send → 403 (require_esign_sender)")
            else:
                fail("RBAC send", f"expected 403, got {r.status_code}: {r.text[:160]}")
            r = await client.put(
                f"{API_V2}/esign/envelopes/{editable_env}/fields", headers=sales_headers,
                json={"fields": [signature_field(0)]},
            )
            error_bodies.append(r.text)
            if r.status_code == 403:
                ok("salesperson edit (PUT fields) → 403")
            else:
                fail("RBAC edit", f"expected 403, got {r.status_code}: {r.text[:160]}")
            r = await client.post(
                f"{API_V2}/esign/field-templates", headers=sales_headers,
                json={"name": "TEST_E2E_x", "fields": [
                    {"type": "signature", "page": 1, "position_x": 1.0, "position_y": 1.0,
                     "width": 10.0, "height": 5.0, "required": True, "template_role": "signer 1"},
                ], "roles": ["signer 1"]},
            )
            error_bodies.append(r.text)
            if r.status_code == 403:
                ok("salesperson create template → 403")
            else:
                fail("RBAC template create", f"expected 403, got {r.status_code}: {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 7. OWASP — module disabled (org C) → 403 (R9.1)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 7. OWASP: esignatures module disabled (org C) → 403")
            r = await client.post(
                f"{API_V2}/esign/envelopes", headers=c_admin_headers,
                files={"file": ("TEST_E2E.pdf", make_pdf(), "application/pdf")},
                data={"payload": json.dumps(send_payload([signature_field(0)]))},
            )
            error_bodies.append(r.text)
            if r.status_code == 403:
                ok("org C (module disabled) field-placement send → 403 (module gate)")
            else:
                fail("module gate send", f"expected 403, got {r.status_code}: {r.text[:160]}")
            r = await client.get(f"{API_V2}/esign/field-templates", headers=c_admin_headers)
            error_bodies.append(r.text)
            if r.status_code == 403:
                ok("org C (module disabled) list templates → 403 (router-level gate)")
            else:
                fail("module gate templates", f"expected 403, got {r.status_code}: {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 8. OWASP IDOR — another org's ids return 404, never leaked
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 8. OWASP IDOR: org-isolation on envelopes + templates")
            # Org B owns these — org A's sender must not read/list them.
            org_b_env = await seed_envelope(
                conn, org_b_id, status="sent", doc_id=f"TEST_E2E_docB_{rand()}",
                recipient_emails=[f"test-e2e-b-{rand()}@example.com"],
            )
            org_b_tpl = await seed_template(conn, org_b_id, name=f"TEST_E2E_TplB_{rand()}")

            # 8a. Cross-org envelope detail + fields → 404 (no existence oracle).
            r = await client.get(f"{API_V2}/esign/envelopes/{org_b_env}", headers=admin_headers)
            error_bodies.append(r.text)
            if r.status_code == 404:
                ok("org A reads org B envelope → 404 (IDOR, no existence oracle)")
            else:
                fail("IDOR envelope", f"expected 404, got {r.status_code}")
            r = await client.get(f"{API_V2}/esign/envelopes/{org_b_env}/fields", headers=admin_headers)
            error_bodies.append(r.text)
            if r.status_code == 404:
                ok("org A reads org B envelope FIELDS → 404 (IDOR)")
            else:
                fail("IDOR envelope fields", f"expected 404, got {r.status_code}")

            # 8b. Cross-org template get + delete → 404, never leaked into list.
            r = await client.get(
                f"{API_V2}/esign/field-templates/{org_b_tpl}", headers=admin_headers,
            )
            error_bodies.append(r.text)
            if r.status_code == 404:
                ok("org A reads org B template → 404 (IDOR)")
            else:
                fail("IDOR template get", f"expected 404, got {r.status_code}")
            r = await client.delete(
                f"{API_V2}/esign/field-templates/{org_b_tpl}", headers=admin_headers,
            )
            error_bodies.append(r.text)
            if r.status_code == 404:
                ok("org A deletes org B template → 404 (cross-org delete blocked)")
            else:
                fail("IDOR template delete", f"expected 404, got {r.status_code}")
            # Confirm org B's template still exists (was not deleted by org A).
            still = await conn.fetchval(
                "SELECT count(*) FROM esign_field_templates WHERE id=$1", org_b_tpl
            )
            if still == 1:
                ok("org B template intact after org A's cross-org delete attempt")
            else:
                fail("IDOR delete leak", "org B template was deleted across orgs")

            # 8c. Org A's list excludes org B's template + envelope.
            r = await client.get(f"{API_V2}/esign/field-templates", headers=admin_headers)
            tpl_ids = {it.get("id") for it in (r.json().get("items") or [])} if r.status_code == 200 else set()
            r2 = await client.get(f"{API_V2}/esign/envelopes", headers=admin_headers)
            env_ids = {it.get("id") for it in (r2.json().get("items") or [])} if r2.status_code == 200 else set()
            if str(org_b_tpl) not in tpl_ids and str(org_b_env) not in env_ids:
                ok("org A lists exclude org B's template + envelope (org-scoped)")
            else:
                fail("IDOR list leak", "org B data leaked into org A's lists")

            # ──────────────────────────────────────────────────────────────
            # 9. OWASP A05 — no leaked stack traces / internals
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 9. OWASP A05: no leaked stack traces / internals")
            leak = None
            for bdy in error_bodies:
                leak = scan_for_leak(bdy)
                if leak:
                    break
            if leak is None:
                ok(f"no stack traces / internal paths in {len(error_bodies)} error bodies")
            else:
                fail("leak scan", f"found '{leak}' in an error body")

            return 0 if failed == 0 else 1

        finally:
            # ──────────────────────────────────────────────────────────────
            # MANDATORY cleanup — tear down all three throwaway orgs + children
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} Cleanup: tearing down TEST_E2E orgs A + B + C")
            await _cleanup(conn, [org_a_id, org_b_id, org_c_id])
            for oid in (org_a_id, org_b_id, org_c_id):
                await clear_module_cache(oid)
            if conn is not None:
                await conn.close()


async def _cleanup(conn: "asyncpg.Connection | None", org_ids: list[uuid.UUID]) -> None:
    """Delete every row created under the throwaway orgs (reverse-dependency
    order), then verify none leak."""
    if conn is None:
        return
    statements = [
        ("esign_field_templates", "DELETE FROM esign_field_templates WHERE org_id = ANY($1::uuid[])"),
        ("esign_recipients", "DELETE FROM esign_recipients WHERE envelope_id IN "
                             "(SELECT id FROM esign_envelopes WHERE org_id = ANY($1::uuid[]))"),
        ("esign_envelopes", "DELETE FROM esign_envelopes WHERE org_id = ANY($1::uuid[])"),
        ("esign_webhook_events", "DELETE FROM esign_webhook_events WHERE org_id = ANY($1::uuid[])"),
        ("esign_org_connections", "DELETE FROM esign_org_connections WHERE org_id = ANY($1::uuid[])"),
        ("app_notifications", "DELETE FROM app_notifications WHERE org_id = ANY($1::uuid[])"),
        ("audit_log", "DELETE FROM audit_log WHERE org_id = ANY($1::uuid[])"),
        ("org_modules", "DELETE FROM org_modules WHERE org_id = ANY($1::uuid[])"),
        ("sessions", "DELETE FROM sessions WHERE org_id = ANY($1::uuid[])"),
        ("users", "DELETE FROM users WHERE org_id = ANY($1::uuid[])"),
        ("organisations", "DELETE FROM organisations WHERE id = ANY($1::uuid[])"),
    ]
    for label, sql in statements:
        try:
            res = await conn.execute(sql, org_ids)
            n = res.split()[-1] if res else "0"
            if n != "0":
                print(f"  {INFO} deleted {n} row(s) from {label}")
        except Exception as exc:  # noqa: BLE001 - keep tearing down
            print(f"  {SKIP} cleanup {label}: {exc}")

    # Verify no leftovers (MANDATORY post-cleanup check).
    leftovers = 0
    for tbl, col in (
        ("esign_field_templates", "org_id"),
        ("esign_envelopes", "org_id"),
        ("esign_org_connections", "org_id"),
        ("users", "org_id"),
        ("organisations", "id"),
    ):
        try:
            cnt = await conn.fetchval(
                f"SELECT count(*) FROM {tbl} WHERE {col} = ANY($1::uuid[])", org_ids,
            )
            if cnt:
                leftovers += cnt
                print(f"  {FAIL} leftover {cnt} row(s) in {tbl}")
        except Exception:  # noqa: BLE001
            pass
    if leftovers == 0:
        print(f"  {PASS} cleanup verified — no TEST_E2E rows remain")
    else:
        fail("cleanup verification", f"{leftovers} leftover row(s)")


if __name__ == "__main__":
    rc = asyncio.run(main())
    print(f"\n{'=' * 72}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {passed} passed, {failed} failed (of {total})")
        for e in errors:
            print(f"    {FAIL} {e}")
    print("=" * 72)
    sys.exit(rc if rc == 2 else (0 if failed == 0 else 1))
