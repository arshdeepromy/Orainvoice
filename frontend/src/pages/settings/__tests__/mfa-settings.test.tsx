import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/**
 * Unit tests for MFA frontend components.
 * Validates: Requirements 8.2–8.7, 11.7, 13.1, 13.6
 */

// --- Hoisted mocks ---

const { mockGet, mockPost, mockPatch, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: { get: mockGet, post: mockPost, patch: mockPatch, delete: mockDelete },
  setAccessToken: vi.fn(),
}))

vi.mock('@/components/ui/Modal', () => ({
  Modal: ({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) =>
    open ? (
      <div data-testid="modal" role="dialog" aria-label={title}>
        <h2>{title}</h2>
        <button onClick={onClose}>×</button>
        {children}
      </div>
    ) : null,
}))

const mockCompleteMfa = vi.fn()
const mockNavigate = vi.fn()

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({
    mfaPending: true,
    mfaSessionToken: 'test-mfa-token',
    mfaMethods: ['totp', 'sms', 'email'],
    completeMfa: mockCompleteMfa,
  })),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Mock the UI components used by MfaVerify
vi.mock('@/components/ui', () => ({
  Button: ({ children, loading, ...props }: { children: React.ReactNode; loading?: boolean; [key: string]: unknown }) => (
    <button {...props} disabled={loading as boolean}>
      {loading ? 'Loading...' : children}
    </button>
  ),
  AlertBanner: ({ children, onDismiss }: { children: React.ReactNode; variant?: string; onDismiss?: () => void }) => (
    <div role="alert">
      {children}
      {onDismiss && <button onClick={onDismiss}>Dismiss</button>}
    </div>
  ),
}))

import { TotpEnrolWizard } from '@/components/mfa/TotpEnrolWizard'
import { SmsEnrolWizard } from '@/components/mfa/SmsEnrolWizard'
import { EmailEnrolWizard } from '@/components/mfa/EmailEnrolWizard'
import { PasswordConfirmModal } from '@/components/mfa/PasswordConfirmModal'
import { PasskeyManager } from '@/components/mfa/PasskeyManager'
import { MfaVerify } from '@/pages/auth/MfaVerify'
import { useAuth } from '@/contexts/AuthContext'

beforeEach(() => {
  vi.clearAllMocks()
  // Reset useAuth to default MFA-pending state
  vi.mocked(useAuth).mockReturnValue({
    mfaPending: true,
    mfaSessionToken: 'test-mfa-token',
    mfaMethods: ['totp', 'sms', 'email'],
    completeMfa: mockCompleteMfa,
  } as ReturnType<typeof useAuth>)
})

// ============================================================
// 1. TotpEnrolWizard
// ============================================================

