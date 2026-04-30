import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Page,
  Messages,
  Message,
  Messagebar,
  List,
  ListItem,
  Block,
  Preloader,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import apiClient from '@/api/client'

interface Conversation {
  id: string
  phone: string
  contact_name: string | null
  last_message: string | null
  last_message_at: string | null
  unread_count: number
}

interface SmsMessage {
  id: string
  direction: 'inbound' | 'outbound'
  body: string
  created_at: string
  status: string | null
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  try { return new Date(dateStr).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }) }
  catch { return dateStr }
}

function SMSContent() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConvo, setSelectedConvo] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<SmsMessage[]>([])
  const [messageText, setMessageText] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  // Fetch conversations
  const fetchConversations = useCallback(async (signal: AbortSignal) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{ items?: Conversation[]; total?: number }>('/api/v2/sms/conversations', { signal })
      setConversations(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load conversations')
    } finally { setIsLoading(false) }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    fetchConversations(c.signal)
    return () => c.abort()
  }, [fetchConversations])

  // Fetch messages for selected conversation
  const fetchMessages = useCallback(async (convoId: string) => {
    try {
      const res = await apiClient.get<{ items?: SmsMessage[]; total?: number }>(`/api/v2/sms/conversations/${convoId}/messages`)
      setMessages(res.data?.items ?? [])
    } catch {
      // Error handled silently
    }
  }, [])

  const handleSelectConvo = useCallback((convo: Conversation) => {
    setSelectedConvo(convo)
    fetchMessages(convo.id)
  }, [fetchMessages])

  const handleSend = useCallback(async () => {
    if (!messageText.trim() || !selectedConvo) return
    setIsSending(true)
    try {
      await apiClient.post('/api/v2/sms/send', {
        phone: selectedConvo.phone,
        message: messageText.trim(),
      })
      setMessages((prev) => [...prev, {
        id: `temp-${Date.now()}`,
        direction: 'outbound',
        body: messageText.trim(),
        created_at: new Date().toISOString(),
        status: 'sent',
      }])
      setMessageText('')
    } catch {
      // Error handled silently
    } finally { setIsSending(false) }
  }, [messageText, selectedConvo])

  // Conversation thread view
  if (selectedConvo) {
    return (
      <Page data-testid="sms-thread-page">
        <KonstaNavbar
          title={selectedConvo.contact_name ?? selectedConvo.phone}
          showBack
          onBack={() => setSelectedConvo(null)}
        />

        <Messages data-testid="sms-messages">
          {messages.map((msg) => (
            <Message
              key={msg.id}
              type={msg.direction === 'outbound' ? 'sent' : 'received'}
              text={msg.body}
              name={msg.direction === 'inbound' ? (selectedConvo.contact_name ?? selectedConvo.phone) : 'You'}
              data-testid={`sms-msg-${msg.id}`}
            />
          ))}
          {messages.length === 0 && (
            <div className="flex items-center justify-center p-8">
              <p className="text-sm text-gray-400 dark:text-gray-500">No messages yet</p>
            </div>
          )}
        </Messages>

        <Messagebar
          value={messageText}
          onInput={(e: React.ChangeEvent<HTMLTextAreaElement>) => setMessageText(e.target.value)}
          placeholder="Type a message…"
          data-testid="sms-messagebar"
        >
          <button
            type="button"
            onClick={handleSend}
            disabled={isSending || !messageText.trim()}
            className="ml-2 text-sm font-semibold text-blue-600 disabled:text-gray-400 dark:text-blue-400"
            data-testid="sms-send-btn"
          >
            {isSending ? '…' : 'Send'}
          </button>
        </Messagebar>
      </Page>
    )
  }

  // Conversation list view
  if (isLoading) {
    return (<Page data-testid="sms-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="sms-page">
      <div className="flex flex-col pb-24">
        {error && (
          <Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>
        )}

        {conversations.length === 0 ? (
          <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No conversations</p></Block>
        ) : (
          <List strongIos outlineIos dividersIos data-testid="sms-conversations-list">
            {conversations.map((convo) => (
              <ListItem key={convo.id} link onClick={() => handleSelectConvo(convo)}
                title={<span className="font-bold text-gray-900 dark:text-gray-100">{convo.contact_name ?? convo.phone}</span>}
                subtitle={<span className="text-xs text-gray-500 dark:text-gray-400 line-clamp-1">{convo.last_message ?? 'No messages'}</span>}
                after={
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-xs text-gray-400 dark:text-gray-500">{formatDate(convo.last_message_at)}</span>
                    {(convo.unread_count ?? 0) > 0 && (
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                        {convo.unread_count}
                      </span>
                    )}
                  </div>
                }
                data-testid={`convo-${convo.id}`}
              />
            ))}
          </List>
        )}
      </div>
    </Page>
  )
}

/**
 * SMS Chat screen — Konsta Messages + Messagebar. ModuleGate `sms`.
 * Requirements: 45.1, 45.2, 45.3, 55.1
 */
export default function SMSComposeScreen() {
  return (
    <ModuleGate moduleSlug="sms">
      <SMSContent />
    </ModuleGate>
  )
}
