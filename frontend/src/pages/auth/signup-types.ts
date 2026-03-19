// Signup form data matching PublicSignupRequest
export interface SignupFormData {
  org_name: string
  admin_email: string
  admin_first_name: string
  admin_last_name: string
  password: string
  confirm_password: string
  plan_id: string
  captcha_code: string
  coupon_code: string
}

// Response from POST /api/v1/auth/signup matching PublicSignupResponse
export interface SignupResponse {
  message: string
  requires_payment: boolean
  payment_amount_cents: number
  admin_email: string

  // Billing breakdown (present when requires_payment is true)
  plan_amount_cents?: number
  gst_amount_cents?: number
  gst_percentage?: number
  processing_fee_cents?: number

  // Present when requires_payment is true (paid plan deferred flow)
  pending_signup_id?: string
  stripe_client_secret?: string
  plan_name?: string

  // Present when requires_payment is false (trial plan immediate flow)
  organisation_id?: string
  organisation_name?: string
  plan_id?: string
  admin_user_id?: string
  trial_ends_at?: string
  signup_token?: string
}


// Public plan for the plan selector
export interface PublicPlan {
  id: string
  name: string
  monthly_price_nzd: number
  trial_duration: number
  trial_duration_unit: string
}

// Signup billing config from GET /api/v1/auth/signup-config
export interface SignupBillingConfig {
  gst_percentage: number
  stripe_fee_percentage: number
  stripe_fee_fixed_cents: number
  pass_fees_to_customer: boolean
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
