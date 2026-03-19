import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'

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
        <p className="text-sm text-gray-600">{description}</p>
        <div>
          <label htmlFor="confirm-password" className="block text-sm text-gray-600 mb-1">
            Password
          </label>
          <input
            id="confirm-password"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            required
            autoComplete="current-password"
            autoFocus
          />
          {error && <p className="text-sm text-red-600 mt-1" role="alert">{error}</p>}
        </div>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 min-h-[36px]"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading || !password}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 min-h-[36px]"
          >
            {loading ? 'Confirming…' : 'Confirm'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
