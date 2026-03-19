interface ConfirmationStepProps {
  email: string
}

export function ConfirmationStep({ email }: ConfirmationStepProps) {
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-6 text-center">
      <svg className="mx-auto h-12 w-12 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
      <h2 className="mt-4 text-xl font-semibold text-gray-900">
        Check your email
      </h2>
      <p className="mt-2 text-sm text-gray-600">
        We've sent a verification link to <span className="font-semibold">{email}</span>.
        Please click the link to verify your email and activate your account.
      </p>
      <p className="mt-3 text-xs text-gray-500">
        The link expires in 48 hours. Check your spam folder if you don't see it.
      </p>
      <a
        href="/login"
        className="mt-4 inline-block rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        Go to login
      </a>
    </div>
  )
}
