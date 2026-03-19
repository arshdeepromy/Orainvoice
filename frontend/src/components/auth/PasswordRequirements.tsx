interface Rule {
  label: string
  met: boolean
}

function getPasswordRules(password: string): Rule[] {
  return [
    { label: 'At least 8 characters', met: password.length >= 8 },
    { label: 'One uppercase letter', met: /[A-Z]/.test(password) },
    { label: 'One lowercase letter', met: /[a-z]/.test(password) },
    { label: 'One number', met: /\d/.test(password) },
    { label: 'One special character (!@#$%^&*…)', met: /[^A-Za-z0-9]/.test(password) },
  ]
}

export function PasswordRequirements({ password }: { password: string }) {
  const rules = getPasswordRules(password)
  if (!password) return null

  return (
    <ul className="mt-1.5 space-y-0.5 text-xs" role="list" aria-label="Password requirements">
      {rules.map(r => (
        <li key={r.label} className="flex items-center gap-1.5">
          {r.met ? (
            <svg className="h-3.5 w-3.5 text-green-500 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
          ) : (
            <svg className="h-3.5 w-3.5 text-gray-300 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <circle cx="10" cy="10" r="4" />
            </svg>
          )}
          <span className={r.met ? 'text-green-600' : 'text-gray-500'}>{r.label}</span>
        </li>
      ))}
    </ul>
  )
}

export function allPasswordRulesMet(password: string): boolean {
  return getPasswordRules(password).every(r => r.met)
}

export function PasswordMatch({
  password,
  confirmPassword,
}: {
  password: string
  confirmPassword: string
}) {
  if (!confirmPassword) return null
  const match = password === confirmPassword

  return (
    <div className="mt-1.5 text-xs flex items-center gap-1.5">
      {match ? (
        <svg className="h-3.5 w-3.5 text-green-500 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
        </svg>
      ) : (
        <svg className="h-3.5 w-3.5 text-red-400 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
        </svg>
      )}
      <span className={match ? 'text-green-600' : 'text-red-500'}>
        {match ? 'Passwords match' : 'Passwords do not match'}
      </span>
    </div>
  )
}
