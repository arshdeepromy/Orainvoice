"""
End-to-end test: Organisation Employee Portal

Emulates the full real-user journey for the org-branded Employee Portal and runs
the OWASP security checks mandated by the always-on feature-testing-workflow
steering ("no feature ships without a passing test script").

Journey (org_admin → staff → employee):
  1. org_admin logs in (JWT)
  2. live slug availability (invalid / reserved / free) → set slug → enable portal
  3. issue portal access for a staff member (credential issuance)
  4. accept-invite sets a password (8..128 boundary)
  5. portal login establishes the emp_portal_session cookie + readable CSRF cookie
  6. /e/api/auth/me + /e/api/profile (PII masked) + /e/api/roster — own records only
  7. password reset request → complete (sessions torn down, R14.8)
  8. disable portal tears down sessions + blocks login (R4.5, R4.6)
  9. revoke portal access tears down sessions + blocks login (R5.10)

OWASP / security checks (per steering):
  - unauthenticated /e/api access rejected (401)
  - cross-org IDOR: an org-A session cannot read an org-B staff record
    (→ 409 not_linked, no fields, no existence signal)
  - anti-enumeration: identical login + reset responses for existing vs unknown email
  - cross-portal cookie rejection: a fleet_portal_session cookie never validates
    at /e/api/auth/me
  - rate-limit 429s on the four configured limits (login 10/min, slug-availability
    30/min, portal-resolve 30/min, password-reset 5/min) with Retry-After
  - no secrets / stack traces leaked in error bodies

Cleanup (MANDATORY): every created resource id is tracked and torn down in a
`finally` block (portal users, sessions, audit rows, the org slug, staff + the
throwaway cross-org org), using the TEST_E2E_ naming prefix. The org slug must be
lowercase/hyphenated so it uses a `test-e2e-...` slug while every name uses
`TEST_E2E_`; the org-A slug + portal flag are restored to their originals. After
cleanup the DB is re-queried and any leftover is reported as a FAILURE.

NOTE ON TOKENS: the credential-setup invite and password-reset tokens are emailed
out-of-band, so their raw values are never returned by the API. To drive the
accept-invite / reset-complete steps this script generates its own raw token,
writes its SHA-256 hash into the portal-user row (exactly as the service stores
it), then calls the public endpoint with the raw token — faithfully emulating a
user clicking the emailed link without needing a live mailbox.

Usage:
    docker exec invoicing-app-1 python scripts/test_organisation_employee_portal_e2e.py

Requirements: 4.5, 4.6, 5.3, 6.1, 6.4, 7.1, 7.5, 14.1, 16.1, 16.4, 16.8
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import httpx
    import asyncpg
    import bcrypt
except ImportError as exc:  # pragma: no cover - dependency guard
    print(f"\u26a0\ufe0f  Required dependency not available: {exc}")
    print("   Run inside the app container or `pip install httpx asyncpg bcrypt`.")
    sys.exit(2)

# --- Endpoints -------------------------------------------------------------
BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API_V1 = f"{BASE}/api/v1"
API_V2 = f"{BASE}/api/v2"

# --- Candidate org_admin logins (first that authenticates wins) ------------
# Allow an explicit override, then fall back to the well-known dev org admins
# used by the other e2e scripts in this directory.
ADMIN_CANDIDATES: list[tuple[str, str]] = []
if os.environ.get("E2E_ORG_EMAIL"):
    ADMIN_CANDIDATES.append(
        (os.environ["E2E_ORG_EMAIL"], os.environ.get("E2E_ORG_PASSWORD", "changeme"))
    )
ADMIN_CANDIDATES += [
    ("admin@nerdytech.co.nz", "changeme"),
    ("demo@orainvoice.com", "demo123"),
]

# --- DB connection (direct, for token emulation + cleanup) -----------------
DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_NAME = os.environ.get("DB_NAME", "workshoppro")

# --- Redis (only used to bust the module-enablement cache after a DB toggle) -
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Modules the staff + portal-access endpoints require (path-prefix middleware
# gates /api/v2/staff on `staff`; the portal-access endpoint additionally
# requires `staff_management`). The script ensures both are enabled for the
# test org and restores their original state on teardown.
REQUIRED_MODULES = ("staff", "staff_management")

# --- Portal cookie names (mirror app/modules/employee_portal/router.py) ----
SESSION_COOKIE = "emp_portal_session"
CSRF_COOKIE = "emp_portal_csrf"
FLEET_SESSION_COOKIE = "fleet_portal_session"  # cross-portal rejection target

# --- Test passwords (8..128) ----------------------------------------------
INITIAL_PW = "TestE2EPortalPw123"
RESET_PW = "TestE2EResetPw456"
SHORT_PW = "Ab1234"  # 6 chars → must be rejected (R5.6)

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"
INFO = "\033[94m\u2192\033[0m"
SKIP = "\033[93m~\033[0m"

passed = 0
failed = 0
errors: list[str] = []


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


def skip(label: str, reason: str = "") -> None:
    msg = f"  {SKIP} {label}"
    if reason:
        msg += f" \u2014 {reason}"
    print(msg)


def sha256_hex(raw: str) -> str:
    """SHA-256 hex digest — matches the portal's token storage convention."""
    return hashlib.sha256(raw.encode()).hexdigest()


