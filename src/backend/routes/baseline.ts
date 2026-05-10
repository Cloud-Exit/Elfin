import { z } from 'zod'
import { requireAuth } from '../auth.js'
import { prisma } from '../db.js'
import { baselineSubmitSchema, baselineSchema, baselineCategories, baselineQuestions, baselineFieldsSchema } from '../utils/schemas.js'
import type { BaselineFields, BaselineCategory } from '../utils/schemas.js'

type BaselineData = BaselineFields & {
  completed: boolean
  updatedAt: string
}

type CategoryStatus = {
  category: BaselineCategory
  question: string
  answered: boolean
  response?: string
}

const storedBaselineSchema = baselineFieldsSchema.extend({
  completed: z.boolean().optional().default(false),
  updatedAt: z.string().optional(),
})

function parseBaseline(raw: string | null): BaselineData | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    const result = storedBaselineSchema.safeParse(parsed)
    if (!result.success) return null
    return {
      conditions: result.data.conditions,
      meds: result.data.meds,
      allergies: result.data.allergies,
      fitness: result.data.fitness,
      mentalHealth: result.data.mentalHealth,
      vision: result.data.vision,
      chronicPain: result.data.chronicPain,
      diet: result.data.diet,
      completed: result.data.completed,
      updatedAt: result.data.updatedAt ?? new Date().toISOString(),
    }
  } catch {
    return null
  }
}

function isComplete(baseline: BaselineData): boolean {
  return baselineCategories.every((cat) => {
    const val = baseline[cat]
    return typeof val === 'string' && val.trim().length > 0
  })
}

function buildInterviewState(baseline: BaselineData | null): {
  categories: CategoryStatus[]
  answered: number
  total: number
  nextCategory: BaselineCategory | null
  completed: boolean
} {
  const categories: CategoryStatus[] = baselineCategories.map((cat) => {
    const response = baseline?.[cat]
    const question = baselineQuestions[cat]
    return {
      category: cat,
      question,
      answered: typeof response === 'string' && response.trim().length > 0,
      ...(response && response.trim().length > 0 ? { response } : {}),
    }
  })
  const answered = categories.filter((c) => c.answered).length
  const unanswered = categories.find((c) => !c.answered)
  return {
    categories,
    answered,
    total: baselineCategories.length,
    nextCategory: (unanswered?.category ?? null),
    completed: baseline?.completed ?? false,
  }
}

export async function handleBaseline(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'baseline') return null

  try {
    if (parts.length === 2 && req.method === 'GET') return await getBaseline(req)
    if (parts.length === 2 && req.method === 'POST') return await submitBaseline(req)
    if (parts.length === 2 && req.method === 'DELETE') return await resetBaseline(req)
    return Response.json({ error: 'not found' }, { status: 404 })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    console.error('Baseline API Error:', err)
    return Response.json({ error: err.message }, { status: 400 })
  }
}

async function getBaseline(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const user = await prisma.user.findUnique({
    where: { id: ctx.userId },
    select: { baseline: true },
  })
  if (!user) throw new Error('user not found')

  const baseline = parseBaseline(user.baseline)
  const interview = buildInterviewState(baseline)
  return Response.json({
    needsBaseline: !interview.completed,
    baseline,
    interview,
  })
}

async function submitBaseline(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const body = await req.json().catch(() => ({}))

  const user = await prisma.user.findUnique({
    where: { id: ctx.userId },
    select: { baseline: true },
  })
  if (!user) throw new Error('user not found')

  const existing = parseBaseline(user.baseline) ?? { completed: false, updatedAt: '' }

  if (body.category) {
    const submitResult = baselineSubmitSchema.safeParse(body)
    if (!submitResult.success) {
      const msg = submitResult.error.issues
        .map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`)
        .join('; ')
      return Response.json({ error: msg }, { status: 400 })
    }
    const { category, response } = submitResult.data
    if (!category || !response) {
      return Response.json({ error: 'response is required when category is provided' }, { status: 400 })
    }
    existing[category] = response
  } else {
    const fullResult = baselineSchema.safeParse(body)
    if (!fullResult.success) {
      const msg = fullResult.error.issues
        .map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`)
        .join('; ')
      return Response.json({ error: msg }, { status: 400 })
    }
    for (const cat of baselineCategories) {
      const val = fullResult.data[cat]
      if (typeof val === 'string' && val.trim().length > 0) {
        existing[cat] = val
      }
    }
  }

  existing.completed = isComplete(existing)
  existing.updatedAt = new Date().toISOString()

  const updated = await prisma.user.update({
    where: { id: ctx.userId },
    data: { baseline: JSON.stringify(existing) },
    select: { baseline: true },
  })

  const parsed = parseBaseline(updated.baseline)
  const interview = buildInterviewState(parsed)
  return Response.json({
    baseline: parsed,
    needsBaseline: !interview.completed,
    interview,
  })
}

async function resetBaseline(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const user = await prisma.user.findUnique({
    where: { id: ctx.userId },
    select: { baseline: true },
  })
  if (!user) throw new Error('user not found')

  await prisma.user.update({
    where: { id: ctx.userId },
    data: { baseline: null },
  })

  return Response.json({ ok: true, needsBaseline: true })
}