describe('TotpEnrolWizard', () => {
  const onComplete = vi.fn()
  const onCancel = vi.fn()

  it('renders setup step with Continue and Cancel buttons', () => {
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)
    expect(screen.getByText('Continue')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
    expect(screen.getByText(/authenticator app/i)).toBeInTheDocument()
  })

  it('transitions to verify step on Continue click', async () => {
    mockPost.mockResolvedValueOnce({
      data: { qr_uri: 'otpauth://totp/BudgetFlow:user@test.com?secret=JBSWY3DPEHPK3PXP', secret: 'JBSWY3DPEHPK3PXP', message: 'Scan QR code' },
    })

    const user = userEvent.setup()
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Continue'))

    await waitFor(() => {
      expect(screen.getByText('Step 1: Scan QR code')).toBeInTheDocument()
    })
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    expect(screen.getByLabelText('Verification code')).toBeInTheDocument()
    expect(screen.getByText('Verify')).toBeInTheDocument()
  })

  it('shows success state after valid code verification', async () => {
    mockPost
      .mockResolvedValueOnce({
        data: { qr_uri: 'otpauth://totp/test', secret: 'TESTSECRET', message: 'OK' },
      })
      .mockResolvedValueOnce({ data: { message: 'Verified' } })

    const user = userEvent.setup()
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Continue'))
    await waitFor(() => expect(screen.getByLabelText('Verification code')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Verification code'), '123456')
    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(screen.getByText('Authenticator app enabled')).toBeInTheDocument()
    })
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('calls onComplete when Done is clicked after success', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { qr_uri: 'otpauth://totp/test', secret: 'S', message: 'OK' } })
      .mockResolvedValueOnce({ data: { message: 'Verified' } })

    const user = userEvent.setup()
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Continue'))
    await waitFor(() => expect(screen.getByLabelText('Verification code')).toBeInTheDocument())
    await user.type(screen.getByLabelText('Verification code'), '123456')
    await user.click(screen.getByText('Verify'))
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument())

    await user.click(screen.getByText('Done'))
    expect(onComplete).toHaveBeenCalled()
  })

  it('shows error on API failure during enrolment start', async () => {
    mockPost.mockRejectedValueOnce({
      response: { data: { detail: 'Enrolment failed' } },
    })

    const user = userEvent.setup()
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Continue'))

    await waitFor(() => {
      expect(screen.getByText('Enrolment failed')).toBeInTheDocument()
    })
  })

  it('shows error on invalid code verification', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { qr_uri: 'otpauth://totp/test', secret: 'S', message: 'OK' } })
      .mockRejectedValueOnce({ response: { data: { detail: 'Invalid TOTP code' } } })

    const user = userEvent.setup()
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Continue'))
    await waitFor(() => expect(screen.getByLabelText('Verification code')).toBeInTheDocument())
    await user.type(screen.getByLabelText('Verification code'), '000000')
    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(screen.getByText('Invalid TOTP code')).toBeInTheDocument()
    })
  })

  it('calls onCancel when Cancel is clicked', async () => {
    const user = userEvent.setup()
    render(<TotpEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalled()
  })
})


// ============================================================
// 2. SmsEnrolWizard
// ============================================================

describe('SmsEnrolWizard', () => {
  const onComplete = vi.fn()
  const onCancel = vi.fn()

  it('renders phone input step with Send code button', () => {
    render(<SmsEnrolWizard onComplete={onComplete} onCancel={onCancel} />)
    expect(screen.getByLabelText(/phone number/i)).toBeInTheDocument()
    expect(screen.getByText('Send code')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })

  it('transitions to verify step after sending code', async () => {
    mockPost.mockResolvedValueOnce({
      data: { method: 'sms', message: 'Code sent to +6421*****67' },
    })

    const user = userEvent.setup()
    render(<SmsEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.type(screen.getByLabelText(/phone number/i), '+64211234567')
    await user.click(screen.getByText('Send code'))

    await waitFor(() => {
      expect(screen.getByLabelText(/6-digit verification code/i)).toBeInTheDocument()
    })
    expect(screen.getByText('Verify')).toBeInTheDocument()
    expect(screen.getByText('Resend code')).toBeInTheDocument()
  })

  it('shows success state after valid code verification', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { method: 'sms', message: 'Code sent' } })
      .mockResolvedValueOnce({ data: { message: 'Verified' } })

    const user = userEvent.setup()
    render(<SmsEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.type(screen.getByLabelText(/phone number/i), '+64211234567')
    await user.click(screen.getByText('Send code'))
    await waitFor(() => expect(screen.getByLabelText(/6-digit verification code/i)).toBeInTheDocument())

    await user.type(screen.getByLabelText(/6-digit verification code/i), '123456')
    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(screen.getByText('SMS verification enabled')).toBeInTheDocument()
    })
  })

  it('handles resend code', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { method: 'sms', message: 'Code sent' } })
      .mockResolvedValueOnce({ data: { method: 'sms', message: 'Code resent' } })

    const user = userEvent.setup()
    render(<SmsEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.type(screen.getByLabelText(/phone number/i), '+64211234567')
    await user.click(screen.getByText('Send code'))
    await waitFor(() => expect(screen.getByText('Resend code')).toBeInTheDocument())

    await user.click(screen.getByText('Resend code'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(2)
    })
  })

  it('shows error on SMS delivery failure', async () => {
    mockPost.mockRejectedValueOnce({
      response: { data: { detail: 'SMS could not be delivered' } },
    })

    const user = userEvent.setup()
    render(<SmsEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.type(screen.getByLabelText(/phone number/i), '+64211234567')
    await user.click(screen.getByText('Send code'))

    await waitFor(() => {
      expect(screen.getByText('SMS could not be delivered')).toBeInTheDocument()
    })
  })
})

