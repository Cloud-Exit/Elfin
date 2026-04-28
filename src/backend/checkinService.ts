import { prisma } from './db.js'
import { baselineFieldsSchema } from './utils/schemas.js'

interface CheckinContext {
  baseline: Record<string, string> | null
  recentJournal: Array<{ content: string; date: Date }>
  lastCheckin: {
    date: Date
    mentalScore?: number | null
    physicalScore?: number | null
    staminaScore?: number | null
    responses?: Record<string, string>
  } | null
}

/**
 * AI check-in service boundary.
 * Default implementation uses deterministic keyword-based scoring.
 * Swap with llama-server-backed impl when AI inference is available.
 */
function isStringRecord(value: unknown): value is Record<string, string> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  for (const [key, val] of Object.entries(value)) {
    if (typeof key !== 'string' || typeof val !== 'string' || !val.trim()) return false
  }
  return true
}

export interface AICheckinService {
  generateQuestions(context: CheckinContext): Promise<Record<string, string>>
  scoreResponses(responses: Record<string, string>, context: CheckinContext): Promise<{
    mentalScore: number
    physicalScore: number
    staminaScore: number
  }>
}

/**
 * Default deterministic implementation.
 * Replaced by AI-backed service when llama-server is available.
 */
export class DeterministicCheckinService implements AICheckinService {
  async generateQuestions(context: CheckinContext): Promise<Record<string, string>> {
    return generateCheckinQuestions(context)
  }

  async scoreResponses(responses: Record<string, string>, context: CheckinContext): Promise<{
    mentalScore: number
    physicalScore: number
    staminaScore: number
  }> {
    return scoreResponses(responses, context.baseline)
  }
}

/**
 * Llama-server AI implementation.
 * Activated when inferenceEndpoint is configured.
 */
export class LlamaCheckinService implements AICheckinService {
  constructor(
    private inferenceEndpoint: string,
    private fallback: AICheckinService,
  ) {}

  private buildCheckinPrompt(context: CheckinContext): string {
    let prompt = `You are a health check-in assistant. Generate 5-8 concise daily check-in questions as a JSON object with short keys and question values.\n\n`
    prompt += `INSTRUCTIONS: Return ONLY valid JSON like {"key": "question?"}. No markdown, no explanation.\n\n`

    if (context.baseline && Object.keys(context.baseline).length > 0) {
      prompt += 'USER HEALTH BASELINE:\n'
      for (const [key, value] of Object.entries(context.baseline)) {
        if (value && value.trim()) {
          prompt += `- ${key}: ${value}\n`
        }
      }
      prompt += '\n'
    }

    if (context.recentJournal.length > 0) {
      prompt += 'RECENT JOURNAL ENTRIES:\n'
      for (const entry of context.recentJournal) {
        const truncated = entry.content.length > 200 ? entry.content.slice(0, 200) + '...' : entry.content
        prompt += `- ${truncated}\n`
      }
      prompt += '\n'
    }

    if (context.lastCheckin) {
      prompt += 'LAST CHECK-IN:\n'
      prompt += `Date: ${context.lastCheckin.date.toISOString().slice(0, 10)}\n`
      if (context.lastCheckin.mentalScore != null) prompt += `Mental score: ${context.lastCheckin.mentalScore}\n`
      if (context.lastCheckin.physicalScore != null) prompt += `Physical score: ${context.lastCheckin.physicalScore}\n`
      if (context.lastCheckin.staminaScore != null) prompt += `Stamina score: ${context.lastCheckin.staminaScore}\n`
      if (context.lastCheckin.responses) {
        prompt += 'Responses:\n'
        for (const [key, value] of Object.entries(context.lastCheckin.responses)) {
          prompt += `- ${key}: ${value}\n`
        }
      }
      prompt += '\n'
    }

    prompt += 'Generate questions that reference the user\'s specific baseline conditions, recent journal events, and any changes since last check-in. Focus on mood, pain, energy, sleep, and any baseline-specific concerns.'
    return prompt
  }

  private buildScoringPrompt(responses: Record<string, string>, context: CheckinContext): string {
    let prompt = `You are a health scoring assistant. Score the user's check-in responses on a 1-10 scale where 5 = normal baseline.\n\n`
    prompt += `INSTRUCTIONS: Return ONLY valid JSON like {"mentalScore": 5, "physicalScore": 7, "staminaScore": 3}. No markdown, no explanation.\n\n`

    if (context.baseline && Object.keys(context.baseline).length > 0) {
      prompt += 'USER HEALTH BASELINE:\n'
      for (const [key, value] of Object.entries(context.baseline)) {
        if (value && value.trim()) {
          prompt += `- ${key}: ${value}\n`
        }
      }
      prompt += '\n'
    }

    prompt += 'USER RESPONSES:\n'
    for (const [key, value] of Object.entries(responses)) {
      prompt += `- ${key}: ${value}\n`
    }

    prompt += '\nScore each dimension. New symptoms not in baseline get lower scores. Stable baseline conditions are scored relative to expected state. Sharp declines get prominent demerits.'
    return prompt
  }