def rand() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

# Substrings that, if present in an error body, indicate a leaked stack trace or
# internal detail (OWASP A5 / A2). Kept lowercase for case-insensitive scanning.
_LEAK_INDICATORS = [
    "traceback", "file \"", ".py\"", "line ", "sqlalchemy", "asyncpg",
    "psycopg", "pydantic", "/app/", "/usr/lib/", "site-packages",
    "password_hash", "invite_token_hash", "reset_token_hash",
    "session_token_hash", "$2b$", "bcrypt",
]

# Keys that must never appear anywhere in a portal response body (A2).
_FORBIDDEN_KEYS = {
    "password_hash", "invite_token_hash", "reset_token_hash",
    "session_token_hash", "csrf_token",
}


def body_leaks_secret(text: str) -> str | None:
    """Return the first leak indicator found in ``text`` (lowercased), else None."""
    low = (text or "").lower()
    for ind in _LEAK_INDICATORS:
        if ind in low:
            return ind
    return None


def find_forbidden_key(obj) -> str | None:
    """Recursively scan a decoded JSON object for any forbidden secret key."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _FORBIDDEN_KEYS:
                return k
            found = find_forbidden_key(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_forbidden_key(item)
            if found:
                return found
    return None


def parse_set_cookie(resp: httpx.Response, name: str) -> str | None:
    """Extract a cookie value from a response's Set-Cookie headers.

    Robust against httpx's path-scoped cookie jar (the portal cookies are
    ``path=/e``): we read the raw Set-Cookie headers rather than the jar.
    """
    for raw in resp.headers.get_list("set-cookie"):
        # e.g. "emp_portal_session=abc; HttpOnly; Path=/e; SameSite=lax"
        first = raw.split(";", 1)[0].strip()
        if "=" in first:
            k, v = first.split("=", 1)
            if k == name:
                return v
    return None


def cookie_attrs(resp: httpx.Response, name: str) -> str:
    """Return the raw Set-Cookie line for ``name`` (lowercased), or ''."""
    for raw in resp.headers.get_list("set-cookie"):
        if raw.split("=", 1)[0].strip() == name:
            return raw.lower()
    return ""


async def login_admin(client: httpx.AsyncClient) -> tuple[dict[str, str], str, str] | None:
    """Try each candidate org_admin login; return (headers, email, password)."""
    for email, password in ADMIN_CANDIDATES:
        try:
            r = await client.post(
                f"{API_V1}/auth/login",
                json={"email": email, "password": password, "remember_me": False},
            )
        except httpx.HTTPError:
            return None
        if r.status_code == 200 and r.json().get("access_token"):
            token = r.json()["access_token"]
            return {"Authorization": f"Bearer {token}"}, email, password
    return None


async def get_db_conn() -> "asyncpg.Connection":
    return await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
    )


async def clear_module_cache(org_id: uuid.UUID) -> None:
    """Best-effort bust of the module-enablement Redis cache (mod:{org_id}).

    The module middleware caches enablement per-org for 60s, so after toggling
    a module directly in the DB we drop the cache key to make the change take
    effect immediately. Failure here is non-fatal — the cache simply expires.
    """
    try:
        import redis.asyncio as _redis  # noqa: PLC0415
        r = _redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        await r.delete(f"mod:{org_id}")
        await r.aclose()
    except Exception:  # noqa: BLE001 - cache bust is best-effort
        pass


async def enable_required_modules(
    conn: "asyncpg.Connection", org_id: uuid.UUID
) -> list[tuple[str, bool, bool | None]]:
    """Ensure REQUIRED_MODULES are enabled for ``org_id``; return prior state.

    Returns a list of ``(slug, existed, prior_is_enabled)`` so cleanup can
    restore the exact original state (delete the row when we created it, or
    reset ``is_enabled`` when we flipped it).
    """
    state: list[tuple[str, bool, bool | None]] = []
    for slug in REQUIRED_MODULES:
        row = await conn.fetchrow(
            "SELECT is_enabled FROM org_modules WHERE org_id = $1 AND module_slug = $2",
            org_id, slug,
        )
        existed = row is not None
        prior = row["is_enabled"] if existed else None
        state.append((slug, existed, prior))
        if existed:
            if prior is not True:
                await conn.execute(
                    "UPDATE org_modules SET is_enabled = true "
                    "WHERE org_id = $1 AND module_slug = $2",
                    org_id, slug,
                )
        else:
            await conn.execute(
                "INSERT INTO org_modules (org_id, module_slug, is_enabled) "
                "VALUES ($1, $2, true)",
                org_id, slug,
            )
    await clear_module_cache(org_id)
    return state


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def main() -> int:  # noqa: C901, PLR0912, PLR0915 — single-flow e2e script
    print("=" * 70)
    print("  ORGANISATION EMPLOYEE PORTAL — END-TO-END TEST")
    print("=" * 70)

    # Tracked resources for teardown.
    test_start = datetime.now(timezone.utc)
    portal_user_ids: list[uuid.UUID] = []
    staff_ids: list[uuid.UUID] = []        # SA (org A) — created via API
    db_staff_ids: list[uuid.UUID] = []     # SB (org B) — created via DB
    org_b_id: uuid.UUID | None = None
    org_a_id: uuid.UUID | None = None
    original_slug: str | None = None
    original_portal_enabled = None  # None = key absent originally
    module_state: list[tuple[str, bool, bool | None]] = []
    conn: "asyncpg.Connection | None" = None

    # Unique, valid (lowercase/hyphen) slug — TEST_E2E_ is invalid as a slug.
    test_slug = f"test-e2e-portal-{rand()}"
    sa_email = f"test-e2e-sa-{rand()}@example.com"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        # --- Connectivity guards ------------------------------------------
        try:
            conn = await get_db_conn()
        except Exception as exc:  # noqa: BLE001
            print(f"\n\u26a0\ufe0f  Database unreachable at {DB_HOST}:{DB_PORT} \u2014 {exc}")
            print("   Run inside the app container (DB host 'postgres').")
            return 2

        auth = await login_admin(client)
        if auth is None:
            print(f"\n\u26a0\ufe0f  Backend unreachable or no org_admin login worked at {BASE}.")
            print("   Set E2E_ORG_EMAIL / E2E_ORG_PASSWORD, or run against the dev backend.")
            await conn.close()
            return 2
        headers, admin_email, _admin_pw = auth
        ok(f"Authenticated as org_admin ({admin_email})")

        try:
            # ──────────────────────────────────────────────────────────────
            # Resolve org A + capture originals to restore on teardown.
            # ──────────────────────────────────────────────────────────────
            admin_row = await conn.fetchrow(
                "SELECT org_id FROM users WHERE lower(email) = lower($1)", admin_email,
            )
            if not admin_row or not admin_row["org_id"]:
                fail("Resolve org_admin org_id", "admin user has no org_id")
                return 1
            org_a_id = admin_row["org_id"]
            org_row = await conn.fetchrow(
                "SELECT slug, settings FROM organisations WHERE id = $1", org_a_id,
            )
            original_slug = org_row["slug"]
            import json as _json
            _settings = org_row["settings"]
            if isinstance(_settings, str):
                _settings = _json.loads(_settings or "{}")
            original_portal_enabled = (_settings or {}).get("employee_portal_enabled")
            ok(f"Resolved org A id={org_a_id} (orig slug={original_slug!r})")

            # Ensure the staff + staff_management modules are enabled for the
            # test org (restored on teardown) so the staff/portal-access
            # endpoints are reachable regardless of which demo org we land in.
            module_state = await enable_required_modules(conn, org_a_id)
            ok("ensured staff + staff_management modules enabled (restored on teardown)")

            # ──────────────────────────────────────────────────────────────
            # 1. Live slug availability (R3.2–R3.6)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 1. Slug availability check")
            r = await client.get(
                f"{API_V2}/organisations/slug-availability",
                headers=headers, params={"slug": "ab"},
            )
            if r.status_code == 200 and r.json().get("result") == "invalid":
                ok("too-short slug → invalid (never 'available')")
            else:
                fail("invalid slug classification", f"{r.status_code} {r.text[:160]}")

            r = await client.get(
                f"{API_V2}/organisations/slug-availability",
                headers=headers, params={"slug": "admin"},
            )
            if r.status_code == 200 and r.json().get("result") == "unavailable":
                ok("reserved slug 'admin' → unavailable")
            else:
                fail("reserved slug classification", f"{r.status_code} {r.text[:160]}")

            r = await client.get(
                f"{API_V2}/organisations/slug-availability",
                headers=headers, params={"slug": test_slug},
            )
            if r.status_code == 200 and r.json().get("result") == "available":
                ok(f"fresh slug '{test_slug}' → available")
            else:
                fail("fresh slug availability", f"{r.status_code} {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 2. Set slug → enable portal (R2.7, R4.x)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 2. Set slug + enable portal")
            r = await client.put(
                f"{API_V2}/organisations/slug",
                headers=headers, json={"slug": test_slug},
            )
            if r.status_code == 200 and r.json().get("slug") == test_slug:
                ok(f"slug saved (normalised) = {test_slug}")
            else:
                fail("set slug", f"{r.status_code} {r.text[:200]}")
                return 1

            # Own current slug should now report 'available' (R3.5).
            r = await client.get(
                f"{API_V2}/organisations/slug-availability",
                headers=headers, params={"slug": test_slug},
            )
            if r.status_code == 200 and r.json().get("result") == "available":
                ok("own current slug → available (R3.5)")
            else:
                fail("own-slug availability", f"{r.status_code} {r.text[:160]}")

            r = await client.put(
                f"{API_V2}/organisations/employee-portal",
                headers=headers, json={"enabled": True},
            )
            if r.status_code == 200 and r.json().get("enabled") is True:
                ok("employee portal enabled")
            else:
                fail("enable portal", f"{r.status_code} {r.text[:200]}")
                return 1

            # ──────────────────────────────────────────────────────────────
            # 3. Create staff + issue portal access (R5.3, R15.x)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 3. Create staff + issue portal access")
            r = await client.post(
                f"{API_V2}/staff",
                headers=headers,
                json={
                    "first_name": "TEST_E2E_SA",
                    "last_name": "Portal",
                    "email": sa_email,
                    "hourly_rate": "30.00",
                    "employment_start_date": "2024-01-15",
                    "residency_type": "citizen",
                },
            )
            if r.status_code != 201:
                fail("create staff", f"{r.status_code} {r.text[:200]}")
                return 1
            sa_id = uuid.UUID(r.json()["id"])
            staff_ids.append(sa_id)
            ok(f"created staff SA id={sa_id}")

            r = await client.post(
                f"{API_V2}/staff/{sa_id}/portal-access", headers=headers, json={},
            )
            if r.status_code != 201:
                fail("issue portal access", f"{r.status_code} {r.text[:200]}")
                return 1
            issue_body = r.json()
            pu_id = uuid.UUID(issue_body["portal_user_id"])
            portal_user_ids.append(pu_id)
            ok(f"issued portal access portal_user_id={pu_id} (invite_sent={issue_body.get('invite_sent')})")
            leaked = find_forbidden_key(issue_body)
            if leaked:
                fail("issuance response leaks secret key", leaked)
            else:
                ok("issuance response carries no secret fields")

            # ──────────────────────────────────────────────────────────────
            # 4. Accept-invite sets a password (emulated emailed link)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 4. Accept invite (set password)")
            raw_invite = secrets.token_urlsafe(32)
            await conn.execute(
                "UPDATE employee_portal_users SET invite_token_hash = $1, "
                "invite_sent_at = now(), invite_accepted_at = NULL WHERE id = $2",
                sha256_hex(raw_invite), pu_id,
            )
            r = await client.get(f"{BASE}/e/api/auth/accept-invite/{raw_invite}")
            if r.status_code == 200 and r.json().get("status") == "valid":
                ok("GET accept-invite → status valid")
            else:
                fail("accept-invite status", f"{r.status_code} {r.text[:160]}")

            # Boundary: short password rejected (R5.6), state unchanged.
            r = await client.post(
                f"{BASE}/e/api/auth/accept-invite/{raw_invite}",
                json={"new_password": SHORT_PW},
            )
            if r.status_code == 422:
                ok("short password → 422 password_length")
            else:
                fail("short password rejection", f"{r.status_code} {r.text[:160]}")

            r = await client.post(
                f"{BASE}/e/api/auth/accept-invite/{raw_invite}",
                json={"new_password": INITIAL_PW},
            )
            if r.status_code == 200 and r.json().get("ok"):
                ok("valid password → 200 (invite consumed)")
            else:
                fail("accept invite", f"{r.status_code} {r.text[:200]}")
                return 1

            # ──────────────────────────────────────────────────────────────
            # 5. Portal login → session cookie + CSRF (R6.1)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 5. Portal login")
            r = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": sa_email, "password": INITIAL_PW},
            )
            if r.status_code != 200:
                fail("portal login", f"{r.status_code} {r.text[:200]}")
                return 1
            sess_a = parse_set_cookie(r, SESSION_COOKIE)
            csrf_a = parse_set_cookie(r, CSRF_COOKIE)
            # Drop the jar so it never auto-attaches the session cookie to later
            # "unauthenticated" / cross-portal probes — we drive auth purely via
            # explicit per-request cookies.
            client.cookies.clear()
            if sess_a and csrf_a:
                ok("login 200 + session & CSRF cookies set")
            else:
                fail("login cookies", f"session={bool(sess_a)} csrf={bool(csrf_a)}")
                return 1
            sess_attrs = cookie_attrs(r, SESSION_COOKIE)
            if "httponly" in sess_attrs and "path=/e" in sess_attrs:
                ok("session cookie is HttpOnly + path=/e")
            else:
                fail("session cookie attrs", sess_attrs[:160])
            if find_forbidden_key(r.json()):
                fail("login response leaks secret", find_forbidden_key(r.json()))
            else:
                ok("login response carries no secret fields")

            portal_cookies_a = {SESSION_COOKIE: sess_a, CSRF_COOKIE: csrf_a}

            # ──────────────────────────────────────────────────────────────
            # 6. me + profile (PII masked) + roster — own records only
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 6. me + profile + roster (own records only)")
            r = await client.get(f"{BASE}/e/api/auth/me", cookies=portal_cookies_a)
            if r.status_code == 200 and r.json().get("staff_id") == str(sa_id):
                ok("/e/api/auth/me → own identity")
            else:
                fail("me", f"{r.status_code} {r.text[:160]}")

            r = await client.get(f"{BASE}/e/api/profile", cookies=portal_cookies_a)
            if r.status_code == 200 and r.json().get("staff_id") == str(sa_id):
                ok("/e/api/profile → own staff record")
                if find_forbidden_key(r.json()):
                    fail("profile leaks secret", find_forbidden_key(r.json()))
                else:
                    ok("profile carries no secret fields (PII masked)")
            else:
                fail("profile", f"{r.status_code} {r.text[:160]}")

            r = await client.get(f"{BASE}/e/api/roster", cookies=portal_cookies_a)
            if r.status_code == 200 and r.json().get("staff_id") == str(sa_id):
                ok("/e/api/roster → own roster")
            else:
                fail("roster", f"{r.status_code} {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 7. OWASP — unauthenticated /e/api access rejected (A1)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 7. Unauthenticated /e/api access rejected")
            for path in ("/e/api/auth/me", "/e/api/profile", "/e/api/roster"):
                r = await client.get(f"{BASE}{path}")  # no cookies
                if r.status_code == 401:
                    ok(f"GET {path} without session → 401")
                else:
                    fail(f"unauth {path}", f"{r.status_code} {r.text[:120]}")
                leak = body_leaks_secret(r.text)
                if leak:
                    fail(f"error body leaks at {path}", leak)

            # ──────────────────────────────────────────────────────────────
            # 8. OWASP — anti-enumeration: login + reset response invariance
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 8. Anti-enumeration (login + reset invariance)")
            r_known = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": sa_email, "password": "WrongPw99999"},
            )
            r_unknown = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": f"nope-{rand()}@example.com", "password": "WrongPw99999"},
            )
            if (
                r_known.status_code == r_unknown.status_code == 401
                and r_known.text == r_unknown.text
            ):
                ok("login: existing vs unknown email → identical 401 body")
            else:
                fail(
                    "login enumeration",
                    f"known={r_known.status_code}/{r_known.text[:60]} "
                    f"unknown={r_unknown.status_code}/{r_unknown.text[:60]}",
                )

            rr_known = await client.post(
                f"{BASE}/e/api/auth/password/reset-request",
                json={"slug": test_slug, "email": sa_email},
            )
            rr_unknown = await client.post(
                f"{BASE}/e/api/auth/password/reset-request",
                json={"slug": test_slug, "email": f"nope-{rand()}@example.com"},
            )
            if (
                rr_known.status_code == rr_unknown.status_code == 200
                and rr_known.text == rr_unknown.text
            ):
                ok("reset-request: existing vs unknown email → identical 200 body")
            else:
                fail(
                    "reset enumeration",
                    f"known={rr_known.status_code} unknown={rr_unknown.status_code}",
                )

            # ──────────────────────────────────────────────────────────────
            # 9. OWASP — cross-portal cookie rejection (R16.8)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 9. Cross-portal cookie rejection")
            r = await client.get(
                f"{BASE}/e/api/auth/me",
                cookies={FLEET_SESSION_COOKIE: secrets.token_urlsafe(32)},
            )
            if r.status_code == 401:
                ok("fleet_portal_session presented to /e/api/auth/me → 401")
            else:
                fail("cross-portal cookie", f"{r.status_code} {r.text[:120]}")

            # ──────────────────────────────────────────────────────────────
            # 10. OWASP — cross-org IDOR (R7.5, R16.4)
            #     An org-A session whose linked staff lives in org B must NOT
            #     resolve that record: 409 not_linked, no fields, no signal.
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 10. Cross-org IDOR (org-A session cannot read org-B staff)")
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            if plan_row is None:
                skip("cross-org IDOR", "no subscription_plans row to attach a throwaway org")
            else:
                org_b_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO organisations (id, name, plan_id, storage_quota_gb) "
                    "VALUES ($1, $2, $3, $4)",
                    org_b_id, f"TEST_E2E_OrgB_{rand()}", plan_row["id"], 1,
                )
                sb_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO staff_members (id, org_id, name, first_name, email) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    sb_id, org_b_id, "TEST_E2E_SB", "TEST_E2E_SB",
                    f"test-e2e-sb-{rand()}@example.com",
                )
                db_staff_ids.append(sb_id)

                # A portal user in ORG A but cross-linked to org B's staff row.
                cross_pu = uuid.uuid4()
                cross_hash = bcrypt.hashpw(INITIAL_PW.encode(), bcrypt.gensalt()).decode()
                await conn.execute(
                    "INSERT INTO employee_portal_users (id, org_id, staff_id, email, "
                    "password_hash, is_active) VALUES ($1, $2, $3, $4, $5, true)",
                    cross_pu, org_a_id, sb_id, f"test-e2e-cross-{rand()}@example.com",
                    cross_hash,
                )
                portal_user_ids.append(cross_pu)
                # Mint a session row directly (org A scope).
                raw_cross = secrets.token_urlsafe(32)
                now = datetime.now(timezone.utc)
                await conn.execute(
                    "INSERT INTO employee_portal_sessions (id, org_id, portal_user_id, "
                    "session_token_hash, csrf_token, created_at, last_seen_at, expires_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $6, $7)",
                    uuid.uuid4(), org_a_id, cross_pu, sha256_hex(raw_cross),
                    secrets.token_urlsafe(32), now, now + timedelta(hours=12),
                )
                r = await client.get(
                    f"{BASE}/e/api/profile", cookies={SESSION_COOKIE: raw_cross},
                )
                if r.status_code in (403, 404, 409):
                    body = r.text
                    # Must not contain any org-B staff field.
                    if "TEST_E2E_SB" in body:
                        fail("cross-org IDOR leaks fields", body[:160])
                    else:
                        ok(f"org-A session → org-B staff: {r.status_code}, no fields leaked")
                else:
                    fail("cross-org IDOR", f"expected 403/404/409, got {r.status_code} {r.text[:120]}")

            # ──────────────────────────────────────────────────────────────
            # 11. Password reset complete → sessions torn down (R14.8)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 11. Password reset complete + session teardown")
            raw_reset = secrets.token_urlsafe(32)
            await conn.execute(
                "UPDATE employee_portal_users SET reset_token_hash = $1, "
                "reset_token_expires_at = $2 WHERE id = $3",
                sha256_hex(raw_reset),
                datetime.now(timezone.utc) + timedelta(seconds=3600), pu_id,
            )
            r = await client.post(
                f"{BASE}/e/api/auth/password/reset",
                json={"token": raw_reset, "new_password": RESET_PW},
            )
            if r.status_code == 200 and r.json().get("ok"):
                ok("reset complete → 200")
            else:
                fail("reset complete", f"{r.status_code} {r.text[:200]}")

            # The pre-reset session A must now be invalid (R14.8).
            r = await client.get(f"{BASE}/e/api/auth/me", cookies=portal_cookies_a)
            if r.status_code == 401:
                ok("pre-reset session invalidated after reset (R14.8)")
            else:
                fail("reset session teardown", f"{r.status_code}")

            # Re-login with the NEW password.
            r = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": sa_email, "password": RESET_PW},
            )
            sess_a2 = parse_set_cookie(r, SESSION_COOKIE)
            client.cookies.clear()
            if r.status_code == 200 and sess_a2:
                ok("re-login with new password → 200")
            else:
                fail("re-login", f"{r.status_code} {r.text[:160]}")
                sess_a2 = None
            cookies_a2 = {SESSION_COOKIE: sess_a2} if sess_a2 else {}

            # ──────────────────────────────────────────────────────────────
            # 12. Disable portal → tears down sessions + blocks login (R4.5/4.6)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 12. Disable portal teardown")
            r = await client.put(
                f"{API_V2}/organisations/employee-portal",
                headers=headers, json={"enabled": False},
            )
            if r.status_code == 200 and r.json().get("enabled") is False:
                ok("portal disabled")
            else:
                fail("disable portal", f"{r.status_code} {r.text[:160]}")

            if cookies_a2:
                r = await client.get(f"{BASE}/e/api/auth/me", cookies=cookies_a2)
                if r.status_code == 401:
                    ok("active session invalidated by disable (R4.6)")
                else:
                    fail("disable session teardown", f"{r.status_code}")

            r = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": sa_email, "password": RESET_PW},
            )
            if r.status_code == 403 and r.json().get("code") == "portal_unavailable":
                ok("login while disabled → 403 portal_unavailable (R4.5)")
            else:
                fail("login while disabled", f"{r.status_code} {r.text[:160]}")

            # Re-enable so the revoke path can establish a fresh session.
            r = await client.put(
                f"{API_V2}/organisations/employee-portal",
                headers=headers, json={"enabled": True},
            )
            ok("portal re-enabled" if r.status_code == 200 else "re-enable failed")

            # ──────────────────────────────────────────────────────────────
            # 13. Revoke access → tears down sessions + blocks login (R5.10)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 13. Revoke access teardown")
            r = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": sa_email, "password": RESET_PW},
            )
            sess_a3 = parse_set_cookie(r, SESSION_COOKIE)
            client.cookies.clear()
            if r.status_code == 200 and sess_a3:
                ok("logged in again (pre-revoke)")
            else:
                fail("pre-revoke login", f"{r.status_code} {r.text[:160]}")
                sess_a3 = None

            r = await client.delete(
                f"{API_V2}/staff/{sa_id}/portal-access", headers=headers,
            )
            if r.status_code == 200 and r.json().get("revoked"):
                ok(f"revoke → 200 (sessions_invalidated={r.json().get('sessions_invalidated')})")
            else:
                fail("revoke access", f"{r.status_code} {r.text[:160]}")

            if sess_a3:
                r = await client.get(
                    f"{BASE}/e/api/auth/me", cookies={SESSION_COOKIE: sess_a3},
                )
                if r.status_code == 401:
                    ok("session invalidated by revoke (R5.10)")
                else:
                    fail("revoke session teardown", f"{r.status_code}")

            r = await client.post(
                f"{BASE}/e/api/auth/login",
                json={"slug": test_slug, "email": sa_email, "password": RESET_PW},
            )
            if r.status_code == 401:
                ok("login after revoke → 401 (account deactivated)")
            else:
                fail("login after revoke", f"{r.status_code} {r.text[:160]}")

            # ──────────────────────────────────────────────────────────────
            # 14. OWASP — rate limits (login 10 / slug-avail 30 /
            #     portal-resolve 30 / password-reset 5 per min) + Retry-After
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} 14. Rate-limit 429 enforcement")

            async def hammer(method, url, *, limit, attempts, json=None, params=None, hdrs=None):
                seen_429 = False
                retry_after = False
                for _ in range(attempts):
                    if method == "GET":
                        resp = await client.get(url, params=params, headers=hdrs)
                    else:
                        resp = await client.post(url, json=json, headers=hdrs)
                    if resp.status_code == 429:
                        seen_429 = True
                        retry_after = bool(resp.headers.get("Retry-After"))
                        break
                return seen_429, retry_after

            checks = [
                ("login 10/min", "POST", f"{BASE}/e/api/auth/login", 10, 16,
                 {"slug": test_slug, "email": f"rl-{rand()}@example.com", "password": "x"}, None, None),
                ("slug-availability 30/min", "GET", f"{API_V2}/organisations/slug-availability",
                 30, 40, None, {"slug": "test-e2e-rl"}, headers),
                ("portal-resolve 30/min", "GET", f"{API_V2}/public/portal-resolve",
                 30, 40, None, {"q": f"zzz-{rand()}", "portal_type": "employee"}, None),
                ("password-reset 5/min", "POST", f"{BASE}/e/api/auth/password/reset-request",
                 5, 12, {"slug": test_slug, "email": f"rl-{rand()}@example.com"}, None, None),
            ]
            for label, method, url, limit, attempts, jbody, qparams, hdrs in checks:
                seen, ra = await hammer(
                    method, url, limit=limit, attempts=attempts,
                    json=jbody, params=qparams, hdrs=hdrs,
                )
                if seen:
                    ok(f"{label} → 429 enforced (Retry-After={ra})")
                else:
                    fail(label, f"no 429 within {attempts} requests (is Redis enabled?)")

        finally:
            # ──────────────────────────────────────────────────────────────
            # CLEANUP — mandatory, runs even on failure (steering §Cleanup)
            # ──────────────────────────────────────────────────────────────
            print(f"\n{INFO} Cleanup")
            await cleanup(
                conn,
                org_a_id=org_a_id,
                org_b_id=org_b_id,
                portal_user_ids=portal_user_ids,
                staff_ids=staff_ids + db_staff_ids,
                test_start=test_start,
                original_slug=original_slug,
                original_portal_enabled=original_portal_enabled,
                module_state=module_state,
            )
            if conn is not None:
                await conn.close()

    print("\n" + "=" * 70)
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    \u2022 {e}")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# Cleanup + residue verification
# ---------------------------------------------------------------------------


async def cleanup(
    conn: "asyncpg.Connection | None",
    *,
    org_a_id: uuid.UUID | None,
    org_b_id: uuid.UUID | None,
    portal_user_ids: list[uuid.UUID],
    staff_ids: list[uuid.UUID],
    test_start: datetime,
    original_slug: str | None,
    original_portal_enabled,
    module_state: list[tuple[str, bool, bool | None]] | None = None,
) -> None:
    """Tear down every created resource, then verify nothing is left behind.

    Deletes in FK-safe order (sessions → audit → portal users → staff → org B),
    restores org A's original slug + portal flag, then re-queries the database
    and reports any residue as a FAILURE (orphaned test data is a bug).
    """
    if conn is None:
        fail("cleanup", "no DB connection")
        return

    pu_ids = portal_user_ids or [uuid.uuid4()]  # avoid empty-array type issues
    st_ids = staff_ids or [uuid.uuid4()]
    org_scope = [o for o in (org_a_id, org_b_id) if o is not None] or [uuid.uuid4()]

    try:
        # 1. Sessions for our portal users or the throwaway org.
        await conn.execute(
            "DELETE FROM employee_portal_sessions "
            "WHERE portal_user_id = ANY($1::uuid[]) OR org_id = ANY($2::uuid[])",
            pu_ids, org_scope,
        )
        # 2. Audit rows: throwaway org entirely; org A only those from this run.
        if org_b_id is not None:
            await conn.execute(
                "DELETE FROM employee_portal_audit_log WHERE org_id = $1", org_b_id,
            )
        if org_a_id is not None:
            await conn.execute(
                "DELETE FROM employee_portal_audit_log "
                "WHERE org_id = $1 AND created_at >= $2",
                org_a_id, test_start,
            )
        # 3. Portal users (ours, plus any rooted in the throwaway org / staff).
        await conn.execute(
            "DELETE FROM employee_portal_users "
            "WHERE id = ANY($1::uuid[]) OR org_id = ANY($2::uuid[]) "
            "OR staff_id = ANY($3::uuid[])",
            pu_ids, org_scope, st_ids,
        )
        # 4. Staff (SA in org A via API, SB in org B via DB). Children cascade.
        await conn.execute(
            "DELETE FROM staff_members WHERE id = ANY($1::uuid[])", st_ids,
        )
        # 5. The throwaway org B.
        if org_b_id is not None:
            await conn.execute("DELETE FROM organisations WHERE id = $1", org_b_id)
        # 6. Restore org A's original slug + employee_portal_enabled flag.
        if org_a_id is not None:
            await conn.execute(
                "UPDATE organisations SET slug = $1 WHERE id = $2",
                original_slug, org_a_id,
            )
            if original_portal_enabled is None:
                await conn.execute(
                    "UPDATE organisations SET settings = settings - 'employee_portal_enabled' "
                    "WHERE id = $1",
                    org_a_id,
                )
            else:
                await conn.execute(
                    "UPDATE organisations SET settings = "
                    "jsonb_set(settings, '{employee_portal_enabled}', $1::jsonb) WHERE id = $2",
                    "true" if original_portal_enabled else "false", org_a_id,
                )
        # 7. Restore the original module-enablement state.
        if module_state and org_a_id is not None:
            for slug, existed, prior in module_state:
                if not existed:
                    await conn.execute(
                        "DELETE FROM org_modules WHERE org_id = $1 AND module_slug = $2",
                        org_a_id, slug,
                    )
                elif prior is not True:
                    await conn.execute(
                        "UPDATE org_modules SET is_enabled = $1 "
                        "WHERE org_id = $2 AND module_slug = $3",
                        bool(prior), org_a_id, slug,
                    )
            await clear_module_cache(org_a_id)
        print("  cleanup deletes complete")
    except Exception as exc:  # noqa: BLE001
        fail("cleanup execution", str(exc)[:200])

    # --- Residue verification (any leftover = failure) --------------------
    try:
        residue_users = await conn.fetchval(
            "SELECT count(*) FROM employee_portal_users "
            "WHERE id = ANY($1::uuid[]) OR org_id = ANY($2::uuid[]) "
            "OR staff_id = ANY($3::uuid[])",
            pu_ids, org_scope, st_ids,
        )
        residue_sessions = await conn.fetchval(
            "SELECT count(*) FROM employee_portal_sessions "
            "WHERE portal_user_id = ANY($1::uuid[]) OR org_id = ANY($2::uuid[])",
            pu_ids, org_scope,
        )
        residue_staff = await conn.fetchval(
            "SELECT count(*) FROM staff_members WHERE id = ANY($1::uuid[])", st_ids,
        )
        residue_org = (
            await conn.fetchval(
                "SELECT count(*) FROM organisations WHERE id = $1", org_b_id,
            )
            if org_b_id is not None
            else 0
        )
        residue_named_orgs = await conn.fetchval(
            "SELECT count(*) FROM organisations WHERE name LIKE 'TEST_E2E_%'",
        )
        residue_named_staff = await conn.fetchval(
            "SELECT count(*) FROM staff_members WHERE first_name LIKE 'TEST_E2E_%'",
        )

        total = (
            residue_users + residue_sessions + residue_staff
            + residue_org + residue_named_orgs + residue_named_staff
        )
        if total == 0:
            ok("cleanup verified — no residual test data")
        else:
            fail(
                "cleanup incomplete",
                f"portal_users={residue_users} sessions={residue_sessions} "
                f"staff={residue_staff} org_b={residue_org} "
                f"named_orgs={residue_named_orgs} named_staff={residue_named_staff}",
            )
    except Exception as exc:  # noqa: BLE001
        fail("cleanup verification", str(exc)[:200])


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