// ============================================================
// 3. EmailEnrolWizard
// ============================================================

describe('EmailEnrolWizard', () => {
  const onComplete = vi.fn()
  const onCancel = vi.fn()

  it('renders send step with Send code button', () => {
    render(<EmailEnrolWizard onComplete={onComplete} onCancel={onCancel} />)
    expect(screen.getByText('Send code')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
    expect(screen.getByText(/verification code will be sent/i)).toBeInTheDocument()
  })

  it('transitions to verify step after sending code', async () => {
    mockPost.mockResolvedValueOnce({
      data: { method: 'email', message: 'Code sent to your email' },
    })

    const user = userEvent.setup()
    render(<EmailEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Send code'))

    await waitFor(() => {
      expect(screen.getByLabelText(/6-digit verification code/i)).toBeInTheDocument()
    })
    expect(screen.getByText('Verify')).toBeInTheDocument()
    expect(screen.getByText('Resend code')).toBeInTheDocument()
  })

  it('shows success state after valid code verification', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { method: 'email', message: 'Code sent' } })
      .mockResolvedValueOnce({ data: { message: 'Verified' } })

    const user = userEvent.setup()
    render(<EmailEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Send code'))
    await waitFor(() => expect(screen.getByLabelText(/6-digit verification code/i)).toBeInTheDocument())

    await user.type(screen.getByLabelText(/6-digit verification code/i), '654321')
    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(screen.getByText('Email verification enabled')).toBeInTheDocument()
    })
  })

  it('handles resend code', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { method: 'email', message: 'Code sent' } })
      .mockResolvedValueOnce({ data: { method: 'email', message: 'Code resent' } })

    const user = userEvent.setup()
    render(<EmailEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Send code'))
    await waitFor(() => expect(screen.getByText('Resend code')).toBeInTheDocument())

    await user.click(screen.getByText('Resend code'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(2)
    })
  })

  it('shows error on email delivery failure', async () => {
    mockPost.mockRejectedValueOnce({
      response: { data: { detail: 'Verification email could not be sent' } },
    })

    const user = userEvent.setup()
    render(<EmailEnrolWizard onComplete={onComplete} onCancel={onCancel} />)

    await user.click(screen.getByText('Send code'))

    await waitFor(() => {
      expect(screen.getByText('Verification email could not be sent')).toBeInTheDocument()
    })
  })
})


// ============================================================
// 4. PasswordConfirmModal
// ============================================================

describe('PasswordConfirmModal', () => {
  const onClose = vi.fn()
  const onConfirm = vi.fn()

  it('renders nothing when not open', () => {
    render(<PasswordConfirmModal open={false} onClose={onClose} onConfirm={onConfirm} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders modal with password input when open', () => {
    render(<PasswordConfirmModal open={true} onClose={onClose} onConfirm={onConfirm} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByText('Confirm')).toBeInTheDocument()
    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })

  it('calls onConfirm with password on submit', async () => {
    onConfirm.mockResolvedValueOnce(undefined)
    const user = userEvent.setup()
    render(<PasswordConfirmModal open={true} onClose={onClose} onConfirm={onConfirm} />)

    await user.type(screen.getByLabelText('Password'), 'mypassword123')
    await user.click(screen.getByText('Confirm'))

    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledWith('mypassword123')
    })
  })

  it('shows error when onConfirm throws', async () => {
    onConfirm.mockRejectedValueOnce(new Error('Invalid password'))
    const user = userEvent.setup()
    render(<PasswordConfirmModal open={true} onClose={onClose} onConfirm={onConfirm} />)

    await user.type(screen.getByLabelText('Password'), 'wrongpassword')
    await user.click(screen.getByText('Confirm'))

    await waitFor(() => {
      expect(screen.getByText('Incorrect password')).toBeInTheDocument()
    })
  })

  it('calls onClose and clears state on Cancel', async () => {
    const user = userEvent.setup()
    render(<PasswordConfirmModal open={true} onClose={onClose} onConfirm={onConfirm} />)

    await user.type(screen.getByLabelText('Password'), 'sometext')
    await user.click(screen.getByText('Cancel'))

    expect(onClose).toHaveBeenCalled()
  })
})

