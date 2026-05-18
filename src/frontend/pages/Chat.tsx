import { useState, useEffect, useRef, Fragment, type ReactNode } from 'react'
import { PageHeader } from '../components/PageHeader'
import { fetchWithAuth } from '../utils/fetchWithAuth'

const CITATION_REGEX = /\[([A-Za-z0-9_\-. ]+\.[A-Za-z0-9]{1,8})(?:#chunk_(\d+))?\]/g

function sourceUrl(filename: string): string {
  const token = localStorage.getItem('token') ?? ''
  const base = filename.split('#')[0] ?? filename
  return `/api/sources/${encodeURIComponent(base)}?token=${encodeURIComponent(token)}`
}

function renderWithCitations(text: string, onOpenSource?: (filename: string) => void): ReactNode {
  const nodes: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  CITATION_REGEX.lastIndex = 0
  while ((match = CITATION_REGEX.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index))
    }
    const filename = match[1]!
    const chunk = match[2]
    const label = chunk ? `[${filename}#chunk_${chunk}]` : `[${filename}]`
    const matchIndex = match.index
    nodes.push(
      <a
        key={`${matchIndex}-${filename}`}
        href="#"
        onClick={(e) => {
          e.preventDefault()
          onOpenSource?.(filename)
        }}
        style={{
          color: 'var(--link-color)',
          textDecoration: 'underline',
          textDecorationThickness: '2px',
          fontWeight: 'bold',
          cursor: 'pointer',
          padding: '0 2px',
        }}
        title={`Open ${filename}`}
      >
        {label}
      </a>,
    )
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }
  return nodes.map((n, i) => <Fragment key={i}>{n}</Fragment>)
}

interface ChatSession {
  id: string
  title: string
  updatedAt: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  sources?: any
  images?: any
}

const SAMPLE_PROMPTS = [
  'I think my leg is broken, what do I do?',
  'I found a water source, how do I purify the water?',
  'Someone has a deep cut that won\'t stop bleeding',
  'How do I build a shelter with no tools?',
  'What wild berries are safe to eat?',
  'Someone is showing signs of heat stroke',
]

const MAX_IMAGE_ATTACHMENTS = 2
const MAX_IMAGE_DIMENSION = 1024
const MAX_IMAGE_DATA_URL_LENGTH = 2_000_000

function parseMessageImages(images: any): string[] {
  if (!images) return []
  try {
    const parsed = typeof images === 'string' ? JSON.parse(images) : images
    if (!Array.isArray(parsed)) return []
    return parsed.filter((image): image is string => typeof image === 'string' && image.startsWith('data:image/'))
  } catch {
    return []
  }
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('failed to read image'))
    reader.readAsDataURL(file)
  })
}

