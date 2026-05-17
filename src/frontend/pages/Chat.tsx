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
          color: '#66ffcc',
          textDecoration: 'underline',
          textDecorationThickness: '2px',
          fontWeight: 'bold',
          cursor: 'pointer',
          textShadow: '0 0 4px rgba(102, 255, 204, 0.6)',
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

function EmptyChatState({
  hasSessions,
  onNewChat,
  onSamplePrompt,
}: {
  hasSessions: boolean
  onNewChat: () => void
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
            'linear-gradient(180deg, rgba(var(--alt), 0.2) 0%, rgba(0, 0, 0, 0.42) 100%)',
          boxShadow: 'inset 0 0 0 1px rgba(var(--main), 0.08), 0 0 2rem rgba(var(--alt), 0.12)',
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
                background: 'rgba(0,0,0,0.4)',
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

        <button className="btn" onClick={onNewChat} style={{ padding: '0.95rem 1.6rem', minWidth: '15rem' }}>
          + START NEW CHAT
        </button>
      </div>
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
  const [viewerUrl, setViewerUrl] = useState<string | null>(null)
  const [viewerTitle, setViewerTitle] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const pendingPromptRef = useRef<string | null>(null)

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

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const fetchMessages = async (sessionId: string) => {
    try {
      const res = await fetchWithAuth(`/api/chat/sessions/${sessionId}/messages`)
      if (res.ok) {
        const data = await res.json()
        const msgs: Message[] = (data.messages || []).reverse()
        setMessages(msgs)

        const last = msgs[msgs.length - 1]
        if (last && last.role === 'user' && !loading) {
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
                  setLoading(false)
                  stopPolling()
                  fetchSessions()
                }
              } catch {}
            }, 3000)
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
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleNewChat = async () => {
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
      }
    } catch (err) {
      console.error('Failed to create new chat', err)
    }
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

  const handleSend = async (e?: React.FormEvent, directMessage?: string) => {
    e?.preventDefault()
    const userMessageContent = directMessage || input.trim()
    if (!userMessageContent || loading || !selectedSessionId) return

    setInput('')
    setLoading(true)

    const tempUserId = `tmp-u-${Date.now()}`
    const tempAssistantId = `tmp-a-${Date.now()}`
    setMessages(prev => [
      ...prev,
      { id: tempUserId, role: 'user', content: userMessageContent, createdAt: new Date().toISOString() },
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
        body: JSON.stringify({ sessionId: selectedSessionId, message: userMessageContent }),
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
      <div style={{ display: 'flex', height: 'calc(100% - 60px)', gap: '1rem', marginTop: '1rem' }}>
        
        {/* Left Pane: Chat Sessions List */}
        <div style={{ flex: '0 0 250px', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
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
              <EmptyChatState hasSessions={sessions.length > 0} onNewChat={handleNewChat} onSamplePrompt={handleSamplePrompt} />
            ) : messages.length === 0 ? (
              <div
                className="placeholder"
                style={{
                  margin: 'auto',
                  textAlign: 'center',
                  minHeight: '12rem',
                  flexDirection: 'column',
                  gap: '0.75rem',
                }}
              >
                <div style={{ color: 'rgba(var(--main), 0.5)' }}>New chat ready.</div>
                <div style={{ color: 'rgba(var(--main), 0.3)', fontSize: '0.88rem', letterSpacing: '0.18rem' }}>
                  Ask Elfin something to begin.
                </div>
              </div>
            ) : (
              messages.map(m => (
                <div 
                  key={m.id} 
                  style={{
                    alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '80%',
                    background: m.role === 'user' ? 'rgba(var(--main), 0.15)' : 'rgba(var(--alt), 0.1)',
                    border: `1px solid ${m.role === 'user' ? 'rgba(var(--main), 0.3)' : 'rgba(var(--alt), 0.4)'}`,
                    padding: '1rem',
                    borderRadius: '4px'
                  }}
                >
                  <div style={{ fontWeight: 'bold', marginBottom: '0.5rem', color: m.role === 'user' ? 'rgb(var(--main))' : 'rgb(var(--alt))' }}>
                    {m.role === 'user' ? 'YOU' : 'ELFIN'}
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                    {m.role === 'assistant' ? renderWithCitations(m.content, handleOpenSource) : m.content}
                  </div>
                  {m.sources && (
                    <div style={{ marginTop: '1rem', borderTop: '1px solid rgba(var(--alt), 0.3)', paddingTop: '0.5rem' }}>
                      <div style={{ fontSize: '0.8em', color: 'rgba(var(--alt), 0.8)', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                        SOURCES RETRIEVED:
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
                                background: 'rgba(0,0,0,0.3)',
                                padding: '0.5rem',
                                borderRadius: '4px',
                                marginBottom: '0.5rem',
                                borderLeft: `2px solid ${isKiwix ? '#4da6ff' : 'rgb(var(--alt))'}`
                              }}>
                                <div style={{ fontWeight: 'bold', color: isKiwix ? '#4da6ff' : 'rgb(var(--alt))', marginBottom: '0.25rem' }}>
                                  {isOpenable ? (
                                    <a
                                      href="#"
                                      onClick={(e) => {
                                        e.preventDefault()
                                        handleOpenSource(displayLabel, src.kiwixPath)
                                      }}
                                      style={{ color: isKiwix ? '#4da6ff' : '#66ffcc', textDecoration: 'underline', textDecorationThickness: '2px', cursor: 'pointer', textShadow: `0 0 4px ${isKiwix ? 'rgba(77, 166, 255, 0.6)' : 'rgba(102, 255, 204, 0.6)'}` }}
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
          <form onSubmit={handleSend} style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder={selectedSessionId ? "Ask Elfin something..." : "Select a chat first..."}
              disabled={loading || !selectedSessionId}
              style={{ 
                flex: 1, 
                padding: '1rem', 
                background: 'rgba(0,0,0,0.5)', 
                color: 'rgb(var(--main))', 
                border: '1px solid rgba(var(--main), 0.4)',
                fontFamily: 'inherit',
                fontSize: '1.1em'
              }}
            />
            <button type="submit" className="btn" disabled={loading || !input.trim() || !selectedSessionId} style={{ padding: '0 2rem' }}>
              SEND
            </button>
          </form>
        </div>
      </div>

      {viewerUrl && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ width: '90%', height: '85%', display: 'flex', flexDirection: 'column', border: '1px solid rgba(var(--main), 0.4)', background: '#111' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 1rem', borderBottom: '1px solid rgba(var(--main), 0.3)', background: 'rgba(0,0,0,0.6)' }}>
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
