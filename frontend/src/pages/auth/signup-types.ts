// Signup form data matching PublicSignupRequest
export interface SignupFormData {
  org_name: string
  admin_email: string
  admin_first_name: string
  admin_last_name: string
  password: string
  plan_id: string
  captcha_code: string
}

// Response from POST /api/v1/auth/signup matching PublicSignupResponse
export interface SignupResponse {
  message: string
  organisation_id: string
  organisation_name: string
  plan_id: string
  admin_user_id: string
  admin_email: string
  trial_ends_at: string
  stripe_setup_intent_client_secret: string
  signup_token: string
}

// Public plan for the plan selector
export interface PublicPlan {
  id: string
  name: string
  monthly_price_nzd: number
  trial_duration: number
  trial_duration_unit: string
}

// Response from GET /api/v1/auth/plans
export interface PublicPlanListResponse {
  plans: PublicPlan[]
}

// Request body for POST /api/v1/auth/verify-email
export interface VerifyEmailRequest {
  token: string
  password: string
}

// Response from POST /api/v1/auth/verify-email matching VerifyEmailResponse
export interface VerifyEmailResponse {
  message: string
  access_token: string
  refresh_token: string
  token_type: string
}
