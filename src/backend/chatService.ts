import { prisma } from './db.js'
import { baselineFieldsSchema } from './utils/schemas.js'

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

export interface AIChatService {
  generateReply(
    message: string,
    context: ChatContext,
    history: Array<{ role: string; content: string }>,
  ): Promise<{ content: string }>
}

export class DeterministicChatService implements AIChatService {
  async generateReply(
    message: string,
    context: ChatContext,
    _history: Array<{ role: string; content: string }>,
  ): Promise<{ content: string }> {
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
    let prompt = `You are Elfin, an offline survival companion AI. You help users with health tracking, survival knowledge, and daily wellbeing. Always be supportive, practical, and direct.\n\n`
    prompt += `IMPORTANT: Reference the user's personal context when relevant. Never present unverified medical advice as fact. Label health assessments as "AI-estimated."\n\n`

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
  ): Promise<string | null> {
    try {
      const messages: Array<{ role: string; content: string }> = [
        { role: 'system', content: systemPrompt },
      ]

      for (const turn of history.slice(-6)) {
        messages.push(turn)
      }
      messages.push({ role: 'user', content: message })

      const res = await fetch(`${this.inferenceEndpoint}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.modelName,
          messages,
          temperature: 0.7,
          max_tokens: 1024,
        }),
        signal: AbortSignal.timeout(30_000),
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

  async generateReply(
    message: string,
    context: ChatContext,
    history: Array<{ role: string; content: string }>,
  ): Promise<{ content: string }> {
    const systemPrompt = this.buildSystemPrompt(context)
    const response = await this.callLlama(systemPrompt, message, history)

    if (response) {
      return { content: response.trim() }
    }

    return this.fallback.generateReply(message, context, history)
  }
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
