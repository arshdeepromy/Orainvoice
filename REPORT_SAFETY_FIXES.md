# Report Pages Safety Fixes - ISSUE-017

## Summary

Fixed systemic undefined data access pattern across all 16 report pages. This was causing crashes when API returned null/undefined values or when data arrays were empty.

## Problem Pattern

Two critical issues found across all report files:

1. **Unsafe fmt() functions**: Called `.toLocaleString()` on potentially undefined values
   ```typescript
   // BEFORE (unsafe)
   const fmt = (v: number) => v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })
   
   // AFTER (safe)
   const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'
   ```

2. **Unsafe .map() calls**: Called `.map()` on arrays without checking if they exist
   ```typescript
   // BEFORE (unsafe)
   data.services.map((s) => ...)
   
   // AFTER (safe)
   data.services && data.services.length > 0 ? data.services.map((s) => ...) : placeholder
   ```

## Files Fixed (16 total)

All files in `frontend/src/pages/reports/`:

1. CarjamUsage.tsx - Fixed fmt() and daily_breakdown.map()
2. RevenueSummary.tsx - Already fixed in ISSUE-015
3. GstReturnSummary.tsx - Fixed fmt()
4. TopServices.tsx - Fixed fmt() and services.map() (2 locations)
5. JobReport.tsx - Fixed fmt()
6. OutstandingInvoices.tsx - Fixed fmt() and invoices.map()
7. FleetReport.tsx - Fixed fmt() and vehicles.map()
8. InventoryReport.tsx - Fixed fmt()
9. InvoiceStatus.tsx - Fixed fmt() and statuses.map() (2 locations)
10. TaxReturnReport.tsx - Fixed fmt()
11. ProjectReport.tsx - Fixed fmt()
12. POSReport.tsx - Fixed fmt()
13. CustomerStatement.tsx - Fixed fmt() and lines.map()
14. SmsUsage.tsx - Fixed fmt() and daily_breakdown.map()
15. HospitalityReport.tsx - Fixed fmt()
16. StorageUsage.tsx - Fixed breakdown.map()

## Changes Applied

### 1. Updated all fmt() functions

- Added `| undefined` to parameter type
- Added null check: `v != null ? ... : '0.00'` (or '$0.00' for currency)
- Handles both null and undefined safely

### 2. Added safety checks before .map() calls

- Check array exists: `data.array && data.array.length > 0`
- Provide fallback UI when no data available
- Consistent empty state messages

### 3. Added fallback rendering

- Empty state messages for tables
- Placeholder text for charts
- Consistent user experience across all reports

## Testing

- All 16 files pass TypeScript diagnostics with no errors
- No breaking changes to existing functionality
- Graceful degradation when API returns empty/null data

## Related Issues

- ISSUE-012: ModuleContext - modules.filter is not a function
- ISSUE-013: InvoiceList - data.items is undefined
- ISSUE-015: RevenueSummary - data.monthly_breakdown is undefined
- ISSUE-017: This fix (systemic report page safety)

## Prevention

This fix follows the mandatory workflow in `.kiro/steering/issue-tracking-workflow.md`:

1. ✅ Logged issue in ISSUE_TRACKER.md before fixing
2. ✅ Checked for regressions from previous fixes
3. ✅ Scanned entire app for similar bug patterns
4. ✅ Fixed ALL instances, not just the reported one
5. ✅ Documented all files changed and related issues

All future report pages should follow this pattern from the start.
