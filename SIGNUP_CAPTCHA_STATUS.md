# Signup with CAPTCHA - Implementation Status

## ✅ Completed Features

### Backend
1. **CAPTCHA Generation** (`app/core/captcha.py`)
   - Random 6-character code generation
   - PNG image rendering with distortion and noise
   - Redis storage with 5-minute TTL
   - One-time use verification

2. **API Endpoints**
   - `GET /api/v1/auth/captcha` - Returns CAPTCHA image (200 OK ✅)
   - `POST /api/v1/auth/signup` - Verifies CAPTCHA before account creation

3. **Security**
   - Added `/api/v1/auth/captcha` to public paths in auth middleware
   - CAPTCHA codes stored in Redis with short TTL
   - One-time use (deleted after verification)
   - HttpOnly cookies for captcha_id

### Frontend
1. **CAPTCHA Display**
   - Image loads automatically on page load
   - Refresh button to get new CAPTCHA
   - Loading state with spinner
   - Error handling with auto-refresh

2. **User Experience**
   - Green checkmark appears when 6 characters entered
   - Input field turns green when verified
   - Signup button disabled until CAPTCHA verified
   - Auto-uppercase input for better UX

3. **Form Validation**
   - Validates 6-character code
   - Shows error messages
   - Prevents submission without valid CAPTCHA

## Current Behavior

1. User navigates to `/signup`
2. CAPTCHA image loads automatically
3. User fills out form fields
4. User enters 6-character CAPTCHA code
5. Input field turns green with checkmark when 6 characters entered
6. Signup button becomes enabled
7. On submit, backend verifies CAPTCHA code
8. If valid, account is created
9. If invalid, error message shown and user can refresh CAPTCHA

## Visual Feedback

- **Loading**: Gray box with spinner while CAPTCHA loads
- **Loaded**: CAPTCHA image displayed (200x80 pixels)
- **Verified**: Green border + checkmark icon when 6 characters entered
- **Button**: Disabled (gray) until CAPTCHA verified, enabled (blue) when ready

## Testing

To test the complete flow:

1. Navigate to `http://localhost:3000/signup`
2. Observe CAPTCHA image loads
3. Fill out all form fields
4. Enter the 6-character code from CAPTCHA image
5. Watch input field turn green with checkmark
6. Signup button should become enabled
7. Click "Sign up"
8. Should create account if CAPTCHA is correct

## Error Scenarios

1. **Wrong CAPTCHA code**: Shows error "Invalid CAPTCHA code. Please try again."
2. **Expired CAPTCHA**: Shows error "CAPTCHA verification required. Please refresh and try again."
3. **Missing CAPTCHA**: Signup button disabled, cannot submit
4. **Image load failure**: Auto-refreshes CAPTCHA

## Rate Limiting

- Auth endpoints: 10 requests/minute per IP
- CAPTCHA endpoint: Included in auth rate limit
- If rate limited: 429 error, wait 1 minute

## Configuration

CAPTCHA settings in `app/core/captcha.py`:
```python
CAPTCHA_LENGTH = 6
CAPTCHA_TTL = timedelta(minutes=5)
CAPTCHA_WIDTH = 200
CAPTCHA_HEIGHT = 80
CAPTCHA_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # Excludes O, I, 0, 1
```

## Files Modified

### Backend
- `app/core/captcha.py` - CAPTCHA generation logic
- `app/modules/auth/router.py` - Added CAPTCHA endpoint
- `app/modules/organisations/schemas.py` - Added captcha_code field
- `app/middleware/auth.py` - Added CAPTCHA to public paths
- `pyproject.toml` - Added Pillow dependency

### Frontend
- `frontend/src/pages/auth/Signup.tsx` - CAPTCHA UI and logic
- `frontend/src/pages/auth/signup-types.ts` - Added captcha_code field
- `frontend/src/pages/auth/signup-validation.ts` - CAPTCHA validation

## Next Steps (Optional Enhancements)

1. Add audio CAPTCHA for accessibility
2. Add CAPTCHA difficulty levels
3. Track bot attempt statistics
4. Add admin dashboard for CAPTCHA analytics
5. Option to integrate external services (reCAPTCHA, hCaptcha)
