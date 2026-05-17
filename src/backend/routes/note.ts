import { requireAuth } from '../auth.js'
import { prisma } from '../db.js'
import { parsePagination } from '../utils/pagination.js'
import { noteCreateSchema, noteUpdateSchema } from '../utils/schemas.js'

export async function handleNote(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'notes') return null

  try {
    if (parts.length === 2 && req.method === 'GET') return await listNotes(req)
    if (parts.length === 2 && req.method === 'POST') return await createNote(req)
    if (parts.length === 3 && req.method === 'GET') return await getNote(req, parts[2]!)
    if (parts.length === 3 && req.method === 'PUT') return await updateNote(req, parts[2]!)
    if (parts.length === 3 && req.method === 'DELETE') return await deleteNote(req, parts[2]!)
    return Response.json({ error: 'not found' }, { status: 404 })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    console.error('Note API Error:', err)
    return Response.json({ error: 'internal server error' }, { status: 500 })
  }
}

async function listNotes(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const { limit, offset } = parsePagination(new URL(req.url))
  const url = new URL(req.url)
  const q = url.searchParams.get('q') ?? undefined

  const where = {
    userId: ctx.userId,
    ...(q && {
      OR: [
        { title: { contains: q } },
        { content: { contains: q } }
      ]
    }),
  }

  const [notes, total] = await Promise.all([
    prisma.note.findMany({
      where,
      orderBy: { updatedAt: 'desc' },
      take: limit,
      skip: offset,
      select: { id: true, title: true, content: true, createdAt: true, updatedAt: true },
    }),
    prisma.note.count({ where }),
  ])

  return Response.json({ notes, total, limit, offset })
}

async function createNote(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const body = await req.json().catch(() => ({}))
  const result = noteCreateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  const note = await prisma.note.create({
    data: { userId: ctx.userId, title: result.data.title, content: result.data.content },
    select: { id: true, title: true, content: true, createdAt: true, updatedAt: true },
  })

  return Response.json({ note }, { status: 201 })
}

async function getNote(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const note = await prisma.note.findFirst({
    where: { id, userId: ctx.userId },
    select: { id: true, title: true, content: true, createdAt: true, updatedAt: true },
  })
  if (!note) return Response.json({ error: 'not found' }, { status: 404 })
  return Response.json({ note })
}

async function updateNote(req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(req)
  const existing = await prisma.note.findFirst({ where: { id, userId: ctx.userId } })
  if (!existing) return Response.json({ error: 'not found' }, { status: 404 })

  const body = await req.json().catch(() => ({}))
  const result = noteUpdateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  const note = await prisma.note.update({
    where: { id },
    data: {
      ...(result.data.title !== undefined && { title: result.data.title }),
      ...(result.data.content !== undefined && { content: result.data.content }),
    },
    select: { id: true, title: true, content: true, createdAt: true, updatedAt: true },
  })

  return Response.json({ note })
}

async function deleteNote(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const existing = await prisma.note.findFirst({ where: { id, userId: ctx.userId } })
  if (!existing) return Response.json({ error: 'not found' }, { status: 404 })
  await prisma.note.delete({ where: { id } })
  return Response.json({ ok: true })
}