async function compressImage(file: File): Promise<string> {
  const raw = await readFileAsDataUrl(file)
  const image = new Image()
  image.src = raw
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('failed to decode image'))
  })

  const scale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(image.width, image.height))
  const width = Math.max(1, Math.round(image.width * scale))
  const height = Math.max(1, Math.round(image.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('failed to prepare image')
  ctx.drawImage(image, 0, 0, width, height)
  const compressed = canvas.toDataURL('image/jpeg', 0.78)
  if (compressed.length > MAX_IMAGE_DATA_URL_LENGTH) {
    throw new Error('image is too large after compression')
  }
  return compressed
}

function EmptyChatState({
  hasSessions,
  onNewChat,
  onAttachImage,
  onSamplePrompt,
}: {
  hasSessions: boolean
  onNewChat: () => void
  onAttachImage: () => void
  onSamplePrompt: (prompt: string) => void
}) {
  return (
    <div
      style={{
        margin: 'auto',
        width: 'min(100%, 44rem)',
        minHeight: '20rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: '100%',
          padding: '2.5rem 2rem',
          border: '1px solid rgba(var(--main), 0.28)',
          background:
            'linear-gradient(180deg, rgba(var(--alt), 0.12) 0%, rgba(var(--alt), 0.04) 100%)',
          boxShadow: 'inset 0 0 0 1px rgba(var(--main), 0.08)',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '0.78rem',
            letterSpacing: '0.32rem',
            textTransform: 'uppercase',
            color: 'rgba(var(--alt), 0.95)',
            marginBottom: '1rem',
          }}
        >
          Elfin AI Chat
        </div>
        <div
          style={{
            fontSize: '2rem',
            lineHeight: 1.1,
            letterSpacing: '0.12rem',
            textTransform: 'uppercase',
            marginBottom: '1rem',
            color: 'rgb(var(--main))',
            textShadow: '0 0 1.2rem rgba(var(--main), 0.18)',
          }}
        >
          Offline Survival Assistant
        </div>
        <div
          style={{
            maxWidth: '32rem',
            margin: '0 auto 1.75rem',
            color: 'rgba(var(--main), 0.68)',
            lineHeight: 1.6,
            fontSize: '0.96rem',
          }}
        >
          {hasSessions
            ? 'Pick up an old thread from the left, or try one of these:'
            : 'Ask anything about survival, first aid, water, shelter, or food safety.'}
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '0.6rem',
          marginBottom: '1.5rem',
          textAlign: 'left',
        }}>
          {SAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => onSamplePrompt(prompt)}
              style={{
                background: 'var(--source-bg)',
                border: '1px solid rgba(var(--main), 0.2)',
                color: 'rgba(var(--main), 0.8)',
                padding: '0.75rem 1rem',
                cursor: 'pointer',
                fontFamily: 'inherit',
                fontSize: '0.88rem',
                lineHeight: 1.4,
                transition: 'border-color 0.15s, color 0.15s',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'rgba(var(--alt), 0.6)'
                e.currentTarget.style.color = 'rgb(var(--alt))'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'rgba(var(--main), 0.2)'
                e.currentTarget.style.color = 'rgba(var(--main), 0.8)'
              }}
            >
              {prompt}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
          <button className="btn" onClick={onNewChat} style={{ padding: '0.95rem 1.6rem', minWidth: '15rem' }}>
            + START NEW CHAT
          </button>
          <button
            className="btn"
            onClick={onAttachImage}
            style={{
              padding: '0.95rem 1.6rem',
              minWidth: '15rem',
              borderColor: 'rgba(var(--alt), 0.8)',
              color: 'rgb(var(--alt))',
            }}
          >
            + ATTACH IMAGE
          </button>
        </div>
      </div>
    </div>
  )
}

function SamplePromptGrid({
  onAttachImage,
  onSamplePrompt,
}: {
  onAttachImage: () => void
  onSamplePrompt: (prompt: string) => void
}) {
  return (
    <div style={{ margin: 'auto', width: 'min(100%, 40rem)', textAlign: 'center' }}>
        <div style={{ color: 'rgba(var(--main), 0.5)', marginBottom: '1rem', fontSize: '0.88rem', letterSpacing: '0.18rem', textTransform: 'uppercase' }}>
        Try a prompt, type your own below, or attach an image
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.6rem', textAlign: 'left' }}>
        {SAMPLE_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onSamplePrompt(prompt)}
            style={{
              background: 'var(--source-bg)',
              border: '1px solid rgba(var(--main), 0.2)',
              color: 'rgba(var(--main), 0.8)',
              padding: '0.75rem 1rem',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: '0.88rem',
              lineHeight: 1.4,
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = 'rgba(var(--alt), 0.6)'
              e.currentTarget.style.color = 'rgb(var(--alt))'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'rgba(var(--main), 0.2)'
              e.currentTarget.style.color = 'rgba(var(--main), 0.8)'
            }}
          >
            {prompt}
          </button>
        ))}
      </div>
      <button
        className="btn"
        onClick={onAttachImage}
        style={{
          marginTop: '1.25rem',
          padding: '0.9rem 1.4rem',
          minWidth: '16rem',
          borderColor: 'rgba(var(--alt), 0.8)',
          color: 'rgb(var(--alt))',
        }}
      >
        + ATTACH IMAGE
      </button>
    </div>
  )
}

