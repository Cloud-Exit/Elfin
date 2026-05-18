import { prisma } from './db.js'
import { baselineFieldsSchema } from './utils/schemas.js'

const EMBED_ENDPOINT = process.env.ELFIN_EMBED_ENDPOINT || 'http://localhost:8082'
const QDRANT_ENDPOINT = process.env.QDRANT_URL || 'http://localhost:6333'
const EMBED_MODEL = process.env.EMBED_MODEL || 'nomic-embed-text-v1.5.Q8_0.gguf'
const QDRANT_COLLECTION = process.env.QDRANT_COLLECTION || 'elfin_docs'
const KIWIX_ENDPOINT = process.env.KIWIX_URL || 'http://localhost:8083'

async function embedQuery(text: string): Promise<number[] | null> {
  try {
    const res = await fetch(`${EMBED_ENDPOINT}/v1/embeddings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: text, model: EMBED_MODEL }),
      signal: AbortSignal.timeout(60_000)
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.data?.[0]?.embedding || null
  } catch (err) {
    console.error('Failed to embed query:', err)
    return null
  }
}

async function queryQdrant(vector: number[], limit = 3): Promise<any[]> {
  try {
    const res = await fetch(`${QDRANT_ENDPOINT}/collections/${QDRANT_COLLECTION}/points/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: vector,
        limit,
        with_payload: true,
        with_vector: false
      }),
      signal: AbortSignal.timeout(60_000)
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.result?.points || []
  } catch (err) {
    console.error('Failed to query Qdrant:', err)
    return []
  }
}

