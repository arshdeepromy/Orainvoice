---
inclusion: auto
---

# Feature Testing Workflow

Every new feature, module, or option MUST be tested end-to-end using Python scripts that emulate real user interactions before it is considered complete. This is mandatory — no feature ships without a passing test script.

## When to Run This Workflow

- After implementing any new feature, page, or module
- After fixing a bug that changes user-facing behaviour
- After modifying API endpoints, database schemas, or business logic
- Before deploying to production

## Test Script Requirements

### Location and Naming

- Test scripts go in `scripts/` with prefix `test_` (e.g. `scripts/test_purchase_orders_e2e.py`)
- Scripts run inside the app container: `docker exec invoicing-app-1 python scripts/test_xxx.py`
- Base URL for API calls: `http://localhost:8000` (direct to uvicorn, bypasses nginx)

### Structure

Every test script must follow this pattern:

```python
"""
End-to-end test: [Feature Name]

Emulates a user clicking through the full workflow:
1. [Step description]
2. [Step description]
...

Usage:
    docker exec invoicing-app-1 python scripts/test_feature_e2e.py
"""

import asyncio
import sys
import httpx

BASE = "http://localhost:8000"

# Test accounts
DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"
ADMIN_EMAIL = "admin@orainvoice.com"
ADMIN_PASSWORD = "admin123"

passed = 0
failed = 0
errors = []

def ok(label: str):
    global passed
    passed += 1
    print(f"  ✅ {label}")

def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    msg = f"  ❌ {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    errors.append(f"{label}: {detail}")

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as client:
        # Step 1: Login (emulate user entering credentials)
        # Step 2: Navigate to page (emulate GET requests the frontend makes)
        # Step 3: Fill form and submit (emulate POST/PUT with exact payload frontend sends)
        # Step 4: Verify response matches expected
        # Step 5: Verify database state (use asyncpg direct query)
        # Step 6: Clean up test data
        pass

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
```

### What Each Test Must Cover

#### 1. Authentication Flow
- Login as the appropriate user role (org_admin for most features, global_admin for platform features)
- Verify the access token is returned
- Use the token for all subsequent requests

#### 2. Read Operations (emulate page load)
- GET the list endpoint (what the frontend fetches when the page loads)
- Verify response structure matches what the frontend expects
- Verify pagination works (if applicable)
- Verify filters work (if applicable)

#### 3. Create Operations (emulate form submission)
- POST with the exact payload the frontend sends (check `buildPayload` or form submit handler)
- Verify 201/200 response with correct data
- Verify the created record appears in subsequent GET requests
- Verify database state via direct asyncpg query

#### 4. Update Operations (emulate edit + save)
- PUT with modified fields
- Verify response reflects changes
- Verify database state

#### 5. Delete Operations (emulate delete button click)
- DELETE the record
- Verify it's gone from GET list
- Verify database state
- Test FK violation handling (try deleting something that's referenced)

#### 6. Edge Cases
- Empty/missing required fields → expect 422
- Invalid data types → expect 422
- Duplicate entries (if uniqueness is enforced)
- Unauthorized access (wrong role) → expect 401/403
- Non-existent IDs → expect 404

#### 7. Database Verification
- Use asyncpg to directly query the database after each write operation
- Verify the row exists with correct values
- Verify related tables are updated (e.g. stock levels after invoice)
- Connection string: `host='postgres', port=5432, user='postgres', password='postgres', database='workshoppro'`

### OWASP Top 10 Security Checks

Every test script MUST include these security checks relevant to the feature:

#### A1: Broken Access Control
- Try accessing the endpoint without a token → expect 401
- Try accessing org A's data with org B's token → expect 403 or empty results
- Try accessing admin-only endpoints with a salesperson token → expect 403
- Try IDOR: use a valid token but request another org's resource by ID

#### A2: Cryptographic Failures
- Verify sensitive data (passwords, tokens) is never returned in API responses
- Verify PII is not logged in error responses

#### A3: Injection
- Send SQL injection payloads in text fields (e.g. `'; DROP TABLE --`)
- Send XSS payloads in text fields (e.g. `<script>alert(1)</script>`)
- Verify they're stored safely and don't cause errors

#### A4: Insecure Design
- Verify rate limiting on sensitive endpoints (login, signup)
- Verify business logic can't be bypassed (e.g. can't mark invoice as paid without payment)

#### A5: Security Misconfiguration
- Verify error responses don't leak stack traces or internal paths
- Verify CORS headers are correct

#### A7: Authentication Failures
- Verify expired/invalid tokens are rejected
- Verify token refresh works correctly

#### A8: Data Integrity
- Verify totals are calculated correctly (subtotal, tax, total)
- Verify stock levels change correctly after operations
- Verify audit logs are created for sensitive operations

### Cleanup — MANDATORY

**Every test script MUST clean up ALL data it creates.** This is non-negotiable. Previous test runs left 42 "Preservation Test Org" organisations and 66 "Test Plan" subscription plans in the dev database, requiring manual SQL cleanup. This must never happen again.

**Rules:**

1. **Track every created resource ID** — maintain a list of IDs created during the test (org IDs, plan IDs, customer IDs, etc.)
2. **Delete in reverse dependency order** — child records first (invoices, customers, users, branches), then parent records (organisations, plans)
3. **Use a `finally` block** — cleanup must run even if the test fails or crashes:
   ```python
   created_ids = {"orgs": [], "plans": [], "customers": []}
   try:
       # ... test logic that appends to created_ids ...
   finally:
       await cleanup(client, created_ids)
   ```
4. **Use a recognizable prefix** — all test data names MUST start with `TEST_E2E_` (e.g., `TEST_E2E_Org_1234`, `TEST_E2E_Plan_abc`)
5. **Verify cleanup succeeded** — after cleanup, query the database to confirm no test records remain:
   ```python
   # Verify no orphaned test data
   resp = await client.get("/admin/organisations", headers=headers)
   remaining = [o for o in resp.json().get("organisations", []) if o["name"].startswith("TEST_E2E_")]
   if remaining:
       fail(f"Cleanup incomplete: {len(remaining)} test orgs remain")
   ```
6. **Never create data without a cleanup path** — if an API doesn't have a DELETE endpoint, use direct SQL via asyncpg to clean up
7. **Property-based tests (Hypothesis)** — use mocks instead of hitting the real database. If they must create real data, use pytest fixtures with `yield` and cleanup in the teardown

**If cleanup fails, the test MUST report it as a failure** — not silently continue. Orphaned test data is a bug.

## Running Tests

### Single feature test
```bash
docker exec invoicing-app-1 python scripts/test_feature_e2e.py
```

### All e2e tests
```bash
docker exec invoicing-app-1 bash -c "for f in scripts/test_*_e2e.py; do echo '--- Running $f ---'; python $f; done"
```

## Existing Test Scripts (Reference)

- `scripts/test_global_branding_e2e.py` — Platform branding CRUD + public endpoint
- `scripts/test_catalogue_parts.py` — Parts catalogue create/update flow
- `scripts/test_storage_packages_e2e.py` — Storage addon purchase/resize/remove

## After Testing

1. If all tests pass: feature is ready for review
2. If tests fail: fix the issue, re-run the test, update the issue tracker if it's a bug
3. Commit the test script alongside the feature code
4. The test script serves as living documentation of the feature's expected behaviour
