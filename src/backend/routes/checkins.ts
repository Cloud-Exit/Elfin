import { requireAuth } from '../auth.js'
import { prisma } from '../db.js'
import { parsePagination } from '../utils/pagination.js'
import { checkinCreateSchema, checkinUpdateSchema } from '../utils/schemas.js'

function decodeCheckin(checkin: any) {
  return {
    ...checkin,
    questions: JSON.parse(checkin.questions),
    responses: JSON.parse(checkin.responses),
  }
}

export async function handleCheckins(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'checkins') return null

  try {
    if (parts.length === 2 && req.method === 'GET') {
      return await listCheckins(req)
    }
    if (parts.length === 2 && req.method === 'POST') {
      return await createCheckin(req)
    }
    if (parts.length === 3 && req.method === 'GET') {
      return await getCheckin(req, parts[2]!)
    }
    if (parts.length === 3 && req.method === 'PUT') {
      return await updateCheckin(req, parts[2]!)
    }
    if (parts.length === 3 && req.method === 'DELETE') {
      return await deleteCheckin(req, parts[2]!)
    }
    return Response.json({ error: 'not found' }, { status: 404 })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    return Response.json({ error: err.message }, { status: 400 })
  }
}

async function listCheckins(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const url = new URL(req.url)
  const { limit, offset } = parsePagination(url)
  const fromDate = url.searchParams.get('fromDate') ?? undefined
  const toDate = url.searchParams.get('toDate') ?? undefined

  const where = {
    userId: ctx.userId,
    ...(fromDate && { date: { gte: new Date(fromDate) } }),
    ...(toDate && { date: { lte: new Date(toDate) } }),
  }

  const [checkins, total] = await Promise.all([
    prisma.checkIn.findMany({
      where,
      orderBy: { date: 'desc' },
      take: limit,
      skip: offset,
      select: {
        id: true,
        date: true,
        questions: true,
        responses: true,
        aiSummary: true,
        mentalScore: true,
        physicalScore: true,
        staminaScore: true,
        categories: true,
        createdAt: true,
      },
    }),
    prisma.checkIn.count({ where }),
  ])

  return Response.json({
    checkins: checkins.map(decodeCheckin),
    total,
    limit,
    offset,
  })
}

async function createCheckin(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const body = await req.json().catch(() => ({}))
  const result = checkinCreateSchema.safeParse(body)

  if (!result.success) {
    const msg = result.error.issues
      .map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`)
      .join('; ')
    return Response.json({ error: msg }, { status: 400 })
  }

  const data = result.data
  const checkin = await prisma.checkIn.create({
    data: {
      userId: ctx.userId,
      questions: JSON.stringify(data.questions),
      responses: JSON.stringify(data.responses),
      mentalScore: data.mentalScore ?? null,
      physicalScore: data.physicalScore ?? null,
      staminaScore: data.staminaScore ?? null,
      date: data.date ?? new Date(),
    },
    select: {
      id: true,
      date: true,
      questions: true,
      responses: true,
      aiSummary: true,
      mentalScore: true,
      physicalScore: true,
      staminaScore: true,
      categories: true,
      createdAt: true,
    },
  })

  return Response.json({ checkin: decodeCheckin(checkin) }, { status: 201 })
}

async function getCheckin(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const checkin = await prisma.checkIn.findFirst({
    where: { id, userId: ctx.userId },
    select: {
      id: true,
      date: true,
      questions: true,
      responses: true,
      aiSummary: true,
      mentalScore: true,
      physicalScore: true,
      staminaScore: true,
      categories: true,
      createdAt: true,
    },
  })

  if (!checkin) {
    return Response.json({ error: 'not found' }, { status: 404 })
  }

  return Response.json({ checkin: decodeCheckin(checkin) })
}

async function updateCheckin(req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(req)
  const existing = await prisma.checkIn.findFirst({
    where: { id, userId: ctx.userId },
  })

  if (!existing) {
    return Response.json({ error: 'not found' }, { status: 404 })
  }

  const body = await req.json().catch(() => ({}))
  const result = checkinUpdateSchema.safeParse(body)

  if (!result.success) {
    const msg = result.error.issues
      .map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`)
      .join('; ')
    return Response.json({ error: msg }, { status: 400 })
  }

  const data = result.data
  const checkin = await prisma.checkIn.update({
    where: { id },
    data: {
      ...(data.questions !== undefined && { questions: JSON.stringify(data.questions) }),
      ...(data.responses !== undefined && { responses: JSON.stringify(data.responses) }),
      ...(data.mentalScore !== undefined && { mentalScore: data.mentalScore }),
      ...(data.physicalScore !== undefined && { physicalScore: data.physicalScore }),
      ...(data.staminaScore !== undefined && { staminaScore: data.staminaScore }),
      ...(data.date !== undefined && { date: data.date }),
    },
    select: {
      id: true,
      date: true,
      questions: true,
      responses: true,
      aiSummary: true,
      mentalScore: true,
      physicalScore: true,
      staminaScore: true,
      categories: true,
      createdAt: true,
    },
  })

  return Response.json({ checkin: decodeCheckin(checkin) })
}

async function deleteCheckin(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const existing = await prisma.checkIn.findFirst({
    where: { id, userId: ctx.userId },
  })

  if (!existing) {
    return Response.json({ error: 'not found' }, { status: 404 })
  }

  await prisma.checkIn.delete({ where: { id } })
  return Response.json({ ok: true })
}
