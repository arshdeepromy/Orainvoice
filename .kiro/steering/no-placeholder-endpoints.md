---
inclusion: auto
---

# No Placeholder Endpoints

## Problem Statement

When implementing a spec, it's tempting to create endpoint handlers that return hardcoded empty data (e.g. `return {items: [], total: 0}`) and mark the task complete because the route exists and returns the correct response shape. This leads to:

- Frontend pages that render "empty state" permanently because the backend never returns real data.
- Green test suites that verify shape but not substance.
- Duplicated endpoints when an existing module already provides the same feature.

## Rules

### Rule 1: Every list endpoint MUST query the database

If an endpoint is registered and the frontend calls it, it MUST execute a real database query — even if the result set is empty because no data exists yet. "Returns empty items" is acceptable when the DB table is empty. "Returns hardcoded `[]` without querying" is NEVER acceptable.

**Bad:**
```python
@router.get("/")
async def list_things(db: AsyncSession = Depends(get_db_session)):
    # Placeholder — will be wired later
    return {"items": [], "total": 0}
```

**Good:**
```python
@router.get("/")
async def list_things(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Thing).where(Thing.org_id == org_id))
    items = list(result.scalars().all())
    return {"items": [serialize(t) for t in items], "total": len(items)}
```

### Rule 2: Check for existing endpoints before creating new ones

Before creating any endpoint, search the codebase for:
1. An existing endpoint that serves the same data (grep for the table name in all router files)
2. An existing service function that queries what you need
3. An existing frontend component that already calls a similar endpoint

If an existing endpoint exists, **delegate to it or import its service function** — do NOT create a parallel empty endpoint.

**Check command:**
```
grep -r "table_name" app/modules/*/router.py app/modules/*/service.py
```

### Rule 3: Frontend endpoints must match backend reality

When a frontend component calls an API endpoint, the backend handler for that endpoint must be wired to real data before the task is marked complete. The verify step must include:

1. Confirming the endpoint returns non-empty data when test fixtures exist
2. OR confirming the endpoint runs a real query that would return data if rows existed

### Rule 4: "Outline" phases are design docs, not code

When a spec says "Phase X (outline only)", that means:
- Write the design notes in the spec
- Do NOT create placeholder endpoint handlers
- Do NOT create frontend pages pointing at non-existent endpoints
- When the phase is later executed, implement end-to-end (backend query + frontend display + real data flow)

If you want to scaffold the module structure (files, imports), mark the handlers explicitly as `raise NotImplementedError("Phase X — not yet implemented")` so any accidental call fails loudly rather than silently returning empty data.

### Rule 5: Verify steps must assert data content, not just shape

Task verify steps should include at least one assertion that confirms real data flows through the endpoint when test data exists. Shape-only tests (`assert 'items' in response.json()`) are necessary but NOT sufficient.

**Minimum verify for a list endpoint:**
```python
# Insert test fixture
# Call endpoint
# Assert len(response.json()['items']) > 0
# Assert first item has expected field values from the fixture
```

## Frontend Corollary

### Rule 6: Every API call in a useEffect must be tested against the live dev server

Before marking a frontend task complete, manually confirm in the browser that:
1. The API call fires (check Network tab)
2. The response contains real data (or an empty list from a real query, not a hardcoded stub)
3. The UI renders the data correctly

### Rule 7: Settings pages must round-trip

For any settings/config page:
1. Load the page — confirm it fetches current values from the API
2. Change a value and save — confirm the PUT succeeds (200)
3. Reload the page — confirm the changed value persists

If any step fails, the wiring is incomplete.
