import { reactive, html } from 'https://esm.sh/@arrow-js/core'

// -- State --
const state = reactive({
  tab: 'ai',
  messages: [],
  input: '',
  sending: false,
  serverStatus: 'loading',
})

const tabs = [
  { id: 'ai', label: 'AI' },
  { id: 'encyclopedia', label: 'Encyclopedia' },
  { id: 'maps', label: 'Maps' },
  { id: 'movies', label: 'Movies' },
  { id: 'music', label: 'Music' },
  { id: 'books', label: 'Books' },
  { id: 'games', label: 'Games' },
]

// -- Health check --
async function checkHealth() {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    state.serverStatus = data.status === 'healthy' ? 'ok'
      : data.status === 'degraded' ? 'degraded' : 'err'
    state.services = data
  } catch {
    state.serverStatus = 'err'
    state.services = {}
  }
}
checkHealth()
setInterval(checkHealth, 30000)

// -- Chat --
// messages: { role: 'user'|'assistant'|'error', content: string, sources?: Source[] }

async function sendMessage() {
  const text = state.input.trim()
  if (!text || state.sending) return

  state.messages.push({ role: 'user', content: text })
  state.input = ''
  state.sending = true

  const assistantMsg = { role: 'assistant', content: '', sources: [] }
  state.messages.push(assistantMsg)

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })

    if (!res.ok) {
      const err = await res.text()
      assistantMsg.content = `Error: ${err}`
      assistantMsg.role = 'error'
      state.messages = [...state.messages]
      state.sending = false
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const msg = JSON.parse(line)
          if (msg.type === 'sources' && msg.sources) {
            assistantMsg.sources = msg.sources
          } else if (msg.type === 'token' && msg.content) {
            assistantMsg.content += msg.content
          } else if (msg.type === 'error') {
            assistantMsg.content = `Error: ${msg.error}`
            assistantMsg.role = 'error'
          }
          state.messages = [...state.messages]
        } catch {
          // skip malformed
        }
      }
    }

    // Remaining buffer
    if (buffer.trim()) {
      try {
        const msg = JSON.parse(buffer)
        if (msg.type === 'token' && msg.content) {
          assistantMsg.content += msg.content
          state.messages = [...state.messages]
        }
      } catch { /* skip */ }
    }
  } catch (err) {
    assistantMsg.content = `Connection error: ${err.message}`
    assistantMsg.role = 'error'
    state.messages = [...state.messages]
  }

  state.sending = false
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

// -- Render helpers --
function renderSources(sources) {
  if (!sources || sources.length === 0) return html`<span></span>`
  return html`
    <div class="sources">
      <div class="sources-header">Sources</div>
      ${sources.map((s, i) => html`
        <div class="source">
          <div class="source-label">[${i + 1}] ${s.source_file}${s.page ? ` — p.${s.page}` : ''}</div>
          <div class="source-text">${s.text}</div>
        </div>
      `)}
    </div>
  `
}

function renderMessage(m) {
  if (m.role === 'user') {
    return html`<div class="message user">${m.content}</div>`
  }
  if (m.role === 'error') {
    return html`<div class="message error">${m.content}</div>`
  }
  // assistant
  return html`
    <div class="message assistant">
      <div class="message-text">${m.content}</div>
      ${renderSources(m.sources)}
    </div>
  `
}

// -- Tab content --
function aiTab() {
  return html`
    <div class="chat-container">
      <div class="chat-messages" id="chat-messages">
        ${() => state.messages.length === 0
          ? html`<div class="placeholder">Ask anything</div>`
          : html`<div>${() => state.messages.map(m => renderMessage(m))}</div>`
        }
      </div>
      <div class="chat-input-area">
        <input
          class="chat-input"
          type="text"
          placeholder="Type a message..."
          value="${() => state.input}"
          @input="${(e) => { state.input = e.target.value }}"
          @keydown="${handleKeydown}"
          .disabled="${() => state.sending}"
        />
        <button
          class="send-btn"
          @click="${sendMessage}"
          .disabled="${() => state.sending || !state.input.trim()}"
        >
          ${() => state.sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  `
}

function placeholderTab(name) {
  return () => html`<div class="placeholder">${name} — coming soon</div>`
}

const tabContent = {
  ai: aiTab,
  encyclopedia: placeholderTab('Encyclopedia'),
  maps: placeholderTab('Maps'),
  movies: placeholderTab('Movies'),
  music: placeholderTab('Music'),
  books: placeholderTab('Books'),
  games: placeholderTab('Games'),
}

// -- App shell --
const app = html`
  <div class="crt-frame">
    <div class="crt-scanlines"></div>
    <div class="crt-glow"></div>
    <div class="crt-output">
      <div class="pipboy">
        <div class="header">
          <h1>Faraday-OS</h1>
          <div class="status">
            <span class="status-dot ${() => state.serverStatus}"></span>
            ${() => state.serverStatus === 'ok' ? 'Systems online'
                  : state.serverStatus === 'degraded' ? 'Degraded'
                  : state.serverStatus === 'loading' ? 'Connecting...'
                  : 'Offline'}
          </div>
        </div>
        <div class="tabs">
          ${() => tabs.map(t => html`
            <button
              class="tab ${() => state.tab === t.id ? 'active' : ''}"
              @click="${() => { state.tab = t.id }}"
            >${t.label}</button>
          `)}
        </div>
        <div class="content">
          ${() => tabContent[state.tab]()}
        </div>
      </div>
    </div>
  </div>
`

app(document.getElementById('app'))
