import { requireAuth } from '../auth.js'
import { prisma } from '../db.js'
import { parsePagination } from '../utils/pagination.js'
import { journalCreateSchema, journalUpdateSchema } from '../utils/schemas.js'

export async function handleJournal(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'journal') return null

  try {
    if (parts.length === 2 && req.method === 'GET') return await listJournal(req)
    if (parts.length === 2 && req.method === 'POST') return await createJournal(req)
    if (parts.length === 3 && req.method === 'GET') return await getJournal(req, parts[2]!)
    if (parts.length === 3 && req.method === 'PUT') return await updateJournal(req, parts[2]!)
    if (parts.length === 3 && req.method === 'DELETE') return await deleteJournal(req, parts[2]!)
    return Response.json({ error: 'not found' }, { status: 404 })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    return Response.json({ error: err.message }, { status: 400 })
  }
}

async function listJournal(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const { limit, offset } = parsePagination(new URL(req.url))
  const url = new URL(req.url)
  const fromDate = url.searchParams.get('fromDate') ?? undefined
  const toDate = url.searchParams.get('toDate') ?? undefined

  const where = {
    userId: ctx.userId,
    ...(fromDate && { date: { gte: new Date(fromDate) } }),
    ...(toDate && { date: { lte: new Date(toDate) } }),
  }

  const [entries, total] = await Promise.all([
    prisma.journalEntry.findMany({
      where,
      orderBy: { date: 'desc' },
      take: limit,
      skip: offset,
      select: { id: true, content: true, date: true, aiSummary: true, aiCategories: true, createdAt: true },
    }),
    prisma.journalEntry.count({ where }),
  ])

  return Response.json({ entries, total, limit, offset })
}

async function createJournal(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const body = await req.json().catch(() => ({}))
  const result = journalCreateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  const entry = await prisma.journalEntry.create({
    data: { userId: ctx.userId, content: result.data.content, date: result.data.date ?? new Date() },
    select: { id: true, content: true, date: true, aiSummary: true, aiCategories: true, createdAt: true },
  })

  return Response.json({ entry }, { status: 201 })
}

async function getJournal(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const entry = await prisma.journalEntry.findFirst({
    where: { id, userId: ctx.userId },
    select: { id: true, content: true, date: true, aiSummary: true, aiCategories: true, createdAt: true },
  })
  if (!entry) return Response.json({ error: 'not found' }, { status: 404 })
  return Response.json({ entry })
}

async function updateJournal(req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(req)
  const existing = await prisma.journalEntry.findFirst({ where: { id, userId: ctx.userId } })
  if (!existing) return Response.json({ error: 'not found' }, { status: 404 })

  const body = await req.json().catch(() => ({}))
  const result = journalUpdateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  const entry = await prisma.journalEntry.update({
    where: { id },
    data: {
      ...(result.data.content !== undefined && { content: result.data.content }),
      ...(result.data.date !== undefined && { date: result.data.date }),
    },
    select: { id: true, content: true, date: true, aiSummary: true, aiCategories: true, createdAt: true },
  })

  return Response.json({ entry })
}

async function deleteJournal(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const existing = await prisma.journalEntry.findFirst({ where: { id, userId: ctx.userId } })
  if (!existing) return Response.json({ error: 'not found' }, { status: 404 })
  await prisma.journalEntry.delete({ where: { id } })
  return Response.json({ ok: true })
}
