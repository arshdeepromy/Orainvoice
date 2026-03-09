import type { SignupFormData } from './signup-types'

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateSignupForm(data: SignupFormData): Record<string, string> {
  const errors: Record<string, string> = {}

  if (!data.org_name || data.org_name.length < 1 || data.org_name.length > 255) {
    errors.org_name = 'Organisation name must be between 1 and 255 characters'
  }

  if (!data.admin_email || !EMAIL_REGEX.test(data.admin_email)) {
    errors.admin_email = 'Please enter a valid email address'
  }

  if (!data.admin_first_name || data.admin_first_name.length < 1 || data.admin_first_name.length > 100) {
    errors.admin_first_name = 'First name must be between 1 and 100 characters'
  }

  if (!data.admin_last_name || data.admin_last_name.length < 1 || data.admin_last_name.length > 100) {
    errors.admin_last_name = 'Last name must be between 1 and 100 characters'
  }

  if (!data.password || data.password.length < 8 || data.password.length > 128) {
    errors.password = 'Password must be between 8 and 128 characters'
  }

  if (!data.captcha_code || data.captcha_code.length !== 6) {
    errors.captcha_code = 'Please enter the 6-character CAPTCHA code'
  }

  if (!data.plan_id) {
    errors.plan_id = 'Please select a plan'
  }

  return errors
}

export function validateVerifyEmailForm(password: string, confirmPassword: string): Record<string, string> {
  const errors: Record<string, string> = {}

  if (password.length < 10) {
    errors.password = 'Password must be at least 10 characters'
  }

  if (password !== confirmPassword) {
    errors.confirmPassword = 'Passwords do not match'
  }

  return errors
}
