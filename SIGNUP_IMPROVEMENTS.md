# Signup Flow Improvements

## Changes Made

### 1. Removed Stripe Integration from Trial Signup
- **Issue**: Signup was failing because Stripe API calls were being made during trial signup, but Stripe keys were not configured
- **Solution**: Removed all Stripe integration from the signup flow. Payment collection will happen later when trial ends or user manually adds payment method
- **Files Modified**:
  - `app/modules/organisations/service.py` - Removed Stripe customer and SetupIntent creation
  - `frontend/src/pages/auth/Signup.tsx` - Removed Stripe card form step

### 2. Added Password Field to Signup Form
- **Issue**: Users were not able to set their password during signup
- **Solution**: Added password field to signup form and hash password during account creation
- **Changes**:
  - User account is created with `is_email_verified=True` and hashed password
  - User can immediately login after signup without email verification
  - Password must be 8-128 characters
- **Files Modified**:
  - `app/modules/organisations/schemas.py` - Added `password` field to `PublicSignupRequest`
  - `app/modules/organisations/service.py` - Hash password and set `is_email_verified=True`
  - `app/modules/auth/router.py` - Pass password to signup service
  - `frontend/src/pages/auth/signup-types.ts` - Added `password` to `SignupFormData`
  - `frontend/src/pages/auth/signup-validation.ts` - Added password validation
  - `frontend/src/pages/auth/Signup.tsx` - Added password input field

### 3. Dynamic Trial Period Display
- **Issue**: Trial period was hardcoded as "14-day free trial"
- **Solution**: Display trial period from selected subscription plan
- **Changes**:
  - Backend already includes `trial_duration` and `trial_duration_unit` in `PublicPlanResponse`
  - Frontend now displays dynamic trial period based on selected plan
  - Example: "Start your 30-day free trial" or "Start your 2-week free trial"
- **Files Modified**:
  - `frontend/src/pages/auth/signup-types.ts` - Added trial fields to `PublicPlan` interface
  - `frontend/src/pages/auth/Signup.tsx` - Display dynamic trial period

## New Signup Flow

1. User fills out signup form:
   - Organisation name
   - Email address
   - First name
   - Last name
   - Password (new!)
   - Select plan

2. Backend creates:
   - Organisation with trial status
   - User account with hashed password and `is_email_verified=True`
   - Signup token (for potential onboarding wizard)

3. User sees success message and can immediately login

4. No Stripe integration during trial - payment collection happens later

## Testing

To test the signup flow:

1. Navigate to `/signup`
2. Fill out the form with:
   - Organisation name: "Test Company"
   - Email: "test@example.com"
   - First name: "John"
   - Last name: "Doe"
   - Password: "password123"
   - Select any plan
3. Click "Sign up"
4. Should see success message
5. Click "Go to login"
6. Login with email and password

## Notes

- Trial period is calculated from the subscription plan's `trial_duration` and `trial_duration_unit` fields
- If plan has no trial configured, defaults to 14 days (defined in `_TRIAL_DAYS` constant)
- Stripe integration can be added later for payment collection when trial ends
