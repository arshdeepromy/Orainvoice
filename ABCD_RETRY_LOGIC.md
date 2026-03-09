# ABCD API Retry Logic Implementation

## Issue
The ABCD API returns a null response when Carjam is still fetching data from their sources. This is expected behavior, not an error.

## Root Cause
The ABCD API works asynchronously:
1. First request triggers data fetch from Carjam's sources
2. Returns null response with `Refresh` header
3. Subsequent requests return actual data once ready

## Solution
Implemented automatic retry logic with clear user feedback.

### Backend Changes

#### 1. Special Error Code
**File:** `app/integrations/carjam.py`

Changed from generic error to special code:
```python
# Before
raise CarjamError("Carjam ABCD data not ready, retry in 1 second")

# After
raise CarjamError("ABCD_FETCHING")
```

#### 2. Automatic Retry Logic
**File:** `app/modules/admin/router.py`

Implemented 3-attempt retry with 1-second delays:

```python
max_retries = 3
retry_delay = 1.0

for attempt in range(max_retries):
    try:
        result = await client.lookup_vehicle_abcd(rego, use_mvr=use_mvr)
        # Success - return result
        return JSONResponse(...)
    except CarjamError as exc:
        if str(exc) == "ABCD_FETCHING":
            if attempt < max_retries - 1:
                # Retry after delay
                await asyncio.sleep(retry_delay)
                continue
            else:
                # Max retries reached
                return JSONResponse(
                    status_code=202,  # Accepted but not ready
                    content={
                        "success": False,
                        "message": "Carjam is still fetching data. Please try again in a few seconds.",
                        "retry_suggested": True,
                    }
                )
```

**Response Codes:**
- `200` - Success (data found)
- `202` - Accepted (data being fetched, retry suggested)
- `404` - Not found
- `429` - Rate limit exceeded
- `502` - Carjam service error

### Frontend Changes

#### 1. Enhanced Handler
**File:** `frontend/src/pages/admin/Integrations.tsx`

```typescript
const handleAbcdLookup = async () => {
  // ... validation ...
  
  const res = await apiClient.post<{
    success: boolean
    message: string
    data?: any
    source?: string
    mvr_used?: boolean
    attempts?: number
    retry_suggested?: boolean
  }>(`/admin/integrations/carjam/lookup-test-abcd`, { 
    rego: abcdRego.trim(),
    use_mvr: abcdUseMvr
  })
  
  if (res.data.success) {
    const attemptsMsg = res.data.attempts && res.data.attempts > 1 
      ? ` (${res.data.attempts} attempts)` 
      : ''
    onToast('success', `ABCD lookup successful${attemptsMsg}`)
  } else if (res.data.retry_suggested) {
    onToast('info', 'Carjam is fetching data. Please try again in a few seconds.')
  }
}
```

#### 2. Enhanced Result Display

```tsx
<AlertBanner
  variant={
    abcdResult.success ? 'success' : 
    abcdResult.retry_suggested ? 'info' : 
    'error'
  }
  title={
    abcdResult.success ? 'ABCD Lookup Successful' : 
    abcdResult.retry_suggested ? 'Data Being Fetched' : 
    'ABCD Lookup Failed'
  }
>
  <p>{abcdResult.message}</p>
  {abcdResult.retry_suggested && (
    <p className="text-sm mt-2">
      ℹ️ The ABCD API is asynchronously fetching data from Carjam. 
      This is normal for first-time lookups. Please wait a few seconds and try again.
    </p>
  )}
</AlertBanner>
```

## User Experience

### Scenario 1: Data Available Immediately
1. User enters rego and clicks "ABCD Lookup"
2. Backend makes 1 request
3. Data returned immediately
4. Success message: "Vehicle found: TOYOTA NOAH"

### Scenario 2: Data Being Fetched (1 retry)
1. User enters rego and clicks "ABCD Lookup"
2. Backend makes request #1 → null response
3. Backend waits 1 second
4. Backend makes request #2 → data returned
5. Success message: "Vehicle found: TOYOTA NOAH (2 attempts)"

### Scenario 3: Data Still Being Fetched (max retries)
1. User enters rego and clicks "ABCD Lookup"
2. Backend makes 3 requests with 1s delays
3. All return null (data still being fetched)
4. Info message: "Carjam is still fetching data. Please try again in a few seconds."
5. User waits a few seconds and clicks again
6. Data now available → Success!

## Technical Details

### Retry Strategy
- **Max Attempts**: 3
- **Delay Between Attempts**: 1 second
- **Total Max Wait**: ~3 seconds
- **Timeout Per Attempt**: 30 seconds

### Why This Works
1. First request triggers Carjam to fetch data from their sources
2. Carjam typically has data ready within 1-2 seconds
3. Automatic retries handle most cases without user intervention
4. If data takes longer, user gets clear message to retry manually

### Error Handling
```python
try:
    result = await client.lookup_vehicle_abcd(rego, use_mvr=use_mvr)
except CarjamError as exc:
    if str(exc) == "ABCD_FETCHING":
        # Handle retry logic
    else:
        # Other errors (rate limit, not found, etc.)
        raise
```

## Benefits

1. **Automatic Retry**: Most lookups succeed without user intervention
2. **Clear Feedback**: Users understand what's happening
3. **No False Errors**: "Data being fetched" is not treated as failure
4. **Attempt Tracking**: Shows how many retries were needed
5. **User Control**: If max retries reached, user can manually retry

## Testing

### Test Case 1: New Vehicle (First Lookup)
```bash
# First attempt may return 202 (data being fetched)
# Automatic retries should succeed within 3 attempts
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{
  "rego": "NEW123",
  "use_mvr": true
}

# Expected: 200 OK with attempts: 2 or 3
```

### Test Case 2: Cached Vehicle
```bash
# Should return immediately (already in Carjam's cache)
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{
  "rego": "QTD216",
  "use_mvr": true
}

# Expected: 200 OK with attempts: 1
```

### Test Case 3: Very Slow Fetch
```bash
# If data takes >3 seconds to fetch
POST /api/v1/admin/integrations/carjam/lookup-test-abcd
{
  "rego": "SLOW123",
  "use_mvr": true
}

# Expected: 202 Accepted with retry_suggested: true
# User waits and retries manually → 200 OK
```

## Files Modified

1. `app/integrations/carjam.py` - Changed error to "ABCD_FETCHING" code
2. `app/modules/admin/router.py` - Added retry loop with 3 attempts
3. `frontend/src/pages/admin/Integrations.tsx` - Enhanced UI feedback

## Status
✅ **COMPLETE** - ABCD retry logic fully implemented.

The ABCD lookup now handles asynchronous data fetching gracefully with automatic retries and clear user feedback!