// ============================================================
// 5. PasskeyManager
// ============================================================

describe('PasskeyManager', () => {
  const onUpdate = vi.fn().mockResolvedValue(undefined)
  const onSuccess = vi.fn()

  const mockCredentials = [
    {
      credential_id: 'cred-1',
      device_name: 'Work Laptop',
      created_at: '2024-01-15T10:00:00Z',
      last_used_at: '2024-06-01T14:30:00Z',
    },
    {
      credential_id: 'cred-2',
      device_name: 'YubiKey',
      created_at: '2024-03-20T08:00:00Z',
      last_used_at: null,
    },
  ]

  beforeEach(() => {
    // Ensure WebAuthn is "supported"
    Object.defineProperty(window, 'PublicKeyCredential', {
      value: vi.fn(),
      writable: true,
      configurable: true,
    })
  })

  it('shows warning when WebAuthn is not supported', async () => {
    Object.defineProperty(window, 'PublicKeyCredential', {
      value: undefined,
      writable: true,
      configurable: true,
    })

    render(<PasskeyManager onUpdate={onUpdate} onSuccess={onSuccess} />)

    expect(screen.getByText(/does not support passkeys/i)).toBeInTheDocument()
  })

  it('lists registered passkeys', async () => {
    mockGet.mockResolvedValueOnce({ data: mockCredentials })

    render(<PasskeyManager onUpdate={onUpdate} onSuccess={onSuccess} />)

    await waitFor(() => {
      expect(screen.getByText('Work Laptop')).toBeInTheDocument()
    })
    expect(screen.getByText('YubiKey')).toBeInTheDocument()
    expect(screen.getByText('Register new passkey')).toBeInTheDocument()
  })

  it('shows name prompt when Register new passkey is clicked', async () => {
    mockGet.mockResolvedValueOnce({ data: [] })

    const user = userEvent.setup()
    render(<PasskeyManager onUpdate={onUpdate} onSuccess={onSuccess} />)

    await waitFor(() => expect(screen.getByText('Register new passkey')).toBeInTheDocument())

    await user.click(screen.getByText('Register new passkey'))

    expect(screen.getByText('Name your passkey')).toBeInTheDocument()
    expect(screen.getByLabelText('Passkey name')).toBeInTheDocument()
  })

  it('shows inline rename input when Rename is clicked', async () => {
    mockGet.mockResolvedValueOnce({ data: mockCredentials })

    const user = userEvent.setup()
    render(<PasskeyManager onUpdate={onUpdate} onSuccess={onSuccess} />)

    await waitFor(() => expect(screen.getByText('Work Laptop')).toBeInTheDocument())

    const renameButtons = screen.getAllByText('Rename')
    await user.click(renameButtons[0])

    expect(screen.getByLabelText('New passkey name')).toBeInTheDocument()
    expect(screen.getByText('Save')).toBeInTheDocument()
  })

  it('saves renamed passkey', async () => {
    mockGet
      .mockResolvedValueOnce({ data: mockCredentials })
      .mockResolvedValueOnce({ data: [{ ...mockCredentials[0], device_name: 'Home PC' }, mockCredentials[1]] })
    mockPatch.mockResolvedValueOnce({ data: {} })

    const user = userEvent.setup()
    render(<PasskeyManager onUpdate={onUpdate} onSuccess={onSuccess} />)

    await waitFor(() => expect(screen.getByText('Work Laptop')).toBeInTheDocument())

    const renameButtons = screen.getAllByText('Rename')
    await user.click(renameButtons[0])

    const input = screen.getByLabelText('New passkey name')
    await user.clear(input)
    await user.type(input, 'Home PC')
    await user.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/auth/passkey/credentials/cred-1', { device_name: 'Home PC' })
    })
    expect(onSuccess).toHaveBeenCalledWith('Passkey renamed')
  })

  it('opens password modal when Remove is clicked', async () => {
    mockGet.mockResolvedValueOnce({ data: mockCredentials })

    const user = userEvent.setup()
    render(<PasskeyManager onUpdate={onUpdate} onSuccess={onSuccess} />)

    await waitFor(() => expect(screen.getByText('Work Laptop')).toBeInTheDocument())

    const removeButtons = screen.getAllByText('Remove')
    await user.click(removeButtons[0])

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
    expect(screen.getByText('Remove Passkey')).toBeInTheDocument()
  })
})


