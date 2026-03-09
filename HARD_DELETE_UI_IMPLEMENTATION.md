# Hard Delete UI Implementation

## Overview
Added hard delete functionality to the Organizations admin page with immediate UI updates.

## Changes Made

### Frontend: `frontend/src/pages/admin/Organisations.tsx`

1. **Added HardDeleteModal Component**
   - Two-step confirmation process
   - Step 1: Enter reason for deletion
   - Step 2: Type "PERMANENTLY DELETE" to confirm
   - Clear warning about irreversible action
   - Lists what will be deleted

2. **Added Hard Delete State**
   - `hardDeleteOrg` state to track which org is being hard deleted

3. **Added handleHardDelete Function**
   - Calls `PUT /admin/organisations/{id}` with `action: 'hard_delete_request'`
   - Gets confirmation token
   - Calls `DELETE /admin/organisations/{id}/hard` with token and confirm text
   - **Immediately removes org from UI** using `setOrgs((prev) => prev.filter(...))`
   - No need to refetch data from server

4. **Updated Actions Column**
   - Changed "Delete" button to "Soft Delete"
   - Added "Hard Delete" button
   - Both buttons only show for non-deleted orgs

## Key Features

### Immediate UI Update
When hard delete succeeds, the organization is immediately removed from the table without refetching:
```typescript
setOrgs((prev) => prev.filter((o) => o.id !== hardDeleteOrg.id))
```

### Extra Safety Confirmation
Hard delete requires typing "PERMANENTLY DELETE" exactly, not just the org name.

### Clear Visual Warnings
- Red error banner with ⚠️ icon
- Lists all data that will be deleted
- Button shows "⚠️ DELETE PERMANENTLY"

## User Flow

1. Click "Hard Delete" button on organization row
2. Modal opens with warning and reason input
3. Enter reason, click "Continue"
4. Step 2: Type "PERMANENTLY DELETE" exactly
5. Click "⚠️ DELETE PERMANENTLY"
6. Organization immediately disappears from table
7. Success toast shows confirmation

## Testing

1. Navigate to Admin > Organisations
2. Find an organization to test with
3. Click "Hard Delete"
4. Follow the two-step process
5. Verify organization disappears immediately
6. Check backend logs to confirm deletion
7. Verify data is removed from database

## Files Modified

- `frontend/src/pages/admin/Organisations.tsx` - Added hard delete modal and handler
