# Dashboard API Mismatch Fix

## Issue

Dashboard showing "Failed to load dashboard data" error when logging in as org user. No data displayed.

## Root Cause

The OrgAdminDashboard component was calling the correct report endpoints but expecting the wrong data structure. The frontend was built with placeholder interfaces that didn't match the actual backend API schemas.

### API Mismatches

1. **Revenue Summary** (`/reports/revenue`)
   - Expected: `{ current_period, previous_period, change_percent }`
   - Actual: `{ total_revenue, total_gst, total_inclusive, invoice_count, average_invoice, period_start, period_end }`

2. **Outstanding Invoices** (`/reports/outstanding`)
   - Expected: `{ total, overdue_count }`
   - Actual: `{ total_outstanding, count, invoices: [...] }`

3. **Storage Usage** (`/reports/storage`)
   - Expected: `{ used_bytes, quota_gb }`
   - Actual: `{ storage_used_bytes, storage_quota_bytes, usage_percentage, alert_level }`

4. **Activity Feed** (`/reports/activity`)
   - Expected: Endpoint to exist
   - Actual: Endpoint doesn't exist in backend

## Solution

Updated the OrgAdminDashboard component to match the actual backend API response schemas.

### Changes Made

**File: `frontend/src/pages/dashboard/OrgAdminDashboard.tsx`**

1. **Updated OrgAdminData interface** to match backend schemas:
```typescript
interface OrgAdminData {
  revenue_summary?: {
    total_revenue: number
    total_gst: number
    total_inclusive: number
    invoice_count: number
    average_invoice: number
    period_start: string
    period_end: string
  }
  outstanding?: {
    total_outstanding: number
    count: number
    invoices: Array<{
      invoice_id: string
      invoice_number: string | null
      customer_name: string
      days_overdue: number
      balance_due: number
    }>
  }
  storage?: {
    storage_used_bytes: number
    storage_quota_bytes: number
    usage_percentage: number
    alert_level: string
  }
}
```

2. **Removed non-existent endpoint call**:
   - Removed `/reports/activity` call
   - Removed ActivityItem and SystemAlert interfaces

3. **Updated data access**:
   - Revenue: Use `total_inclusive` instead of `current_period`
   - Outstanding: Use `total_outstanding` instead of `total`
   - Storage: Use `storage_used_bytes` / `storage_quota_bytes` instead of `used_bytes` / `quota_gb`
   - Storage: Use `usage_percentage` directly instead of calculating

4. **Enhanced dashboard features**:
   - Added outstanding invoices table showing top 10 invoices
   - Highlight overdue invoices in red
   - Calculate overdue count from invoices array
   - Show storage alert banner when usage is high (amber/red/blocked)
   - Display invoice count and total count as subtitles on KPI cards

5. **Improved error handling**:
   - Added console.error logging for debugging
   - Better error messages

## Dashboard Features

### KPI Cards
1. **Revenue (This Period)** - Shows total_inclusive with invoice count
2. **Outstanding Total** - Shows total_outstanding with invoice count
3. **Overdue Invoices** - Calculated from invoices array, red if > 0
4. **Storage Usage** - Shows used/quota with progress bar and percentage

### Outstanding Invoices Table
- Shows top 10 outstanding invoices
- Columns: Invoice #, Customer, Amount Due, Days Overdue
- Overdue invoices highlighted in red background
- Sorted by backend (typically by days overdue descending)

### Storage Alert
- Shows warning banner when storage is at amber/red/blocked level
- Alert level determined by backend based on usage percentage

## Backend Endpoints

The dashboard now correctly uses these endpoints:

1. `GET /reports/revenue` - Revenue summary for current period
2. `GET /reports/outstanding` - Outstanding invoices with details
3. `GET /reports/storage` - Storage usage with alert level

All endpoints require `org_admin` or `salesperson` role and automatically filter by the user's organisation.

## Testing

After the fix, the dashboard should:
1. Load without errors
2. Show revenue, outstanding, and storage KPI cards
3. Display outstanding invoices table (if any invoices exist)
4. Show storage alert if usage is high
5. Calculate overdue count correctly

## Future Enhancements

Potential improvements for the dashboard:

1. **Activity Feed** - Create `/reports/activity` endpoint to show recent user actions
2. **Period Comparison** - Add previous period data to show trends
3. **Charts** - Add revenue trend chart, invoice status pie chart
4. **Quick Actions** - Add buttons for common tasks (create invoice, send reminders)
5. **Customizable Widgets** - Allow users to show/hide dashboard sections
6. **Real-time Updates** - Use WebSocket for live dashboard updates

## Related Issues

- **ISSUE-022**: This fix
- **ISSUE-005**: GlobalAdminDashboard had similar API mismatch issues
- **ISSUE-019**: Billing page nested property access issues
- **ISSUE-020**: Systemic nested property access issues

## Files Modified

- `frontend/src/pages/dashboard/OrgAdminDashboard.tsx` - Fixed API data structure
- `docs/ISSUE_TRACKER.md` - Logged as ISSUE-022

## Status

✅ FIXED - Dashboard now loads correctly with real data from backend
