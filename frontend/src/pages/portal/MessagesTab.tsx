import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { usePortalLocale } from './PortalLocaleContext'
import { formatDate } from './portalFormatters'

interface PortalMessage {
  id: string
  direction: string
  body: string
  created_at: string
  status: string | null
}

interface MessagesTabProps {
  token: string
}

export function MessagesTab({ token }: MessagesTabProps) {
  const locale = usePortalLocale()
  const [messages, setMessages] = useState<PortalMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const fetchMessages = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get(`/portal/${token}/messages`, { signal: controller.signal })
        setMessages(res.data?.messages ?? [])
      } catch (err) {
        if (!controller.signal.aborted) setError('Failed to load messages.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchMessages()
    return () => controller.abort()
  }, [token])

  if (loading) return <div className="py-8"><Spinner label="Loading messages" /></div>
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (messages.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-500">No messages found.</p>
  }

  return (
    <div className="flex flex-col gap-3 max-w-2xl mx-auto">
      {messages.map((msg) => {
        const isOutbound = msg.direction === 'outbound'
        return (
          <div
            key={msg.id}
            className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[75%] rounded-lg px-4 py-2 text-sm ${
                isOutbound
                  ? 'bg-blue-50 text-gray-900'
                  : 'bg-gray-100 text-gray-900'
              }`}
              style={isOutbound ? { backgroundColor: 'color-mix(in srgb, var(--portal-accent, #2563eb) 10%, white)' } : undefined}
            >
              <p className="whitespace-pre-wrap break-words">{msg.body}</p>
              <div className={`mt-1 flex items-center gap-2 text-xs text-gray-400 ${isOutbound ? 'justify-end' : ''}`}>
                <span>{formatDate(msg.created_at, locale)}</span>
                {isOutbound && msg.status && (
                  <span className="capitalize">{msg.status}</span>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
