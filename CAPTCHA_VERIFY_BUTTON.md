# CAPTCHA Verify Button Implementation

## Feature

Added a "Verify" button that checks the CAPTCHA code with the backend before allowing signup. Shows an animated success message when verified.

## User Flow

1. User sees CAPTCHA image
2. User enters 6-character code
3. User clicks **"Verify"** button
4. Backend validates the code
5. **Success**: Animated green message appears ✅ "CAPTCHA verified successfully!"
6. **Failure**: Error message shown, CAPTCHA auto-refreshes after 2 seconds
7. Signup button only enabled after successful verification

## Implementation

### Backend

**New Endpoint: `POST /api/v1/auth/verify-captcha`**

```python
@router.post("/verify-captcha")
async def verify_captcha_endpoint(request: Request, payload: dict):
    """Verify CAPTCHA without creating account.
    
    Allows frontend to verify before form submission.
    Code is NOT deleted so it can be used for actual signup.
    """
    captcha_id = request.cookies.get("captcha_id")
    captcha_code = payload.get("captcha_code", "")
    
    # Don't delete - allow reuse for signup
    is_valid = await verify_captcha(captcha_id, captcha_code, delete_after=False)
    
    if not is_valid:
        return JSONResponse(status_code=400, 
            content={"detail": "Invalid CAPTCHA code. Please try again."})
    
    return JSONResponse(status_code=200,
        content={"message": "CAPTCHA verified successfully"})
```

**Updated `verify_captcha()` function:**
```python
async def verify_captcha(captcha_id: str, user_input: str, delete_after: bool = True):
    """Verify CAPTCHA with optional deletion.
    
    Args:
        delete_after: If True, delete code after verification (for signup)
                     If False, keep code for reuse (for pre-verification)
    """
```

### Frontend

**New States:**
```typescript
const [captchaVerified, setCaptchaVerified] = useState(false)
const [captchaVerifying, setCaptchaVerifying] = useState(false)
const [captchaError, setCaptchaError] = useState<string | null>(null)
```

**Verify Function:**
```typescript
async function verifyCaptcha() {
  setCaptchaVerifying(true)
  try {
    await apiClient.post('/auth/verify-captcha', {
      captcha_code: formData.captcha_code
    })
    setCaptchaVerified(true)  // Show success message
  } catch (err) {
    setCaptchaError('Invalid CAPTCHA code')
    setTimeout(() => refreshCaptcha(), 2000)  // Auto-refresh
  } finally {
    setCaptchaVerifying(false)
  }
}
```

**UI Components:**

1. **Before Verification:**
```tsx
<Input
  value={formData.captcha_code}
  onChange={(e) => handleFieldChange('captcha_code', e.target.value.toUpperCase())}
  maxLength={6}
/>
<Button
  onClick={verifyCaptcha}
  loading={captchaVerifying}
  disabled={formData.captcha_code.length !== 6}
>
  Verify
</Button>
```

2. **After Verification (Animated Success):**
```tsx
<div className="flex items-center gap-2 p-3 bg-green-50 border border-green-200 rounded-md animate-fadeIn">
  <svg className="w-5 h-5 text-green-600">✓</svg>
  <span className="text-sm font-medium text-green-800">
    CAPTCHA verified successfully!
  </span>
</div>
```

3. **Signup Button:**
```tsx
<Button 
  type="submit" 
  disabled={!captchaVerified}  // Only enabled after verification
>
  Sign up
</Button>
```

### Animation

**CSS (frontend/src/index.css):**
```css
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-fadeIn {
  animation: fadeIn 0.3s ease-out;
}
```

## Security

### Two-Step Verification

1. **Pre-verification** (Verify button):
   - Checks code validity
   - Does NOT delete code
   - Provides immediate feedback

2. **Final verification** (Signup):
   - Checks code again
   - Deletes code (one-time use)
   - Creates account

### Benefits

✅ User gets immediate feedback
✅ Prevents form submission with wrong CAPTCHA
✅ Code still secure (deleted on actual signup)
✅ Better UX (no wasted form submissions)

## Error Handling

### Invalid Code
- Shows error message
- Auto-refreshes CAPTCHA after 2 seconds
- User can try again with new code

### Expired Code
- Shows "CAPTCHA verification required"
- User clicks refresh to get new code

### Network Error
- Shows "Failed to verify CAPTCHA"
- User can retry

## Files Modified

### Backend
- `app/core/captcha.py` - Added `delete_after` parameter
- `app/modules/auth/router.py` - Added `/verify-captcha` endpoint
- `app/middleware/auth.py` - Added endpoint to public paths
- `app/middleware/rate_limit.py` - Excluded from rate limiting

### Frontend
- `frontend/src/pages/auth/Signup.tsx` - Added verify button and logic
- `frontend/src/index.css` - Added fadeIn animation

## User Experience

**Before:**
- Enter code → Click signup → Wait → Error (if wrong)
- Wasted time filling form

**After:**
- Enter code → Click verify → Instant feedback
- Only proceed if verified ✅
- No wasted form submissions

## Testing

1. Navigate to `/signup`
2. Enter wrong code (e.g., `ABCDEF`)
3. Click "Verify"
4. Should see error + auto-refresh
5. Enter correct code
6. Click "Verify"
7. Should see animated green success message
8. Signup button becomes enabled
9. Click "Sign up"
10. Account created successfully