function stripHtml(html: string): string {
  return html
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&#\d+;/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

async function searchKiwix(query: string, limit = 1): Promise<any[]> {
  try {
    const searchUrl = `${KIWIX_ENDPOINT}/search?pattern=${encodeURIComponent(query)}&pageLength=${limit}`
    const res = await fetch(searchUrl, { signal: AbortSignal.timeout(10_000) })
    if (!res.ok) return []
    const html = await res.text()

    const results: any[] = []
    const linkRegex = /<a[^>]+href="([^"]*\/content\/([^/]+)\/([^"]+))"[^>]*>([^<]*)<\/a>/gi
    let match
    while ((match = linkRegex.exec(html)) !== null) {
      const [, href, book, path, title] = match
      if (!path || path.includes('search') || !title?.trim()) continue
      results.push({ book, path: decodeURIComponent(path), title: title.trim(), href })
    }

    if (results.length === 0) return []

    const articles: any[] = []
    for (const result of results.slice(0, limit)) {
      try {
        const articleUrl = `${KIWIX_ENDPOINT}/content/${encodeURIComponent(result.book)}/${result.path}`
        const articleRes = await fetch(articleUrl, { signal: AbortSignal.timeout(10_000) })
        if (!articleRes.ok) continue
        const articleHtml = await articleRes.text()
        const text = stripHtml(articleHtml)
        if (text.length < 100) continue
        const excerpt = text.slice(0, 600)
        const source = `kiwix:${result.book}:${result.title}`
        articles.push({
          source,
          text: excerpt,
          score: null,
          kiwixPath: `/content/${encodeURIComponent(result.book)}/${result.path}`,
        })
        console.log(`  [kiwix] ${source}: ${excerpt.slice(0, 80).replace(/\s+/g, ' ')}`)
      } catch {
        continue
      }
    }
    return articles
  } catch (err) {
    console.error('Kiwix search failed:', err)
    return []
  }
}

export interface ChatContext {
  baseline: Record<string, string> | null
  recentJournal: Array<{ content: string; date: Date }>
  lastCheckin: {
    date: Date
    mentalScore?: number | null
    physicalScore?: number | null
    staminaScore?: number | null
  } | null
  recentNotes: Array<{ title: string; content: string; updatedAt: Date }>
}

export type StreamEvent =
  | { type: 'sources'; sources: any[] }
  | { type: 'delta'; content: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export interface AIChatService {
  generateReply(
    message: string,
    context: ChatContext,
    history: Array<{ role: string; content: string }>,
    images?: string[],
  ): Promise<{ content: string; sources?: any[] }>
  streamReply?(
    message: string,
    context: ChatContext,
    history: Array<{ role: string; content: string }>,
    images?: string[],
  ): AsyncGenerator<StreamEvent, void, unknown>
  inferTitle?(userMessage: string, aiResponse: string): Promise<string | null>
}

export class DeterministicChatService implements AIChatService {
  async generateReply(
    message: string,
    context: ChatContext,
    _history: Array<{ role: string; content: string }>,
    _images?: string[],
  ): Promise<{ content: string; sources?: any[] }> {
    let reply = 'I received your message. '

    const hasBaseline = context.baseline && Object.keys(context.baseline).length > 0
    const hasJournal = context.recentJournal.length > 0
    const hasNotes = context.recentNotes.length > 0
    const hasCheckin = context.lastCheckin !== null

    if (hasBaseline || hasJournal || hasNotes || hasCheckin) {
      reply += 'I have access to your personal context. '
    }

    if (hasBaseline) {
      reply += 'Your health baseline is on file. '
    }
    if (hasJournal) {
      reply += `I can see your ${context.recentJournal.length} recent journal entries. `
    }
    if (hasCheckin) {
      reply += 'Your latest check-in scores are available. '
    }
    if (hasNotes) {
      reply += `I have access to your ${context.recentNotes.length} recent notes. `
    }

    reply += `You asked: "${message.slice(0, 100)}". Without AI inference active, I can only acknowledge your context. Connect llama-server for full responses.`
    return { content: reply }
  }
}

function fenceContent(text: string): string {
  return text.split('\n').map(line => `> ${line}`).join('\n')
}

export class LlamaChatService implements AIChatService {
  constructor(
    private inferenceEndpoint: string,
    private fallback: AIChatService,
    private modelName: string = process.env.ELFIN_CHAT_MODEL || 'gemma-4-E4B',
  ) {}

  private buildSystemPrompt(context: ChatContext): string {
    let prompt = `You are Elfin, an offline survival assistant. The user is in a disaster scenario with no outside help, hospitals, or phone networks.

Rules:
- Respond as step-by-step instructions. Every response should be numbered action steps the user follows in order.
- Each step: one clear action with specific details (amounts, timing, materials).
- After steps: warning signs that mean the situation is getting worse.
- No disclaimers ("I am not a doctor"), no "call 911", no thinking steps.
- Cite retrieved sources using their EXACT filename: [actual_filename.pdf#chunk_N].
- If the user attaches an image, analyze only visible details. Say what you can see, what it may imply, and what source-backed steps to take. Do not claim certainty about medical diagnoses, plants, animals, or chemicals from the image alone.
- 8-15 steps typical. Be thorough.\n\n`

    if (context.baseline && Object.keys(context.baseline).length > 0) {
      prompt += '--- USER HEALTH BASELINE ---\n'
      for (const [key, value] of Object.entries(context.baseline)) {
        if (value && value.trim()) {
          prompt += `${key}: ${fenceContent(value)}\n`
        }
      }
      prompt += '\n'
    }

    if (context.recentJournal.length > 0) {
      prompt += '--- RECENT JOURNAL ENTRIES ---\n'
      for (const entry of context.recentJournal) {
        const truncated = entry.content.length > 200 ? entry.content.slice(0, 200) + '...' : entry.content
        const dateStr = entry.date.toISOString().slice(0, 10)
        prompt += `[${dateStr}] ${fenceContent(truncated)}\n`
      }
      prompt += '\n'
    }

    if (context.lastCheckin) {
      prompt += '--- LATEST CHECK-IN ---\n'
      prompt += `Date: ${context.lastCheckin.date.toISOString().slice(0, 10)}\n`
      if (context.lastCheckin.mentalScore != null) prompt += `Mental: ${context.lastCheckin.mentalScore}/10\n`
      if (context.lastCheckin.physicalScore != null) prompt += `Physical: ${context.lastCheckin.physicalScore}/10\n`
      if (context.lastCheckin.staminaScore != null) prompt += `Stamina: ${context.lastCheckin.staminaScore}/10\n`
      prompt += '\n'
    }

    if (context.recentNotes.length > 0) {
      prompt += '--- USER NOTES ---\n'
      for (const note of context.recentNotes) {
        const truncated = note.content.length > 150 ? note.content.slice(0, 150) + '...' : note.content
        prompt += `[${note.title}] ${fenceContent(truncated)}\n`
      }
      prompt += '\n'
    }

    prompt += '--- END CONTEXT ---\n'
    prompt += 'Use this context to personalize your responses. If the user asks about health, reference their baseline and recent trends. If they ask about something unrelated, respond normally.'
    return prompt
  }

  private async callLlama(
    systemPrompt: string,
    message: string,
    history: Array<{ role: string; content: string }>,
    temperature: number = 0.4,
    images: string[] = [],
  ): Promise<string | null> {
    try {
      const messages: Array<{ role: string; content: any }> = [
        { role: 'system', content: systemPrompt },
      ]

      for (const turn of history.slice(-4)) {
        messages.push(turn)
      }
      messages.push({ role: 'user', content: buildUserContent(message, images) })

      const res = await fetch(`${this.inferenceEndpoint}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.modelName,
          messages,
          temperature,
          max_tokens: Number(process.env.ELFIN_CHAT_MAX_TOKENS || 384),
          reasoning_budget: Number(process.env.ELFIN_CHAT_REASONING_BUDGET ?? -1),
        }),
        signal: AbortSignal.timeout(Number(process.env.ELFIN_CHAT_TIMEOUT_MS || 300_000)),
      })
      if (!res.ok) {
        console.error(`llama-server returned ${res.status} for chat request`)
        return null
      }
      const body = await res.json()
      return body.choices?.[0]?.message?.content ?? null
    } catch (err: any) {
      console.error(`llama-server call failed for chat: ${err.message || err}`)
      return null
    }
  }

  async inferTitle(userMessage: string, aiResponse: string): Promise<string | null> {
    const systemPrompt = "You are a title generator. Summarize the following exchange into a concise title of 3-5 words. Do not use quotes. Output only the title."
    const message = `User: ${userMessage}\nAI: ${aiResponse}\n\nTitle:`

    const response = await this.callLlama(systemPrompt, message, [], 0.3)
    if (response) {
      return response.trim()
    }
    return null
  }

  private async retrieve(message: string): Promise<{ sources: any[]; retrievedContext: string }> {
    const vector = await embedQuery(message)
    const sources: any[] = []
    let retrievedContext = ''
    if (vector) {
      const points = await queryQdrant(vector, 3)
      console.log(`Qdrant returned ${points.length} points for query: "${message.slice(0, 80)}"`)
      if (points.length > 0) {
        for (const point of points) {
          const payload = point.payload || {}
          if (payload.text) {
            const src = payload.source_file || payload.source || 'unknown'
            const chunk = payload.chunk_index != null ? `${src}#chunk_${payload.chunk_index}` : src
            const preview = String(payload.text).slice(0, 80).replace(/\s+/g, ' ')
            console.log(`  [${point.score?.toFixed(3) ?? '?'}] ${chunk}: ${preview}`)
            const truncatedText = String(payload.text).length > 400 ? String(payload.text).slice(0, 400) + '...' : String(payload.text)
            retrievedContext += `[Source: ${chunk}]\n${truncatedText}\n\n`
            sources.push({ source: chunk, text: payload.text, score: point.score })
          }
        }
      }
    } else {
      console.error('Vector was null, skipped Qdrant query.')
    }

    const kiwixResults = await searchKiwix(message, 1)
    for (const article of kiwixResults) {
      const truncatedText = article.text.length > 600 ? article.text.slice(0, 600) + '...' : article.text
      retrievedContext += `[Source: ${article.source}]\n${truncatedText}\n\n`
      sources.push(article)
    }

    return { sources, retrievedContext }
  }

  private buildAugmentedMessage(message: string, sources: any[], retrievedContext: string): string {
    if (sources.length > 0) {
      return `REFERENCE:\n${retrievedContext}---\n${message}`
    }
    return message
  }

  private async *streamLlama(
    systemPrompt: string,
    message: string,
    history: Array<{ role: string; content: string }>,
    images: string[] = [],
  ): AsyncGenerator<string, void, unknown> {
    const messages: Array<{ role: string; content: any }> = [
      { role: 'system', content: systemPrompt },
    ]
    for (const turn of history.slice(-4)) messages.push(turn)
    messages.push({ role: 'user', content: buildUserContent(message, images) })

    const res = await fetch(`${this.inferenceEndpoint}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.modelName,
        messages,
        temperature: 0.4,
        max_tokens: Number(process.env.ELFIN_CHAT_MAX_TOKENS || 384),
        stream: true,
        reasoning_budget: Number(process.env.ELFIN_CHAT_REASONING_BUDGET ?? -1),
      }),
      signal: AbortSignal.timeout(Number(process.env.ELFIN_CHAT_STREAM_TIMEOUT_MS || 600_000)),
    })

    if (!res.ok || !res.body) {
      throw new Error(`llama-server returned ${res.status} for stream request`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let nl
        while ((nl = buf.indexOf('\n')) !== -1) {
          const line = buf.slice(0, nl).trim()
          buf = buf.slice(nl + 1)
          if (!line || !line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (data === '[DONE]') return
          try {
            const obj = JSON.parse(data)
            const delta = obj.choices?.[0]?.delta?.content
            if (typeof delta === 'string' && delta.length > 0) yield delta
          } catch {
            // ignore malformed line
          }
        }
      }
    } finally {
      try { reader.releaseLock() } catch {}
    }
  }

  async *streamReply(
    message: string,
    context: ChatContext,
    history: Array<{ role: string; content: string }>,
    images: string[] = [],
  ): AsyncGenerator<StreamEvent, void, unknown> {
    const systemPrompt = this.buildSystemPrompt(context)
    const { sources, retrievedContext } = await this.retrieve(message)
    yield { type: 'sources', sources }
    const augmented = this.buildAugmentedMessage(message, sources, retrievedContext)

    try {
      for await (const delta of this.streamLlama(systemPrompt, augmented, history, images)) {
        yield { type: 'delta', content: delta }
      }
      yield { type: 'done' }
    } catch (err: any) {
      console.error(`llama-server stream failed: ${err?.message || err}`)
      const fb = await this.fallback.generateReply(message, context, history)
      yield { type: 'delta', content: fb.content }
      yield { type: 'done' }
    }
  }

  async generateReply(
    message: string,
    context: ChatContext,
    history: Array<{ role: string; content: string }>,
    images: string[] = [],
  ): Promise<{ content: string; sources?: any[] }> {
    const systemPrompt = this.buildSystemPrompt(context)
    const { sources, retrievedContext } = await this.retrieve(message)
    const augmentedMessage = this.buildAugmentedMessage(message, sources, retrievedContext)
    const response = await this.callLlama(systemPrompt, augmentedMessage, history, 0.4, images)
    if (response) {
      return { content: response.trim(), sources }
    }
    return this.fallback.generateReply(message, context, history, images)
  }
}

function buildUserContent(message: string, images: string[] = []): any {
  const cleanImages = images.filter((image) => image.startsWith('data:image/')).slice(0, 2)
  if (cleanImages.length === 0) return message
  return [
    { type: 'text', text: message },
    ...cleanImages.map((image) => ({
      type: 'image_url',
      image_url: { url: image },
    })),
  ]
}

export let chatService: AIChatService = new DeterministicChatService()

export function setChatService(service: AIChatService): void {
  chatService = service
}

export async function gatherChatContext(userId: string): Promise<ChatContext> {
  const [user, recentJournal, lastCheckin, recentNotes] = await Promise.all([
    prisma.user.findUnique({
      where: { id: userId },
      select: { baseline: true },
    }),
    prisma.journalEntry.findMany({
      where: {
        userId,
        date: { gte: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000) },
      },
      orderBy: { date: 'desc' },
      take: 10,
      select: { content: true, date: true },
    }),
    prisma.checkIn.findFirst({
      where: { userId },
      orderBy: { date: 'desc' },
      select: { date: true, mentalScore: true, physicalScore: true, staminaScore: true },
    }),
    prisma.note.findMany({
      where: { userId },
      orderBy: { updatedAt: 'desc' },
      take: 5,
      select: { title: true, content: true, updatedAt: true },
    }),
  ])

  const baseline = user?.baseline ? (() => {
    try {
      const parsed = JSON.parse(user.baseline)
      const result = baselineFieldsSchema.safeParse(parsed)
      return result.success ? result.data : null
    } catch {
      return null
    }
  })() : null

  return {
    baseline,
    recentJournal,
    lastCheckin: lastCheckin ? {
      date: lastCheckin.date,
      mentalScore: lastCheckin.mentalScore,
      physicalScore: lastCheckin.physicalScore,
      staminaScore: lastCheckin.staminaScore,
    } : null,
    recentNotes,
  }
}
