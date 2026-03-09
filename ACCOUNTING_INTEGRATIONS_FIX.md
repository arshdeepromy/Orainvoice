# Accounting Integrations Fix

## Issue

Accounting settings page showing error: "We couldn't load your accounting integration settings. Please refresh the page or try again later."

## Root Cause

Two issues:

1. **Wrong endpoint path**: Frontend was calling `/org/integrations/accounting` but the backend accounting router is mounted at `/org/accounting`

2. **Missing consolidated endpoint**: Frontend expected a single endpoint returning:
```json
{
  "xero": { "connected": false, "account_name": null, ... },
  "myob": { "connected": false, "account_name": null, ... },
  "sync_log": [...]
}
```

But the backend only had separate endpoints:
- `GET /org/accounting/connections` - Returns array of connections
- `GET /org/accounting/sync-log` - Returns array of sync log entries

## Solution

### Backend Changes

**1. Created consolidated dashboard endpoint**

Added `GET /org/accounting/` endpoint that returns all data the frontend needs in one call:

```python
@router.get("/", response_model=AccountingDashboardResponse)
async def get_accounting_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get consolidated accounting integration data for dashboard view."""
    # Combines connections and sync log into single response
```

**2. Added new schemas**

```python
class AccountingConnectionDetail(BaseModel):
    provider: str
    connected: bool
    account_name: Optional[str]
    connected_at: Optional[str]
    last_sync_at: Optional[str]
    sync_status: str  # idle, syncing, success, failed
    error_message: Optional[str]

class SyncLogEntryDashboard(BaseModel):
    id: str
    provider: str
    entity_type: str
    entity_id: str
    entity_ref: str  # Human-readable reference
    status: str  # success or failed
    error_message: Optional[str]
    synced_at: str

class AccountingDashboardResponse(BaseModel):
    xero: AccountingConnectionDetail
    myob: AccountingConnectionDetail
    sync_log: list[SyncLogEntryDashboard]
```

**3. Added retry endpoint**

```python
@router.post("/sync/{entry_id}/retry")
async def retry_sync_entry_endpoint(...)
```

**4. Updated service function**

Updated `_connection_to_dict()` to include missing fields:
- `account_name` (placeholder: None)
- `sync_status` (placeholder: "idle")
- `error_message` (placeholder: None)

### Frontend Changes

Updated all API endpoint paths in `AccountingIntegrations.tsx`:

| Old Path | New Path |
|----------|----------|
| `/org/integrations/accounting` | `/org/accounting` |
| `/org/integrations/accounting/{provider}/connect` | `/org/accounting/connect/{provider}` |
| `/org/integrations/accounting/{provider}/disconnect` | `/org/accounting/disconnect/{provider}` |
| `/org/integrations/accounting/sync/{id}/retry` | `/org/accounting/sync/{id}/retry` |

Also changed response field name:
- `redirect_url` → `authorization_url`

## Backend Restart Required

The backend must be restarted for the new endpoints to be available:

```bash
docker-compose restart app
```

## Features

The accounting integrations page now supports:

### Connection Management
- View Xero and MYOB connection status
- Connect to Xero or MYOB via OAuth
- Disconnect from providers
- See last sync time and connection date

### Sync Log
- View recent sync activity (last 50 entries)
- See which invoices/payments/credit notes were synced
- View sync status (success/failed)
- Retry failed syncs individually
- See error messages for failed syncs

### UI Features
- Connection cards showing status badges
- Sync log table with sortable columns
- Retry buttons for failed syncs
- Toast notifications for actions
- Loading states and error handling

## API Endpoints

### Dashboard View
- `GET /org/accounting/` - Get all accounting data (xero, myob, sync_log)

### Connection Management
- `GET /org/accounting/connections` - List connections
- `POST /org/accounting/connect/{provider}` - Initiate OAuth flow
- `GET /org/accounting/callback/{provider}` - OAuth callback handler
- `POST /org/accounting/disconnect/{provider}` - Disconnect provider

### Sync Management
- `GET /org/accounting/sync-log` - View sync log with filters
- `POST /org/accounting/sync/{provider}` - Retry all failed syncs for provider
- `POST /org/accounting/sync/{entry_id}/retry` - Retry specific sync entry

All endpoints require `org_admin` or `global_admin` role.

## Future Enhancements

The following fields are currently placeholders and should be implemented:

1. **account_name**: Store the connected account name from OAuth response
   - Add `account_name` column to `accounting_integrations` table
   - Extract from Xero/MYOB OAuth response
   - Display in connection card

2. **sync_status**: Track real-time sync status
   - Add `sync_status` column to `accounting_integrations` table
   - Update when Celery sync tasks start/complete
   - Show "syncing" status with spinner in UI

3. **error_message**: Store last sync error
   - Add `last_error_message` column to `accounting_integrations` table
   - Update when sync fails
   - Display in connection card alert

4. **Actual retry logic**: Currently retry endpoint just returns success
   - Implement Celery task to re-sync failed entries
   - Queue retry jobs
   - Update sync log status

## Testing

After restarting the backend:

1. Navigate to Settings → Accounting
2. Should see two connection cards (Xero and MYOB) showing "Not connected"
3. Should see "No sync activity yet" message
4. Click "Connect Xero" or "Connect MYOB" to test OAuth flow (requires API keys configured)

## Files Modified

- `app/modules/accounting/router.py` - Added dashboard and retry endpoints
- `app/modules/accounting/schemas.py` - Added dashboard response schemas
- `app/modules/accounting/service.py` - Updated _connection_to_dict
- `frontend/src/pages/settings/AccountingIntegrations.tsx` - Updated API paths
- `docs/ISSUE_TRACKER.md` - Logged as ISSUE-023

## Status

✅ IMPLEMENTED - Backend restart required

After restarting, the accounting integrations page should load without errors.
