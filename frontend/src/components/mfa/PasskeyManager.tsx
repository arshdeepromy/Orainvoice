import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { PasswordConfirmModal } from '@/components/mfa/PasswordConfirmModal'

interface PasskeyManagerProps {
  onUpdate: () => Promise<void>
  onSuccess: (msg: string) => void
}

interface PasskeyCredential {
  credential_id: string
  device_name: string
  created_at: string
  last_used_at: string | null
}

// --- Base64url helpers ---

function base64urlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const pad = base64.length % 4 === 0 ? '' : '='.repeat(4 - (base64.length % 4))
  const binary = atob(base64 + pad)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function PasskeyManager({ onUpdate, onSuccess }: PasskeyManagerProps) {
  const [webAuthnSupported, setWebAuthnSupported] = useState(true)
  const [credentials, setCredentials] = useState<PasskeyCredential[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Registration state
  const [registering, setRegistering] = useState(false)
  const [deviceName, setDeviceName] = useState('')
  const [showNamePrompt, setShowNamePrompt] = useState(false)

  // Rename state
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameLoading, setRenameLoading] = useState(false)

  // Remove state
  const [removeId, setRemoveId] = useState<string | null>(null)
  const [removeLoading, setRemoveLoading] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined' && !window.PublicKeyCredential) {
      setWebAuthnSupported(false)
      setLoading(false)
    }
  }, [])

  const fetchCredentials = useCallback(async () => {
    try {
      const res = await apiClient.get<PasskeyCredential[]>('/auth/passkey/credentials')
      setCredentials(res.data)
      setError('')
    } catch {
      setError('Failed to load passkeys')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (webAuthnSupported) {
      fetchCredentials()
    }
  }, [webAuthnSupported, fetchCredentials])

  const startRegistration = () => {
    setDeviceName('')
    setShowNamePrompt(true)
    setError('')
  }

  const handleRegister = async () => {
    const name = deviceName.trim() || 'My Passkey'
    setShowNamePrompt(false)
    setRegistering(true)
    setError('')

    try {
      // Step 1: Get registration options from server
      const optionsRes = await apiClient.post<{ options: Record<string, unknown> }>(
        '/auth/passkey/register/options',
        { device_name: name },
      )
      const options = optionsRes.data.options as {
        challenge: string
        user: { id: string; name: string; displayName: string }
        rp: { id: string; name: string }
        pubKeyCredParams: Array<{ type: string; alg: number }>
        timeout: number
        excludeCredentials?: Array<{ id: string; type: string }>
        authenticatorSelection?: Record<string, unknown>
        attestation?: string
      }

      // Step 2: Convert base64url fields to ArrayBuffer for WebAuthn API
      // Use the current hostname as rp.id so it always matches the browser
      // origin — avoids Bitwarden rejecting hardcoded "localhost".
      const rp: PublicKeyCredentialRpEntity = {
        name: options.rp.name,
        id: window.location.hostname,
      }

      const publicKeyOptions: PublicKeyCredentialCreationOptions = {
        challenge: base64urlToBuffer(options.challenge),
        rp,
        user: {
          id: base64urlToBuffer(options.user.id),
          name: options.user.name,
          displayName: options.user.displayName,
        },
        pubKeyCredParams: options.pubKeyCredParams as PublicKeyCredentialParameters[],
        timeout: options.timeout,
        excludeCredentials: options.excludeCredentials?.map(c => ({
          id: base64urlToBuffer(c.id),
          type: c.type as PublicKeyCredentialType,
        })),
        authenticatorSelection: options.authenticatorSelection as AuthenticatorSelectionCriteria | undefined,
        attestation: (options.attestation as AttestationConveyancePreference) ?? 'none',
      }

      // Step 3: Invoke browser WebAuthn API
      const credential = await navigator.credentials.create({
        publicKey: publicKeyOptions,
      }) as PublicKeyCredential | null

      if (!credential) {
        setError('Passkey registration was cancelled')
        return
      }

      const response = credential.response as AuthenticatorAttestationResponse

      // Step 4: Send attestation to server
      await apiClient.post('/auth/passkey/register/verify', {
        credential: {
          client_data_b64: bufferToBase64url(response.clientDataJSON),
          attestation_b64: bufferToBase64url(response.attestationObject),
          credential_id_b64: bufferToBase64url(credential.rawId),
        },
      })

      onSuccess('Passkey registered successfully')
      await fetchCredentials()
      await onUpdate()
    } catch (err: unknown) {
      console.error('[PasskeyManager] Registration error:', err)
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      if ((err as DOMException)?.name === 'NotAllowedError') {
        setError('Passkey registration was cancelled or timed out')
      } else if ((err as DOMException)?.name === 'SecurityError') {
        setError('Security error: the passkey RP ID does not match this domain. Check WebAuthn configuration.')
      } else if (err instanceof DOMException) {
        setError(`Browser error: ${err.message}`)
      } else {
        setError(detail ?? 'Failed to register passkey')
      }
    } finally {
      setRegistering(false)
    }
  }

  const handleRenameStart = (cred: PasskeyCredential) => {
    setRenamingId(cred.credential_id)
    setRenameValue(cred.device_name)
    setError('')
  }

  const handleRenameSave = async () => {
    if (!renamingId || !renameValue.trim()) return
    setRenameLoading(true)
    setError('')
    try {
      await apiClient.patch(`/auth/passkey/credentials/${renamingId}`, {
        device_name: renameValue.trim(),
      })
      setRenamingId(null)
      onSuccess('Passkey renamed')
      await fetchCredentials()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to rename passkey')
    } finally {
      setRenameLoading(false)
    }
  }

  const handleRenameCancel = () => {
    setRenamingId(null)
    setRenameValue('')
  }

  const handleRemoveConfirm = async (password: string) => {
    if (!removeId) return
    setRemoveLoading(true)
    setError('')
    try {
      await apiClient.delete(`/auth/passkey/credentials/${removeId}`, {
        data: { password },
      })
      setRemoveId(null)
      onSuccess('Passkey removed')
      await fetchCredentials()
      await onUpdate()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      throw new Error(detail ?? 'Failed to remove passkey')
    } finally {
      setRemoveLoading(false)
    }
  }

  // --- Render ---

  if (!webAuthnSupported) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
        <h4 className="text-sm font-medium text-gray-900">Passkeys</h4>
        <p className="text-sm text-gray-500">Manage your passkeys for passwordless authentication.</p>
        <div className="rounded-md bg-amber-50 border border-amber-200 p-3">
          <p className="text-sm text-amber-800">
            Your browser does not support passkeys. Please use a supported browser to register and manage passkeys.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium text-gray-900">Passkeys</h4>
          <p className="text-sm text-gray-500">Manage your passkeys for passwordless authentication.</p>
        </div>
        <button
          onClick={startRegistration}
          disabled={registering}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          type="button"
        >
          {registering ? 'Registering…' : 'Register new passkey'}
        </button>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3" role="alert">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Device name prompt */}
      {showNamePrompt && (
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 space-y-3">
          <p className="text-sm font-medium text-gray-900">Name your passkey</p>
          <p className="text-sm text-gray-600">
            Give this passkey a friendly name to help you identify it later (e.g. "Work Laptop", "YubiKey").
          </p>
          <input
            type="text"
            value={deviceName}
            onChange={e => setDeviceName(e.target.value)}
            placeholder="My Passkey"
            maxLength={50}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label="Passkey name"
            autoFocus
          />
          <div className="flex gap-2">
            <button
              onClick={() => setShowNamePrompt(false)}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              type="button"
            >
              Cancel
            </button>
            <button
              onClick={handleRegister}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
              type="button"
            >
              Continue
            </button>
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-4">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" role="status" aria-label="Loading passkeys" />
        </div>
      )}

      {/* Passkey list */}
      {!loading && credentials.length === 0 && (
        <p className="text-sm text-gray-400">No passkeys registered yet.</p>
      )}

      {!loading && credentials.length > 0 && (
        <div className="divide-y divide-gray-100">
          {credentials.map(cred => (
            <div key={cred.credential_id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                {renamingId === cred.credential_id ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={renameValue}
                      onChange={e => setRenameValue(e.target.value)}
                      maxLength={50}
                      className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      aria-label="New passkey name"
                      autoFocus
                    />
                    <button
                      onClick={handleRenameSave}
                      disabled={renameLoading || !renameValue.trim()}
                      className="rounded border border-gray-300 px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 disabled:opacity-50"
                      type="button"
                    >
                      {renameLoading ? 'Saving…' : 'Save'}
                    </button>
                    <button
                      onClick={handleRenameCancel}
                      className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
                      type="button"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    <p className="text-sm font-medium text-gray-900 truncate">{cred.device_name}</p>
                    <p className="text-xs text-gray-500">
                      Registered {formatDate(cred.created_at)} · Last used {formatDate(cred.last_used_at)}
                    </p>
                  </>
                )}
              </div>

              {renamingId !== cred.credential_id && (
                <div className="flex items-center gap-2 ml-3 shrink-0">
                  <button
                    onClick={() => handleRenameStart(cred)}
                    className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
                    type="button"
                  >
                    Rename
                  </button>
                  <button
                    onClick={() => setRemoveId(cred.credential_id)}
                    className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                    type="button"
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Password confirmation for removal */}
      <PasswordConfirmModal
        open={removeId !== null}
        onClose={() => setRemoveId(null)}
        onConfirm={handleRemoveConfirm}
        loading={removeLoading}
        title="Remove Passkey"
        description="Enter your password to confirm removing this passkey."
      />
    </div>
  )
}
