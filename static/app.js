import { reactive, html } from 'https://esm.sh/@arrow-js/core'

// -- State --
const state = reactive({
  tab: 'ai',
  messages: [],
  input: '',
  sending: false,
  ollamaStatus: 'loading',
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
    state.ollamaStatus = data.status === 'healthy' ? 'ok' : 'err'
  } catch {
    state.ollamaStatus = 'err'
  }
}
checkHealth()
setInterval(checkHealth, 30000)

// -- Chat --
async function sendMessage() {
  const text = state.input.trim()
  if (!text || state.sending) return

  state.messages.push({ role: 'user', content: text })
  state.input = ''
  state.sending = true

  // Add empty assistant message to stream into
  const assistantMsg = { role: 'assistant', content: '' }
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
      // Force reactivity update
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
      buffer = lines.pop() // keep incomplete line

      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const chunk = JSON.parse(line)
          if (chunk.message && chunk.message.content) {
            assistantMsg.content += chunk.message.content
            // Force reactivity
            state.messages = [...state.messages]
          }
        } catch {
          // skip malformed lines
        }
      }
    }

    // Process remaining buffer
    if (buffer.trim()) {
      try {
        const chunk = JSON.parse(buffer)
        if (chunk.message && chunk.message.content) {
          assistantMsg.content += chunk.message.content
          state.messages = [...state.messages]
        }
      } catch {
        // skip
      }
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

// -- Tab content --
function aiTab() {
  return html`
    <div class="chat-container">
      <div class="chat-messages" id="chat-messages">
        ${() => state.messages.length === 0
          ? html`<div class="placeholder">Ask anything</div>`
          : html`<div>${() => state.messages.map(m =>
              html`<div class="message ${m.role}">${m.content}</div>`
            )}</div>`
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
  <div id="app">
    <div class="header">
      <h1>Faraday-OS</h1>
      <div class="status">
        <span class="status-dot ${() => state.ollamaStatus}"></span>
        ${() => state.ollamaStatus === 'ok' ? 'Ollama connected'
              : state.ollamaStatus === 'loading' ? 'Connecting...'
              : 'Ollama offline'}
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
`

app(document.getElementById('app'))