  private async callLlama(prompt: string): Promise<string | null> {
    try {
      const res = await fetch(`${this.inferenceEndpoint}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'gemma-4-E4B',
          messages: [{ role: 'user', content: prompt }],
          temperature: 0.7,
          max_tokens: 512,
        }),
      })
      if (!res.ok) return null
      const body = await res.json()
      return body.choices?.[0]?.message?.content ?? null
    } catch {
      return null
    }
  }

  async generateQuestions(context: CheckinContext): Promise<Record<string, string>> {
    const prompt = this.buildCheckinPrompt(context)
    const response = await this.callLlama(prompt)

    if (response) {
      try {
        const cleaned = response.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim()
        const parsed = JSON.parse(cleaned)
        if (isStringRecord(parsed)) {
          return parsed
        }
      } catch {
        // Fall through to deterministic
      }
    }

    return this.fallback.generateQuestions(context)
  }

  async scoreResponses(responses: Record<string, string>, context: CheckinContext): Promise<{
    mentalScore: number
    physicalScore: number
    staminaScore: number
  }> {
    const prompt = this.buildScoringPrompt(responses, context)
    const response = await this.callLlama(prompt)

    if (response) {
      try {
        const cleaned = response.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim()
        const parsed = JSON.parse(cleaned)
        const mental = Math.max(1, Math.min(10, Number(parsed.mentalScore) || 5))
        const physical = Math.max(1, Math.min(10, Number(parsed.physicalScore) || 5))
        const stamina = Math.max(1, Math.min(10, Number(parsed.staminaScore) || 5))
        return { mentalScore: mental, physicalScore: physical, staminaScore: stamina }
      } catch {
        // Fall through to deterministic
      }
    }

    return this.fallback.scoreResponses(responses, context)
  }
}

// Default instance — swap with LlamaCheckinService when inferenceEndpoint available
export let checkinService: AICheckinService = new DeterministicCheckinService()

// Allow injecting a different service (e.g. for tests or when AI is available)
export function setCheckinService(service: AICheckinService): void {
  checkinService = service
}

const MENTAL_KEYWORDS = ['anxious', 'anxiety', 'depressed', 'depression', 'stress', 'stressed', 'mood', 'sleep', 'insomnia', 'tired', 'fatigued', 'focus', 'concentra', 'hopeless', 'overwhelm', 'panic', 'worry', 'sad', 'happy', 'calm', 'peaceful', 'good mood', 'great', 'well']
const PHYSICAL_KEYWORDS = ['pain', 'ache', 'hurt', 'injury', 'wound', 'bleed', 'fever', 'sick', 'nausea', 'vomiting', 'headache', 'dizzy', 'weak', 'mobility', 'limp', 'swollen', 'rash', 'breath', 'chest', 'stomach', 'hurt', 'stiff', 'numb']
const STAMINA_KEYWORDS = ['energy', 'tired', 'exhausted', 'fatigue', 'stamina', 'endurance', 'strength', 'weak', 'sleep', 'rest', 'active', 'exercise', 'workout', 'run', 'walk', 'climb', 'carry', 'lift', 'heavy', 'light']

function scoreDimension(responses: Record<string, string>, baseline: Record<string, string> | null, dimension: 'mental' | 'physical' | 'stamina'): number {
  const keywords = dimension === 'mental' ? MENTAL_KEYWORDS : dimension === 'physical' ? PHYSICAL_KEYWORDS : STAMINA_KEYWORDS
  const allText = Object.values(responses).join(' ').toLowerCase()
  const baselineText = baseline ? Object.values(baseline).join(' ').toLowerCase() : ''

  let score = 5
  let negativeCount = 0
  let positiveCount = 0

  for (const keyword of keywords) {
    if (allText.includes(keyword)) {
      if (['happy', 'calm', 'peaceful', 'good', 'great', 'well', 'active', 'strength', 'rest'].includes(keyword)) {
        positiveCount++
      } else {
        negativeCount++
        if (!baselineText.includes(keyword)) {
          negativeCount++
        }
      }
    }
  }

  score -= negativeCount * 0.5
  score += positiveCount * 0.3
  return Math.max(1, Math.min(10, Math.round(score * 10) / 10))
}

export async function gatherCheckinContext(userId: string): Promise<CheckinContext> {
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { baseline: true },
  })

  const baseline = user?.baseline ? (() => {
    try {
      const parsed = JSON.parse(user.baseline)
      const result = baselineFieldsSchema.safeParse(parsed)
      return result.success ? result.data : null
    } catch {
      return null
    }
  })() : null

  const recentJournal = await prisma.journalEntry.findMany({
    where: { userId },
    orderBy: { date: 'desc' },
    take: 5,
    select: { content: true, date: true },
  })

  const lastCheckin = await prisma.checkIn.findFirst({
    where: { userId },
    orderBy: { date: 'desc' },
    select: { date: true, mentalScore: true, physicalScore: true, staminaScore: true, responses: true },
  })

  return {
    baseline,
    recentJournal,
    lastCheckin: lastCheckin ? {
      date: lastCheckin.date,
      mentalScore: lastCheckin.mentalScore,
      physicalScore: lastCheckin.physicalScore,
      staminaScore: lastCheckin.staminaScore,
      responses: lastCheckin.responses ? JSON.parse(lastCheckin.responses) : undefined,
    } : null,
  }
}

function extractJournalTopics(entries: Array<{ content: string; date: Date }>): Array<{ text: string; date: Date }> {
  const topics: Array<{ text: string; date: Date }> = []
  const healthKeywords = ['pain', 'sleep', 'energy', 'mood', 'anxiety', 'stress', 'depression', 'headache', 'nausea', 'fatigue', 'tired', 'sore', 'stiff', 'weak', 'dizzy', 'breath', 'chest', 'stomach', 'heart', 'medication', 'meds', 'doctor', 'appointment', 'workout', 'exercise', 'food', 'diet', 'water', 'rest', 'insomnia', 'panic', 'worry', 'sad', 'happy', 'calm', 'focus']

  for (const entry of entries) {
    const sentences = entry.content.split(/[.!?]+/).map((s) => s.trim()).filter((s) => s.length > 20 && s.length < 250)
    for (const sentence of sentences) {
      const lower = sentence.toLowerCase()
      const hasHealthContent = healthKeywords.some((kw) => lower.includes(kw))
      if (hasHealthContent && topics.length < 3) {
        topics.push({ text: sentence, date: entry.date })
        break
      }
    }
    if (topics.length < 3 && sentences.length > 0 && !sentences.some((s) => topics.some((t) => t.text === s))) {
      const firstMeaningful = sentences.find((s) => s.length > 30)
      if (firstMeaningful) {
        topics.push({ text: firstMeaningful, date: entry.date })
      }
    }
  }
  return topics.slice(0, 3)
}

function generateCheckinQuestions(context: CheckinContext): Record<string, string> {
  const questions: Record<string, string> = {}

  questions['mood'] = 'How is your mood and mental state today?'
  questions['pain'] = 'Any pain, discomfort, or physical symptoms today?'
  questions['energy'] = 'How is your energy level and stamina today?'
  questions['sleep'] = 'How did you sleep last night?'
  questions['nutrition'] = 'How have you been eating and drinking today?'

  if (context.baseline) {
    if (context.baseline.conditions?.trim()) {
      questions['conditions'] = `You mentioned ${context.baseline.conditions}. How are those managing today?`
    }
    if (context.baseline.chronicPain?.trim()) {
      questions['chronicPain'] = `Regarding your chronic pain (${context.baseline.chronicPain}): any changes today?`
    }
    if (context.baseline.mentalHealth?.trim()) {
      questions['mentalHealth'] = `How are you managing ${context.baseline.mentalHealth} today?`
    }
  }

  const journalTopics = extractJournalTopics(context.recentJournal)
  let followupIdx = 1
  for (const topic of journalTopics) {
    const daysAgo = Math.floor((Date.now() - topic.date.getTime()) / (1000 * 60 * 60 * 24))
    const timeRef = daysAgo === 0 ? 'today' : daysAgo === 1 ? 'yesterday' : `${daysAgo} days ago`
    const truncated = topic.text.length > 100 ? topic.text.slice(0, 100) + '...' : topic.text
    questions[`journalFollowup${followupIdx++}`] = `You mentioned "${truncated}" in your journal ${timeRef}. Has anything changed since then?`
  }

  if (context.lastCheckin) {
    const daysSince = Math.floor((Date.now() - context.lastCheckin.date.getTime()) / (1000 * 60 * 60 * 24))
    if (daysSince > 0) {
      questions['sinceLastCheckin'] = `It's been ${daysSince} day${daysSince > 1 ? 's' : ''} since your last check-in. Any significant changes?`
    }
    if (context.lastCheckin.mentalScore != null && context.lastCheckin.mentalScore < 4) {
      questions['mentalFollowup'] = 'Your last mental health score was low. Any changes or support needed?'
    }
    if (context.lastCheckin.physicalScore != null && context.lastCheckin.physicalScore < 4) {
      questions['physicalFollowup'] = 'Your last physical health score was low. Any new symptoms or improvements?'
    }
  }

  return questions
}

export function scoreResponses(responses: Record<string, string>, baseline: Record<string, string> | null): {
  mentalScore: number
  physicalScore: number
  staminaScore: number
} {
  return {
    mentalScore: scoreDimension(responses, baseline, 'mental'),
    physicalScore: scoreDimension(responses, baseline, 'physical'),
    staminaScore: scoreDimension(responses, baseline, 'stamina'),
  }
}