export function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [viewerUrl, setViewerUrl] = useState<string | null>(null)
  const [viewerTitle, setViewerTitle] = useState('')
  const [selectedImages, setSelectedImages] = useState<string[]>([])
  const [imageError, setImageError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const pendingPromptRef = useRef<string | null>(null)

  useEffect(() => {
    if (!viewerUrl) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setViewerUrl(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [viewerUrl])

  const handleOpenSource = (filename: string, kiwixPath?: string) => {
    if (kiwixPath) {
      setViewerUrl(kiwixPath)
    } else {
      setViewerUrl(sourceUrl(filename))
    }
    setViewerTitle(filename)
  }

  const fetchSessions = async () => {
    try {
      const res = await fetchWithAuth('/api/chat/sessions')
      if (res.ok) {
        const data = await res.json()
        setSessions(data.sessions || [])
        // Default to first session if none selected
        if (!selectedSessionId && data.sessions && data.sessions.length > 0) {
          setSelectedSessionId(data.sessions[0].id)
        }
      }
    } catch (err) {
      console.error('Failed to fetch sessions', err)
    }
  }

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastPollContentRef = useRef<string>('')
  const stableCountRef = useRef(0)

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    lastPollContentRef.current = ''
    stableCountRef.current = 0
  }

  const fetchMessages = async (sessionId: string) => {
    try {
      const res = await fetchWithAuth(`/api/chat/sessions/${sessionId}/messages`)
      if (res.ok) {
        const data = await res.json()
        const msgs: Message[] = (data.messages || []).reverse()
        setMessages(msgs)

        const last = msgs[msgs.length - 1]
        const needsPoll = (last && last.role === 'user')
          || (last && last.role === 'assistant' && !last.content?.trim())
        if (needsPoll && !loading) {
          setLoading(true)
          if (!pollRef.current) {
            pollRef.current = setInterval(async () => {
              try {
                const r = await fetchWithAuth(`/api/chat/sessions/${sessionId}/messages`)
                if (!r.ok) return
                const d = await r.json()
                const fresh: Message[] = (d.messages || []).reverse()
                const freshLast = fresh[fresh.length - 1]
                if (freshLast && freshLast.role === 'assistant') {
                  setMessages(fresh)
                  if (freshLast.content === lastPollContentRef.current && freshLast.content.length > 0) {
                    stableCountRef.current++
                  } else {
                    stableCountRef.current = 0
                  }
                  lastPollContentRef.current = freshLast.content
                  if (stableCountRef.current >= 2) {
                    setLoading(false)
                    stopPolling()
                    fetchSessions()
                    setTimeout(() => fetchSessions(), 8000)
                  }
                }
              } catch {}
            }, 2000)
          }
        } else {
          stopPolling()
        }
      }
    } catch (err) {
      console.error('Failed to fetch messages', err)
    }
  }

  useEffect(() => {
    fetchSessions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = null
    stopPolling()
    setLoading(false)
    if (selectedSessionId) {
      fetchMessages(selectedSessionId).then(() => {
        if (pendingPromptRef.current) {
          const prompt = pendingPromptRef.current
          pendingPromptRef.current = null
          handleSend(undefined, prompt)
        }
      })
    } else {
      setMessages([])
    }
  }, [selectedSessionId])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && selectedSessionId && !loading) {
        fetchMessages(selectedSessionId)
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [selectedSessionId, loading])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      stopPolling()
    }
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: loading ? 'instant' : 'smooth' })
  }, [messages, loading])

  const createChatSession = async (): Promise<string | null> => {
    try {
      const res = await fetchWithAuth('/api/chat/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat' })
      })
      if (res.ok) {
        const data = await res.json()
        setSessions([data.session, ...sessions])
        setSelectedSessionId(data.session.id)
        return data.session.id
      }
    } catch (err) {
      console.error('Failed to create new chat', err)
    }
    return null
  }

  const handleNewChat = async () => {
    await createChatSession()
  }

  const handleAttachImage = async () => {
    if (!selectedSessionId) {
      const id = await createChatSession()
      if (!id) return
      window.setTimeout(() => fileInputRef.current?.click(), 0)
      return
    }
    fileInputRef.current?.click()
  }

  const handleDeleteSession = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (!confirm('Delete this chat?')) return
    try {
      const res = await fetchWithAuth(`/api/chat/sessions/${id}`, {
        method: 'DELETE'
      })
      if (res.ok) {
        if (selectedSessionId === id) {
          setSelectedSessionId(null)
          setMessages([])
        }
        await fetchSessions()
      }
    } catch (err) {
      console.error('Failed to delete chat', err)
    }
  }

  const handleSamplePrompt = async (prompt: string) => {
    try {
      const res = await fetchWithAuth('/api/chat/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat' })
      })
      if (res.ok) {
        const data = await res.json()
        setSessions([data.session, ...sessions])
        setSelectedSessionId(data.session.id)
        pendingPromptRef.current = prompt
      }
    } catch (err) {
      console.error('Failed to create chat for sample prompt', err)
    }
  }

  const handleImageFiles = async (files: FileList | null) => {
    setImageError('')
    if (!files || files.length === 0) return
    const imageFiles = Array.from(files).filter(file => file.type.startsWith('image/'))
    const slots = MAX_IMAGE_ATTACHMENTS - selectedImages.length
    if (slots <= 0) {
      setImageError(`Only ${MAX_IMAGE_ATTACHMENTS} images can be attached.`)
      return
    }

    try {
      const compressed: string[] = []
      for (const file of imageFiles.slice(0, slots)) {
        compressed.push(await compressImage(file))
      }
      if (compressed.length === 0) {
        setImageError('Choose a PNG, JPG, or WebP image.')
        return
      }
      setSelectedImages(prev => [...prev, ...compressed].slice(0, MAX_IMAGE_ATTACHMENTS))
    } catch (err: any) {
      setImageError(err?.message || 'Could not attach image.')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleSend = async (e?: React.FormEvent, directMessage?: string) => {
    e?.preventDefault()
    const outgoingImages = directMessage ? [] : selectedImages
    const userMessageContent = directMessage || input.trim() || (outgoingImages.length > 0 ? 'Analyze this image for survival-relevant details.' : '')
    if ((!userMessageContent && outgoingImages.length === 0) || loading || !selectedSessionId) return

    setInput('')
    if (!directMessage) setSelectedImages([])
    setLoading(true)

    const tempUserId = `tmp-u-${Date.now()}`
    const tempAssistantId = `tmp-a-${Date.now()}`
    setMessages(prev => [
      ...prev,
      { id: tempUserId, role: 'user', content: userMessageContent, images: outgoingImages.length > 0 ? outgoingImages : null, createdAt: new Date().toISOString() },
      { id: tempAssistantId, role: 'assistant', content: '', createdAt: new Date(Date.now() + 1).toISOString() },
    ])

    const updateAssistant = (patch: Partial<Message>) => {
      setMessages(prev => prev.map(m => (m.id === tempAssistantId ? { ...m, ...patch } : m)))
    }

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/chat/sessions/${selectedSessionId}/messages?stream=1`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          sessionId: selectedSessionId,
          message: userMessageContent,
          images: outgoingImages.length > 0 ? outgoingImages : undefined,
        }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        if (res.status === 401) {
          localStorage.removeItem('token')
          window.location.href = '/'
          return
        }
        updateAssistant({ content: `[error] HTTP ${res.status}` })
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let acc = ''
      let accSources: any = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let sep
        while ((sep = buf.indexOf('\n\n')) !== -1) {
          const chunk = buf.slice(0, sep)
          buf = buf.slice(sep + 2)
          for (const line of chunk.split('\n')) {
            if (!line.startsWith('data:')) continue
            const payload = line.slice(5).trim()
            if (!payload) continue
            let ev: any
            try { ev = JSON.parse(payload) } catch { continue }
            if (ev.type === 'sources') {
              accSources = ev.sources
              updateAssistant({ sources: accSources })
            } else if (ev.type === 'delta') {
              acc += ev.content
              updateAssistant({ content: acc })
            } else if (ev.type === 'done' && ev.message) {
              setMessages(prev => prev.map(m => {
                if (m.id === tempUserId) return m
                if (m.id === tempAssistantId) return ev.message
                return m
              }))
            } else if (ev.type === 'user_message' && ev.message) {
              setMessages(prev => prev.map(m => (m.id === tempUserId ? ev.message : m)))
            } else if (ev.type === 'title' && ev.title) {
              setSessions(prev => prev.map(s => s.id === ev.sessionId ? { ...s, title: ev.title } : s))
            } else if (ev.type === 'error') {
              updateAssistant({ content: acc + `\n[error] ${ev.message}` })
            }
          }
        }
      }

      fetchSessions()
    } catch (err: any) {
      if (err?.name === 'AbortError') return
      console.error('Stream error', err)
      updateAssistant({ content: `[error] ${err?.message || 'connection failed'}` })
    } finally {
      abortRef.current = null
      setLoading(false)
    }
  }

  return (
    <>
      <PageHeader title="AI Chat" />
      <div style={{ display: 'flex', flex: 1, minHeight: 0, gap: '1rem', marginTop: '1rem' }}>

        {/* Left Pane: Chat Sessions List */}
        <div style={{ width: '250px', minWidth: '180px', maxWidth: '250px', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <button className="btn" onClick={handleNewChat} style={{ padding: '0.75rem' }}>+ NEW CHAT</button>
          
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {sessions.map(s => (
              <div 
                key={s.id} 
                onClick={() => setSelectedSessionId(s.id)}
                style={{ 
                  padding: '1rem', 
                  border: `1px solid ${selectedSessionId === s.id ? 'rgb(var(--main))' : 'rgba(var(--main), 0.2)'}`,
                  cursor: 'pointer',
                  background: selectedSessionId === s.id ? 'rgba(var(--alt), 0.1)' : 'transparent',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}
              >
                <div style={{ overflow: 'hidden' }}>
                  <div style={{ fontWeight: 'bold', marginBottom: '0.25rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.title}</div>
                  <div style={{ fontSize: '0.8em', color: 'rgba(var(--main), 0.5)' }}>
                    {new Date(s.updatedAt).toLocaleDateString()}
                  </div>
                </div>
                <button 
                  onClick={(e) => handleDeleteSession(e, s.id)}
                  style={{
                    background: 'transparent',
                    border: '1px solid rgba(255, 68, 68, 0.4)',
                    color: '#f44',
                    padding: '0.25rem 0.5rem',
                    cursor: 'pointer',
                    fontSize: '0.8em'
                  }}
                >
                  X
                </button>
              </div>
            ))}
            {sessions.length === 0 && <div className="text-dim" style={{ textAlign: 'center', marginTop: '2rem' }}>No chats found</div>}
          </div>
        </div>

        {/* Right Pane: Chat Messages Area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="card" style={{ flex: 1, overflowY: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {!selectedSessionId ? (
              <EmptyChatState
                hasSessions={sessions.length > 0}
                onNewChat={handleNewChat}
                onAttachImage={handleAttachImage}
                onSamplePrompt={handleSamplePrompt}
              />
            ) : messages.length === 0 ? (
              <SamplePromptGrid
                onAttachImage={handleAttachImage}
                onSamplePrompt={(prompt) => handleSend(undefined, prompt)}
              />
            ) : (
              messages.map(m => (
                <div 
                  key={m.id} 
                  style={{
                    alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: m.role === 'user' ? '80%' : '95%',
                    background: m.role === 'user' ? 'var(--msg-user)' : 'var(--msg-assistant)',
                    border: `1px solid ${m.role === 'user' ? 'rgba(var(--main), 0.3)' : 'rgba(var(--alt), 0.4)'}`,
                    padding: '1rem',
                    borderRadius: '4px'
                  }}
                >
                  <div style={{ fontWeight: 'bold', marginBottom: '0.5rem', color: m.role === 'user' ? 'rgb(var(--main))' : 'rgb(var(--alt))' }}>
                    {m.role === 'user' ? 'YOU' : 'ELFIN'}
                  </div>
                  {parseMessageImages(m.images).length > 0 && (
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                      {parseMessageImages(m.images).map((image, idx) => (
                        <img
                          key={`${m.id}-image-${idx}`}
                          src={image}
                          alt={`Attached image ${idx + 1}`}
                          style={{
                            width: '9rem',
                            maxHeight: '7rem',
                            objectFit: 'cover',
                            border: '1px solid rgba(var(--alt), 0.45)',
                            background: '#050805',
                          }}
                        />
                      ))}
                    </div>
                  )}
                  {m.sources && (
                    <div style={{ marginBottom: '0.75rem', borderBottom: '1px solid rgba(var(--alt), 0.3)', paddingBottom: '0.5rem' }}>
                      <div style={{ fontSize: '0.8em', color: 'rgba(var(--alt), 0.8)', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                        SOURCES:
                      </div>
                      {(() => {
                        try {
                          const parsedSources = typeof m.sources === 'string' ? JSON.parse(m.sources) : m.sources
                          if (!Array.isArray(parsedSources) || parsedSources.length === 0) return null
                          
                          return parsedSources.map((src, idx) => {
                            const fullSource: string = src.source || 'Unknown Source'
                            const isKiwix = fullSource.startsWith('kiwix:')
                            const filename = isKiwix ? fullSource : fullSource.split('#')[0]
                            const isOpenable = filename && filename !== 'Unknown Source' && filename !== 'unknown'
                            const displayLabel = isKiwix ? fullSource.replace('kiwix:', '').replace(':', ' / ') : fullSource
                            return (
                              <div key={idx} style={{
                                fontSize: '0.85em',
                                color: 'rgba(var(--main), 0.7)',
                                background: 'var(--source-bg)',
                                padding: '0.5rem',
                                borderRadius: '4px',
                                marginBottom: '0.5rem',
                                borderLeft: `2px solid ${isKiwix ? 'var(--link-kiwix)' : 'var(--source-border)'}`
                              }}>
                                <div style={{ fontWeight: 'bold', color: isKiwix ? '#4da6ff' : 'rgb(var(--alt))', marginBottom: '0.25rem' }}>
                                  {isOpenable ? (
                                    <a
                                      href="#"
                                      onClick={(e) => {
                                        e.preventDefault()
                                        handleOpenSource(displayLabel, src.kiwixPath)
                                      }}
                                      style={{ color: isKiwix ? 'var(--link-kiwix)' : 'var(--link-color)', textDecoration: 'underline', textDecorationThickness: '2px', cursor: 'pointer' }}
                                      title={`Open ${displayLabel}`}
                                    >
                                      {isKiwix ? `[Wiki: ${displayLabel}]` : `[${fullSource}]`}
                                    </a>
                                  ) : (
                                    <>[{fullSource}]</>
                                  )}
                                  {src.score != null && ` (Relevance: ${Math.round((src.score || 0) * 100)}%)`}
                                </div>
                                <div style={{ fontStyle: 'italic', opacity: 0.8 }}>
                                  "{src.text && src.text.length > 150 ? src.text.substring(0, 150) + '...' : src.text}"
                                </div>
                              </div>
                            )
                          })
                        } catch (e) {
                          return null
                        }
                      })()}
                    </div>
                  )}
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                    {m.role === 'assistant' ? renderWithCitations(m.content, handleOpenSource) : m.content}
                  </div>
                </div>
              ))
            )}
            {loading && (
              <div style={{ alignSelf: 'flex-start', color: 'rgb(var(--alt))', padding: '1rem' }}>
                Elfin is typing<span className="cursor-blink">_</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <form onSubmit={handleSend} style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {(selectedImages.length > 0 || imageError) && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                flexWrap: 'wrap',
                padding: '0.65rem',
                border: '1px solid rgba(var(--main), 0.22)',
                background: 'rgba(var(--alt), 0.06)',
              }}>
                {selectedImages.map((image, idx) => (
                  <div key={`selected-${idx}`} style={{ position: 'relative' }}>
                    <img
                      src={image}
                      alt={`Selected image ${idx + 1}`}
                      style={{
                        width: '5.5rem',
                        height: '4.2rem',
                        objectFit: 'cover',
                        border: '1px solid rgba(var(--alt), 0.45)',
                        background: '#050805',
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => setSelectedImages(prev => prev.filter((_, i) => i !== idx))}
                      style={{
                        position: 'absolute',
                        top: '-0.45rem',
                        right: '-0.45rem',
                        width: '1.3rem',
                        height: '1.3rem',
                        border: '1px solid rgba(255, 68, 68, 0.65)',
                        background: '#210707',
                        color: '#ff7777',
                        cursor: 'pointer',
                        lineHeight: 1,
                      }}
                      aria-label="Remove image"
                    >
                      x
                    </button>
                  </div>
                ))}
                {imageError && <span style={{ color: '#ff7777', fontSize: '0.86rem' }}>{imageError}</span>}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                onChange={e => handleImageFiles(e.target.files)}
                style={{ display: 'none' }}
              />
              <button
                type="button"
                className="btn"
                disabled={loading || !selectedSessionId || selectedImages.length >= MAX_IMAGE_ATTACHMENTS}
                onClick={() => fileInputRef.current?.click()}
                style={{
                  padding: '0 1rem',
                  minWidth: '10.5rem',
                  borderColor: 'rgba(var(--alt), 0.75)',
                  color: 'rgb(var(--alt))',
                }}
                title="Attach image for Gemma vision"
              >
                + ATTACH IMAGE
              </button>
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder={selectedSessionId ? "Ask Elfin something..." : "Select a chat first..."}
                disabled={loading || !selectedSessionId}
                style={{
                  flex: 1,
                  padding: '1rem',
                  background: 'var(--msg-assistant)',
                  color: 'rgb(var(--main))',
                  border: '1px solid rgba(var(--main), 0.4)',
                  fontFamily: 'inherit',
                  fontSize: '1.1em'
                }}
              />
              <button type="submit" className="btn" disabled={loading || (!input.trim() && selectedImages.length === 0) || !selectedSessionId} style={{ padding: '0 2rem' }}>
                SEND
              </button>
            </div>
          </form>
        </div>
      </div>

      {viewerUrl && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ width: '90%', height: '85%', display: 'flex', flexDirection: 'column', border: '1px solid rgba(var(--main), 0.4)', background: '#111' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 1rem', borderBottom: '1px solid rgba(var(--main), 0.3)', background: 'var(--bg)' }}>
              <span style={{ color: 'rgb(var(--alt))', fontWeight: 'bold', fontSize: '0.9rem' }}>{viewerTitle}</span>
              <button onClick={() => setViewerUrl(null)} style={{ background: 'transparent', border: '1px solid rgba(var(--main), 0.4)', color: 'rgb(var(--main))', padding: '0.25rem 0.75rem', cursor: 'pointer' }}>CLOSE</button>
            </div>
            <iframe src={viewerUrl} style={{ flex: 1, border: 'none', background: '#fff' }} />
          </div>
        </div>
      )}

      <style>{`
        .cursor-blink { animation: blink 1s step-end infinite; }
        @keyframes blink { 50% { opacity: 0; } }
      `}</style>
    </>
  )
}
