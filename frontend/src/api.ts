import type { HealthResponse, StreamMessage, ServerStatus, ChatMessage } from './types'

export async function fetchHealth(): Promise<ServerStatus> {
  try {
    const res = await fetch('/api/health')
    const data: HealthResponse = await res.json()
    return data.status === 'healthy' ? 'ok'
      : data.status === 'degraded' ? 'degraded' : 'err'
  } catch {
    return 'err'
  }
}

export async function* streamChat(message: string): AsyncGenerator<StreamMessage> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })

  if (!res.ok) {
    const err = await res.text()
    yield { type: 'error', error: err }
    return
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()!

    for (const line of lines) {
      if (!line.trim()) continue
      try {
        yield JSON.parse(line) as StreamMessage
      } catch {
        // skip malformed
      }
    }
  }

  if (buffer.trim()) {
    try {
      yield JSON.parse(buffer) as StreamMessage
    } catch {
      // skip
    }
  }
}
