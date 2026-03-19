import { useState } from 'react'
import apiClient from '@/api/client'

type PanelState = 'idle' | 'generated' | 'dismissed'

interface BackupCodesResponse {
  codes: string[]
}

export function BackupCodesPanel() {
  const [state, setState] = useState<PanelState>('idle')
  const [codes, setCodes] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const generateCodes = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.post<BackupCodesResponse>('/auth/mfa/backup-codes')
      setCodes(res.data.codes)
      setState('generated')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to generate backup codes')
    } finally {
      setLoading(false)
    }
  }

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API may not be available
    }
  }

  const downloadCodes = () => {
    const text = codes.join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'budgetflow-backup-codes.txt'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const dismiss = () => {
    setCodes([])
    setState('dismissed')
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <h4 className="text-sm font-medium text-gray-900">Backup Codes</h4>
      <p className="text-sm text-gray-500">
        Generate backup recovery codes in case you lose access to your MFA methods.
      </p>

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3" role="alert">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* State: codes just generated — show them */}
      {state === 'generated' && codes.length > 0 && (
        <div className="space-y-3">
          <div className="rounded-md bg-amber-50 border border-amber-200 p-3" role="alert">
            <p className="text-sm font-medium text-amber-800">
              These codes are shown only once and cannot be retrieved again.
            </p>
            <p className="text-sm text-amber-700 mt-1">
              Save them in a secure location.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {codes.map((code) => (
              <code
                key={code}
                className="rounded bg-gray-50 border border-gray-200 px-3 py-1.5 text-sm font-mono text-gray-900 text-center select-all"
              >
                {code}
              </code>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              onClick={copyAll}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              type="button"
            >
              {copied ? 'Copied!' : 'Copy all'}
            </button>
            <button
              onClick={downloadCodes}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              type="button"
            >
              Download
            </button>
            <button
              onClick={dismiss}
              className="ml-auto rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
              type="button"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {/* State: dismissed — codes were generated previously */}
      {state === 'dismissed' && (
        <div className="space-y-3">
          <p className="text-sm text-green-700">Codes generated</p>
          <button
            onClick={generateCodes}
            disabled={loading}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            type="button"
          >
            {loading ? 'Generating…' : 'Regenerate codes'}
          </button>
        </div>
      )}

      {/* State: idle — no codes generated yet */}
      {state === 'idle' && (
        <button
          onClick={generateCodes}
          disabled={loading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          type="button"
        >
          {loading ? 'Generating…' : 'Generate backup codes'}
        </button>
      )}
    </div>
  )
}
