# CAPTCHA Implementation for Signup Protection

## Overview

Implemented a custom CAPTCHA system to prevent automated bot signups and scripts from creating accounts. The CAPTCHA generates a random 6-character alphanumeric code and renders it as a distorted image.

## Features

- **Random code generation**: 6-character codes using uppercase letters (excluding O, I) and digits (excluding 0, 1) to avoid confusion
- **Image rendering**: PNG images with distortion, noise, and random positioning
- **Redis storage**: CAPTCHA codes stored in Redis with 5-minute TTL
- **One-time use**: Codes are deleted after verification attempt
- **Refresh capability**: Users can request a new CAPTCHA if needed

## Backend Implementation

### Files Created/Modified

1. **`app/core/captcha.py`** - CAPTCHA generation and verification logic
   - `generate_captcha_code()` - Generates random 6-character code
   - `create_captcha()` - Creates CAPTCHA image and stores code in Redis
   - `verify_captcha()` - Verifies user input against stored code
   - `_render_captcha_image()` - Renders code as distorted PNG image

2. **`app/modules/auth/router.py`** - Added CAPTCHA endpoint
   - `GET /api/v1/auth/captcha` - Returns CAPTCHA image with captcha_id cookie
   - Updated `POST /api/v1/auth/signup` - Verifies CAPTCHA before creating account

3. **`app/modules/organisations/schemas.py`** - Updated signup schema
   - Added `captcha_code` field to `PublicSignupRequest`

4. **`pyproject.toml`** - Added Pillow dependency for image generation

## Frontend Implementation

### Files Modified

1. **`frontend/src/pages/auth/signup-types.ts`**
   - Added `captcha_code` to `SignupFormData` interface

2. **`frontend/src/pages/auth/signup-validation.ts`**
   - Added validation for 6-character CAPTCHA code

3. **`frontend/src/pages/auth/Signup.tsx`**
   - Added CAPTCHA image display
   - Added CAPTCHA code input field
   - Added refresh button to reload CAPTCHA
   - Loads CAPTCHA on component mount

## API Endpoints

### GET /api/v1/auth/captcha

Generates a new CAPTCHA challenge.

**Response:**
- Content-Type: `image/png`
- Cookie: `captcha_id` (HttpOnly, 5-minute expiry)

**Example:**
```bash
curl -c cookies.txt http://localhost:8080/api/v1/auth/captcha -o captcha.png
```

### POST /api/v1/auth/signup

Creates a new account with CAPTCHA verification.

**Request Body:**
```json
{
  "org_name": "My Company",
  "admin_email": "admin@example.com",
  "admin_first_name": "John",
  "admin_last_name": "Doe",
  "password": "securepassword123",
  "plan_id": "uuid-here",
  "captcha_code": "ABC123"
}
```

**Headers:**
- Cookie: `captcha_id=<value from /captcha endpoint>`

**Responses:**
- `200 OK` - Account created successfully
- `400 Bad Request` - Invalid CAPTCHA or validation error
  - "CAPTCHA verification required. Please refresh and try again."
  - "Invalid CAPTCHA code. Please try again."

## Security Features

1. **Rate Limiting**: Auth endpoints limited to 10 requests/minute per IP
2. **One-time use**: CAPTCHA codes deleted after verification attempt
3. **Short TTL**: Codes expire after 5 minutes
4. **HttpOnly cookies**: captcha_id stored in HttpOnly cookie
5. **Case-insensitive**: User input compared case-insensitively for better UX
6. **Character exclusion**: Confusing characters (0/O, 1/I/l) excluded from codes

## Image Generation

The CAPTCHA image includes:
- Random character positioning with offsets
- Random dark colors for each character
- Background noise (random lines)
- Random dots for additional noise
- 200x80 pixel PNG format

## User Experience

1. User navigates to signup page
2. CAPTCHA image loads automatically
3. User fills out form and enters CAPTCHA code
4. If code is incorrect, user can click "Refresh" to get a new CAPTCHA
5. Form submission validates CAPTCHA before creating account

## Testing

To test the CAPTCHA system:

1. Navigate to `/signup`
2. Observe CAPTCHA image loads
3. Try entering incorrect code - should show error
4. Click "Refresh" - should load new CAPTCHA
5. Enter correct code - should allow signup

## Configuration

CAPTCHA settings in `app/core/captcha.py`:
- `CAPTCHA_LENGTH = 6` - Code length
- `CAPTCHA_TTL = 5 minutes` - Expiry time
- `CAPTCHA_WIDTH = 200` - Image width
- `CAPTCHA_HEIGHT = 80` - Image height

## Future Enhancements

Potential improvements:
- Add audio CAPTCHA for accessibility
- Configurable difficulty levels
- Analytics on CAPTCHA success rates
- Admin dashboard to monitor bot attempts
- Option to use external CAPTCHA services (reCAPTCHA, hCaptcha)
