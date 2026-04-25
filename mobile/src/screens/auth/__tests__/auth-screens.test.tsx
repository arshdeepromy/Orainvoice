import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockLogin = vi.fn()
const mockLoginWithGoogle = vi.fn()
const mockCompleteMfa = vi.fn()
const mockCompleteFirebaseMfa = vi.fn()
const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    login: mockLogin,
    loginWithGoogle: mockLoginWithGoogle,
    completeMfa: mockCompleteMfa,
    completeFirebaseMfa: mockCompleteFirebaseMfa,
    mfaPending: true,
    mfaSessionToken: 'test-session',
    mfaMethods: ['totp', 'sms'],
    mfaDefaultMethod: 'totp',
    user: null,
    isAuthenticated: false,
    isLoading: false,
    logout: vi.fn(),
    refreshProfile: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: false,
    isBranchAdmin: false,
    isSalesperson: false,
    isKiosk: false,
  }),
}))

const mockVerify = vi.fn()

vi.mock('@/contexts/BiometricContext', () => ({
  useBiometric: () => ({
    isAvailable: true,
    isEnabled: true,
    setEnabled: vi.fn(),
    verify: mockVerify,
    isVerifying: false,
  }),
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

// ---------------------------------------------------------------------------
// LoginScreen Tests
// ---------------------------------------------------------------------------

describe('LoginScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders email and password fields, remember me toggle, and sign in button', async () => {
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/remember me/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in$/i })).toBeInTheDocument()
  })

  it('renders Google Sign-In button and Forgot Password link', async () => {
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    expect(screen.getByRole('button', { name: /sign in with google/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /forgot your password/i })).toBeInTheDocument()
  })

  it('shows email validation error for invalid email', async () => {
    const user = userEvent.setup()
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    const emailInput = screen.getByLabelText(/email/i)
    await user.type(emailInput, 'not-an-email')

    expect(screen.getByText(/please enter a valid email/i)).toBeInTheDocument()
  })

  it('calls login and navigates to dashboard on successful login', async () => {
    mockLogin.mockResolvedValueOnce({ mfaRequired: false })
    const user = userEvent.setup()
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    await user.type(screen.getByLabelText(/email/i), 'test@example.com')
    await user.type(screen.getByLabelText(/password/i), 'password123')
    await user.click(screen.getByRole('button', { name: /sign in$/i }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123',
        remember: false,
      })
      expect(mockNavigate).toHaveBeenCalledWith('/')
    })
  })

  it('navigates to MFA screen when login requires MFA', async () => {
    mockLogin.mockResolvedValueOnce({ mfaRequired: true })
    const user = userEvent.setup()
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    await user.type(screen.getByLabelText(/email/i), 'test@example.com')
    await user.type(screen.getByLabelText(/password/i), 'password123')
    await user.click(screen.getByRole('button', { name: /sign in$/i }))

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/mfa-verify')
    })
  })

  it('displays backend error message on invalid credentials', async () => {
    mockLogin.mockRejectedValueOnce(new Error('Invalid email or password'))
    const user = userEvent.setup()
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    await user.type(screen.getByLabelText(/email/i), 'test@example.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong')
    await user.click(screen.getByRole('button', { name: /sign in$/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid email or password')
    })
  })

  it('passes remember flag when checkbox is checked', async () => {
    mockLogin.mockResolvedValueOnce({ mfaRequired: false })
    const user = userEvent.setup()
    const LoginScreen = (await import('../LoginScreen')).default
    render(<LoginScreen />, { wrapper: Wrapper })

    await user.type(screen.getByLabelText(/email/i), 'test@example.com')
    await user.type(screen.getByLabelText(/password/i), 'password123')
    await user.click(screen.getByLabelText(/remember me/i))
    await user.click(screen.getByRole('button', { name: /sign in$/i }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123',
        remember: true,
      })
    })
  })
})

// ---------------------------------------------------------------------------
// MfaScreen Tests
// ---------------------------------------------------------------------------

describe('MfaScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders verification code input and verify button', async () => {
    const MfaScreen = (await import('../MfaScreen')).default
    render(<MfaScreen />, { wrapper: Wrapper })

    expect(screen.getByLabelText(/verification code/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /verify/i })).toBeInTheDocument()
  })

  it('renders method selector when multiple methods available', async () => {
    const MfaScreen = (await import('../MfaScreen')).default
    render(<MfaScreen />, { wrapper: Wrapper })

    // The method selector buttons contain the method labels
    expect(screen.getByRole('button', { name: /authenticator app/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sms code/i })).toBeInTheDocument()
  })

  it('calls completeMfa and navigates to dashboard on valid code', async () => {
    mockCompleteMfa.mockResolvedValueOnce(undefined)
    const user = userEvent.setup()
    const MfaScreen = (await import('../MfaScreen')).default
    render(<MfaScreen />, { wrapper: Wrapper })

    await user.type(screen.getByLabelText(/verification code/i), '123456')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(mockCompleteMfa).toHaveBeenCalledWith('123456', 'totp')
      expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
    })
  })

  it('displays error and clears code on invalid MFA code', async () => {
    mockCompleteMfa.mockRejectedValueOnce(new Error('Invalid code'))
    const user = userEvent.setup()
    const MfaScreen = (await import('../MfaScreen')).default
    render(<MfaScreen />, { wrapper: Wrapper })

    const codeInput = screen.getByLabelText(/verification code/i)
    await user.type(codeInput, '000000')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid code')
    })
    // Code should be cleared for retry
    expect(codeInput).toHaveValue('')
  })

  it('renders back to login link', async () => {
    const MfaScreen = (await import('../MfaScreen')).default
    render(<MfaScreen />, { wrapper: Wrapper })

    expect(screen.getByRole('button', { name: /back to login/i })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// BiometricLockScreen Tests
// ---------------------------------------------------------------------------

describe('BiometricLockScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders unlock UI with try again and password fallback buttons', async () => {
    const BiometricLockScreen = (await import('../BiometricLockScreen')).default
    render(<BiometricLockScreen />, { wrapper: Wrapper })

    expect(screen.getByText(/unlock orainvoice/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /use password instead/i })).toBeInTheDocument()
  })

  it('navigates to dashboard on successful biometric verification', async () => {
    mockVerify.mockResolvedValueOnce(true)
    const user = userEvent.setup()
    const BiometricLockScreen = (await import('../BiometricLockScreen')).default
    render(<BiometricLockScreen />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /try again/i }))

    await waitFor(() => {
      expect(mockVerify).toHaveBeenCalled()
      expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
    })
  })

  it('shows error with remaining attempts on failed verification', async () => {
    mockVerify.mockResolvedValueOnce(false)
    const user = userEvent.setup()
    const BiometricLockScreen = (await import('../BiometricLockScreen')).default
    render(<BiometricLockScreen />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /try again/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/attempt/i)
    })
  })

  it('navigates to login after 3 consecutive failures', async () => {
    mockVerify.mockResolvedValue(false)
    const user = userEvent.setup()
    const BiometricLockScreen = (await import('../BiometricLockScreen')).default
    render(<BiometricLockScreen />, { wrapper: Wrapper })

    // The component auto-verifies on mount (failure #1), wait for error to appear
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    // Failure #2
    await user.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    // Failure #3 — should redirect to login
    await user.click(screen.getByRole('button', { name: /try again/i }))

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
    })
  })

  it('navigates to login when Use Password Instead is clicked', async () => {
    const user = userEvent.setup()
    const BiometricLockScreen = (await import('../BiometricLockScreen')).default
    render(<BiometricLockScreen />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /use password instead/i }))

    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
  })
})
