import { reactive, html } from '@arrow-js/core'
import type { AppState, Tab, TabId, ChatMessage, Source } from './types'
import { fetchHealth, streamChat } from './api'

// -- State --
const state = reactive<AppState>({
  tab: 'ai',
  messages: [],
  input: '',
  sending: false,
  serverStatus: 'loading',
  services: {},
})

const tabs: Tab[] = [
  { id: 'ai', label: 'AI' },
  { id: 'encyclopedia', label: 'Encyclopedia' },
  { id: 'maps', label: 'Maps' },
  { id: 'movies', label: 'Movies' },
  { id: 'music', label: 'Music' },
  { id: 'books', label: 'Books' },
  { id: 'games', label: 'Games' },
]

// -- Health check --
async function checkHealth(): Promise<void> {
  state.serverStatus = await fetchHealth()
}
checkHealth()
setInterval(checkHealth, 30_000)

// -- Chat --
async function sendMessage(): Promise<void> {
  const text = state.input.trim()
  if (!text || state.sending) return

  state.messages.push({ role: 'user', content: text })
  state.input = ''
  state.sending = true

  const assistantMsg: ChatMessage = { role: 'assistant', content: '', sources: [] }
  state.messages.push(assistantMsg)

  try {
    for await (const msg of streamChat(text)) {
      switch (msg.type) {
        case 'sources':
          if (msg.sources) assistantMsg.sources = msg.sources
          break
        case 'token':
          if (msg.content) assistantMsg.content += msg.content
          break
        case 'error':
          assistantMsg.content = `Error: ${msg.error}`
          assistantMsg.role = 'error'
          break
      }
      state.messages = [...state.messages]
    }
  } catch (err) {
    assistantMsg.content = `Connection error: ${(err as Error).message}`
    assistantMsg.role = 'error'
    state.messages = [...state.messages]
  }

  state.sending = false
}

function handleKeydown(e: Event): void {
  const ke = e as KeyboardEvent
  if (ke.key === 'Enter' && !ke.shiftKey) {
    ke.preventDefault()
    sendMessage()
  }
}

// -- Render helpers --
function renderSources(sources?: Source[]) {
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

function renderMessage(m: ChatMessage) {
  if (m.role === 'user') {
    return html`<div class="message user">${m.content}</div>`
  }
  if (m.role === 'error') {
    return html`<div class="message error">${m.content}</div>`
  }
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
          @input="${(e: Event) => { state.input = (e.target as HTMLInputElement).value }}"
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

function placeholderTab(name: string) {
  return () => html`<div class="placeholder">${name} — coming soon</div>`
}

const tabContent: Record<TabId, () => ReturnType<typeof html>> = {
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

app(document.getElementById('app')!)
