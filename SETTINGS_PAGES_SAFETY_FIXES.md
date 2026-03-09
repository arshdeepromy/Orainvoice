# Settings Pages Safety Fixes - ISSUE-018

## Summary

Fixed undefined array access pattern in settings pages following the same systemic issue found in ISSUE-012, ISSUE-013, and ISSUE-017. This was causing crashes when API returned wrapped responses or when fetch failed.

## Problem Pattern

Settings pages were calling array methods on potentially non-array or undefined data:

```typescript
// BEFORE (unsafe)
const res = await apiClient.get<Branch[]>('/org/branches')
setBranches(res.data)  // Assumes res.data is always an array
// Later: branches.find(...) crashes if branches is undefined or not an array
```

## Root Causes

1. **API response format mismatch**: Some endpoints return `{ branches: [...], total: number }` instead of array directly
2. **No error fallback**: When API fails, state remains undefined instead of empty array
3. **No null checks**: Operations like `.find()` called without checking if data exists

## Solution Applied

```typescript
// AFTER (safe)
const res = await apiClient.get('/org/branches')
// Handle both array and wrapped response formats
const branchData = Array.isArray(res.data) ? res.data : (res.data?.branches || [])
setBranches(branchData)

// On error, set empty array
catch {
  setBranches([])
}

// Add null check before operations
const assignedBranch = assignBranchId ? branches.find((b) => b.id === assignBranchId) : null
```

## Files Fixed (3 total)

### 1. BranchManagement.tsx
- Fixed `/org/branches` response handling
- Fixed `/org/users` response handling  
- Added null check for `branches.find()` operation
- Added error fallback to empty arrays

### 2. UserManagement.tsx
- Fixed `/org/users` response handling
- Added error fallback to empty array

### 3. WebhookManagement.tsx
- Fixed `/api/v2/outbound-webhooks` response handling
- Fixed `/api/v2/outbound-webhooks/${id}/deliveries` response handling
- Added error fallback to empty arrays

## Files Already Safe

- **ModuleConfiguration.tsx**: Already had proper array handling with normalization
- **CurrencySettings.tsx**: Uses proper response structure
- **OrgSettings.tsx**: Doesn't fetch arrays
- **AccountingIntegrations.tsx**: Doesn't fetch arrays

## Changes Applied

### 1. Dual format handling
```typescript
const data = Array.isArray(res.data) ? res.data : (res.data?.branches || [])
```
Handles both:
- Direct array: `[{...}, {...}]`
- Wrapped response: `{ branches: [{...}], total: 10 }`

### 2. Error fallbacks
```typescript
catch {
  addToast('error', 'Failed to load')
  setBranches([])  // Prevent undefined state
}
```

### 3. Null checks before operations
```typescript
const item = id ? array.find(x => x.id === id) : null
```

## Testing

- All 3 files pass TypeScript diagnostics with no errors
- No breaking changes to existing functionality
- Graceful degradation when API returns unexpected format or fails

## Related Issues

- ISSUE-012: ModuleContext - modules.filter is not a function
- ISSUE-013: InvoiceList - data.items is undefined
- ISSUE-015: RevenueSummary - data.monthly_breakdown is undefined
- ISSUE-017: Report pages - systemic undefined data access
- ISSUE-018: This fix (settings pages safety)

## Prevention

This fix follows the mandatory workflow in `.kiro/steering/issue-tracking-workflow.md`:

1. ✅ Logged issue in ISSUE_TRACKER.md before fixing
2. ✅ Checked for regressions from previous fixes
3. ✅ Scanned entire settings directory for similar bug patterns
4. ✅ Fixed ALL instances found
5. ✅ Documented all files changed and related issues

All future pages that fetch array data should follow this pattern from the start.

## Pattern to Follow

For any page that fetches array data:

```typescript
const [items, setItems] = useState<Item[]>([])  // Initialize with empty array

const fetchData = async () => {
  try {
    const res = await apiClient.get('/endpoint')
    // Handle both formats
    const data = Array.isArray(res.data) ? res.data : (res.data?.items || [])
    setItems(data)
  } catch {
    setItems([])  // Always set empty array on error
  }
}

// Before using array methods, check if needed
const item = id ? items.find(x => x.id === id) : null
```
