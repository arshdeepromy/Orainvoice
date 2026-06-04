import { useState } from 'react'
import { Modal } from '@/components/ui'

interface PasswordConfirmModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (password: string) => Promise<void>
  loading?: boolean
  title?: string
  description?: string
}

/** Reusable modal prompting for current password before destructive MFA actions. */
export function PasswordConfirmModal({
  open,
  onClose,
  onConfirm,
  loading = false,
  title = 'Confirm Password',
  description = 'Enter your password to continue.',
}: PasswordConfirmModalProps) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!password) return
    setError('')
    try {
      await onConfirm(password)
      setPassword('')
    } catch {
      setError('Incorrect password')
    }
  }

  const handleClose = () => {
    setPassword('')
    setError('')
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title={title}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-muted">{description}</p>
        <div>
          <label htmlFor="confirm-password" className="block text-sm text-muted mb-1">
            Password
          </label>
          <input
            id="confirm-password"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            required
            autoComplete="current-password"
            autoFocus
          />
          {error && <p className="text-sm text-danger mt-1" role="alert">{error}</p>}
        </div>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-ctl border border-border px-4 py-2 text-sm text-muted hover:bg-canvas min-h-[36px]"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading || !password}
            className="rounded-ctl bg-danger px-4 py-2 text-sm font-medium text-white hover:brightness-95 disabled:opacity-50 min-h-[36px]"
          >
            {loading ? 'Confirming…' : 'Confirm'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