// ============================================================
// 6. MfaVerify (MfaChallengePage)
// ============================================================

describe('MfaVerify', () => {
  function renderMfaVerify() {
    return render(
      <MemoryRouter initialEntries={['/auth/mfa']}>
        <MfaVerify />
      </MemoryRouter>,
    )
  }

  it('renders method selection buttons for available methods', () => {
    renderMfaVerify()

    expect(screen.getByText('Authenticator app')).toBeInTheDocument()
    expect(screen.getByText('SMS code')).toBeInTheDocument()
    expect(screen.getByText('Email code')).toBeInTheDocument()
    expect(screen.getByText('Backup code')).toBeInTheDocument()
  })

  it('shows 6-digit code input for TOTP method', () => {
    renderMfaVerify()

    // TOTP is the default first method
    const digitInputs = screen.getAllByRole('textbox')
    // 6 digit inputs for TOTP
    expect(digitInputs.length).toBeGreaterThanOrEqual(6)
  })

  it('submits TOTP code via completeMfa', async () => {
    mockCompleteMfa.mockResolvedValueOnce(undefined)

    const user = userEvent.setup()
    renderMfaVerify()

    // Type 6 digits into the individual inputs
    const digitInputs = screen.getAllByLabelText(/digit/i)
    for (let i = 0; i < 6; i++) {
      await user.type(digitInputs[i], String(i + 1))
    }

    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(mockCompleteMfa).toHaveBeenCalledWith('123456', 'totp')
    })
  })

  it('sends challenge OTP when SMS method is selected', async () => {
    mockPost.mockResolvedValue({ data: { message: 'Code sent' } })

    const user = userEvent.setup()
    renderMfaVerify()

    await user.click(screen.getByText('SMS code'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/auth/mfa/challenge/send', {
        mfa_token: 'test-mfa-token',
        method: 'sms',
      })
    })
  })

  it('shows backup code text input when backup method is selected', async () => {
    const user = userEvent.setup()
    renderMfaVerify()

    await user.click(screen.getByText('Backup code'))

    await waitFor(() => {
      expect(screen.getByLabelText(/backup code/i)).toBeInTheDocument()
    })
  })

  it('submits backup code via completeMfa', async () => {
    mockCompleteMfa.mockResolvedValueOnce(undefined)

    const user = userEvent.setup()
    renderMfaVerify()

    await user.click(screen.getByText('Backup code'))
    await waitFor(() => expect(screen.getByLabelText(/backup code/i)).toBeInTheDocument())

    await user.type(screen.getByLabelText(/backup code/i), 'abcd-efgh-ijkl')
    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(mockCompleteMfa).toHaveBeenCalledWith('abcd-efgh-ijkl', 'backup')
    })
  })

  it('shows error on failed MFA verification', async () => {
    mockCompleteMfa.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Invalid code. Please try again.' } },
    })

    const user = userEvent.setup()
    renderMfaVerify()

    // Type 6 digits
    const digitInputs = screen.getAllByLabelText(/digit/i)
    for (let i = 0; i < 6; i++) {
      await user.type(digitInputs[i], '0')
    }

    await user.click(screen.getByText('Verify'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })

  it('redirects to login when not MFA pending', () => {
    vi.mocked(useAuth).mockReturnValue({
      mfaPending: false,
      mfaSessionToken: null,
      mfaMethods: [],
      completeMfa: mockCompleteMfa,
    } as ReturnType<typeof useAuth>)

    renderMfaVerify()

    expect(mockNavigate).toHaveBeenCalledWith('/auth/login')
  })
})
