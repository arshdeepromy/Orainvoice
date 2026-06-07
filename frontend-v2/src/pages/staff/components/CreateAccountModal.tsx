/**
 * CreateAccountModal
 *
 * Shown from the Overview tab Account panel when a staff member has NO
 * linked user account. Collects a password (min 8 chars) and creates an
 * org user account linked to the staff member via the EXISTING backend
 * endpoint:
 *
 *   POST /api/v2/staff/{staffId}/create-account   body: { password }
 *
 * On success the backend links the new user to the staff record and the
 * caller reloads the staff record so the panel flips to the linked state.
 * This is a NEW modal for the Overview tab — it does NOT reuse the list
 * page's `/org/users/invite` flow.
 *
 * The backend requires the staff member to already have an email address;
 * a missing email surfaces as a 400 with a descriptive detail which we
 * render inline.
 *
 * _Requirements: 9.5, 9.6_
 */

import { useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'
import { Button } from '@/components/ui'

interface Props {
  staffId: string
  /** Staff email shown for context; the backend uses this as the login. */
  email: string | null
  onCancel: () => void
  /** Called after the account is created so the caller can reload staff. */
  onCreated: () => void
}

const MIN_PASSWORD_LENGTH = 8

function readErrorDetail(err: unknown): string {
  if (axios.isCancel?.(err)) return ''
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (err instanceof Error) return err.message
  return 'Failed to create user account.'
}

export default function CreateAccountModal({
  staffId,
  email,
  onCancel,
  onCreated,
}: Props) {
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH
  const canSubmit =
    !submitting && password.length >= MIN_PASSWORD_LENGTH && !!email

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await apiClient.post(`/api/v2/staff/${staffId}/create-account`, {
        password,
      })
      onCreated()
    } catch (err) {
      setError(readErrorDetail(err) || 'Failed to create user account.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-account-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 px-4"
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-card bg-card p-6 shadow-pop"
      >
        <h2
          id="create-account-title"
          className="text-[15px] font-semibold text-text"
        >
          Create user account
        </h2>
        <p className="mt-2 text-[13.5px] text-muted">
          Create a login for this staff member so they can sign in and be
          scheduled. They&apos;ll sign in with their email address.
        </p>

        <div className="mt-4">
          <label className="block text-[12.5px] font-medium text-muted mb-[7px]">
            Email
          </label>
          <div className="flex h-[42px] items-center rounded-ctl border border-border bg-canvas px-[13px] text-[13.5px] text-text">
            <span className="mono truncate">{email ?? '—'}</span>
          </div>
          {!email && (
            <p className="mt-1.5 text-[12px] text-danger">
              This staff member needs an email address before an account can
              be created.
            </p>
          )}
        </div>

        <div className="mt-4">
          <label
            htmlFor="create-account-password"
            className="block text-[12.5px] font-medium text-muted mb-[7px]"
          >
            Temporary password
          </label>
          <input
            id="create-account-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
            className="h-[42px] w-full rounded-ctl border border-border-strong bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            aria-invalid={tooShort}
          />
          {tooShort && (
            <p className="mt-1.5 text-[12px] text-danger">
              Password must be at least {MIN_PASSWORD_LENGTH} characters.
            </p>
          )}
        </div>

        {error && (
          <p className="mt-4 text-[13px] text-danger" role="alert">
            {error}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="inline-flex h-10 items-center justify-center rounded-ctl bg-accent px-4 text-[13.5px] font-semibold text-white hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Creating…' : 'Create account'}
          </button>
        </div>
      </form>
    </div>
  )
}
