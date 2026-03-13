import { useState, useEffect, useCallback, useRef } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Conversation {
  id: string
  phone_number: string
  contact_name: string | null
  last_message_preview: string
  last_message_at: string
  unread_count: number
  is_archived: boolean
}

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  body: string
  from_number: string
  to_number: string
  status: string
  parts_count: number
  cost_nzd: number | null
  sent_at: string | null
  delivered_at: string | null
  created_at: string
}

interface SmsTemplate {
  id: string
  name: string
  body: string
}

interface ValidationResult {
  success: boolean
  error?: string
  carrier?: string
  current_network?: string
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const POLL_INTERVAL = 15_000
const SMS_PART_LENGTH = 160

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTimestamp(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffDays = Math.floor(diffMs / 86_400_000)

  if (diffDays === 0) {
    return d.toLocaleTimeString('en-NZ', { hour: 'numeric', minute: '2-digit', hour12: true })
  }
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) {
    return d.toLocaleDateString('en-NZ', { weekday: 'short' })
  }
  return d.toLocaleDateString('en-NZ', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function formatMessageTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-NZ', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function computeParts(text: string): number {
  return text.length === 0 ? 0 : Math.ceil(text.length / SMS_PART_LENGTH)
}

/* ------------------------------------------------------------------ */
/*  Status indicator                                                   */
/* ------------------------------------------------------------------ */

function StatusIndicator({ status }: { status: string }) {
  const map: Record<string, { label: string; color: string; icon: string }> = {
    pending: { label: 'Pending', color: 'text-gray-400', icon: '○' },
    accepted: { label: 'Accepted', color: 'text-blue-500', icon: '✓' },
    queued: { label: 'Queued', color: 'text-blue-400', icon: '◷' },
    delivered: { label: 'Delivered', color: 'text-green-500', icon: '✓✓' },
    undelivered: { label: 'Undelivered', color: 'text-red-500', icon: '✕' },
    failed: { label: 'Failed', color: 'text-red-500', icon: '✕' },
  }
  const s = map[status] ?? map.pending
  return (
    <span className={`text-xs ${s.color}`} title={s.label} aria-label={`Status: ${s.label}`}>
      {s.icon}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  New Conversation Dialog                                            */
/* ------------------------------------------------------------------ */

function NewConversationDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (convId: string) => void
}) {
  const [phone, setPhone] = useState('')
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setPhone('')
      setBody('')
      setValidation(null)
      setError(null)
    }
  }, [open])

  const validateNumber = useCallback(async (number: string) => {
    if (number.length < 8) {
      setValidation(null)
      return
    }
    setValidating(true)
    try {
      const res = await apiClient.post('/api/v2/org/sms/validate-number', { number })
      setValidation(res.data)
    } catch {
      setValidation({ success: false, error: 'Validation unavailable' })
    } finally {
      setValidating(false)
    }
  }, [])

  // Debounced validation
  useEffect(() => {
    if (!phone) { setValidation(null); return }
    const timer = setTimeout(() => validateNumber(phone), 600)
    return () => clearTimeout(timer)
  }, [phone, validateNumber])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!phone.trim() || !body.trim()) return
    setSending(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v2/org/sms/conversations/new', {
        phone_number: phone.trim(),
        body: body.trim(),
      })
      onCreated(res.data.id)
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Failed to start conversation')
    } finally {
      setSending(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true" aria-label="New conversation">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">New Conversation</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Input
              label="Phone number"
              placeholder="+6421234567"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              error={validation && !validation.success ? validation.error : undefined}
            />
            {validating && <p className="mt-1 text-xs text-gray-400">Validating…</p>}
            {validation?.success && validation.carrier && (
              <p className="mt-1 text-xs text-green-600">
                ✓ {validation.carrier}{validation.current_network ? ` (${validation.current_network})` : ''}
              </p>
            )}
          </div>
          <div>
            <label htmlFor="new-conv-body" className="text-sm font-medium text-gray-700">Message</label>
            <textarea
              id="new-conv-body"
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              rows={3}
              placeholder="Type your message…"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
            <p className="mt-1 text-xs text-gray-400">
              {body.length} chars · {computeParts(body)} part{computeParts(body) !== 1 ? 's' : ''}
            </p>
          </div>
          {error && <AlertBanner variant="error">{error}</AlertBanner>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={sending} disabled={!phone.trim() || !body.trim()}>
              Send
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Template Selector                                                  */
/* ------------------------------------------------------------------ */

function TemplateSelector({ onSelect }: { onSelect: (body: string) => void }) {
  const [templates, setTemplates] = useState<SmsTemplate[]>([])
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await apiClient.get('/api/v2/org/notification-templates', { params: { channel: 'sms' } })
        if (!cancelled) {
          const items = res.data?.items ?? res.data ?? []
          setTemplates(Array.isArray(items) ? items : [])
        }
      } catch {
        // Templates are optional — silently ignore
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (templates.length === 0) return null

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="rounded p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
        title="Insert template"
        aria-label="Insert template"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-1 w-64 max-h-48 overflow-y-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg" role="menu" aria-label="SMS templates">
          {templates.map((t) => (
            <button
              key={t.id}
              role="menuitem"
              className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 focus-visible:bg-gray-100 focus-visible:outline-none"
              onClick={() => { onSelect(t.body); setOpen(false) }}
            >
              <span className="font-medium text-gray-800">{t.name}</span>
              <span className="block truncate text-xs text-gray-500">{t.body}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Conversation List                                                  */
/* ------------------------------------------------------------------ */

function ConversationList({
  conversations,
  selectedId,
  search,
  onSearchChange,
  onSelect,
  onNewConversation,
  loading,
}: {
  conversations: Conversation[]
  selectedId: string | null
  search: string
  onSearchChange: (v: string) => void
  onSelect: (c: Conversation) => void
  onNewConversation: () => void
  loading: boolean
}) {
  return (
    <div className="flex h-full flex-col border-r border-gray-200 bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <h2 className="text-lg font-semibold text-gray-900">SMS</h2>
        <Button size="sm" onClick={onNewConversation} aria-label="New conversation">
          + New
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <Input
          label=""
          placeholder="Search conversations…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          aria-label="Search conversations"
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto" role="listbox" aria-label="Conversations">
        {loading && conversations.length === 0 && (
          <div className="flex justify-center py-8">
            <Spinner size="sm" label="Loading conversations" />
          </div>
        )}
        {!loading && conversations.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-gray-400">No conversations yet</p>
        )}
        {conversations.map((c) => (
          <button
            key={c.id}
            role="option"
            aria-selected={c.id === selectedId}
            onClick={() => onSelect(c)}
            className={`w-full px-4 py-3 text-left transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${
              c.id === selectedId ? 'bg-blue-50' : ''
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium text-gray-900">
                    {c.contact_name || c.phone_number}
                  </span>
                  {c.unread_count > 0 && (
                    <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-blue-600 px-1.5 text-xs font-semibold text-white" aria-label={`${c.unread_count} unread`}>
                      {c.unread_count}
                    </span>
                  )}
                </div>
                {c.contact_name && (
                  <p className="text-xs text-gray-400">{c.phone_number}</p>
                )}
                <p className="mt-0.5 truncate text-sm text-gray-500">{c.last_message_preview}</p>
              </div>
              <span className="shrink-0 text-xs text-gray-400">
                {formatTimestamp(c.last_message_at)}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Message Thread                                                     */
/* ------------------------------------------------------------------ */

function MessageThread({
  conversation,
  messages,
  loading,
  composeText,
  onComposeChange,
  onSend,
  sending,
  onBack,
}: {
  conversation: Conversation | null
  messages: Message[]
  loading: boolean
  composeText: string
  onComposeChange: (v: string) => void
  onSend: () => void
  sending: boolean
  onBack: () => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!conversation) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-50">
        <p className="text-gray-400">Select a conversation to start messaging</p>
      </div>
    )
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  const parts = computeParts(composeText)

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Thread header */}
      <div className="flex items-center gap-3 border-b border-gray-200 px-4 py-3">
        {/* Back button for mobile */}
        <button
          onClick={onBack}
          className="rounded p-1 text-gray-400 hover:text-gray-600 md:hidden"
          aria-label="Back to conversations"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-medium text-gray-900">
            {conversation.contact_name || conversation.phone_number}
          </h3>
          {conversation.contact_name && (
            <p className="text-xs text-gray-500">{conversation.phone_number}</p>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3" role="log" aria-label="Message history" aria-live="polite">
        {loading && messages.length === 0 && (
          <div className="flex justify-center py-8">
            <Spinner size="sm" label="Loading messages" />
          </div>
        )}
        {messages.map((m) => {
          const isOutbound = m.direction === 'outbound'
          return (
            <div key={m.id} className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[75%] rounded-lg px-3 py-2 ${
                  isOutbound
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-900'
                }`}
              >
                <p className="whitespace-pre-wrap break-words text-sm">{m.body}</p>
                <div className={`mt-1 flex items-center gap-1.5 text-xs ${isOutbound ? 'text-blue-200' : 'text-gray-400'}`}>
                  <span>{formatMessageTime(m.sent_at || m.created_at)}</span>
                  {isOutbound && <StatusIndicator status={m.status} />}
                </div>
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>

      {/* Compose bar */}
      <div className="border-t border-gray-200 px-4 py-3">
        <div className="flex items-end gap-2">
          <TemplateSelector onSelect={onComposeChange} />
          <div className="flex-1">
            <textarea
              className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus-visible:outline-none"
              rows={2}
              placeholder="Type a message…"
              value={composeText}
              onChange={(e) => onComposeChange(e.target.value)}
              onKeyDown={handleKeyDown}
              aria-label="Compose message"
            />
            <div className="mt-1 flex items-center justify-between text-xs text-gray-400">
              <span>
                {composeText.length} / {SMS_PART_LENGTH} · {parts} part{parts !== 1 ? 's' : ''}
              </span>
              <span>Shift+Enter for new line</span>
            </div>
          </div>
          <Button
            onClick={onSend}
            loading={sending}
            disabled={!composeText.trim()}
            size="sm"
            aria-label="Send message"
          >
            Send
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main SmsChat Component                                             */
/* ------------------------------------------------------------------ */

export function SmsChat() {
  /* ---- state ---- */
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConv, setSelectedConv] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [search, setSearch] = useState('')
  const [composeText, setComposeText] = useState('')
  const [loadingConvs, setLoadingConvs] = useState(true)
  const [loadingMsgs, setLoadingMsgs] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newDialogOpen, setNewDialogOpen] = useState(false)
  // Mobile: when a conversation is selected, show thread instead of list
  const [mobileShowThread, setMobileShowThread] = useState(false)

  /* ---- refs for polling ---- */
  const selectedConvRef = useRef<Conversation | null>(null)
  selectedConvRef.current = selectedConv
  const searchRef = useRef(search)
  searchRef.current = search

  /* ---- fetch conversations ---- */
  const fetchConversations = useCallback(async (searchQuery?: string) => {
    try {
      const res = await apiClient.get('/api/v2/org/sms/conversations', {
        params: { page: 1, per_page: 50, search: searchQuery ?? searchRef.current },
      })
      setConversations(res.data.items ?? [])
    } catch {
      setError('Failed to load conversations')
    } finally {
      setLoadingConvs(false)
    }
  }, [])

  /* ---- fetch messages for selected conversation ---- */
  const fetchMessages = useCallback(async (convId: string) => {
    setLoadingMsgs(true)
    try {
      const res = await apiClient.get(`/api/v2/org/sms/conversations/${convId}/messages`, {
        params: { page: 1, per_page: 200 },
      })
      setMessages(res.data.items ?? [])
    } catch {
      setError('Failed to load messages')
    } finally {
      setLoadingMsgs(false)
    }
  }, [])

  /* ---- initial load ---- */
  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  /* ---- debounced search ---- */
  useEffect(() => {
    const timer = setTimeout(() => {
      setLoadingConvs(true)
      fetchConversations(search)
    }, 300)
    return () => clearTimeout(timer)
  }, [search, fetchConversations])

  /* ---- load messages when conversation selected ---- */
  useEffect(() => {
    if (selectedConv) {
      fetchMessages(selectedConv.id)
      // Mark as read
      apiClient.post(`/api/v2/org/sms/conversations/${selectedConv.id}/read`).catch(() => {})
      // Update local unread count
      setConversations((prev) =>
        prev.map((c) => (c.id === selectedConv.id ? { ...c, unread_count: 0 } : c)),
      )
    } else {
      setMessages([])
    }
  }, [selectedConv, fetchMessages])

  /* ---- 15-second polling ---- */
  useEffect(() => {
    const interval = setInterval(() => {
      fetchConversations()
      if (selectedConvRef.current) {
        fetchMessages(selectedConvRef.current.id)
      }
    }, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [fetchConversations, fetchMessages])

  /* ---- select conversation ---- */
  function handleSelectConversation(c: Conversation) {
    setSelectedConv(c)
    setComposeText('')
    setMobileShowThread(true)
  }

  /* ---- send reply (optimistic) ---- */
  async function handleSend() {
    if (!selectedConv || !composeText.trim()) return
    const body = composeText.trim()
    setComposeText('')
    setSending(true)

    // Optimistic message
    const optimisticMsg: Message = {
      id: `optimistic-${Date.now()}`,
      direction: 'outbound',
      body,
      from_number: '',
      to_number: selectedConv.phone_number,
      status: 'pending',
      parts_count: computeParts(body),
      cost_nzd: null,
      sent_at: null,
      delivered_at: null,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticMsg])

    // Update conversation preview locally
    setConversations((prev) =>
      prev.map((c) =>
        c.id === selectedConv.id
          ? { ...c, last_message_preview: body.slice(0, 100), last_message_at: optimisticMsg.created_at }
          : c,
      ),
    )

    try {
      const res = await apiClient.post(`/api/v2/org/sms/conversations/${selectedConv.id}/reply`, { body })
      // Replace optimistic message with real status
      setMessages((prev) =>
        prev.map((m) =>
          m.id === optimisticMsg.id
            ? { ...m, id: res.data.id ?? m.id, status: res.data.status ?? 'accepted' }
            : m,
        ),
      )
    } catch {
      // Mark optimistic message as failed
      setMessages((prev) =>
        prev.map((m) => (m.id === optimisticMsg.id ? { ...m, status: 'failed' } : m)),
      )
    } finally {
      setSending(false)
    }
  }

  /* ---- new conversation created ---- */
  function handleNewConversationCreated(convId: string) {
    fetchConversations().then(() => {
      // Select the newly created conversation
      setConversations((prev) => {
        const found = prev.find((c) => c.id === convId)
        if (found) {
          setSelectedConv(found)
          setMobileShowThread(true)
        }
        return prev
      })
    })
  }

  /* ---- mobile back ---- */
  function handleMobileBack() {
    setMobileShowThread(false)
    setSelectedConv(null)
  }

  /* ---- render ---- */
  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden rounded-lg border border-gray-200 bg-white">
      {error && (
        <div className="absolute left-0 right-0 top-0 z-20 px-4 pt-2">
          <AlertBanner variant="error" onDismiss={() => setError(null)}>{error}</AlertBanner>
        </div>
      )}

      {/* Conversation list — hidden on mobile when thread is shown */}
      <div className={`w-full md:w-80 md:shrink-0 md:block ${mobileShowThread ? 'hidden' : 'block'}`}>
        <ConversationList
          conversations={conversations}
          selectedId={selectedConv?.id ?? null}
          search={search}
          onSearchChange={setSearch}
          onSelect={handleSelectConversation}
          onNewConversation={() => setNewDialogOpen(true)}
          loading={loadingConvs}
        />
      </div>

      {/* Message thread — hidden on mobile when list is shown */}
      <div className={`flex-1 md:block ${mobileShowThread ? 'block' : 'hidden'}`}>
        <MessageThread
          conversation={selectedConv}
          messages={messages}
          loading={loadingMsgs}
          composeText={composeText}
          onComposeChange={setComposeText}
          onSend={handleSend}
          sending={sending}
          onBack={handleMobileBack}
        />
      </div>

      <NewConversationDialog
        open={newDialogOpen}
        onClose={() => setNewDialogOpen(false)}
        onCreated={handleNewConversationCreated}
      />
    </div>
  )
}

export default SmsChat
