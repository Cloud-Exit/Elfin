import { requireAuth } from '../auth.js'
import { prisma } from '../db.js'
import { parsePagination } from '../utils/pagination.js'
import { chatMessageCreateSchema } from '../utils/schemas.js'
import { chatService, gatherChatContext } from '../chatService.js'

const rateLimitStore = new Map<string, { count: number; reset: number }>()
const RATE_LIMIT_MAX = 20
const RATE_LIMIT_WINDOW = 60_000

export function resetRateLimitStore(): void {
  rateLimitStore.clear()
}

function checkRateLimit(userId: string): boolean {
  const now = Date.now()
  if (rateLimitStore.size > 1000) {
    pruneExpiredRateLimits()
  }
  const entry = rateLimitStore.get(userId)
  if (!entry || now > entry.reset) {
    rateLimitStore.set(userId, { count: 1, reset: now + RATE_LIMIT_WINDOW })
    return true
  }
  if (entry.count >= RATE_LIMIT_MAX) {
    return false
  }
  entry.count++
  return true
}

function pruneExpiredRateLimits(): void {
  const now = Date.now()
  for (const [key, entry] of rateLimitStore.entries()) {
    if (now > entry.reset) {
      rateLimitStore.delete(key)
    }
  }
}

export async function handleChat(req: Request, path: string): Promise<Response | null> {
  const pathname = path.split('?')[0]!
  const parts = pathname.split('/').filter(Boolean)
  if (parts[1] !== 'chat') return null

  try {
    if (parts.length === 2 && req.method === 'GET') return await listMessages(req)
    if (parts.length === 2 && req.method === 'POST') return await sendMessage(req)
    if (parts.length === 3 && req.method === 'GET') return await getMessage(req, parts[2]!)
    if (parts.length === 3 && req.method === 'DELETE') return await deleteMessage(req, parts[2]!)
    return Response.json({ error: 'not found' }, { status: 404 })
  } catch (err: any) {
    if (err.message === 'missing token' || err.message === 'invalid token' || err.message === 'user not found') {
      return Response.json({ error: err.message }, { status: 401 })
    }
    return Response.json({ error: 'internal server error' }, { status: 500 })
  }
}

async function listMessages(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)
  const { limit, offset } = parsePagination(new URL(req.url))

  const [messages, total] = await Promise.all([
    prisma.chatMessage.findMany({
      where: { userId: ctx.userId },
      orderBy: { createdAt: 'desc' },
      take: limit,
      skip: offset,
      select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
    }),
    prisma.chatMessage.count({ where: { userId: ctx.userId } }),
  ])

  return Response.json({ messages, total, limit, offset })
}

async function sendMessage(req: Request): Promise<Response> {
  const ctx = await requireAuth(req)

  if (!checkRateLimit(ctx.userId)) {
    return Response.json({ error: 'rate limit exceeded' }, { status: 429 })
  }

  const body = await req.json().catch(() => ({}))
  const result = chatMessageCreateSchema.safeParse(body)
  if (!result.success) {
    return Response.json({ error: result.error.issues.map((i: any) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ') }, { status: 400 })
  }

  const { message, sources, images } = result.data

  const [context, history] = await Promise.all([
    gatherChatContext(ctx.userId),
    prisma.chatMessage.findMany({
      where: { userId: ctx.userId },
      orderBy: { createdAt: 'desc' },
      take: 12,
      select: { role: true, content: true },
    }),
  ])

  const historyReversed = history.reverse().map((m: { role: string; content: string }) => ({ role: m.role, content: m.content }))

  let reply: { content: string }
  try {
    reply = await chatService.generateReply(message, context, historyReversed)
  } catch (err: any) {
    reply = { content: `Sorry, I encountered an error processing your request: ${err.message || 'unknown error'}` }
  }

  const now = new Date()
  const userTs = now
  const assistantTs = new Date(now.getTime() + 1)

  const [, assistantMsg] = await prisma.$transaction([
    prisma.chatMessage.create({
      data: {
        userId: ctx.userId,
        role: 'user',
        content: message,
        sources: sources ? JSON.stringify(sources) : null,
        images: images ? JSON.stringify(images) : null,
        createdAt: userTs,
      },
      select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
    }),
    prisma.chatMessage.create({
      data: {
        userId: ctx.userId,
        role: 'assistant',
        content: reply.content,
        createdAt: assistantTs,
      },
      select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
    }),
  ])

  return Response.json({ message: assistantMsg }, { status: 201 })
}

async function getMessage(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const msg = await prisma.chatMessage.findFirst({
    where: { id, userId: ctx.userId },
    select: { id: true, role: true, content: true, sources: true, images: true, createdAt: true },
  })
  if (!msg) return Response.json({ error: 'not found' }, { status: 404 })
  return Response.json({ message: msg })
}

async function deleteMessage(_req: Request, id: string): Promise<Response> {
  const ctx = await requireAuth(_req)
  const result = await prisma.chatMessage.deleteMany({ where: { id, userId: ctx.userId } })
  if (result.count === 0) return Response.json({ error: 'not found' }, { status: 404 })
  return Response.json({ ok: true })
}
