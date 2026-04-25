import { useState, useCallback } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { MobileButton, MobileInput, MobileCard } from '@/components/ui'
import { ModuleGate } from '@/components/common/ModuleGate'
import apiClient from '@/api/client'

/**
 * SMS Compose screen — message composition with pre-filled customer phone,
 * send via backend Connexus endpoint, delivery confirmation, error handling.
 *
 * Requirements: 38.1, 38.2, 38.3, 38.4
 */
function SMSComposeContent() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const [phone, setPhone] = useState(searchParams.get('phone') ?? '')
  const [message, setMessage] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)

  const charCount = message.length
  const maxChars = 160

  const handleSend = useCallback(async () => {
    if (!phone.trim()) {
      setResult({ success: false, message: 'Phone number is required' })
      return
    }
    if (!message.trim()) {
      setResult({ success: false, message: 'Message is required' })
      return
    }

    setIsSending(true)
    setResult(null)

    try {
      await apiClient.post('/api/v2/sms/send', {
        phone: phone.trim(),
        message: message.trim(),
      })
      setResult({ success: true, message: 'SMS sent successfully' })
      setMessage('')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setResult({ success: false, message: detail ?? 'Failed to send SMS' })
    } finally {
      setIsSending(false)
    }
  }, [phone, message])

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Send SMS</h1>

      <MobileCard>
        <div className="flex flex-col gap-4">
          <MobileInput
            label="Phone Number"
            type="tel"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value)
              setResult(null)
            }}
            placeholder="+64 21 123 4567"
          />

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
              Message
            </label>
            <textarea
              value={message}
              onChange={(e) => {
                setMessage(e.target.value)
                setResult(null)
              }}
              placeholder="Type your message..."
              rows={4}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500"
            />
            <p className={`mt-1 text-right text-xs ${charCount > maxChars ? 'text-red-500' : 'text-gray-500 dark:text-gray-400'}`}>
              {charCount}/{maxChars}
            </p>
          </div>

          {/* Result message */}
          {result && (
            <div
              role="alert"
              className={`rounded-lg p-3 text-sm ${
                result.success
                  ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                  : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
              }`}
            >
              {result.message}
            </div>
          )}

          <MobileButton
            variant="primary"
            fullWidth
            onClick={handleSend}
            isLoading={isSending}
            disabled={!phone.trim() || !message.trim()}
          >
            Send SMS
          </MobileButton>
        </div>
      </MobileCard>
    </div>
  )
}

export default function SMSComposeScreen() {
  return (
    <ModuleGate moduleSlug="sms">
      <SMSComposeContent />
    </ModuleGate>
  )
}
