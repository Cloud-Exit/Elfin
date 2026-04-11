export type TabId = 'ai' | 'encyclopedia' | 'maps' | 'movies' | 'music' | 'books' | 'games'

export type ServerStatus = 'ok' | 'degraded' | 'loading' | 'err'

export type MessageRole = 'user' | 'assistant' | 'error'

export interface Source {
  text: string
  source_file: string
  page?: string
}

export interface ChatMessage {
  role: MessageRole
  content: string
  sources?: Source[]
}

export interface Tab {
  id: TabId
  label: string
}

export interface HealthResponse {
  status: string
  llama: string
  embedding: string
  qdrant: string
}

export interface StreamMessage {
  type: 'sources' | 'token' | 'error' | 'done'
  content?: string
  sources?: Source[]
  error?: string
}

export interface AppState {
  tab: TabId
  messages: ChatMessage[]
  input: string
  sending: boolean
  serverStatus: ServerStatus
  services: Partial<HealthResponse>
}
